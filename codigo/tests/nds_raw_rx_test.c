// Test the real RX adapter + CCMP with simulated MAC RAM. This proves
// admission/safety, NOT that the physical NTR chip stores rejected frames.
#define main wpa_fixture_tests
#include "nds_wpa_test.c"
#undef main

#include "arm7/ntr/registers.h"
static u16 registers[0x8000 / 2];
static u16 *reg_address(unsigned offset)
{
    if ((offset & 1) || offset / 2 >= sizeof(registers) / sizeof(registers[0]))
        abort();
    return &registers[offset / 2];
}
#undef WIFI_REG
#define WIFI_REG(ofs) (*reg_address((ofs) & 0x7FFF))
#include "../third_party/dswifi/source/arm7/ntr/rx_queue.c"

static unsigned reads, mutate_at, queue_syncs;
static bool queue_full;
static u32 ring_address(u32 base, u32 offset)
{
    const u32 begin = W_RXBUF_BEGIN & 0x1FFE;
    const u32 end = W_RXBUF_END & 0x1FFE;
    if (begin >= end || base < begin || base >= end) abort();
    return begin + (base - begin + offset) % (end - begin);
}
u16 Wifi_MACReadHWord(u32 base, u32 offset)
{
    ++reads;
    if (mutate_at && reads == mutate_at) {
        u32 address = ring_address(base, HDR_RX_SIZE);
        W_MACMEM(address) ^= 1;
    }
    return W_MACMEM(ring_address(base, offset));
}
void Wifi_MACRead(u16 *dest, u32 base, u32 offset, int length)
{
    for (int i = 0; i < (length + 1) / 2; ++i)
        dest[i] = Wifi_MACReadHWord(base, offset + 2 * i);
}
int enterCriticalSection(void) { return 0; }
void leaveCriticalSection(int state) { (void)state; }
void Wifi_CallSyncHandler(void) { ++queue_syncs; }
void Wifi_NTR_KeepaliveCountReset(void) { }
int Wifi_RxBufferAllocBuffer(size_t total_size)
{
    if (queue_full || wifi.rxbufWrite + total_size > WIFI_RXBUFFER_SIZE) return -1;
    return wifi.rxbufWrite;
}
int Wifi_ProcessReceivedFrame(int base, int length)
{
    (void)length;
    return Wifi_IsDataPayloadFrame(Wifi_MACReadHWord(base, HDR_RX_SIZE))
           ? WFLAG_PACKET_DATA : 0;
}

static void ready_radio(unsigned base)
{
    memset(registers, 0, sizeof(registers));
    reads = mutate_at = queue_syncs = 0;
    queue_full = false;
    setup_connection();
    u8 frame[1024];
    size_t length = make_key_frame(frame, 0x008a, 0, 0x20, NULL, 0, NULL);
    receive(frame, length);
    length = make_key_frame(frame, 0x13ca, 1, 0x20, wrapped_gtk, 56, expected_ptk);
    receive(frame, length);
    CHECK(Wifi_NTR_WpaIsReady());
    W_RXBUF_BEGIN = MAC_RXBUF_START_ADDRESS;
    W_RXBUF_END = MAC_RXBUF_END_ADDRESS;
    W_RXBUF_WRCSR = W_RXBUF_READCSR = base / 2;
    Wifi_RxQueueResetRejected();
}

static size_t wire_frame(u8 *frame, bool group, u64 pn, size_t payload_size)
{
    memset(frame, 0, 1024);
    frame[0] = TYPE_DATA;
    frame[1] = (FC_FROM_DS | FC_PROTECTED_FRAME) >> 8;
    memcpy(frame + 4, ds_mac, 6);
    if (group) memset(frame + 4, 0xff, 6);
    memcpy(frame + 10, ap_mac, 6);
    memcpy(frame + 16, ap_mac, 6);
    write_ccmp_header(frame + 24, pn);
    if (group) frame[27] |= (wpa_gtk.keyidx & 3) << 6;
    u8 payload[344] = {0xaa, 0xaa, 3, 0, 0, 0, 8, 0, 0x45};
    if (payload_size > sizeof(payload)) abort();
    for (size_t i = 9; i < payload_size; ++i) payload[i] = (u8)i;
    if (payload_size >= 28) {
        payload[10] = (payload_size - 8) >> 8;
        payload[11] = payload_size - 8;
    }
    u8 aad[WIFI_NTR_CCMP_AAD_MAX_SIZE], nonce[13];
    const size_t aad_len = make_ccmp_aad(frame, aad);
    make_ccmp_nonce(frame, frame + 24, nonce);
    CHECK(Wifi_NTR_CcmpEncryptAad(group ? wpa_gtk.key : expected_ptk + 32,
        nonce, aad, aad_len, payload, payload_size, frame + 32,
        frame + 32 + payload_size));
    return 40 + payload_size;
}

