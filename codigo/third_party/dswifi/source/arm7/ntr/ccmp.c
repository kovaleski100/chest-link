// SPDX-License-Identifier: MIT
// WPA2-CCMP helpers for the legacy NTR Wi-Fi path.

#include <string.h>

#include "arm7/ntr/ccmp.h"

#include "mbedtls/aes.h"

#define CCMP_MIC_SIZE 8
#define CCMP_AAD_SIZE 22

static int ccmp_aes_block(mbedtls_aes_context *aes, const uint8_t in[16],
                          uint8_t out[16]) {
  return mbedtls_aes_crypt_ecb(aes, MBEDTLS_AES_ENCRYPT, in, out);
}

static int ccmp_mac_block(mbedtls_aes_context *aes, uint8_t state[16],
                          const uint8_t block[16]) {
  uint8_t mixed[16];
  for (size_t i = 0; i < sizeof(mixed); ++i)
    mixed[i] = state[i] ^ block[i];
  return ccmp_aes_block(aes, mixed, state);
}

static int ccmp_mac_data(mbedtls_aes_context *aes, uint8_t state[16],
                         const uint8_t *data, size_t length) {
  uint8_t block[16] = {0};
  while (length >= sizeof(block)) {
    if (ccmp_mac_block(aes, state, data) != 0)
      return -1;
    data += sizeof(block);
    length -= sizeof(block);
  }
  if (length) {
    memcpy(block, data, length);
    if (ccmp_mac_block(aes, state, block) != 0)
      return -1;
  }
  return 0;
}

static int ccmp_compute_tag(mbedtls_aes_context *aes,
                            const uint8_t nonce[13], const uint8_t *aad,
                            size_t aad_length, const uint8_t *plain, size_t length,
                            uint8_t tag[8]) {
  if (length > 0xffff || !aad_length || aad_length > 0xfeff)
    return -1;

  uint8_t block[16] = {0};
  uint8_t state[16] = {0};
  uint8_t counter[16] = {0};

  // B0: AAD present, 8-byte tag, and a two-byte message-length field.
  block[0] = 0x59;
  memcpy(block + 1, nonce, 13);
  block[14] = (uint8_t)(length >> 8);
  block[15] = (uint8_t)length;
  if (ccmp_aes_block(aes, block, state) != 0)
    return -1;

  // CCM encodes a short AAD length as a two-byte big-endian prefix. The first
  // CBC-MAC block holds that prefix and 14 AAD bytes; following AAD bytes are
  // processed in padded blocks.
  memset(block, 0, sizeof(block));
  block[0] = (uint8_t)(aad_length >> 8);
  block[1] = (uint8_t)aad_length;
  const size_t first_aad = aad_length < 14 ? aad_length : 14;
  memcpy(block + 2, aad, first_aad);
  if (ccmp_mac_block(aes, state, block) != 0)
    return -1;
  if (aad_length > first_aad &&
      ccmp_mac_data(aes, state, aad + first_aad, aad_length - first_aad) != 0)
    return -1;

  if (length && ccmp_mac_data(aes, state, plain, length) != 0)
    return -1;

  // S0 masks the CBC-MAC result to form the transmitted MIC.
  counter[0] = 1; // L - 1
  memcpy(counter + 1, nonce, 13);
  if (ccmp_aes_block(aes, counter, block) != 0)
    return -1;
  for (size_t i = 0; i < CCMP_MIC_SIZE; ++i)
    tag[i] = state[i] ^ block[i];
  return 0;
}

static int ccmp_crypt(mbedtls_aes_context *aes, const uint8_t nonce[13],
                      const uint8_t *input, size_t length, uint8_t *output) {
  if (length > 0xffff)
    return -1;

  uint8_t counter[16] = {0};
  uint8_t stream[16];
  counter[0] = 1; // L - 1
  memcpy(counter + 1, nonce, 13);

  uint16_t block_number = 1;
  while (length) {
    counter[14] = (uint8_t)(block_number >> 8);
    counter[15] = (uint8_t)block_number;
    if (ccmp_aes_block(aes, counter, stream) != 0)
      return -1;
    size_t count = length < sizeof(stream) ? length : sizeof(stream);
    for (size_t i = 0; i < count; ++i)
      output[i] = input[i] ^ stream[i];
    input += count;
    output += count;
    length -= count;
    ++block_number;
  }
  return 0;
}

