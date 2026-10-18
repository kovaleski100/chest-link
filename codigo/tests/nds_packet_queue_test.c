// Test the actual Ethernet/802.11 adapter. Only allocation, sync, and the
// hardware critical section are mocked; the consumer follows ARM7's offsets.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TWL_CODE
#include "../third_party/dswifi/source/arm9/lwip/rx_tx.c"

static Wifi_MainStruct wifi;
volatile Wifi_MainStruct *WifiData = &wifi;
static unsigned checks, failures, syncs;
static size_t last_allocation;
static u8 received[1500];
static size_t received_len;

#define CHECK(condition) do { \
    ++checks; \
    if (!(condition)) { \
        fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
        ++failures; \
    } \
} while (0)

int enterCriticalSection(void) { return 0; }
void leaveCriticalSection(int state) { (void)state; }
void Wifi_CallSyncHandler(void) { ++syncs; }
int Wifi_TxBufferAllocBuffer(size_t total_size)
{
    last_allocation = total_size;
    if (wifi.txbufWrite + total_size > WIFI_TXBUFFER_SIZE)
        return -1;
    return wifi.txbufWrite;
}
void dswifi_send_data_to_lwip(void *data, u32 len)
{
    if (len > sizeof(received)) abort();
    memcpy(received, data, len);
    received_len = len;
}

static void test_tx_queue(Wifi_ApSecurityType security, size_t payload_len)
{
    memset(&wifi, 0, sizeof(wifi));
    wifi.curAp.security_type = security;
    const u8 ap[6] = {2, 0, 0, 0, 0, 1};
    const u8 ds[6] = {2, 0, 0, 0, 0, 2};
    memcpy(wifi.curAp.bssid, ap, 6);
    memcpy(wifi.MacAddr, ds, 6);
    syncs = 0;

    u8 ethernet[1500] = {0};
    EthernetFrameHeader *eth = (void *)ethernet;
    memset(eth->dest_mac, 0xff, 6);
    memcpy(eth->src_mac, ds, 6);
    eth->ether_type = 0x0008; // IPv4 in network byte order on the DS.
    const size_t prefix = sizeof(Wifi_TxHeader) + HDR_DATA_MAC_SIZE + 8;
    const size_t overhead = security == AP_SECURITY_WPA2 ? 16 :
                            security == AP_SECURITY_WEP ? 8 : 0;
    const size_t frame_size = prefix + overhead + payload_len + 4;

    // DHCP Discover followed by more IPv4/IPv6/ARP traffic. A wrong cursor
    // lets the first packet through but strands everything queued after it.
    for (unsigned i = 0; i < 8; ++i) {
        memset(ethernet + sizeof(*eth), 0x30 + i, payload_len);
        const size_t start = wifi.txbufWrite;
        CHECK(Wifi_NTR_TransmitFunctionLink(ethernet,
            sizeof(*eth) + payload_len) == 0);
        CHECK(last_allocation == 4 + round_up_32(frame_size) + 4);
        CHECK((read_u32(wifi.txbufData + start) & WFLAG_SEND_SIZE_MASK) == frame_size);
        const Wifi_TxHeader *tx = (const void *)(wifi.txbufData + start + 4);
        CHECK(tx->tx_length == frame_size - sizeof(*tx));
        const size_t next = start + 4 + round_up_32(frame_size);
        CHECK(wifi.txbufWrite == next);
        CHECK(read_u32(wifi.txbufData + next) == 0);
    }

    // Mirror the ARM7 consumer: its next tag is based on the stored size,
    // not the producer's cursor. All eight frames must remain discoverable.
    size_t consumer = 0;
    unsigned consumed = 0;
    while (consumer < wifi.txbufWrite && consumed < 8) {
        const u32 tag = read_u32(wifi.txbufData + consumer);
        if (!tag) break;
        const size_t length = tag & WFLAG_SEND_SIZE_MASK;
        if (length != frame_size) break;
        const size_t body = consumer + 4 + prefix + (overhead ? overhead / 2 : 0);
        CHECK(wifi.txbufData[body] == 0x30 + consumed);
        consumer += 4 + round_up_32(length);
        ++consumed;
    }
    CHECK(consumed == 8);
    CHECK(consumer == wifi.txbufWrite);
    CHECK(syncs == 8);
}