static void store_tail(const u8 *frame, size_t length)
{
    const u32 base = W_RXBUF_WRCSR * 2;
    W_MACMEM(ring_address(base, HDR_RX_IEEE_FRAME_SIZE)) = length;
    for (size_t i = 0; i < (length + 1) / 2; ++i) {
        u16 value = frame[2 * i];
        if (2 * i + 1 < length) value |= (u16)frame[2 * i + 1] << 8;
        W_MACMEM(ring_address(base, HDR_RX_SIZE + 2 * i)) = value;
    }
    reads = 0;
}

static u32 fixture_crc(const u8 *data, size_t length)
{
    u32 crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < length; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1) ? 0xEDB88320u : 0);
    }
    return ~crc;
}

static void store_tail_with_fcs(u8 *frame, size_t length, u16 reported_size)
{
    const u32 crc = fixture_crc(frame, length);
    for (unsigned i = 0; i < 4; ++i) frame[length + i] = crc >> (i * 8);
    store_tail(frame, length + 4);
    W_MACMEM(ring_address(W_RXBUF_WRCSR * 2, HDR_RX_IEEE_FRAME_SIZE)) = reported_size;
}

static void test_uncommitted_length(void)
{
    CHECK(fixture_crc((const u8 *)"123456789", 9) == 0xCBF43926u);
    u8 frame[1024];
    for (unsigned wrap = 0; wrap <= 1; ++wrap) {
        for (unsigned stale = 0; stale < 4; ++stale) {
            const u32 base = wrap ? MAC_RXBUF_END_OFFSET - 16 : MAC_RXBUF_START_OFFSET;
            ready_radio(base);
            const size_t length = wire_frame(frame, false, 1, 336);
            // Last accepted M3 length, a previous larger frame, zero, and an
            // uncropped wire length. None identifies this rejected frame.
            const u16 reported[] = {187, 500, 0, length + 4};
            store_tail_with_fcs(frame, length, reported[stale]);
            Wifi_RxQueueFlush();
            CHECK(queue_syncs == 1);
            CHECK(wifi.stats[WSTAT_NTR_CCMP_VALID] == 1);
            CHECK(wpa_pairwise_rx_pn[WPA_CCMP_NON_QOS_TID] == 1);
            CHECK(wifi.stats[WSTAT_NTR_RX_FCS_BOUNDARY] == 1);
            CHECK(wifi.stats[WSTAT_NTR_RX_REPORTED_SIZE] == reported[stale]);
            CHECK(wifi.stats[WSTAT_NTR_RX_FRAME_SIZE] == length);
            CHECK(read_u32((const u8 *)wifi.rxbufData) == length - 16);
            CHECK(W_RXBUF_WRCSR == base / 2 && W_RXBUF_READCSR == base / 2);
        }
    }
}

static void test_no_fcs_and_bad_mic(void)
{
    u8 frame[1024];
    for (unsigned group = 0; group <= 1; ++group) {
        ready_radio(MAC_RXBUF_END_OFFSET - 16);
        const size_t length = wire_frame(frame, group, 1, 336);
        CHECK(Wifi_NTR_WpaProbeRxSize(frame, length) == length);
        store_tail(frame, length); // No on-air FCS is present in this RAM image.
        W_MACMEM(ring_address(W_RXBUF_WRCSR * 2, HDR_RX_IEEE_FRAME_SIZE)) = 187;
        Wifi_RxQueueFlush();
        CHECK(queue_syncs == 1);
        CHECK(wifi.stats[WSTAT_NTR_CCMP_VALID] == 1);
        CHECK(wifi.stats[WSTAT_NTR_RX_FCS_BOUNDARY] == 0);
        CHECK(wifi.stats[WSTAT_NTR_RX_FRAME_SIZE] == length);

        ready_radio(MAC_RXBUF_START_OFFSET);
        const size_t bad_length = wire_frame(frame, group, 1, 336);
        frame[bad_length - 1] ^= 1; // Valid-looking length, invalid CCMP tag.
        store_tail_with_fcs(frame, bad_length, 187); // CRC is valid, MIC isn't.
        Wifi_RxQueueFlush();
        CHECK(queue_syncs == 0);
        CHECK(wifi.stats[WSTAT_NTR_RX_FCS_BOUNDARY] == 1);
        CHECK(wifi.stats[WSTAT_NTR_CCMP_MIC_FAILED] == 1);
        CHECK(wifi.stats[WSTAT_NTR_CCMP_VALID] == 0);
        CHECK(all_zero(wpa_pairwise_rx_pn, sizeof(wpa_pairwise_rx_pn)) &&
              all_zero(wpa_group_rx_pn, sizeof(wpa_group_rx_pn)));
    }
}

