// Exercise the real DS IPv4 configuration across hotspot/router changes.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../third_party/dswifi/source/arm9/lwip/netif.c"

static Wifi_MainStruct wifi;
volatile Wifi_MainStruct *WifiData = &wifi;
static ip_addr_t dns_servers[2];
static bool leased;
static bool simulate_callback;
static unsigned checks, failures, starts, stops;

#define CHECK(condition) do { ++checks; if (!(condition)) { \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); ++failures; \
} } while (0)

void dns_setserver(u8_t index, const ip_addr_t *ip) { dns_servers[index] = *ip; }
const ip_addr_t *dns_getserver(u8_t index) { return &dns_servers[index]; }
void dhcp_stop(struct netif *n) { (void)n; ++stops; leased = false; }
err_t dhcp_start(struct netif *n) { (void)n; ++starts; return ERR_OK; }
void dhcp_inform(struct netif *n) { (void)n; }
u8_t dhcp_supplied_address(const struct netif *n) { (void)n; return leased; }
void dhcp6_disable(struct netif *n) { (void)n; }
err_t dhcp6_enable_stateless(struct netif *n) { (void)n; return ERR_OK; }
void netif_set_link_up(struct netif *n) { n->flags |= NETIF_FLAG_LINK_UP; }
void netif_set_link_down(struct netif *n) { n->flags &= ~NETIF_FLAG_LINK_UP; }
err_t netifapi_netif_common(struct netif *n, netifapi_void_fn v, netifapi_errt_fn e)
{ if (v) v(n); return e ? e(n) : ERR_OK; }
err_t netifapi_netif_set_addr(struct netif *n, const ip4_addr_t *ip,
                              const ip4_addr_t *mask, const ip4_addr_t *gw)
{
    ip_addr_copy_from_ip4(n->ip_addr, *ip);
    ip_addr_copy_from_ip4(n->netmask, *mask);
    ip_addr_copy_from_ip4(n->gw, *gw);
    if (simulate_callback) wifi_netif_set_up(); // Cooperative thread resumes.
    return ERR_OK;
}

int main(void)
{
    wifi_lwip_enabled = true;
    dswifi_netif.flags = NETIF_FLAG_UP | NETIF_FLAG_LINK_UP;
    dswifi_link_is_up = true;
    const u32 hotspot = 0x022ae70a, gateway = 0x012ae70a, mask = 0x00ffffff;
    Wifi_SetIP(hotspot, gateway, mask, gateway, 0);
    CHECK(!wifi_using_dhcp());
    CHECK(Wifi_GetIP() == hotspot);
    wifi_netif_set_up();
    CHECK(wifi_ipv4_ready());

    // Observed regression: automatic mode must not inherit hotspot IPv4/DNS.
    simulate_callback = true;
    Wifi_SetIP(0, 0, 0, 0, 0);
    simulate_callback = false;
    CHECK(wifi_using_dhcp());
    CHECK(Wifi_GetIP() == 0);
    CHECK(!wifi_ipv4_ready());
    CHECK(wifi_get_gateway() == 0);
    CHECK(wifi_get_netmask() == 0);
    CHECK(wifi_get_dns(0) == 0 && wifi_get_dns(1) == 0);
    CHECK(!wifi_netif_is_up());
    unsigned before = starts;
    wifi_netif_set_up();
    CHECK(starts == before + 1);
    CHECK(Wifi_GetIP() == 0);

    // A second transition discards an old router lease too.
    ip4_addr_t assigned = {0x2c00000a};
    netifapi_netif_set_addr(&dswifi_netif, &assigned, &assigned, &assigned);
    leased = true;
    CHECK(wifi_ipv4_ready());
    Wifi_SetIP(0, 0, 0, 0, 0);
    CHECK(!leased);
    CHECK(Wifi_GetIP() == 0 && wifi_get_gateway() == 0);
    CHECK(!wifi_netif_is_up());

    // Failed router setup can still restore the original static hotspot.
    Wifi_SetIP(hotspot, gateway, mask, gateway, 0);
    wifi_netif_set_up();
    CHECK(!wifi_using_dhcp());
    CHECK(Wifi_GetIP() == hotspot);
    CHECK(wifi_get_gateway() == gateway);
    CHECK(wifi_get_netmask() == mask);
    CHECK(wifi_get_dns(0) == gateway);
    CHECK(wifi_netif_is_up());
    CHECK(wifi_ipv4_ready());
    CHECK(stops > 0);
    dswifi_use_dhcp = true;
    leased = false;
    CHECK(!wifi_ipv4_ready()); // Nonzero IP/DNS alone is not a lease.
    leased = true;
    CHECK(wifi_ipv4_ready());
    wifi_netif_set_down();
    CHECK(!wifi_ipv4_ready());
    printf("DS IPv4: %u checks, %u failures\n", checks, failures);
    return failures ? 1 : 0;
}
