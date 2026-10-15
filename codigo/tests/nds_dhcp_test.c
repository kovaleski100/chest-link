// Real lwIP DHCP/UDP/IP/timer code and real NTR Ethernet adapter. The clock and
// radio are synthetic. No live router credentials or captured payloads used.
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define TWL_CODE
#include "../third_party/dswifi/source/arm9/lwip/rx_tx.c"
#include "lwip/init.h"
#include "lwip/dhcp.h"
#include "lwip/etharp.h"
#include "lwip/dns.h"
#include "lwip/inet_chksum.h"
#include "lwip/timeouts.h"
#include "lwip/prot/dhcp.h"
#include "netif/ethernet.h"

static Wifi_MainStruct wifi;
volatile Wifi_MainStruct *WifiData = &wifi;
static struct netif interface;
static unsigned checks, failures;
static u32_t clock_ms;
static const u8 ap[6] = {2, 0, 0, 0, 0, 1};
static const u8 ds[6] = {2, 0, 0, 0, 0, 2};

#define CHECK(condition) do { ++checks; if (!(condition)) { \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); ++failures; \
} } while (0)

u32_t sys_now(void) { return clock_ms; }
u32_t sys_jiffies(void) { return clock_ms; }
u32 Wifi_Random(void) { return 0x12345678; }
int enterCriticalSection(void) { return 0; }
void leaveCriticalSection(int state) { (void)state; }
void Wifi_CallSyncHandler(void) {}
int Wifi_TxBufferAllocBuffer(size_t size)
{
    if (wifi.txbufWrite + size >= WIFI_TXBUFFER_SIZE) return -1;
    return wifi.txbufWrite;
}
void dswifi_send_data_to_lwip(void *data, u32 size)
{
    struct pbuf *p = pbuf_alloc(PBUF_RAW, size, PBUF_RAM);
    if (!p) abort();
    if (pbuf_take(p, data, size) != ERR_OK) abort();
    if (interface.input(p, &interface) != ERR_OK) pbuf_free(p);
}
static err_t link_output(struct netif *n, struct pbuf *p)
{
    (void)n;
    u8 ethernet[1500];
    if (p->tot_len > sizeof(ethernet)) return ERR_BUF;
    pbuf_copy_partial(p, ethernet, p->tot_len, 0);
    return Wifi_NTR_TransmitFunctionLink(ethernet, p->tot_len) ? ERR_MEM : ERR_OK;
}
static err_t init_netif(struct netif *n)
{
    n->name[0] = 'd'; n->name[1] = 's';
    n->output = etharp_output;
    n->linkoutput = link_output;
    n->hwaddr_len = 6;
    memcpy(n->hwaddr, ds, 6);
    n->mtu = 1300;
    n->hostname = "synthetic-ds";
    n->flags = NETIF_FLAG_BROADCAST | NETIF_FLAG_ETHARP | NETIF_FLAG_ETHERNET;
    return ERR_OK;
}
static void advance(unsigned milliseconds)
{
    for (unsigned i = 0; i < milliseconds / 100; ++i) {
        clock_ms += 100;
        sys_check_timeouts();
    }
}
static unsigned queued_dhcp(u8 type)
{
    size_t cursor = 0;
    unsigned count = 0;
    while (cursor < wifi.txbufWrite) {
        const u32 tag = read_u32(wifi.txbufData + cursor);
        if (!tag) break; // Same condition that stops the ARM7 consumer.
        const size_t size = tag & WFLAG_SEND_SIZE_MASK;
        if (size < sizeof(Wifi_TxHeader) + 24 + 8 + 8 + 12 ||
            cursor + 4 + round_up_32(size) > wifi.txbufWrite)
            break;
        const u8 *ip = wifi.txbufData + cursor + 4 + sizeof(Wifi_TxHeader) + 24 + 8 + 8;
        if (size >= sizeof(Wifi_TxHeader) + 24 + 8 + 8 + 28 + 240 + 3 + 12 &&
            ip[0] == 0x45 && ip[9] == 17 && ip[20] == 0 && ip[21] == 68 &&
            ip[28 + 240] == 53 && ip[28 + 242] == type)
            ++count;
        cursor += 4 + round_up_32(size);
    }
    return count;
}
static void deliver_reply(u8 type, bool broadcast)
{
    u8 frame[700] = {0};
    IEEE_DataFrameHeader *ieee = (void *)frame;
    ieee->frame_control = TYPE_DATA | FC_FROM_DS;
    if (broadcast) memset(ieee->addr_1, 0xff, 6);
    else memcpy(ieee->addr_1, ds, 6);
    memcpy(ieee->addr_2, ap, 6);
    memcpy(ieee->addr_3, ap, 6);
    const u8 snap[] = {0xaa, 0xaa, 3, 0, 0, 0, 8, 0};
    memcpy(frame + 24, snap, 8);
    u8 *ip = frame + 32, *udp = ip + 20;
    struct dhcp_msg *msg = (void *)(udp + 8);
    msg->op = DHCP_BOOTREPLY; msg->htype = 1; msg->hlen = 6;
    msg->xid = lwip_htonl(netif_dhcp_data(&interface)->xid);
    IP4_ADDR(&msg->yiaddr, 10, 0, 0, 25);
    memcpy(msg->chaddr, ds, 6);
    msg->cookie = PP_HTONL(DHCP_MAGIC_COOKIE);
    const u8 options[] = {
        53, 1, type, 54, 4, 10, 0, 0, 1,
        51, 4, 0, 0, 0x0e, 0x10, 1, 4, 255, 255, 255, 0,
        3, 4, 10, 0, 0, 1, 6, 4, 10, 0, 0, 1, 255
    };
    memcpy(msg->options, options, sizeof(options));
    const size_t udp_size = 8 + 240 + sizeof(options);
    const size_t ip_size = 20 + udp_size;
    ip[0] = 0x45; ip[2] = (u8)(ip_size >> 8); ip[3] = (u8)ip_size;
    ip[8] = 64; ip[9] = 17;
    ip[12] = 10; ip[15] = 1;
    if (broadcast) memset(ip + 16, 255, 4);
    else { ip[16] = 10; ip[19] = 25; }
    const u16 checksum = inet_chksum(ip, 20);
    memcpy(ip + 10, &checksum, 2);
    udp[1] = 67; udp[3] = 68;
    udp[4] = (u8)(udp_size >> 8); udp[5] = (u8)udp_size;
    // A zero IPv4 UDP checksum is permitted. IP checksum is real.
    Wifi_NTR_SendPacketToLwip(frame, 32 + ip_size);
}
static void run_exchange(bool broadcast)
{
    dhcp_stop(&interface);
    netif_set_link_down(&interface);
    const ip4_addr_t zero = {0};
    netif_set_addr(&interface, &zero, &zero, &zero);
    wifi.txbufRead = wifi.txbufWrite = 0;
    memset(wifi.txbufData, 0, sizeof(wifi.txbufData));
    netif_set_link_up(&interface);
    CHECK(dhcp_start(&interface) == ERR_OK);
    CHECK(queued_dhcp(DHCP_DISCOVER) == 1);
    CHECK(!dhcp_supplied_address(&interface));
    // Simulate one lost Discover; its retry must remain reachable in the queue.
    advance(2500);
    CHECK(queued_dhcp(DHCP_DISCOVER) >= 2);
    deliver_reply(DHCP_OFFER, broadcast);
    CHECK(netif_dhcp_data(&interface)->state == DHCP_STATE_REQUESTING);
    CHECK(queued_dhcp(DHCP_REQUEST) == 1);
    CHECK(!dhcp_supplied_address(&interface));
    deliver_reply(DHCP_ACK, broadcast);
    CHECK(dhcp_supplied_address(&interface));
    CHECK(ip4_addr_get_u32(netif_ip4_addr(&interface)) == PP_HTONL(0x0a000019));
    CHECK(ip4_addr_get_u32(netif_ip4_gw(&interface)) == PP_HTONL(0x0a000001));
    CHECK(ip4_addr_get_u32(netif_ip4_netmask(&interface)) == PP_HTONL(0xffffff00));
    CHECK(ip4_addr_get_u32(ip_2_ip4(dns_getserver(0))) == PP_HTONL(0x0a000001));
}
int main(void)
{
    wifi.curAp.security_type = AP_SECURITY_WPA2;
    memcpy(wifi.curAp.bssid, ap, 6); memcpy(wifi.MacAddr, ds, 6);
    lwip_init();
    CHECK(netif_add(&interface, NULL, NULL, NULL, NULL, init_netif, ethernet_input) == &interface);
    netif_set_default(&interface); netif_set_up(&interface);
    run_exchange(false); // IPv4 unicast Offer/ACK before an address is assigned.
    run_exchange(true); // Broadcast Offer/ACK is also accepted.
    dhcp_release_and_stop(&interface); dhcp_cleanup(&interface);
    netif_remove(&interface);
    printf("DS DHCP exchange: %u checks, %u failures\n", checks, failures);
    return failures ? 1 : 0;
}
