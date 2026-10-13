// SPDX-License-Identifier: MIT
// WPA2-Personal (PSK/AES-CCMP) supplicant for the legacy NTR Wi-Fi path.

#include <string.h>

#include <nds.h>

#include "arm7/debug.h"
#include "arm7/ipc.h"
#include "arm7/ntr/tx_queue.h"
#include "arm7/ntr/wpa.h"
#include "arm7/twl/ieee/wpa.h"
#include "common/common_ntr_defs.h"
#include "common/ieee_defs.h"
#include "common/mac_addresses.h"
#include "common/random.h"
#include "common/wifi_shared.h"

#include "arm7/ntr/ccmp.h"

#define WPA_EAPOL_TYPE_KEY 3
#define WPA_KEY_DESCRIPTOR_RSN 2
#define WPA_KEY_FIXED_LENGTH 95
#define WPA_KEY_DATA_OFFSET 99
#define WPA_KEY_MIC_OFFSET 81
#define WPA_KEY_INFO_PAIRWISE 0x0008
#define WPA_KEY_INFO_INSTALL 0x0040
#define WPA_KEY_INFO_ACK 0x0080
#define WPA_KEY_INFO_MIC 0x0100
#define WPA_KEY_INFO_SECURE 0x0200
#define WPA_KEY_INFO_ENCRYPTED 0x1000
#define WPA_EAPOL_MAX_SIZE 512
#define WPA_FRAME_MAX_SIZE (sizeof(Wifi_TxHeader) + HDR_DATA_MAC_SIZE + 8 + \
                            WPA_EAPOL_MAX_SIZE)

typedef enum {
    WPA_NTR_IDLE,
    WPA_NTR_WAIT_MESSAGE_1,
    WPA_NTR_WAIT_MESSAGE_3,
    WPA_NTR_READY,
    WPA_NTR_FAILED,
} Wifi_NTR_WpaState;

static Wifi_NTR_WpaState wpa_state;
static bool wpa_crypto_initialized;
static u8 wpa_anonce[32];
static u8 wpa_snonce[32];
static ptk_keyinfo wpa_ptk;
static gtk_keyinfo wpa_gtk;
static u64 wpa_handshake_replay;
static u64 wpa_tx_pn;
static u64 wpa_pairwise_rx_pn;
static u64 wpa_group_rx_pn;
static u16 wpa_tx_sequence;

static u16 read_be16(const u8 *data)
{
    return ((u16)data[0] << 8) | data[1];
}

static void wipe_volatile(volatile u8 *data, size_t length)
{
    while (length--)
        *data++ = 0;
}

static u64 read_be64(const u8 *data)
{
    u64 value = 0;
    for (size_t i = 0; i < 8; ++i)
        value = (value << 8) | data[i];
    return value;
}

static void write_be16(u8 *data, u16 value)
{
    data[0] = value >> 8;
    data[1] = value & 0xFF;
}

static void write_be64(u8 *data, u64 value)
{
    for (int i = 7; i >= 0; --i)
    {
        data[i] = value & 0xFF;
        value >>= 8;
    }
}

static u64 read_ccmp_pn(const u8 *header)
{
    return (u64)header[0] | ((u64)header[1] << 8) |
           ((u64)header[4] << 16) | ((u64)header[5] << 24) |
           ((u64)header[6] << 32) | ((u64)header[7] << 40);
}

static u64 read_le48(const u8 *data)
{
    u64 value = 0;
    for (int i = 5; i >= 0; --i)
        value = (value << 8) | data[i];
    return value;
}

static void write_ccmp_header(u8 *header, u64 pn)
{
    header[0] = pn & 0xFF;
    header[1] = (pn >> 8) & 0xFF;
    header[2] = 0;
    header[3] = 0x20; // Extended IV, pairwise key ID 0.
    header[4] = (pn >> 16) & 0xFF;
    header[5] = (pn >> 24) & 0xFF;
    header[6] = (pn >> 32) & 0xFF;
    header[7] = (pn >> 40) & 0xFF;
}

