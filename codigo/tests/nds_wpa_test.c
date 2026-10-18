// Exercise the real NTR supplicant and software crypto, mocking only the radio
// and DSi BIOS. Fixtures contain synthetic credentials, never captured secrets.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../third_party/dswifi/source/arm7/ntr/wpa.c"

static Wifi_MainStruct wifi;
volatile Wifi_MainStruct *WifiData = &wifi;
u32 test_reg_ime;
static u32 random_counter;
static u8 transmitted[2048];
static size_t transmitted_len;
static unsigned transmissions, failures, checks;

#define CHECK(condition) do { \
    ++checks; \
    if (!(condition)) { \
        fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
        ++failures; \
    } \
} while (0)

u32 Wifi_Random(void) { return ++random_counter; }
int Wifi_TxArm7QueueAdd(u16 *data, int length)
{
    if (length < 0 || (size_t)length > sizeof(transmitted)) abort();
    memcpy(transmitted, data, length);
    transmitted_len = length;
    ++transmissions;
    return 1;
}
// A DS-mode test must never execute DSi-only BIOS crypto.
void swiSHA1Init(swiSHA1context_t *ctx) { (void)ctx; abort(); }
void swiSHA1Update(swiSHA1context_t *ctx, const void *p, size_t n)
{ (void)ctx; (void)p; (void)n; abort(); }
void swiSHA1Final(void *p, swiSHA1context_t *ctx)
{ (void)p; (void)ctx; abort(); }

static size_t unhex(u8 *out, const char *hex)
{
    size_t length = strlen(hex) / 2;
    for (size_t i = 0; i < length; ++i) {
        unsigned byte;
        if (sscanf(hex + 2 * i, "%2x", &byte) != 1) abort();
        out[i] = byte;
    }
    return length;
}
static bool all_zero(const volatile void *buffer, size_t length)
{
    const volatile u8 *p = buffer;
    for (size_t i = 0; i < length; ++i) if (p[i]) return false;
    return true;
}

static const u8 ap_mac[6] = {2, 0, 0, 0, 0, 1};
static const u8 ds_mac[6] = {2, 0, 0, 0, 0, 2};
static const u8 snap[8] = {0xaa, 0xaa, 3, 0, 0, 0, 0x88, 0x8e};
static u8 expected_pmk[32], expected_ptk[64], wrapped_gtk[56];

static void setup_connection(void)
{
    Wifi_NTR_WpaReset();
    memset(&wifi, 0, sizeof(wifi));
    random_counter = transmissions = 0;
    transmitted_len = 0;
    memcpy(wifi.MacAddr, ds_mac, 6);
    memcpy(wifi.curAp.bssid, ap_mac, 6);
    memcpy(wifi.curAp.ssid, "IEEE", 4);
    wifi.curAp.ssid_len = 4;
    wifi.curAp.security_type = AP_SECURITY_WPA2;
    wifi.curAp.auth_type = AP_AUTH_PSK;
    wifi.curAp.pair_crypt_type = wifi.curAp.group_crypt_type = AP_CRYPT_AES;
    wifi.curAp.rsn_ie_len = unhex(wifi.curAp.rsn_ie,
        "30140100000fac040100000fac040100000fac020000");
    memcpy(wifi.curApSecurity.pass, "password", 8);
    wifi.curApSecurity.pass_len = 8;
    CHECK(Wifi_NTR_WpaPrepareConnection());
    CHECK(memcmp(wifi.curApSecurity.pmk, expected_pmk, 32) == 0);
    CHECK(all_zero(wifi.curApSecurity.pass, sizeof(wifi.curApSecurity.pass)));
    Wifi_NTR_WpaAssociationComplete();
}

