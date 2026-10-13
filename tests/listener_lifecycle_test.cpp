// Exercise the real app startup/dialog/listener code, not just its schedule.
#include "../source/app.cpp"
#include <cerrno>
#include <cassert>
#include <iostream>
#include <map>
#include <netinet/in.h>
#include <sys/socket.h>

namespace {
struct SocketState { unsigned port = 0; bool listening = false; };
std::map<int, SocketState> sockets;
unsigned socketCalls = 0, pinCalls = 0;
uint64_t now = 0;
int nextSocket = 10;
chestlink::NetworkStatus live;
bool failIP = false;
enum class Failure { none, socket, ioctl, bind, listen };
Failure failure = Failure::none;
}

namespace platform {
void init() {}
void shutdown() {}
bool alive() { return true; }
void frame() { ++now; }
unsigned keys() { return A; }
void clear() {}
Touch touch() { return {}; }
void present(const uint16_t *, unsigned, const uint16_t *) {}
void network() {
  if (!live.ipv4Ready) throw chestlink::Error("Sem IPv4");
}
std::string ip() {
  if (failIP) throw chestlink::Error("Falha ao consultar IP");
  return live.ip;
}
const chestlink::NetworkStatus &networkStatus() { return live; }
uint64_t milliseconds() { return now; }
uint32_t makePin() { ++pinCalls; return 123456; }
bool pollNetwork() { return true; }
unsigned maxChestBoxes() { return 500; }
std::vector<chestlink::Store> stores() { return {}; }
void setLaunchPath(const char *) {}
std::string runningApplicationDirectory() { return ""; }
std::string runningApplicationPath() { return ""; }
unsigned removePreviousApplicationVersions(uint32_t, bool &complete) {
  complete = true; return 0;
}
}
namespace gui {
void notice(const std::string &, const std::string &, const std::string &, int) {}
void menu(const std::string &, const std::vector<std::string> &, unsigned, const std::string &) {}
int menuHit(int, int, unsigned, unsigned) { return -1; }
void box(const BoxScreen &) {}
int boxHit(int, int) { return -1; }
void numbers(const std::string &, const std::vector<unsigned> &, unsigned, bool) {}
}
namespace chestlink { PokemonPreview previewPokemon(const uint8_t *) { return {}; } }
extern "C" {
int __wrap_socket(int, int, int) {
  ++socketCalls;
  if (failure == Failure::socket) { errno = EMFILE; return -1; }
  sockets[nextSocket] = {};
  return nextSocket++;
}
int __wrap_close(int fd) { sockets.erase(fd); return 0; }
int __wrap_ioctl(int, unsigned long, ...) {
  if (failure == Failure::ioctl) { errno = EINVAL; return -1; }
  return 0;
}
int __wrap_setsockopt(int, int, int, const void *, socklen_t) { return 0; }
int __wrap_bind(int fd, const sockaddr *address, socklen_t) {
  if (failure == Failure::bind) { errno = EACCES; return -1; }
  const unsigned port = ntohs(reinterpret_cast<const sockaddr_in *>(address)->sin_port);
  for (const auto &socket : sockets)
    if (socket.first != fd && socket.second.port == port) {
      errno = EADDRINUSE; return -1;
    }
  sockets.at(fd).port = port;
  return 0;
}
int __wrap_listen(int fd, int) {
  if (failure == Failure::listen) { errno = EOPNOTSUPP; return -1; }
  sockets.at(fd).listening = true;
  return 0;
}
int __wrap_accept(int fd, sockaddr *, socklen_t *) {
  assert(sockets.at(fd).listening);
  errno = EWOULDBLOCK; return -1;
}
}

int main() {
  live.visible = live.connected = live.ipv4Ready = true;
  live.ssid = "test network"; live.ip = "10.0.0.201";
  // Reproduce the post-update dialog that pumps serviceIncoming before start.
  message("Versoes anteriores removidas: 1.");
  assert(socketCalls == 0 && directListener.server < 0);
  startListener();
  if (directListener.server < 0) {
    std::cerr << "FAIL cleanup dialog left an unreachable listener: "
              << directListener.status << "; sockets still open: " << sockets.size() << '\n';
    return 1;
  }
  assert(socketCalls == 1 && sockets.size() == 1 && pinCalls == 1);
  const int original = directListener.server;
  startListener();
  serviceIncoming();
  assert(directListener.server == original && socketCalls == 1 && pinCalls == 1);
  live.ip = "10.0.0.202";
  serviceIncoming();
  assert(directListener.server != original && sockets.size() == 1);
  assert(directListener.ip == live.ip && directListener.pin == 123456 && pinCalls == 1);
  live.connected = live.ipv4Ready = false;
  serviceIncoming();
  assert(directListener.server < 0 && sockets.empty());
  live.connected = live.ipv4Ready = true;
  serviceIncoming();
  assert(directListener.server >= 0 && sockets.size() == 1 && pinCalls == 1);
  stopListener();
  message("Encerrando.");
  assert(sockets.empty() && directListener.server < 0);
  directListener = {};

  // A failure after opening the socket cannot leave its port occupied.
  failIP = true;
  startListener();
  assert(directListener.server < 0 && sockets.empty());
  assert(directListener.status.find("Falha ao consultar IP") != std::string::npos);
  failIP = false;
  now += 1000;
  serviceIncoming();
  assert(directListener.server >= 0 && sockets.size() == 1);
  stopListener();

  for (Failure stage : {Failure::socket, Failure::ioctl, Failure::bind, Failure::listen}) {
    directListener = {}; failure = stage;
    startListener();
    assert(directListener.server < 0 && sockets.empty());
    assert(directListener.status.find("erro") != std::string::npos);
    failure = Failure::none;
    now += 1000;
    serviceIncoming();
    assert(directListener.server >= 0 && sockets.size() == 1);
    stopListener();
  }
  std::cout << "PASS real startup/dialog, idempotent listener, IP changes, PIN and failure cleanup\n";
}