static void make_ccmp_aad(const u8 *frame, u8 aad[22])
{
    // Mask fields that can change during retransmission or delivery.
    aad[0] = frame[0] & 0x8F;
    aad[1] = frame[1] & 0xC7;
    memcpy(aad + 2, frame + 4, 18); // A1, A2, A3
    aad[20] = frame[22] & 0x0F; // Fragment number only.
    aad[21] = 0;
}

static void make_ccmp_nonce(const u8 *frame, const u8 *ccmp_header,
                            u8 nonce[13])
{
    nonce[0] = 0; // Non-QoS data priority.
    memcpy(nonce + 1, frame + 10, 6); // Transmitter address.
    nonce[7] = ccmp_header[7];
    nonce[8] = ccmp_header[6];
    nonce[9] = ccmp_header[5];
    nonce[10] = ccmp_header[4];
    nonce[11] = ccmp_header[1];
    nonce[12] = ccmp_header[0];
}

static bool send_eapol_key(u16 key_info, u64 replay_counter,
                           const u8 nonce[32], const u8 *key_data,
                           size_t key_data_len, bool with_mic)
{
    if (key_data_len > sizeof(WifiData->curAp.rsn_ie) ||
        WPA_KEY_DATA_OFFSET + key_data_len > WPA_EAPOL_MAX_SIZE)
        return false;

    u8 eapol[WPA_EAPOL_MAX_SIZE] __attribute__((aligned(4))) = {0};
    const size_t eapol_len = WPA_KEY_DATA_OFFSET + key_data_len;
    const size_t body_len = WPA_KEY_FIXED_LENGTH + key_data_len;

    eapol[0] = 2; // WPA2 EAPOL version.
    eapol[1] = WPA_EAPOL_TYPE_KEY;
    write_be16(eapol + 2, body_len);
    eapol[4] = WPA_KEY_DESCRIPTOR_RSN;
    write_be16(eapol + 5, key_info);
    write_be16(eapol + 7, 16); // CCMP temporal key length.
    write_be64(eapol + 9, replay_counter);
    if (nonce)
        memcpy(eapol + 17, nonce, 32);
    write_be16(eapol + 97, key_data_len);
    if (key_data_len)
        memcpy(eapol + WPA_KEY_DATA_OFFSET, key_data, key_data_len);

    if (with_mic)
    {
        u8 mic[16];
        wpa_calc_mic(wpa_ptk.kck, eapol, eapol_len, mic);
        memcpy(eapol + WPA_KEY_MIC_OFFSET, mic, sizeof(mic));
    }

    u8 frame[WPA_FRAME_MAX_SIZE] __attribute__((aligned(4))) = {0};
    Wifi_TxHeader *tx = (void *)frame;
    u8 *ieee = frame + sizeof(Wifi_TxHeader);
    u8 *payload = ieee + HDR_DATA_MAC_SIZE;

    // EAPOL-Key replies target the authenticator, not the PAE discovery group.
    // A1 is the radio receiver and A3 is the Ethernet destination at the AP.
    ieee[0] = (FC_TO_DS | TYPE_DATA) & 0xFF;
    ieee[1] = (FC_TO_DS | TYPE_DATA) >> 8;
    Wifi_CopyMacAddr(ieee + 4, WifiData->curAp.bssid);
    Wifi_CopyMacAddr(ieee + 10, WifiData->MacAddr);
    Wifi_CopyMacAddr(ieee + 16, WifiData->curAp.bssid);
    ieee[22] = wpa_tx_sequence & 0xF0;
    ieee[23] = wpa_tx_sequence >> 8;
    wpa_tx_sequence = (wpa_tx_sequence + 0x10) & 0xFFF0;

    payload[0] = 0xAA;
    payload[1] = 0xAA;
    payload[2] = 0x03;
    payload[3] = payload[4] = payload[5] = 0;
    payload[6] = 0x88;
    payload[7] = 0x8E;
    memcpy(payload + 8, eapol, eapol_len);

    const size_t ieee_len = HDR_DATA_MAC_SIZE + 8 + eapol_len;
    tx->tx_rate = WIFI_TRANSFER_RATE_1MBPS;
    tx->tx_length = ieee_len + 4; // Hardware adds the FCS.
    return Wifi_TxArm7QueueAdd((u16 *)frame,
                               sizeof(Wifi_TxHeader) + ieee_len) != 0;
}

