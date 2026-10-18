#include "network_state.hpp"
#include "network_snapshot.hpp"
#include "core.hpp"
#include "graphics.hpp"
#include "platform.hpp"
#include <3ds.h>
#include <arpa/inet.h>
#include <cerrno>
#include <cstring>
#include <cstdlib>
#include <malloc.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>

namespace platform_detail {
namespace {
bool acReady = false, socReady = false, sampled = false;
uint64_t lastSample = 0;
void *socBuffer = nullptr;
chestlink::NetworkStatus state;
chestlink::ServerProbeSchedule serverSchedule;
int serverSocket = -1;
uint64_t nextServerProbeSend = 0;
uint32_t serverProbeNonce = 0, serverProbeSequence = 0;
constexpr uint16_t SERVER_DISCOVERY_PORT = 40992;

void closeServerProbe() {
  if (serverSocket >= 0) ::close(serverSocket);
  serverSocket = -1;
}

void ensureSockets() {
  if (socReady) return;
  socBuffer = memalign(0x1000, 1024 * 1024);
  if (!socBuffer) throw chestlink::Error("Memoria insuficiente para Wi-Fi.");
  if (R_FAILED(socInit(static_cast<uint32_t *>(socBuffer), 1024 * 1024))) {
    free(socBuffer); socBuffer = nullptr;
    throw chestlink::Error("Servico de rede do 3DS indisponivel.");
  }
  socReady = true;
}

std::string ipv4Text(uint32_t value) {
  in_addr address{};
  address.s_addr = value;
  char buffer[INET_ADDRSTRLEN]{};
  return inet_ntop(AF_INET, &address, buffer, sizeof(buffer)) ? buffer : "";
}

void sendServerDiscovery(uint64_t now) {
  if (serverSocket < 0 || now < nextServerProbeSend) return;
  uint8_t request[12] = {'C', 'L', 'D', 'S', 'D', 'I', 'S', 'C'};
  request[8] = static_cast<uint8_t>(serverProbeNonce >> 24);
  request[9] = static_cast<uint8_t>(serverProbeNonce >> 16);
  request[10] = static_cast<uint8_t>(serverProbeNonce >> 8);
  request[11] = static_cast<uint8_t>(serverProbeNonce);
  sockaddr_in target{};
  target.sin_family = AF_INET;
  target.sin_port = htons(SERVER_DISCOVERY_PORT);
  target.sin_addr.s_addr = htonl(INADDR_BROADCAST);
  (void)sendto(serverSocket, request, sizeof(request), 0,
               reinterpret_cast<const sockaddr *>(&target), sizeof(target));
  nextServerProbeSend = now + 350;
}

void pollServerProbe(uint64_t now) {
  if (serverSchedule.due(now)) {
    serverSchedule.begin(now);
    serverProbeNonce = (static_cast<uint32_t>(now) ^ 0xc1a0d5e3u) +
                       (++serverProbeSequence * 0x9e3779b9u);
    serverSocket = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    int broadcast = 1, nonblocking = 1;
    if (serverSocket < 0 ||
        setsockopt(serverSocket, SOL_SOCKET, SO_BROADCAST, &broadcast,
                   sizeof(broadcast)) < 0 ||
        ioctl(serverSocket, FIONBIO, &nonblocking) < 0) {
      closeServerProbe(); serverSchedule.finish({}, now); return;
    }
    nextServerProbeSend = 0;
  }
  if (!serverSchedule.pending() || serverSocket < 0) return;
  if (serverSchedule.expired(now)) {
    closeServerProbe(); serverSchedule.finish({}, now); return;
  }
  sendServerDiscovery(now);
  uint8_t response[12]{};
  sockaddr_in source{};
  socklen_t sourceLength = sizeof(source);
  const ssize_t received = recvfrom(serverSocket, response, sizeof(response), 0,
      reinterpret_cast<sockaddr *>(&source), &sourceLength);
  if (received < 0) {
    if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) return;
    closeServerProbe(); serverSchedule.finish({}, now); return;
  }
  if (received != sizeof(response) || std::memcmp(response, "CLPCDISC", 8) ||
      ntohs(source.sin_port) != SERVER_DISCOVERY_PORT || !source.sin_addr.s_addr)
    return;
  if (response[8] != static_cast<uint8_t>(serverProbeNonce >> 24) ||
      response[9] != static_cast<uint8_t>(serverProbeNonce >> 16) ||
      response[10] != static_cast<uint8_t>(serverProbeNonce >> 8) ||
      response[11] != static_cast<uint8_t>(serverProbeNonce))
    return;
  const std::string address = ipv4Text(source.sin_addr.s_addr);
  closeServerProbe(); serverSchedule.finish(address, now);
}
} // namespace

void refresh3DSNetworkStatus(bool force) {
  const uint64_t now = platform::milliseconds();
  if (force || !sampled || now - lastSample >= 1000) {
    sampled = true; lastSample = now;
    if (!acReady) acReady = R_SUCCEEDED(acInit());
    u32 status = 0, length = 0;
    // Use the system's visible AP, as ftpd and libctru's own connection wait
    // do. GetStatus == 3 is not a prerequisite for using an existing link.
    const bool statusOK = acReady && R_SUCCEEDED(ACU_GetWifiStatus(&status));
    char ssid[33]{};
    std::string ip;
    bool ssidOK = false;
    if (statusOK && status != 0) {
      ssidOK = R_SUCCEEDED(ACU_GetSSIDLength(&length)) && length <= 32 &&
               R_SUCCEEDED(ACU_GetSSID(ssid));
      try { ensureSockets(); } catch (const chestlink::Error &) {}
      if (socReady) {
        in_addr address{};
        address.s_addr = static_cast<uint32_t>(gethostid());
        char buffer[INET_ADDRSTRLEN]{};
        if (inet_ntop(AF_INET, &address, buffer, sizeof(buffer))) ip = buffer;
      }
    }
    state = nativeNetworkSnapshot(statusOK, status, ssidOK, ssid, length, ip);
    if (serverSchedule.link(state.ssid, state.ip, state.ipv4Ready))
      closeServerProbe();
  }
  pollServerProbe(now);
  state.server = serverSchedule.result();
  state.serverIP = serverSchedule.serverIP();
  gui::setNetworkStatus(state);
}

void require3DSNetwork() {
  refresh3DSNetworkStatus(true);
  if (!state.connected)
    throw chestlink::Error("Wi-Fi desconectado. Ative-o e configure a rede nas definicoes do 3DS.");
  ensureSockets();
  if (!state.ipv4Ready)
    throw chestlink::Error("3DS sem IP na rede atual. Confira a conexao nas definicoes do console.");
}

const chestlink::NetworkStatus &network3DSStatus() { return state; }

void shutdown3DSNetwork() {
  closeServerProbe();
  if (socReady) socExit();
  if (socBuffer) free(socBuffer);
  if (acReady) acExit();
  socReady = acReady = sampled = false; socBuffer = nullptr;
  state = {}; serverSchedule = {};
}
} // namespace platform_detail