static void test_prefix_boundaries(void)
{
    u8 key[16] = {0}, nonce[13] = {0}, aad[22] = {0};
    u8 plain[120] = {0xaa, 0xaa, 3, 0, 0, 0}, cipher[120] = {0}, tag[8];
    size_t length = 999;
    CHECK(!Wifi_NTR_CcmpProbePayloadLength(key, nonce, cipher, 15, &length));
    CHECK(length == 0);
    for (unsigned protocol = 0; protocol < 4; ++protocol) {
        memset(plain + 6, 0, sizeof(plain) - 6);
        size_t expected;
        if (protocol == 0) {
            plain[6] = 8; plain[8] = 0x45; plain[11] = 64;
            expected = 8 + 64;
        } else if (protocol == 1) {
            plain[6] = 8; plain[7] = 6;
            memcpy(plain + 8, "\0\x01\x08\0\x06\x04", 6);
            expected = 8 + 28;
        } else if (protocol == 2) {
            plain[6] = 0x86; plain[7] = 0xdd; plain[8] = 0x60; plain[13] = 32;
            expected = 8 + 40 + 32;
        } else {
            plain[6] = 0x88; plain[7] = 0x8e; plain[8] = 1; plain[9] = 3; plain[11] = 95;
            expected = 8 + 4 + 95;
        }
        CHECK(Wifi_NTR_CcmpEncrypt(key, nonce, aad, plain, sizeof(plain), cipher, tag));
        CHECK(Wifi_NTR_CcmpProbePayloadLength(key, nonce, cipher, sizeof(cipher), &length));
        CHECK(length == expected);
        CHECK(!Wifi_NTR_CcmpProbePayloadLength(key, nonce, cipher, expected - 1, &length));
        CHECK(length == 0);
    }
    plain[0] ^= 1; // An unknown/deformed SNAP prefix is not a size oracle.
    CHECK(Wifi_NTR_CcmpEncrypt(key, nonce, aad, plain, sizeof(plain), cipher, tag));
    CHECK(!Wifi_NTR_CcmpProbePayloadLength(key, nonce, cipher, sizeof(cipher), &length));
    CHECK(length == 0);
}

static void test_recovery(void)
{
    u8 frame[1024];
    for (unsigned group = 0; group <= 1; ++group) {
        // Exercise a normal tail and one whose header/body wraps the ring.
        for (unsigned wrap = 0; wrap <= 1; ++wrap) {
            const u32 base = wrap ? MAC_RXBUF_END_OFFSET - 16 : MAC_RXBUF_START_OFFSET;
            ready_radio(base);
            size_t length = wire_frame(frame, group, 1, 343);
            store_tail(frame, length);
            Wifi_RxQueueFlush();
            CHECK(queue_syncs == 1);
            CHECK(wifi.stats[WSTAT_NTR_RX_RAM_CANDIDATES] == 1);
            CHECK(wifi.stats[WSTAT_NTR_CCMP_VALID] == 1);
            CHECK(W_RXBUF_WRCSR == base / 2 && W_RXBUF_READCSR == base / 2);
            const u8 *queued = (const u8 *)wifi.rxbufData;
            CHECK(read_u32(queued) == 24 + 343);
            CHECK(!(queued[4 + 1] & 0x40));
            CHECK(memcmp(queued + 4 + 24, "\xaa\xaa\x03\0\0\0\x08\0\x45", 9) == 0);
            Wifi_RxQueueFlush();
            CHECK(queue_syncs == 1); // Unchanged RAM is not queued repeatedly.
            CHECK(wifi.stats[WSTAT_NTR_RX_RAM_CANDIDATES] == 1);
            Wifi_RxQueueResetRejected();
            Wifi_RxQueueFlush();
            CHECK(queue_syncs == 1); // CCMP replay still blocks after cache reset.
            CHECK(wifi.stats[WSTAT_NTR_CCMP_VALID] == 1);
        }
    }
}