static bool verify_eapol_mic(const u8 *eapol, size_t eapol_len)
{
    if (eapol_len < WPA_KEY_DATA_OFFSET || eapol_len > WPA_EAPOL_MAX_SIZE)
        return false;

    u8 copy[WPA_EAPOL_MAX_SIZE];
    u8 expected[16];
    memcpy(copy, eapol, eapol_len);
    memset(copy + WPA_KEY_MIC_OFFSET, 0, 16);
    wpa_calc_mic(wpa_ptk.kck, copy, eapol_len, expected);

    u8 difference = 0;
    for (size_t i = 0; i < sizeof(expected); ++i)
        difference |= expected[i] ^ eapol[WPA_KEY_MIC_OFFSET + i];
    memset(copy, 0, eapol_len);
    memset(expected, 0, sizeof(expected));
    return difference == 0;
}

static bool handle_eapol(const u8 *frame, size_t frame_len)
{
    if (frame_len < HDR_DATA_MAC_SIZE + 8 + 4 ||
        !Wifi_CmpMacAddr(frame + 4, WifiData->MacAddr) ||
        !Wifi_CmpMacAddr(frame + 10, WifiData->curAp.bssid))
        return false;

    const u8 *snap = frame + HDR_DATA_MAC_SIZE;
    if (snap[0] != 0xAA || snap[1] != 0xAA || snap[2] != 0x03 ||
        snap[3] || snap[4] || snap[5] || snap[6] != 0x88 || snap[7] != 0x8E)
        return false;

    const u8 *eapol = snap + 8;
    const size_t available = frame_len - HDR_DATA_MAC_SIZE - 8;
    if (available < WPA_KEY_DATA_OFFSET || eapol[1] != WPA_EAPOL_TYPE_KEY ||
        eapol[4] != WPA_KEY_DESCRIPTOR_RSN)
        return false;

    const size_t eapol_len = 4 + read_be16(eapol + 2);
    if (eapol_len > available || eapol_len < WPA_KEY_DATA_OFFSET ||
        eapol_len > WPA_EAPOL_MAX_SIZE)
        return false;

    const u16 key_info = read_be16(eapol + 5);
    const u64 replay = read_be64(eapol + 9);
    const size_t key_data_len = read_be16(eapol + 97);
    if (WPA_KEY_DATA_OFFSET + key_data_len != eapol_len)
        return false;

    if ((key_info & 0x0007) != 2)
        return false;

    if ((key_info & (WPA_KEY_INFO_ACK | WPA_KEY_INFO_MIC)) == WPA_KEY_INFO_ACK &&
        (key_info & WPA_KEY_INFO_PAIRWISE) &&
        (wpa_state == WPA_NTR_WAIT_MESSAGE_1 ||
         wpa_state == WPA_NTR_WAIT_MESSAGE_3))
    {
        // Message 1/4: AP nonce and replay counter. Generate one SNonce and
        // keep it for retransmitted M1 packets so the PTK remains stable.
        if (wpa_state == WPA_NTR_WAIT_MESSAGE_1)
        {
            memcpy(wpa_anonce, eapol + 17, sizeof(wpa_anonce));
            for (size_t i = 0; i < sizeof(wpa_snonce); ++i)
                wpa_snonce[i] = Wifi_Random() & 0xFF;
            wpa_handshake_replay = replay;
            u8 dev_mac[6];
            u8 ap_mac[6];
            u8 pmk[32];
            memcpy(dev_mac, (const void *)WifiData->MacAddr, sizeof(dev_mac));
            memcpy(ap_mac, (const void *)WifiData->curAp.bssid, sizeof(ap_mac));
            memcpy(pmk, (const void *)WifiData->curApSecurity.pmk, sizeof(pmk));
            wpa_calc_ptk(dev_mac, ap_mac, wpa_snonce, wpa_anonce, pmk, &wpa_ptk);
            memset(pmk, 0, sizeof(pmk));
            // Retain the PMK for reassociation within this connection. The
            // passphrase is already erased; disconnect/reset erases the PMK.
        }
        else if (replay < wpa_handshake_replay ||
                 memcmp(wpa_anonce, eapol + 17, sizeof(wpa_anonce)) != 0)
        {
            return false;
        }

        if (!send_eapol_key(0x010A, replay, wpa_snonce,
                            (const u8 *)WifiData->curAp.rsn_ie,
                            WifiData->curAp.rsn_ie_len, true))
            return false;
        // AP retries may carry a higher counter with the same ANonce. Echo
        // that counter in M2 without generating new temporal keys/SNonce.
        wpa_handshake_replay = replay;
        wpa_state = WPA_NTR_WAIT_MESSAGE_3;
        return false;
    }

    const u16 message_3_mask = WPA_KEY_INFO_INSTALL | WPA_KEY_INFO_ACK |
                               WPA_KEY_INFO_MIC | WPA_KEY_INFO_SECURE;
    if ((key_info & WPA_KEY_INFO_PAIRWISE) &&
        (key_info & message_3_mask) == message_3_mask &&
        wpa_state == WPA_NTR_WAIT_MESSAGE_3 && replay > wpa_handshake_replay &&
        memcmp(wpa_anonce, eapol + 17, sizeof(wpa_anonce)) == 0)
    {
        if (!verify_eapol_mic(eapol, eapol_len))
        {
            wpa_state = WPA_NTR_FAILED;
            WifiData->authlevel = WIFI_AUTHLEVEL_ERROR;
            return false;
        }

        if (key_info & WPA_KEY_INFO_ENCRYPTED)
        {
            if (key_data_len < 24 || (key_data_len & 7) != 0)
            {
                wpa_state = WPA_NTR_FAILED;
                WifiData->authlevel = WIFI_AUTHLEVEL_ERROR;
                return false;
            }
            memset(&wpa_gtk, 0, sizeof(wpa_gtk));
            wpa_decrypt_gtk(wpa_ptk.kek, eapol + WPA_KEY_DATA_OFFSET,
                            key_data_len, &wpa_gtk);
            static const u8 gtk_kde[4] = {0x00, 0x0F, 0xAC, 0x01};
            if (memcmp(wpa_gtk.keytype, gtk_kde, sizeof(gtk_kde)) != 0)
            {
                wpa_state = WPA_NTR_FAILED;
                WifiData->authlevel = WIFI_AUTHLEVEL_ERROR;
                return false;
            }
            wpa_group_rx_pn = read_le48(eapol + 65);
        }

        if (!send_eapol_key(0x030A, replay, NULL, NULL, 0, true))
            return false;
        wpa_handshake_replay = replay;
        wpa_state = WPA_NTR_READY;
        WifiData->authlevel = WIFI_AUTHLEVEL_ASSOCIATED;
        WLOG_PUTS("W: WPA2 handshake complete\n");
        WLOG_FLUSH();
        return false;
    }

    // An AP may retransmit message 3 when message 4 was lost.
    if ((key_info & message_3_mask) == message_3_mask &&
        (key_info & WPA_KEY_INFO_PAIRWISE) &&
        wpa_state == WPA_NTR_READY && replay == wpa_handshake_replay &&
        verify_eapol_mic(eapol, eapol_len))
        send_eapol_key(0x030A, replay, NULL, NULL, 0, true);

    const u16 group_message_1_mask = WPA_KEY_INFO_ACK | WPA_KEY_INFO_MIC |
                                     WPA_KEY_INFO_SECURE | WPA_KEY_INFO_ENCRYPTED;
    if (!(key_info & WPA_KEY_INFO_PAIRWISE) &&
        (key_info & group_message_1_mask) == group_message_1_mask &&
        wpa_state == WPA_NTR_READY && replay > wpa_handshake_replay &&
        (key_info & 0x0007) == 2 &&
        verify_eapol_mic(eapol, eapol_len) &&
        key_data_len >= 24 && (key_data_len & 7) == 0)
    {
        gtk_keyinfo new_gtk = {0};
        wpa_decrypt_gtk(wpa_ptk.kek, eapol + WPA_KEY_DATA_OFFSET,
                        key_data_len, &new_gtk);
        static const u8 gtk_kde[4] = {0x00, 0x0F, 0xAC, 0x01};
        if (memcmp(new_gtk.keytype, gtk_kde, sizeof(gtk_kde)) == 0 &&
            send_eapol_key(0x0302, replay, NULL, NULL, 0, true))
        {
            memcpy(&wpa_gtk, &new_gtk, sizeof(wpa_gtk));
            wpa_group_rx_pn = read_le48(eapol + 65);
            wpa_handshake_replay = replay;
        }
        memset(&new_gtk, 0, sizeof(new_gtk));
    }

    return false;
}