bool Wifi_NTR_CcmpEncryptAad(const uint8_t key[16], const uint8_t nonce[13],
                             const uint8_t *aad, size_t aad_length,
                             const uint8_t *plain, size_t length,
                             uint8_t *cipher, uint8_t mic[8]) {
  if (!key || !nonce || !aad || !aad_length || (!plain && length) ||
      (!cipher && length) || !mic || length > 0xffff)
    return false;

  mbedtls_aes_context aes;
  mbedtls_aes_init(&aes);
  int result = mbedtls_aes_setkey_enc(&aes, key, 128);
  if (result == 0)
    result = ccmp_compute_tag(&aes, nonce, aad, aad_length, plain, length, mic);
  // Authenticate before encrypting so input and output are allowed to alias,
  // as they do in the NTR TX path where the ARM7 edits the frame in place.
  if (result == 0)
    result = ccmp_crypt(&aes, nonce, plain, length, cipher);
  mbedtls_aes_free(&aes);
  return result == 0;
}

bool Wifi_NTR_CcmpEncrypt(const uint8_t key[16], const uint8_t nonce[13],
                          const uint8_t aad[22], const uint8_t *plain,
                          size_t length, uint8_t *cipher, uint8_t mic[8]) {
  return Wifi_NTR_CcmpEncryptAad(key, nonce, aad, CCMP_AAD_SIZE, plain,
                                 length, cipher, mic);
}

bool Wifi_NTR_CcmpProbePayloadLength(const uint8_t key[16],
                                     const uint8_t nonce[13],
                                     const uint8_t *cipher, size_t available,
                                     size_t *payload_length) {
  if (payload_length) *payload_length = 0;
  if (!key || !nonce || !cipher || !payload_length || available < 16)
    return false;
  uint8_t prefix[16] = {0};
  mbedtls_aes_context aes;
  mbedtls_aes_init(&aes);
  int result = mbedtls_aes_setkey_enc(&aes, key, 128);
  if (result == 0) result = ccmp_crypt(&aes, nonce, cipher, sizeof(prefix), prefix);
  mbedtls_aes_free(&aes);
  size_t length = 0;
  if (result == 0 && memcmp(prefix, "\xAA\xAA\x03\0\0\0", 6) == 0) {
    const unsigned protocol = ((unsigned)prefix[6] << 8) | prefix[7];
    if (protocol == 0x0800 && (prefix[8] >> 4) == 4) {
      const unsigned ihl = (prefix[8] & 15) * 4;
      const unsigned total = ((unsigned)prefix[10] << 8) | prefix[11];
      if (ihl >= 20 && total >= ihl) length = 8 + total;
    } else if (protocol == 0x0806 &&
               memcmp(prefix + 8, "\0\x01\x08\0\x06\x04", 6) == 0) {
      length = 8 + 28; // Ethernet/IPv4 ARP.
    } else if (protocol == 0x86DD && (prefix[8] >> 4) == 6) {
      length = 8 + 40 + ((unsigned)prefix[12] << 8) + prefix[13];
    } else if (protocol == 0x888E) {
      length = 8 + 4 + ((unsigned)prefix[10] << 8) + prefix[11];
    }
  }
  // No prefix bytes leave this helper, regardless of validity.
  memset(prefix, 0, sizeof(prefix));
  if (!length || length > available) return false;
  *payload_length = length;
  return true;
}

bool Wifi_NTR_CcmpDecryptAad(const uint8_t key[16], const uint8_t nonce[13],
                             const uint8_t *aad, size_t aad_length,
                             const uint8_t *cipher, size_t length,
                             const uint8_t mic[8], uint8_t *plain) {
  if (!key || !nonce || !aad || !aad_length || (!cipher && length) ||
      (!plain && length) || !mic || length > 0xffff)
    return false;

  mbedtls_aes_context aes;
  uint8_t expected[CCMP_MIC_SIZE];
  uint8_t difference = 0;
  mbedtls_aes_init(&aes);
  int result = mbedtls_aes_setkey_enc(&aes, key, 128);
  if (result == 0)
    result = ccmp_crypt(&aes, nonce, cipher, length, plain);
  if (result == 0)
    result = ccmp_compute_tag(&aes, nonce, aad, aad_length, plain, length,
                              expected);
  if (result == 0) {
    for (size_t i = 0; i < CCMP_MIC_SIZE; ++i)
      difference |= expected[i] ^ mic[i];
  }
  mbedtls_aes_free(&aes);

  if (result != 0 || difference != 0) {
    if (plain && length)
      memset(plain, 0, length);
    return false;
  }
  return true;
}

bool Wifi_NTR_CcmpDecrypt(const uint8_t key[16], const uint8_t nonce[13],
                          const uint8_t aad[22], const uint8_t *cipher,
                          size_t length, const uint8_t mic[8], uint8_t *plain) {
  return Wifi_NTR_CcmpDecryptAad(key, nonce, aad, CCMP_AAD_SIZE, cipher,
                                 length, mic, plain);
}