static void test_qos_recovery(void)
{
    const u8 payload[343] = {
        0xaa, 0xaa, 3, 0, 0, 0, 8, 0, 0x45
    };
    u8 frame[1024];
    for (unsigned group = 0; group <= 1; ++group) {
        const u8 tid = group ? 7 : 5;
        ready_radio(MAC_RXBUF_START_OFFSET);
        const size_t length = make_qos_frame(frame, group, tid, 1,
                                              payload, sizeof(payload));
        CHECK(length == 42 + sizeof(payload));
        store_tail_with_fcs(frame, length, 187);
        Wifi_RxQueueFlush();
        CHECK(queue_syncs == 1);
        CHECK(wifi.stats[WSTAT_NTR_RX_RAM_CANDIDATES] == 1);
        CHECK(wifi.stats[WSTAT_NTR_CCMP_VALID] == 1);
        CHECK(wpa_pairwise_rx_pn[tid] == (group ? 0 : 1));
        CHECK(wpa_group_rx_pn[tid] == (group ? 1 : 0));
        const u8 *queued = (const u8 *)wifi.rxbufData;
        CHECK(read_u32(queued) == 26 + sizeof(payload));
        CHECK(queued[4 + 24] == (tid | 0xA0));
        CHECK(memcmp(queued + 4 + 26, payload, sizeof(payload)) == 0);
        CHECK(!(queued[4 + 1] & 0x40));
    }
}

static void test_rejection(void)
{
    u8 frame[1024];
    ready_radio(MAC_RXBUF_START_OFFSET);
    size_t length = wire_frame(frame, false, 1, 344);
    frame[length - 1] ^= 1;
    store_tail(frame, length);
    Wifi_RxQueueFlush();
    CHECK(queue_syncs == 0);
    CHECK(wpa_pairwise_rx_pn[WPA_CCMP_NON_QOS_TID] == 0);
    CHECK(wifi.stats[WSTAT_NTR_CCMP_MIC_FAILED] == 1);
    // A later complete/valid image must be retried, not blocked by the cache.
    frame[length - 1] ^= 1;
    store_tail(frame, length);
    Wifi_RxQueueFlush();
    CHECK(queue_syncs == 1);
    CHECK(wpa_pairwise_rx_pn[WPA_CCMP_NON_QOS_TID] == 1);

    ready_radio(MAC_RXBUF_START_OFFSET);
    length = wire_frame(frame, false, 1, 344);
    store_tail(frame, length);
    mutate_at = 2 + (length + 1) / 2; // Change RAM during the second read.
    Wifi_RxQueueFlush();
    CHECK(queue_syncs == 0);
    CHECK(wifi.stats[WSTAT_NTR_RX_RAM_CANDIDATES] == 0);
    CHECK(wpa_pairwise_rx_pn[WPA_CCMP_NON_QOS_TID] == 0);

    for (unsigned guard = 0; guard < 6; ++guard) {
        ready_radio(MAC_RXBUF_START_OFFSET);
        length = wire_frame(frame, false, 1, 344);
        if (guard == 0) frame[4] ^= 2; // Not addressed to this console.
        if (guard == 1) frame[10] ^= 2; // Wrong AP.
        store_tail(frame, length);
        if (guard == 2) wifi.curAp.security_type = AP_SECURITY_OPEN;
        if (guard == 3) wifi.curAp.security_type = AP_SECURITY_WEP;
        if (guard == 4) wifi.reqFlags |= WFLAG_REQ_PROMISC;
        if (guard == 5) Wifi_NTR_WpaReset();
        Wifi_RxQueueFlush();
        CHECK(queue_syncs == 0);
        CHECK(wifi.stats[WSTAT_NTR_RX_RAM_CANDIDATES] == 0);
    }

    for (unsigned bad_size = 0; bad_size < 2; ++bad_size) {
        ready_radio(MAC_RXBUF_START_OFFSET);
        W_MACMEM(MAC_RXBUF_START_OFFSET + HDR_RX_IEEE_FRAME_SIZE) = bad_size ? 65535 : 39;
        Wifi_RxQueueFlush();
        CHECK(reads <= 17); // Only inspect the fixed header, never a bogus size.
        CHECK(queue_syncs == 0);
    }
    ready_radio(MAC_RXBUF_START_OFFSET);
    W_RXBUF_WRCSR = W_RXBUF_READCSR = 0;
    Wifi_RxQueueFlush();
    CHECK(reads == 0);

    ready_radio(MAC_RXBUF_START_OFFSET);
    length = wire_frame(frame, false, 1, 344);
    store_tail(frame, length);
    queue_full = true;
    Wifi_RxQueueFlush();
    CHECK(queue_syncs == 0);
    CHECK(wifi.stats[WSTAT_RXQUEUEDLOST] == 0);
    CHECK(wifi.stats[WSTAT_NTR_RX_BACKPRESSURE] == 1);
    CHECK(W_RXBUF_WRCSR == MAC_RXBUF_START_OFFSET / 2);
    CHECK(W_RXBUF_READCSR == MAC_RXBUF_START_OFFSET / 2);
    // Backpressure must not consume the replay number or cache this frame as
    // handled. It is still intact in MAC RAM and must be deliverable once the
    // ARM9 drains its queue, without requiring another radio transmission.
    CHECK(wpa_pairwise_rx_pn[WPA_CCMP_NON_QOS_TID] == 0);
    queue_full = false;
    Wifi_RxQueueFlush();
    CHECK(queue_syncs == 1);
    CHECK(wpa_pairwise_rx_pn[WPA_CCMP_NON_QOS_TID] == 1);
    Wifi_RxQueueFlush();
    CHECK(queue_syncs == 1);
    CHECK(wifi.stats[WSTAT_NTR_CCMP_VALID] == 1);

    // The committed receive path must also leave both the hardware cursor
    // and replay state untouched while the ARM9 has no room.
    ready_radio(MAC_RXBUF_START_OFFSET);
    length = wire_frame(frame, false, 1, 344);
    store_tail(frame, length);
    const u32 next = (MAC_RXBUF_START_OFFSET + HDR_RX_SIZE + round_up_32(length)) / 2;
    W_RXBUF_WRCSR = next;
    queue_full = true;
    Wifi_RxQueueFlush();
    CHECK(queue_syncs == 0);
    CHECK(W_RXBUF_READCSR == MAC_RXBUF_START_OFFSET / 2);
    CHECK(wpa_pairwise_rx_pn[WPA_CCMP_NON_QOS_TID] == 0);
    queue_full = false;
    Wifi_RxQueueFlush();
    CHECK(queue_syncs == 1);
    CHECK(W_RXBUF_READCSR == next);
    CHECK(wpa_pairwise_rx_pn[WPA_CCMP_NON_QOS_TID] == 1);
}

