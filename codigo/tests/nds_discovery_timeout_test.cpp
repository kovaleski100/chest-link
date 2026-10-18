#include "network.hpp"

#include <cassert>
#include <cerrno>
#include <cstddef>
#include <cstring>
#include <algorithm>
#include <sys/socket.h>
#include <unistd.h>

namespace {
unsigned pollCount = 0;
unsigned cancelAt = 0;
unsigned sendCount = 0;
bool pendingConnect = false;
bool spuriousReady = false;
uint64_t clockMs = 7;
unsigned clockStep = 0;
size_t queuedBytes = 0;
}

namespace platform {
bool alive() { return true; }
uint64_t milliseconds() { return clockMs; }
bool pollNetwork() {
  ++pollCount;
  clockMs += clockStep;
  return !cancelAt || pollCount < cancelAt;
}
} // namespace platform

extern "C" ssize_t __wrap_sendto(int fd, const void *data, size_t length,
                                  int flags, const sockaddr *address,
                                  socklen_t addressLength) {
  (void)fd;
  (void)data;
  (void)flags;
  (void)address;
  (void)addressLength;
  ++sendCount;
  return static_cast<ssize_t>(length);
}

extern "C" ssize_t __wrap_recvfrom(int fd, void *data, size_t length,
                                    int flags, sockaddr *address,
                                    socklen_t *addressLength) {
  (void)fd;
  (void)data;
  (void)length;
  (void)flags;
  (void)address;
  (void)addressLength;
  errno = EWOULDBLOCK;
  return -1;
}

extern "C" int __wrap_connect(int fd, const sockaddr *address,
                                socklen_t addressLength) {
  (void)fd;
  (void)address;
  (void)addressLength;
  if (pendingConnect) {
    errno = EINPROGRESS;
    return -1;
  }
  errno = ECONNREFUSED;
  return -1;
}

extern "C" int __wrap_select(int nfds, fd_set *readSet, fd_set *writeSet,
                               fd_set *exceptSet, timeval *timeout) {
  (void)nfds;
  (void)readSet;
  (void)writeSet;
  (void)exceptSet;
  (void)timeout;
  return spuriousReady ? 1 : 0;
}

extern "C" ssize_t __wrap_recv(int, void *data, size_t size, int) {
  if (queuedBytes) {
    const size_t bytes = std::min({queuedBytes, size, size_t(128)});
    std::memset(data, 0x5a, bytes);
    queuedBytes -= bytes;
    return static_cast<ssize_t>(bytes);
  }
  errno = EWOULDBLOCK;
  return -1;
}

int main() {
  using namespace chestlink;
  assert(discoverPCServer(40992, 3000).empty());
  assert(pollCount == 180);
  assert(sendCount == 9);

  pollCount = sendCount = 0;
  cancelAt = 4;
  bool cancelled = false;
  try {
    (void)discoverPCServer(40992, 3000);
  } catch (const Error &error) {
    cancelled = std::string(error.what()) == "Cancelado.";
  }
  assert(cancelled && pollCount == 4);

  pollCount = 0;
  cancelAt = 0;
  pendingConnect = true;
  bool timedOut = false;
  try {
    (void)Connection::connect("192.0.2.1", 40992, 1500);
  } catch (const Error &error) {
    timedOut = std::string(error.what()) ==
               "Tempo de espera esgotado. Origem preservada.";
  }
  pendingConnect = false;
  assert(timedOut && pollCount == 90);

  int sockets[2];
  assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) == 0);
  Connection connection(sockets[0]);
  auto wire = connection.wire(600000);
  wire.setIdleTimeout(10);
  pollCount = 0;
  clockStep = 4;
  spuriousReady = true;
  char byte;
  timedOut = false;
  try { wire.read(&byte, 1); }
  catch (const Error &error) {
    timedOut = std::string(error.what()) ==
               "Tempo de espera esgotado. Origem preservada.";
  }
  assert(timedOut && pollCount == 3); // Repeated EAGAIN cannot reset the deadline.

  pollCount = 0;
  clockStep = 0;
  spuriousReady = false;
  queuedBytes = 1024;
  char queued[1024];
  wire.read(queued, sizeof(queued));
  assert(!queuedBytes && pollCount == 0); // Do not wait for VBlank with data ready.
  for (char value : queued) assert(value == 0x5a);
  close(sockets[1]);
}