static void reset_handshake(void)
{
    wipe_volatile(wpa_anonce, sizeof(wpa_anonce));
    wipe_volatile(wpa_snonce, sizeof(wpa_snonce));
    wipe_volatile((volatile u8 *)&wpa_ptk, sizeof(wpa_ptk));
    wipe_volatile((volatile u8 *)&wpa_gtk, sizeof(wpa_gtk));
    wpa_handshake_replay = 0;
    wpa_tx_pn = 0;
    wpa_pairwise_rx_pn = 0;
    wpa_group_rx_pn = 0;
    wpa_tx_sequence = 0;
    wpa_state = WPA_NTR_IDLE;
}

void Wifi_NTR_WpaReset(void)
{
    reset_handshake();
    if (WifiData)
        wipe_volatile(WifiData->curApSecurity.pmk,
                      sizeof(WifiData->curApSecurity.pmk));
}

bool Wifi_NTR_WpaPrepareConnection(void)
{
    Wifi_NTR_WpaReset();
    if (WifiData->curAp.security_type != AP_SECURITY_WPA2)
        return true;

    WifiData->stats[WSTAT_NTR_CCMP_RX] = 0;
    WifiData->stats[WSTAT_NTR_CCMP_VALID] = 0;
    WifiData->stats[WSTAT_NTR_CCMP_MIC_FAILED] = 0;
    WifiData->stats[WSTAT_NTR_RX_RAM_CANDIDATES] = 0;
    WifiData->stats[WSTAT_NTR_RX_RADIO_REJECTED] = 0;
    WifiData->stats[WSTAT_NTR_RX_FCS_BOUNDARY] = 0;
    WifiData->stats[WSTAT_NTR_RX_REPORTED_SIZE] = 0;
    WifiData->stats[WSTAT_NTR_RX_FRAME_SIZE] = 0;

    if (WifiData->curAp.pair_crypt_type != AP_CRYPT_AES ||
        WifiData->curAp.group_crypt_type != AP_CRYPT_AES ||
        WifiData->curAp.auth_type != AP_AUTH_PSK ||
        WifiData->curAp.rsn_ie_len < 2 ||
        WifiData->curAp.rsn_ie_len > sizeof(WifiData->curAp.rsn_ie) ||
        WifiData->curApSecurity.pass_len < 8 ||
        WifiData->curApSecurity.pass_len > 63)
    {
        wipe_volatile(WifiData->curApSecurity.pass,
                      sizeof(WifiData->curApSecurity.pass));
        WifiData->curApSecurity.pass_len = 0;
        return false;
    }

    if (!wpa_crypto_initialized)
    {
        wpa_mbedtls_init();
        wpa_crypto_initialized = true;
    }

    char ssid[33] = {0};
    char passphrase[64] = {0};
    memcpy(ssid, (const void *)WifiData->curAp.ssid, WifiData->curAp.ssid_len);
    memcpy(passphrase, (const void *)WifiData->curApSecurity.pass,
           WifiData->curApSecurity.pass_len);

    // The KDF is CPU-heavy on the 33 MHz ARM7. Let radio/timer interrupts keep
    // running while PBKDF2 computes the WPA2 pairwise master key.
    u32 old_ime = REG_IME;
    REG_IME = 1;
    u8 pmk[32] = {0};
    const int pmk_result = wpa_calc_pmk(ssid, passphrase, pmk);
    REG_IME = old_ime;

    if (pmk_result != 0)
    {
        memset(pmk, 0, sizeof(pmk));
        wipe_volatile(WifiData->curApSecurity.pmk,
                      sizeof(WifiData->curApSecurity.pmk));
        wipe_volatile(WifiData->curApSecurity.pass,
                      sizeof(WifiData->curApSecurity.pass));
        WifiData->curApSecurity.pass_len = 0;
        memset(passphrase, 0, sizeof(passphrase));
        memset(ssid, 0, sizeof(ssid));
        return false;
    }

    memcpy((void *)WifiData->curApSecurity.pmk, pmk, sizeof(pmk));
    memset(pmk, 0, sizeof(pmk));
    wipe_volatile(WifiData->curApSecurity.pass,
                  sizeof(WifiData->curApSecurity.pass));
    WifiData->curApSecurity.pass_len = 0;

    memset(passphrase, 0, sizeof(passphrase));
    memset(ssid, 0, sizeof(ssid));
    wpa_state = WPA_NTR_WAIT_MESSAGE_1;
    return true;
}