static void test_authenticated_tcp_diagnostics(void)
{
    ready_radio(MAC_RXBUF_START_OFFSET);
    u8 payload[8 + 20 + 20 + 64] = {0xAA, 0xAA, 3, 0, 0, 0, 8, 0};
    u8 *ip = payload + 8, *tcp = ip + 20;
    ip[0] = 0x45; ip[3] = sizeof(payload) - 8; ip[9] = 6;
    tcp[0] = 40992 >> 8; tcp[1] = 40992 & 255;
    tcp[2] = 65000 >> 8; tcp[3] = 65000 & 255;
    tcp[4] = 0x12; tcp[5] = 0x34; tcp[6] = 0x56; tcp[7] = 0x78;
    tcp[12] = 0x50; tcp[13] = 0x18;
    u8 frame[1024];
    const size_t length = make_qos_frame(frame, false, 5, 1, payload, sizeof(payload));
    store_tail_with_fcs(frame, length, 187);
    Wifi_RxQueueFlush();
    CHECK(queue_syncs == 1);
    CHECK(wifi.stats[WSTAT_NTR_TCP_RADIO_PACKETS] == 1);
    CHECK(wifi.stats[WSTAT_NTR_TCP_RADIO_SEQ] == 0x12345678);
    CHECK(wifi.stats[WSTAT_NTR_TCP_RADIO_BYTES] == 64);
    CHECK(wifi.stats[WSTAT_NTR_TCP_LOCAL_PORT] == 65000);
    CHECK(wifi.stats[WSTAT_NTR_TCP_REMOTE_PORT] == 40992);
}

int main(void)
{
    if (wpa_fixture_tests()) return 1;
    unsigned previous = checks;
    test_recovery();
    test_qos_recovery();
    test_rejection();
    test_uncommitted_length();
    test_no_fcs_and_bad_mic();
    test_prefix_boundaries();
    test_authenticated_tcp_diagnostics();
    printf("NTR rejected-RAM RX: %u checks, %u failures (simulated hardware)\n",
           checks - previous, failures);
    return failures ? 1 : 0;
}