static size_t make_key_frame(u8 frame[1024], u16 info, u64 replay,
                             unsigned nonce_start, const u8 *key_data,
                             size_t key_data_len, const u8 *kck)
{
    memset(frame, 0, 1024);
    frame[0] = TYPE_DATA;
    frame[1] = FC_FROM_DS >> 8;
    memcpy(frame + 4, ds_mac, 6);
    memcpy(frame + 10, ap_mac, 6);
    memcpy(frame + 16, ap_mac, 6);
    memcpy(frame + 24, snap, sizeof(snap));
    u8 *e = frame + 32;
    e[0] = 1; // The observed router uses EAPOL version 1.
    e[1] = 3;
    write_be16(e + 2, 95 + key_data_len);
    e[4] = 2;
    write_be16(e + 5, info);
    write_be16(e + 7, 16);
    write_be64(e + 9, replay);
    for (unsigned i = 0; i < 32; ++i) e[17 + i] = nonce_start + i;
    write_be16(e + 97, key_data_len);
    if (key_data_len) memcpy(e + 99, key_data, key_data_len);
    if (kck) wpa_calc_mic(kck, e, 99 + key_data_len, e + 81);
    return 32 + 99 + key_data_len;
}
static void receive(const u8 *frame, size_t length)
{
    u8 output[1024];
    size_t output_len = 999;
    CHECK(!Wifi_NTR_WpaProcessRx(frame, length, output, sizeof(output), &output_len));
    CHECK(output_len == 0); // EAPOL belongs to ARM7, not the IP stack.
}
static const u8 *last_eapol(void)
{
    CHECK(transmitted_len >= sizeof(Wifi_TxHeader) + 32 + 99);
    return transmitted + sizeof(Wifi_TxHeader) + 32;
}

static size_t make_qos_frame(u8 *frame, bool group, u8 tid, u64 pn,
                             const u8 *payload, size_t payload_len)
{
    const size_t header_len = HDR_DATA_MAC_SIZE + 2;
    memset(frame, 0, 1024);
    const u16 frame_control = TYPE_QOS_DATA | FC_FROM_DS | FC_PROTECTED_FRAME;
    frame[0] = frame_control & 0xFF;
    frame[1] = frame_control >> 8;
    if (group) memset(frame + 4, 0xFF, 6);
    else memcpy(frame + 4, ds_mac, 6);
    memcpy(frame + 10, ap_mac, 6);
    memcpy(frame + 16, ap_mac, 6);
    frame[24] = (tid & 0x0F) | 0xA0; // Non-TID QoS bits must not enter AAD.
    u8 *ccmp = frame + header_len;
    write_ccmp_header(ccmp, pn);
    if (group) ccmp[3] |= (wpa_gtk.keyidx & 3) << 6;
    u8 aad[WIFI_NTR_CCMP_AAD_MAX_SIZE], nonce[13];
    const size_t aad_len = make_ccmp_aad(frame, aad);
    make_ccmp_nonce(frame, ccmp, nonce);
    const u8 *key = group ? wpa_gtk.key : expected_ptk + 32;
    CHECK(Wifi_NTR_CcmpEncryptAad(key, nonce, aad, aad_len, payload,
        payload_len, ccmp + 8, ccmp + 8 + payload_len));
    return header_len + 16 + payload_len;
}