void Wifi_NTR_WpaAssociationComplete(void)
{
    if (WifiData->curAp.security_type == AP_SECURITY_WPA2)
    {
        reset_handshake();
        wpa_state = WPA_NTR_WAIT_MESSAGE_1;
    }
}

bool Wifi_NTR_WpaIsReady(void)
{
    return wpa_state == WPA_NTR_READY;
}

bool Wifi_NTR_WpaEncryptTx(u8 *frame, size_t frame_len)
{
    if (!frame || !Wifi_NTR_WpaIsReady() || frame_len < HDR_DATA_MAC_SIZE + 16 ||
        !(frame[1] & 0x40))
        return false;

    u8 *ccmp_header = frame + HDR_DATA_MAC_SIZE;
    u8 *cipher = ccmp_header + 8;
    const size_t plain_len = frame_len - HDR_DATA_MAC_SIZE - 16;
    if (wpa_tx_pn >= 0xFFFFFFFFFFFFULL)
        return false;

    const u64 pn = ++wpa_tx_pn;
    write_ccmp_header(ccmp_header, pn);

    // Give every protected data frame a fresh 802.11 sequence number. The
    // ARM9 lwIP path leaves this field zeroed; APs may discard repeated seqs.
    frame[22] = wpa_tx_sequence & 0xF0;
    frame[23] = wpa_tx_sequence >> 8;
    wpa_tx_sequence = (wpa_tx_sequence + 0x10) & 0xFFF0;

    u8 aad[22], nonce[13];
    make_ccmp_aad(frame, aad);
    make_ccmp_nonce(frame, ccmp_header, nonce);
    return Wifi_NTR_CcmpEncrypt(wpa_ptk.tk, nonce, aad,
                                cipher, plain_len, cipher,
                                cipher + plain_len);
}

