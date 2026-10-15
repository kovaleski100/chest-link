#include "../platform/3ds/network_state.hpp"
#include "graphics.hpp"
#include <3ds.h>
#include <arpa/inet.h>
#include <cassert>
#include <cerrno>
#include <cstring>
#include <iostream>
#include <sys/socket.h>

namespace {
uint64_t now = 0;
u32 nativeWifiStatus = 0;
Result acResult = 0, statusResult = 0, socResult = 0;
Result ssidResult = 0;
const char *nativeSSID = "TestNetwork";
uint32_t nativeIP = 0;
unsigned socCalls = 0, acExits = 0, socExits = 0, sockets = 0, closed = 0;
unsigned legacyStatusQueries = 0;
bool writable = false, established = false;
int socketError = 0;
chestlink::NetworkStatus drawn;
}
namespace platform { uint64_t milliseconds() { return now; } }
namespace gui { void setNetworkStatus(const chestlink::NetworkStatus &state) { drawn = state; } }
Result acInit() { return acResult; }
void acExit() { ++acExits; }
Result socInit(u32 *, u32) { ++socCalls; return socResult; }
void socExit() { ++socExits; }
Result ACU_GetStatus(u32 *out) { ++legacyStatusQueries; *out = 1; return 0; }
Result ACU_GetWifiStatus(u32 *out) { *out = nativeWifiStatus; return statusResult; }
Result ACU_GetSSIDLength(u32 *out) { *out = std::strlen(nativeSSID); return 0; }
Result ACU_GetSSID(char *out) { std::memcpy(out, nativeSSID, std::strlen(nativeSSID)); return ssidResult; }
extern "C" {
long __wrap_gethostid() { return nativeIP; }
int __wrap_socket(int, int, int) { ++sockets; return 7; }
int __wrap_close(int fd) { assert(fd == 7); ++closed; return 0; }
int __wrap_ioctl(int, unsigned long, ...) { return 0; }
int __wrap_connect(int, const sockaddr *, socklen_t) {
  errno = established ? EISCONN : EINPROGRESS;
  return -1;
}
int __wrap_select(int, fd_set *, fd_set *, fd_set *, timeval *timeout) {
  assert(timeout->tv_sec == 0 && timeout->tv_usec == 0);
  return writable ? 1 : 0;
}
int __wrap_getsockopt(int, int, int, void *out, socklen_t *) {
  *static_cast<int *>(out) = socketError; return 0;
}
}

int main() {
  using namespace platform_detail;
  acResult = -1;
  refresh3DSNetworkStatus();
  assert(drawn.visible && !drawn.connected && socCalls == 0);
  // A visible AP can have a nonzero WifiStatus while GetStatus is not 3.
  // Neither the IP lookup nor SOC init may be blocked by the unrelated query.
  acResult = 0; nativeWifiStatus = 1; now = 1000;
  refresh3DSNetworkStatus();
  assert(drawn.connected && !drawn.ipv4Ready && drawn.ip.empty() && sockets == 0);
  assert(socCalls == 1 && drawn.ssid == nativeSSID);
  nativeIP = inet_addr("10.0.0.147"); now = 1500;
  refresh3DSNetworkStatus();
  assert(!drawn.ipv4Ready); // Sampling is periodic, not an IPC query every frame.
  now = 2000;
  refresh3DSNetworkStatus();
  assert(drawn.ipv4Ready && drawn.ip == "10.0.0.147" && sockets == 1);
  assert(drawn.internet == chestlink::InternetAccess::checking);
  socketError = -26; writable = established = true; now = 2001;
  refresh3DSNetworkStatus();
  assert(drawn.internet == chestlink::InternetAccess::reachable && closed == 1);
  assert(socCalls == 1); // SOC not repeatedly allocated on each refresh.
  nativeIP = inet_addr("10.0.0.148"); now = 3000;
  writable = established = false;
  refresh3DSNetworkStatus();
  assert(drawn.ip == "10.0.0.148" && sockets == 2);
  nativeWifiStatus = 0; now = 4000;
  refresh3DSNetworkStatus();
  assert(!drawn.connected && !drawn.ipv4Ready && drawn.ssid.empty() && drawn.ip.empty());
  assert(drawn.internet == chestlink::InternetAccess::unknown && closed == 2);
  // gethostid still carries its previous value: native AC status wins.
  bool refused = false;
  try { require3DSNetwork(); } catch (const chestlink::Error &) { refused = true; }
  assert(refused);
  nativeWifiStatus = 2; now = 5000;
  refresh3DSNetworkStatus();
  assert(drawn.connected && drawn.ipv4Ready && sockets == 3);
  require3DSNetwork();
  now = 9000;
  refresh3DSNetworkStatus();
  assert(drawn.internet == chestlink::InternetAccess::unconfirmed && closed == 3);
  statusResult = -1; now = 10000;
  refresh3DSNetworkStatus();
  assert(drawn.ip.empty() && !drawn.connected);
  statusResult = 0; now = 11000;
  refresh3DSNetworkStatus();
  assert(sockets == 4);
  shutdown3DSNetwork();
  assert(closed == 4 && acExits == 1 && socExits == 1);
  socResult = -1;
  refresh3DSNetworkStatus();
  assert(drawn.connected && !drawn.ipv4Ready && drawn.ip.empty());
  refused = false;
  try { require3DSNetwork(); } catch (const chestlink::Error &) { refused = true; }
  assert(refused); // AC connected alone cannot claim a usable SOC/IP endpoint.
  socResult = 0; now += 1000;
  refresh3DSNetworkStatus();
  assert(drawn.connected && drawn.ipv4Ready && sockets == 5);
  shutdown3DSNetwork();
  assert(closed == 5 && acExits == 2 && socExits == 2);
  // SSID metadata failure must not deny an otherwise usable native link/IP.
  ssidResult = -1;
  refresh3DSNetworkStatus();
  assert(drawn.connected && drawn.ipv4Ready && drawn.ssid.empty());
  require3DSNetwork();
  shutdown3DSNetwork();
  assert(closed == 6 && acExits == 3 && socExits == 3);
  assert(legacyStatusQueries == 0);
  std::cout << "PASS native 3DS AC/SOC polling, stale IP removal, reconnect and nonblocking probe\n";
}