static void test_handshake(void)
{
    u8 frame[1024];
    setup_connection();
    size_t length = make_key_frame(frame, 0x008a, 0, 0x20, NULL, 0, NULL);
    receive(frame, length);
    CHECK(transmissions == 1);
    CHECK(memcmp(transmitted + sizeof(Wifi_TxHeader) + 16, ap_mac, 6) == 0);
    CHECK(memcmp(&wpa_ptk, expected_ptk, 64) == 0);
    CHECK(memcmp(wifi.curApSecurity.pmk, expected_pmk, 32) == 0);
    CHECK(read_be16(last_eapol() + 5) == 0x010a);
    CHECK(read_be64(last_eapol() + 9) == 0);
    CHECK(verify_eapol_mic(last_eapol(), 99 + wifi.curAp.rsn_ie_len));

    // Captured regression: this router advances its counter on M1 retries.
    length = make_key_frame(frame, 0x008a, 1, 0x20, NULL, 0, NULL);
    receive(frame, length);
    CHECK(transmissions == 2);
    CHECK(read_be64(last_eapol() + 9) == 1);
    CHECK(random_counter == 32); // Stable SNonce/PTK for the same handshake.
    CHECK(memcmp(&wpa_ptk, expected_ptk, 64) == 0);
    unsigned before = transmissions;
    receive(frame, length); // Same-counter retry is also answered.
    CHECK(transmissions == before + 1);
    before = transmissions;
    length = make_key_frame(frame, 0x008a, 0, 0x20, NULL, 0, NULL);
    receive(frame, length);
    CHECK(transmissions == before); // Reject old counter.
    length = make_key_frame(frame, 0x008a, 2, 0x40, NULL, 0, NULL);
    receive(frame, length);
    CHECK(transmissions == before); // Do not change nonce within this exchange.

    length = make_key_frame(frame, 0x13ca, 2, 0x20, wrapped_gtk, 56, expected_ptk);
    receive(frame, length);
    CHECK(Wifi_NTR_WpaIsReady());
    CHECK(wifi.authlevel == WIFI_AUTHLEVEL_ASSOCIATED);
    CHECK(read_be16(last_eapol() + 5) == 0x030a);
    CHECK(wpa_gtk.keyidx == 1);
    for (unsigned i = 0; i < 16; ++i) CHECK(wpa_gtk.key[i] == 0x40 + i);

    // Lost M4: resend without reinstalling keys/resetting replay protection.
    wpa_tx_pn = 123;
    wpa_pairwise_rx_pn[WPA_CCMP_NON_QOS_TID] = 45;
    wpa_group_rx_pn[WPA_CCMP_NON_QOS_TID] = 67;
    before = transmissions;
    receive(frame, length);
    CHECK(transmissions == before + 1);
    CHECK(wpa_tx_pn == 123 &&
          wpa_pairwise_rx_pn[WPA_CCMP_NON_QOS_TID] == 45 &&
          wpa_group_rx_pn[WPA_CCMP_NON_QOS_TID] == 67);

    // A fresh association needs fresh temporal keys but the original PMK.
    Wifi_NTR_WpaAssociationComplete();
    CHECK(!Wifi_NTR_WpaIsReady());
    CHECK(all_zero(&wpa_ptk, sizeof(wpa_ptk)));
    CHECK(all_zero(&wpa_gtk, sizeof(wpa_gtk)));
    CHECK(wpa_tx_pn == 0 && all_zero(wpa_pairwise_rx_pn, sizeof(wpa_pairwise_rx_pn)) &&
          all_zero(wpa_group_rx_pn, sizeof(wpa_group_rx_pn)));
    length = make_key_frame(frame, 0x008a, 0, 0x40, NULL, 0, NULL);
    receive(frame, length);
    u8 reassociated_ptk[64];
    unhex(reassociated_ptk,
        "e5308bdf6886e288a56f595ad9ec26d7f1671df6c6cf4b5d593acf58df1a713a3"
        "61511c9c6ce05176520fbaa6fab3a506892fe7fb3596a682a4c22800a79e5ec");
    CHECK(memcmp(&wpa_ptk, reassociated_ptk, 64) == 0);
    Wifi_NTR_WpaReset();
    CHECK(all_zero(wifi.curApSecurity.pmk, 32));
    CHECK(all_zero(&wpa_ptk, sizeof(wpa_ptk)));
}

static void test_invalid_mic(void)
{
    u8 frame[1024];
    setup_connection();
    size_t length = make_key_frame(frame, 0x008a, 0, 0x20, NULL, 0, NULL);
    receive(frame, length);
    unsigned before = transmissions;
    length = make_key_frame(frame, 0x13ca, 1, 0x20, wrapped_gtk, 56, expected_ptk);
    frame[32 + 81] ^= 1;
    receive(frame, length);
    CHECK(!Wifi_NTR_WpaIsReady());
    CHECK(transmissions == before);
    CHECK(wifi.authlevel == WIFI_AUTHLEVEL_ERROR);
    Wifi_NTR_WpaReset();
}

