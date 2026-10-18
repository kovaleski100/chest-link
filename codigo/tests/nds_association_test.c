// Real ARM9 connection-state machine with simulated radio/link transitions.
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "../third_party/dswifi/source/arm9/access_point.c"

static Wifi_MainStruct wifi;
volatile Wifi_MainStruct *WifiData = &wifi;
bool wifi_lwip_enabled = true;
static bool link_up, use_dhcp, ip_ready;
static unsigned link_up_calls, failures, checks;
static u32 address, dns;

#define CHECK(condition) do { \
    ++checks; \
    if (!(condition)) { \
        fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
        ++failures; \
    } \
} while (0)

bool wifi_netif_is_up(void) { return link_up; }
void wifi_netif_set_up(void) { link_up = true; ++link_up_calls; }
void wifi_netif_set_down(void) { link_up = false; }
bool wifi_using_dhcp(void) { return use_dhcp; }
bool wifi_ipv4_ready(void) { return link_up && ip_ready; }
u32 wifi_get_ip(void) { return address; }
u32 wifi_get_dns(int index) { (void)index; return dns; }
bool wifi_get_ip6(struct in6_addr *ip) { (void)ip; return false; }
void Wifi_ScanMode(void) { wifi.reqMode = WIFIMODE_SCAN; }
void Wifi_InternetMode(void) { wifi.reqLibraryMode = DSWIFI_INTERNET; }
void Wifi_SetIP(u32 ip, u32 gateway, u32 mask, u32 dns1, u32 dns2)
{ (void)gateway; (void)mask; (void)dns2; address = ip; dns = dns1; }
u32 SLasm_Acquire(volatile u32 *p, u32 owner) { *p = owner; return SPINLOCK_OK; }
u32 SLasm_Release(volatile u32 *p, u32 owner)
{ (void)owner; *p = SPINLOCK_OWNER_NOBODY; return SPINLOCK_OK; }

static void connected(void)
{
    memset(&wifi, 0, sizeof(wifi));
    wifi.curLibraryMode = wifi.reqLibraryMode = DSWIFI_INTERNET;
    wifi.curMode = wifi.reqMode = WIFIMODE_CONNECTED;
    wifi_connect_state = WIFI_CONNECT_DONE;
    wifi_lwip_enabled = true;
    address = 0x022ae70a; // Network-order 10.231.42.2 on little-endian hosts.
    dns = 0x012ae70a;
    use_dhcp = false;
    ip_ready = true;
    link_up = true;
    link_up_calls = 0;
}

int main(void)
{
    connected();
    CHECK(Wifi_AssocStatus() == ASSOCSTATUS_ASSOCIATED);
    CHECK(link_up_calls == 0);

    // A cached IP is not evidence that the radio is still connected.
    for (int mode = WIFIMODE_DISABLED; mode <= WIFIMODE_SCAN; ++mode) {
        connected();
        wifi.curMode = mode;
        link_up = false;
        CHECK(Wifi_AssocStatus() != ASSOCSTATUS_ASSOCIATED);
        CHECK(!link_up);
        CHECK(address != 0);
    }
    connected();
    wifi.curMode = WIFIMODE_CANNOTCONNECT;
    link_up = false;
    CHECK(Wifi_AssocStatus() == ASSOCSTATUS_CANNOTCONNECT);
    CHECK(!link_up);

    connected();
    wifi.curMode = WIFIMODE_CONNECTING;
    link_up = false;
    CHECK(Wifi_AssocStatus() == ASSOCSTATUS_ASSOCIATING);
    CHECK(!link_up);
    wifi.curMode = WIFIMODE_CONNECTED;
    CHECK(Wifi_AssocStatus() == ASSOCSTATUS_ASSOCIATED);
    CHECK(link_up);

    connected();
    Wifi_DisconnectAP();
    CHECK(Wifi_AssocStatus() != ASSOCSTATUS_ASSOCIATED);

    // Even a connected radio needs the IP link enabled before reporting ready.
    connected();
    link_up = false;
    CHECK(Wifi_AssocStatus() == ASSOCSTATUS_ASSOCIATED);
    CHECK(link_up_calls == 1);
    CHECK(link_up);

    connected();
    use_dhcp = true;
    CHECK(Wifi_AssocStatus() == ASSOCSTATUS_ASSOCIATED);
    CHECK(Wifi_AssocStatus() == ASSOCSTATUS_ASSOCIATED);

    connected();
    wifi_connect_state = WIFI_CONNECT_DHCPING;
    wifi.curMode = WIFIMODE_CONNECTING;
    link_up = false;
    CHECK(Wifi_AssocStatus() != ASSOCSTATUS_ASSOCIATED);
    CHECK(!link_up);

    connected();
    wifi_lwip_enabled = false;
    CHECK(Wifi_AssocStatus() == ASSOCSTATUS_ASSOCIATED);

    connected();
    use_dhcp = true;
    ip_ready = false; // Cached IP/DNS must not stand in for a DHCP lease.
    wifi_connect_state = WIFI_CONNECT_DHCPING;
    CHECK(Wifi_AssocStatus() == ASSOCSTATUS_ACQUIRINGDHCP);
    CHECK(!Wifi_IsIPReady());
    ip_ready = true;
    CHECK(Wifi_AssocStatus() == ASSOCSTATUS_ASSOCIATED);
    CHECK(Wifi_IsIPReady());

    connected();
    memcpy(wifi.curAp.ssid, "Current", 7);
    wifi.curAp.ssid_len = 7;
    Wifi_AccessPoint current;
    CHECK(Wifi_GetCurrentAP(&current));
    CHECK(strcmp(current.ssid, "Current") == 0);
    wifi.curMode = WIFIMODE_SCAN;
    CHECK(!Wifi_GetCurrentAP(&current));
    CHECK(current.ssid[0] == 0);
    printf("DS association: %u checks, %u failures\n", checks, failures);
    return failures ? 1 : 0;
}