static void test_rx_ethernet(void)
{
    memset(&wifi, 0, sizeof(wifi));
    const u8 ap[6] = {2, 0, 0, 0, 0, 1};
    const u8 ds[6] = {2, 0, 0, 0, 0, 2};
    memcpy(wifi.MacAddr, ds, 6);
    u8 frame[400] = {0};
    IEEE_DataFrameHeader *ieee = (void *)frame;
    ieee->frame_control = FC_FROM_DS | TYPE_DATA;
    memcpy(ieee->addr_1, ds, 6);
    memcpy(ieee->addr_2, ap, 6);
    memcpy(ieee->addr_3, ap, 6);
    const u8 snap[] = {0xaa, 0xaa, 3, 0, 0, 0, 8, 0};
    memcpy(frame + HDR_DATA_MAC_SIZE, snap, sizeof(snap));
    memset(frame + HDR_DATA_MAC_SIZE + sizeof(snap), 0x45, 336);
    received_len = 0;
    Wifi_NTR_SendPacketToLwip(frame, HDR_DATA_MAC_SIZE + sizeof(snap) + 336);
    CHECK(received_len == sizeof(EthernetFrameHeader) + 336);
    CHECK(memcmp(received, ds, 6) == 0);
    CHECK(memcmp(received + 6, ap, 6) == 0);
    CHECK(received[12] == 8 && received[13] == 0);
    CHECK(received[14] == 0x45 && received[received_len - 1] == 0x45);

    for (unsigned htc = 0; htc <= 1; ++htc) {
        memset(frame, 0, sizeof(frame));
        ieee = (void *)frame;
        ieee->frame_control = FC_FROM_DS | TYPE_QOS_DATA |
                              (htc ? FC_ORDER : 0);
        memcpy(ieee->addr_1, ds, 6);
        memcpy(ieee->addr_2, ap, 6);
        memcpy(ieee->addr_3, ap, 6);
        frame[24] = 5;
        const size_t header_size = 26 + (htc ? 4 : 0);
        if (htc) memset(frame + 26, 0x44, 4);
        memcpy(frame + header_size, snap, sizeof(snap));
        memset(frame + header_size + sizeof(snap), 0x46, 336);
        received_len = 0;
        Wifi_NTR_SendPacketToLwip(frame,
            header_size + sizeof(snap) + 336);
        CHECK(received_len == sizeof(EthernetFrameHeader) + 336);
        CHECK(memcmp(received, ds, 6) == 0);
        CHECK(memcmp(received + 6, ap, 6) == 0);
        CHECK(received[12] == 8 && received[13] == 0);
        CHECK(received[14] == 0x46 && received[received_len - 1] == 0x46);
    }
}

static void test_tcp_diagnostics(void)
{
    memset(&wifi, 0, sizeof(wifi));
    wifi.curAp.security_type = AP_SECURITY_WPA2;
    wifi.stats[WSTAT_NTR_TCP_LOCAL_PORT] = 65000;
    wifi.stats[WSTAT_NTR_TCP_REMOTE_PORT] = 40992;
    u8 ethernet[14 + 40] = {0};
    ethernet[12] = 8;
    u8 *ip = ethernet + 14, *tcp = ip + 20;
    ip[0] = 0x45; ip[3] = 40; ip[9] = 6;
    tcp[0] = 65000 >> 8; tcp[1] = 65000 & 255;
    tcp[2] = 40992 >> 8; tcp[3] = 40992 & 255;
    tcp[8] = 0x89; tcp[9] = 0xAB; tcp[10] = 0xCD; tcp[11] = 0xEF;
    tcp[12] = 0x50; tcp[13] = 0x10;
    Wifi_NTR_TcpInfo info;
    CHECK(Wifi_NTR_TcpFromIP(ip, 40, &info));
    CHECK(info.ack == 0x89ABCDEF && info.src == 65000 && info.dst == 40992);
    CHECK(Wifi_NTR_TcpIsTrackedAck(&wifi, &info));
    CHECK(Wifi_NTR_TransmitFunctionLink(ethernet, sizeof(ethernet)) == 0);
    CHECK(wifi.stats[WSTAT_NTR_TCP_ACK_QUEUED] == 1);
    CHECK(wifi.stats[WSTAT_NTR_TCP_ACK_VALUE] == 0x89ABCDEF);
    const u8 *queued = wifi.txbufData + 4 + sizeof(Wifi_TxHeader);
    CHECK(Wifi_NTR_TcpFromWifi(queued, 24 + 8 + 8 + 40 + 8, true, &info));
    CHECK(info.ack == 0x89ABCDEF);
    // Failed enqueue, unrelated connection, SYN/RST and malformed/fragmented
    // IP packets must not be reported as a queued ACK for this flow.
    wifi.txbufWrite = WIFI_TXBUFFER_SIZE - 4;
    CHECK(Wifi_NTR_TransmitFunctionLink(ethernet, sizeof(ethernet)) == -1);
    CHECK(wifi.stats[WSTAT_NTR_TCP_ACK_QUEUED] == 1);
    info.src--;
    CHECK(!Wifi_NTR_TcpIsTrackedAck(&wifi, &info));
    info.src++; info.flags |= 2;
    CHECK(!Wifi_NTR_TcpIsTrackedAck(&wifi, &info));
    for (unsigned len = 0; len < 40; ++len)
        CHECK(!Wifi_NTR_TcpFromIP(ip, len, &info));
    ip[6] = 0x20;
    CHECK(!Wifi_NTR_TcpFromIP(ip, 40, &info));
    ip[6] = 0; tcp[12] = 0xF0;
    CHECK(!Wifi_NTR_TcpFromIP(ip, 40, &info));
}

int main(void)
{
    test_tcp_diagnostics();
    for (size_t len = 332; len <= 339; ++len) {
        test_tx_queue(AP_SECURITY_OPEN, len);
        test_tx_queue(AP_SECURITY_WEP, len);
        test_tx_queue(AP_SECURITY_WPA2, len);
    }
    test_rx_ethernet();
    printf("NTR packet queue: %u checks, %u failures\n", checks, failures);
    return failures ? 1 : 0;
}