static void test_encrypted_receive(void)
{
    u8 frame[1024], protected_frame[1024], output[1024];
    setup_connection();
    size_t length = make_key_frame(frame, 0x008a, 0, 0x20, NULL, 0, NULL);
    receive(frame, length);
    length = make_key_frame(frame, 0x13ca, 1, 0x20, wrapped_gtk, 56, expected_ptk);
    receive(frame, length);
    CHECK(Wifi_NTR_WpaIsReady());

    // Group-key negotiation can arrive protected with the pairwise CCMP key.
    length = make_key_frame(frame, 0x1382, 2, 0, wrapped_gtk, 56, expected_ptk);
    memcpy(protected_frame, frame, 24);
    protected_frame[1] |= 0x40;
    write_ccmp_header(protected_frame + 24, 1);
    u8 aad[WIFI_NTR_CCMP_AAD_MAX_SIZE], nonce[13];
    size_t aad_len = make_ccmp_aad(protected_frame, aad);
    make_ccmp_nonce(protected_frame, protected_frame + 24, nonce);
    CHECK(Wifi_NTR_CcmpEncryptAad(expected_ptk + 32, nonce, aad, aad_len,
                                  frame + 24, length - 24,
                                  protected_frame + 32,
                                  protected_frame + length + 8));
    unsigned before = transmissions;
    receive(protected_frame, length + 16);
    CHECK(transmissions == before + 1);
    CHECK(read_be16(last_eapol() + 5) == 0x0302);
    CHECK(read_be64(last_eapol() + 9) == 2);
    CHECK(wpa_pairwise_rx_pn[WPA_CCMP_NON_QOS_TID] == 1);
    before = transmissions;
    receive(protected_frame, length + 16); // Repeated CCMP PN is rejected.
    CHECK(transmissions == before);

    // Ordinary protected data must be decrypted/forwarded, unlike EAPOL.
    const u8 payload[] = {0xaa, 0xaa, 3, 0, 0, 0, 8, 0, 0x45, 0, 0, 20};
    write_ccmp_header(protected_frame + 24, 2);
    make_ccmp_nonce(protected_frame, protected_frame + 24, nonce);
    CHECK(Wifi_NTR_CcmpEncryptAad(expected_ptk + 32, nonce, aad, aad_len,
                                  payload, sizeof(payload), protected_frame + 32,
                                  protected_frame + 32 + sizeof(payload)));
    length = 40 + sizeof(payload);
    size_t output_len = 0;
    CHECK(Wifi_NTR_WpaProcessRx(protected_frame, length, output,
                                sizeof(output), &output_len));
    CHECK(output_len == 24 + sizeof(payload));
    CHECK(!(output[1] & 0x40));
    CHECK(memcmp(output + 24, payload, sizeof(payload)) == 0);
    CHECK(wpa_pairwise_rx_pn[WPA_CCMP_NON_QOS_TID] == 2);
    receive(protected_frame, length); // Data replay is rejected too.

    // RX queue decrypts in place, moving the plaintext eight bytes to the
    // left over the CCMP header. Test DHCP-sized unicast AND GTK broadcasts.
    u8 dhcp_payload[344] = {0xaa, 0xaa, 3, 0, 0, 0, 8, 0, 0x45};
    for (size_t i = 9; i < sizeof(dhcp_payload); ++i)
        dhcp_payload[i] = (u8)i;
    for (unsigned group = 0; group <= 1; ++group) {
        protected_frame[0] = TYPE_DATA;
        protected_frame[1] = (FC_FROM_DS | FC_PROTECTED_FRAME) >> 8;
        if (group) memset(protected_frame + 4, 0xff, 6);
        else memcpy(protected_frame + 4, ds_mac, 6);
        write_ccmp_header(protected_frame + 24, 3);
        if (group) protected_frame[27] |= (wpa_gtk.keyidx & 3) << 6;
        aad_len = make_ccmp_aad(protected_frame, aad);
        make_ccmp_nonce(protected_frame, protected_frame + 24, nonce);
        const u8 *key = group ? wpa_gtk.key : expected_ptk + 32;
        CHECK(Wifi_NTR_CcmpEncryptAad(key, nonce, aad, aad_len,
            dhcp_payload, sizeof(dhcp_payload), protected_frame + 32,
            protected_frame + 32 + sizeof(dhcp_payload)));
        CHECK(Wifi_NTR_WpaProcessRx(protected_frame,
            40 + sizeof(dhcp_payload), protected_frame,
            sizeof(protected_frame), &output_len));
        CHECK(output_len == 24 + sizeof(dhcp_payload));
        CHECK(memcmp(protected_frame + 24, dhcp_payload, sizeof(dhcp_payload)) == 0);
        CHECK(!(protected_frame[1] & 0x40));
    }

    // QoS CCMP uses the TID in both its nonce and AAD, and maintains replay
    // state independently for each TID.
    const u8 qos_payload[28] = {
        0xaa, 0xaa, 3, 0, 0, 0, 8, 0, 0x45, 0, 0, 20
    };
    length = make_qos_frame(protected_frame, false, 5, 1, qos_payload,
                            sizeof(qos_payload));
    CHECK(Wifi_NTR_WpaProbeRxSize(protected_frame, length) == length);
    CHECK(Wifi_NTR_WpaProcessRx(protected_frame, length, output,
        sizeof(output), &output_len));
    CHECK(output_len == 26 + sizeof(qos_payload));
    CHECK(memcmp(output + 26, qos_payload, sizeof(qos_payload)) == 0);
    CHECK(wpa_pairwise_rx_pn[5] == 1);
    CHECK(wpa_pairwise_rx_pn[6] == 0);

    // Changing TID without recomputing CCMP must fail authentication and must
    // not advance the new TID's replay state.
    protected_frame[24] = 6 | 0xA0;
    CHECK(!Wifi_NTR_WpaProcessRx(protected_frame, length, output,
        sizeof(output), &output_len));
    CHECK(wpa_pairwise_rx_pn[6] == 0);
    length = make_qos_frame(protected_frame, false, 6, 1, qos_payload,
                            sizeof(qos_payload));
    CHECK(Wifi_NTR_WpaProcessRx(protected_frame, length, output,
        sizeof(output), &output_len));
    CHECK(wpa_pairwise_rx_pn[6] == 1);
    CHECK(!Wifi_NTR_WpaProcessRx(protected_frame, length, output,
        sizeof(output), &output_len)); // Replay on TID 6.
    CHECK(wpa_pairwise_rx_pn[5] == 1);
    Wifi_NTR_WpaReset();
}

