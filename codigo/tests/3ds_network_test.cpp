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
bool respondToDiscovery = false;
uint8_t discoveryNonce[4]{};
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
int __wrap_setsockopt(int, int, int, const void *, socklen_t) { return 0; }
ssize_t __wrap_sendto(int, const void *data, size_t size, int,
                      const sockaddr *, socklen_t) {
  const auto *packet = static_cast<const uint8_t *>(data);
  if (size == 12) std::memcpy(discoveryNonce, packet + 8, 4);
  return static_cast<ssize_t>(size);
}
ssize_t __wrap_recvfrom(int, void *data, size_t size, int,
                        sockaddr *source, socklen_t *sourceLength) {
  if (!respondToDiscovery) { errno = EAGAIN; return -1; }
  assert(size >= 12);
  auto *packet = static_cast<uint8_t *>(data);
  std::memcpy(packet, "CLPCDISC", 8);
  std::memcpy(packet + 8, discoveryNonce, 4);
  auto *address = reinterpret_cast<sockaddr_in *>(source);
  address->sin_family = AF_INET;
  address->sin_port = htons(40992);
  address->sin_addr.s_addr = inet_addr("10.0.0.9");
  *sourceLength = sizeof(*address);
  return 12;
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
  assert(drawn.server == chestlink::ServerAvailability::searching);
  respondToDiscovery = true; now = 2001;
  refresh3DSNetworkStatus();
  assert(drawn.server == chestlink::ServerAvailability::connected &&
         drawn.serverIP == "10.0.0.9" && closed == 1);
  assert(socCalls == 1); // SOC not repeatedly allocated on each refresh.
  nativeIP = inet_addr("10.0.0.148"); now = 3000;
  respondToDiscovery = false;
  refresh3DSNetworkStatus();
  assert(drawn.ip == "10.0.0.148" && sockets == 2 &&
         drawn.server == chestlink::ServerAvailability::searching);
  nativeWifiStatus = 0; now = 4000;
  refresh3DSNetworkStatus();
  assert(!drawn.connected && !drawn.ipv4Ready && drawn.ssid.empty() && drawn.ip.empty());
  assert(drawn.server == chestlink::ServerAvailability::unknown && closed == 2);
  // gethostid still carries its previous value: native AC status wins.
  bool refused = false;
  try { require3DSNetwork(); } catch (const chestlink::Error &) { refused = true; }
  assert(refused);
  nativeWifiStatus = 2; now = 5000;
  refresh3DSNetworkStatus();
  assert(drawn.connected && drawn.ipv4Ready && sockets == 3);
  require3DSNetwork();
  now = 8000;
  refresh3DSNetworkStatus();
  assert(drawn.server == chestlink::ServerAvailability::notFound && closed == 3);
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
