// SPDX-License-Identifier: MIT
// WPA2-CCMP helpers for the legacy NTR Wi-Fi path.

#ifndef DSWIFI_ARM7_NTR_CCMP_H__
#define DSWIFI_ARM7_NTR_CCMP_H__

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Infer only a candidate payload length from a CTR-decrypted fixed prefix.
// Does NOT authenticate it or expose plaintext. Full MIC validation is still
// required before accepting/forwarding ANY bytes.
bool Wifi_NTR_CcmpProbePayloadLength(const uint8_t key[16],
                                     const uint8_t nonce[13],
                                     const uint8_t *cipher, size_t available,
                                     size_t *payload_length);

// 802.11 CCMP uses a 128-bit AES key, a 13-byte nonce, and an 8-byte MIC.
// The DS driver only sends non-QoS data frames, whose authenticated header is
// 22 bytes. CCM uses L=2, so one MSDU cannot exceed 65535 bytes.
bool Wifi_NTR_CcmpEncrypt(const uint8_t key[16], const uint8_t nonce[13],
                          const uint8_t aad[22], const uint8_t *plain,
                          size_t length, uint8_t *cipher, uint8_t mic[8]);
bool Wifi_NTR_CcmpDecrypt(const uint8_t key[16], const uint8_t nonce[13],
                          const uint8_t aad[22], const uint8_t *cipher,
                          size_t length, const uint8_t mic[8], uint8_t *plain);

#endif