static void test_ccmp(void)
{
    const u8 plain[] = "WPA2 software CCMP test";
    const size_t length = sizeof(plain) - 1;
    u8 key[16], nonce[13], aad[22], expected[64], cipher[64], mic[8], decoded[64];
    for (unsigned i = 0; i < sizeof(key); ++i) key[i] = i;
    for (unsigned i = 0; i < sizeof(nonce); ++i) nonce[i] = i;
    for (unsigned i = 0; i < sizeof(aad); ++i) aad[i] = i;
    // Independent Python cryptography AESCCM (8-byte tag) fixture.
    CHECK(unhex(expected, "4164f5ba737a95e42ee052d5f8145d9bae502456135e056f4c462f7f05e8c3") == length + 8);
    CHECK(Wifi_NTR_CcmpEncrypt(key, nonce, aad, plain, length, cipher, mic));
    CHECK(memcmp(cipher, expected, length) == 0);
    CHECK(memcmp(mic, expected + length, 8) == 0);
    CHECK(Wifi_NTR_CcmpDecrypt(key, nonce, aad, cipher, length, mic, decoded));
    CHECK(memcmp(decoded, plain, length) == 0);
    memcpy(decoded, plain, length);
    CHECK(Wifi_NTR_CcmpEncrypt(key, nonce, aad, decoded, length, decoded, mic));
    CHECK(memcmp(decoded, expected, length) == 0);
    CHECK(Wifi_NTR_CcmpDecrypt(key, nonce, aad, decoded, length, mic, decoded));
    CHECK(memcmp(decoded, plain, length) == 0);
    mic[0] ^= 1;
    CHECK(!Wifi_NTR_CcmpDecrypt(key, nonce, aad, cipher, length, mic, decoded));
    CHECK(all_zero(decoded, length));

    const u8 qos_plain[] = "QoS CCMP test vector";
    u8 qos_aad[WIFI_NTR_CCMP_AAD_MAX_SIZE];
    for (unsigned i = 0; i < sizeof(qos_aad); ++i) qos_aad[i] = i;
    CHECK(unhex(expected,
        "475be7a8104ab7d27ae356d4e91468bd80746b50f19e86e5f0b46aeb") ==
        sizeof(qos_plain) - 1 + 8);
    CHECK(Wifi_NTR_CcmpEncryptAad(key, nonce, qos_aad, sizeof(qos_aad),
        qos_plain, sizeof(qos_plain) - 1, cipher, mic));
    CHECK(memcmp(cipher, expected, sizeof(qos_plain) - 1) == 0);
    CHECK(memcmp(mic, expected + sizeof(qos_plain) - 1, 8) == 0);
    CHECK(Wifi_NTR_CcmpDecryptAad(key, nonce, qos_aad, sizeof(qos_aad),
        cipher, sizeof(qos_plain) - 1, mic, decoded));
    CHECK(memcmp(decoded, qos_plain, sizeof(qos_plain) - 1) == 0);
}

