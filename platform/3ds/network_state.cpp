#include "network_state.hpp"
#include "network_snapshot.hpp"
#include "core.hpp"
#include "graphics.hpp"
#include "platform.hpp"
#include <3ds.h>
#include <arpa/inet.h>
#include <cerrno>
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
chestlink::InternetProbeSchedule internet;
int probeSocket = -1;

void closeProbe() {
  if (probeSocket >= 0) ::close(probeSocket);
  probeSocket = -1;
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

sockaddr_in probeAddress() {
  sockaddr_in peer{};
  peer.sin_family = AF_INET;
  peer.sin_port = htons(443);
  peer.sin_addr.s_addr = inet_addr("1.1.1.1");
  return peer;
}

void pollProbe(uint64_t now) {
  if (internet.due(now)) {
    internet.begin(now);
    probeSocket = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    int nonblocking = 1;
    if (probeSocket < 0 || ioctl(probeSocket, FIONBIO, &nonblocking) < 0) {
      closeProbe(); internet.finish(false, now); return;
    }
    // Same read-only TCP reachability indicator as DS. It does not validate
    // DNS/TLS or send credentials or bank contents to this public resolver.
    auto peer = probeAddress();
    int result = ::connect(probeSocket, reinterpret_cast<sockaddr *>(&peer), sizeof(peer));
    if (!result) {
      closeProbe(); internet.finish(true, now); return;
    }
    if (errno != EINPROGRESS && errno != EWOULDBLOCK && errno != EAGAIN) {
      closeProbe(); internet.finish(false, now); return;
    }
  }
  if (!internet.pending() || probeSocket < 0) return;
  if (internet.expired(now)) {
    closeProbe(); internet.finish(false, now); return;
  }
  fd_set writable, errors;
  FD_ZERO(&writable); FD_ZERO(&errors);
  FD_SET(probeSocket, &writable); FD_SET(probeSocket, &errors);
  timeval immediate{0, 0};
  const int result = select(probeSocket + 1, nullptr, &writable, &errors, &immediate);
  if ((result < 0 && errno == EINTR) || !result) return;
  int error = 0;
  socklen_t length = sizeof(error);
  const int queried = result > 0
      ? getsockopt(probeSocket, SOL_SOCKET, SO_ERROR, &error, &length) : -1;
  if (!queried && error == -26) {
    // Native SOC can retain its internal EINPROGRESS after TCP established.
    auto peer = probeAddress();
    int retry = ::connect(probeSocket, reinterpret_cast<sockaddr *>(&peer), sizeof(peer));
    if (!retry || (retry < 0 && errno == EISCONN)) error = 0;
  }
  const bool success = result > 0 && !queried && !error;
  closeProbe(); internet.finish(success, now);
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
    if (internet.link(state.ssid, state.ip, state.ipv4Ready)) closeProbe();
  }
  pollProbe(now);
  state.internet = internet.result();
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
  closeProbe();
  if (socReady) socExit();
  if (socBuffer) free(socBuffer);
  if (acReady) acExit();
  socReady = acReady = sampled = false; socBuffer = nullptr;
  state = {}; internet = {};
}
} // namespace platform_detail