size_t Wifi_NTR_WpaProbeRxSize(const u8 *frame, size_t available)
{
    if (!frame || !Wifi_NTR_WpaIsReady() || available < HDR_DATA_MAC_SIZE + 32)
        return 0;
    const u8 *header = frame + HDR_DATA_MAC_SIZE;
    if (!(header[3] & 0x20) || (header[3] & 0x1F) != 0)
        return 0;
    const u8 *key = wpa_ptk.tk;
    if (frame[4] & 1)
    {
        if (memcmp(wpa_gtk.keytype, "\x00\x0f\xac\x01", 4) != 0 ||
            (header[3] >> 6) != (wpa_gtk.keyidx & 0x03))
            return 0;
        key = wpa_gtk.key;
    }
    u8 nonce[13];
    make_ccmp_nonce(frame, header, nonce);
    size_t payload_length = 0;
    if (!Wifi_NTR_CcmpProbePayloadLength(key, nonce, header + 8,
                                        available - HDR_DATA_MAC_SIZE - 16,
                                        &payload_length))
        return 0;
    return HDR_DATA_MAC_SIZE + 16 + payload_length;
}

bool Wifi_NTR_WpaProcessRx(const u8 *frame, size_t frame_len,
                           u8 *output, size_t output_capacity,
                           size_t *output_len)
{
    if (output_len)
        *output_len = 0;
    if (!frame || !output || !output_len || frame_len < HDR_DATA_MAC_SIZE)
        return false;

    const u16 frame_control = frame[0] | ((u16)frame[1] << 8);
    if (!(frame_control & FC_PROTECTED_FRAME))
    {
        if (wpa_state == WPA_NTR_WAIT_MESSAGE_1 ||
            wpa_state == WPA_NTR_WAIT_MESSAGE_3 ||
            wpa_state == WPA_NTR_READY)
            handle_eapol(frame, frame_len);
        return false;
    }

    WifiData->stats[WSTAT_NTR_CCMP_RX]++;
    if (!Wifi_NTR_WpaIsReady() || frame_len < HDR_DATA_MAC_SIZE + 16 ||
        !Wifi_CmpMacAddr(frame + 10, WifiData->curAp.bssid))
        return false;

    const u8 *ccmp_header = frame + HDR_DATA_MAC_SIZE;
    if (!(ccmp_header[3] & 0x20) || (ccmp_header[3] & 0x1F) != 0)
        return false;

    const bool multicast = (frame[4] & 1) != 0;
    const u8 *key = wpa_ptk.tk;
    u64 *last_pn = &wpa_pairwise_rx_pn;
    if (multicast)
    {
        if (memcmp(wpa_gtk.keytype, "\x00\x0f\xac\x01", 4) != 0 ||
            (ccmp_header[3] >> 6) != (wpa_gtk.keyidx & 0x03))
            return false;
        key = wpa_gtk.key;
        last_pn = &wpa_group_rx_pn;
    }

    const u64 pn = read_ccmp_pn(ccmp_header);
    if (pn <= *last_pn)
        return false;

    const size_t encrypted_len = frame_len - HDR_DATA_MAC_SIZE - 16;
    if (HDR_DATA_MAC_SIZE + encrypted_len > output_capacity)
        return false;

    if (output != frame)
        memcpy(output, frame, HDR_DATA_MAC_SIZE);
    u8 *plain = output + HDR_DATA_MAC_SIZE;
    u8 aad[22], nonce[13];
    make_ccmp_aad(frame, aad);
    make_ccmp_nonce(frame, ccmp_header, nonce);
    if (!Wifi_NTR_CcmpDecrypt(key, nonce, aad,
                              ccmp_header + 8, encrypted_len,
                              ccmp_header + 8 + encrypted_len, plain))
    {
        WifiData->stats[WSTAT_NTR_CCMP_MIC_FAILED]++;
        return false;
    }

    WifiData->stats[WSTAT_NTR_CCMP_VALID]++;
    output[1] &= ~0x40; // Remove Protected bit after successful verification.
    *output_len = HDR_DATA_MAC_SIZE + encrypted_len;
    *last_pn = pn;
    // Encrypted group-key updates are also EAPOL and must stay on the ARM7,
    // rather than reaching lwIP as if they were application data.
    if (encrypted_len >= 8 && memcmp(plain, "\xAA\xAA\x03\x00\x00\x00\x88\x8E", 8) == 0)
    {
        handle_eapol(output, *output_len);
        *output_len = 0;
        return false;
    }
    return true;
}