static void test_hardware_rx_crop(void)
{
    CHECK(Wifi_NTR_RxCropForSecurity(AP_SECURITY_WPA2) == 0x0202);
    CHECK(Wifi_NTR_RxCropForSecurity(AP_SECURITY_OPEN) == 0x0602);
    CHECK(Wifi_NTR_RxCropForSecurity(AP_SECURITY_WEP) == 0x0602);
    u8 frame[1024], wire[1024], output[1024];
    setup_connection();
    size_t length = make_key_frame(frame, 0x008a, 0, 0x20, NULL, 0, NULL);
    receive(frame, length);
    length = make_key_frame(frame, 0x13ca, 1, 0x20, wrapped_gtk, 56, expected_ptk);
    receive(frame, length);
    memcpy(wire, frame, 24);
    wire[1] |= 0x40;
    write_ccmp_header(wire + 24, 1);
    u8 payload[344] = {0xaa, 0xaa, 3, 0, 0, 0, 8, 0, 0x45};
    u8 aad[WIFI_NTR_CCMP_AAD_MAX_SIZE], nonce[13];
    const size_t aad_len = make_ccmp_aad(wire, aad);
    make_ccmp_nonce(wire, wire + 24, nonce);
    CHECK(Wifi_NTR_CcmpEncryptAad(expected_ptk + 32, nonce, aad, aad_len,
        payload, sizeof(payload), wire + 32, wire + 32 + sizeof(payload)));
    const size_t wire_length = 24 + 8 + sizeof(payload) + 8 + 4;
    size_t output_length;
    // The previous register value excludes 12 bytes instead of FCS alone.
    // Simulate the documented size field, not physical RF/IV transformations.
    CHECK(!Wifi_NTR_WpaProcessRx(wire, wire_length - 12, output,
        sizeof(output), &output_length));
    CHECK(WifiData->stats[WSTAT_NTR_CCMP_MIC_FAILED] == 1);
    CHECK(wpa_pairwise_rx_pn[WPA_CCMP_NON_QOS_TID] == 0); // Bad MIC must not advance replay state.
    const unsigned crop = (Wifi_NTR_RxCropForSecurity(AP_SECURITY_WPA2) >> 8) * 2;
    CHECK(Wifi_NTR_WpaProcessRx(wire, wire_length - crop, output,
        sizeof(output), &output_length));
    CHECK(output_length == 24 + sizeof(payload));
    CHECK(memcmp(output + 24, payload, sizeof(payload)) == 0);
    CHECK(WifiData->stats[WSTAT_NTR_CCMP_RX] == 2);
    CHECK(WifiData->stats[WSTAT_NTR_CCMP_VALID] == 1);
    Wifi_NTR_WpaReset();
}

int main(void)
{
    // IEEE/password PMK, PTKs from independent Python hashlib/hmac PRF.
    unhex(expected_pmk, "f42c6fc52df0ebef9ebb4b90b38a5f902e83fe1b135a70e23aed762e9710a12e");
    unhex(expected_ptk,
        "780efffe43dfbbe7cc3ac7765c6f9293196ea7589c3971ab1dde6a3f71e5a9ae2"
        "d7322b5c5adf723dd519ceaaf1b662578a71f0a738735a59f688ea4c2e4cd18");
    unhex(wrapped_gtk,
        "ec20a4839b5ce1bd8502f7a8174748769a69e52db8183cdaf164f7dc429938445"
        "985a078e631f9c6857c2e2b9e4c7e6ed74b8a998547eecf");
    test_handshake();
    test_invalid_mic();
    test_encrypted_receive();
    test_ccmp();
    test_hardware_rx_crop();
    printf("NTR WPA2: %u checks, %u failures\n", checks, failures);
    return failures ? 1 : 0;
}
