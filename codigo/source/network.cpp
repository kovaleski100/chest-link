#include "network.hpp"
#include "platform.hpp"
extern "C" {
#include <arpa/inet.h>
}
#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <netinet/in.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>
#ifdef CL_NDS
#include <nds.h>
#endif
namespace chestlink {
namespace {
void nonblock(int fd) {
  int yes = 1;
  if (ioctl(fd, FIONBIO, &yes) < 0)
    throw Error("Rede: modo nao bloqueante (erro " + std::to_string(errno) + ").");
}
void ready(int fd, bool writing, uint64_t since, unsigned timeout = 180000,
           const std::function<void(bool, size_t)> *activity = nullptr) {
  uint64_t nextHeartbeat = platform::milliseconds() + 10000;
#ifdef CL_NDS
  const uint64_t frameLimit =
      std::max<uint64_t>(1, (static_cast<uint64_t>(timeout) * 60 + 999) / 1000);
  for (uint64_t frame = 0; frame < frameLimit; ++frame) {
    if (!platform::alive() || !platform::pollNetwork())
      throw Error("Cancelado.");
    const uint64_t now = platform::milliseconds();
    if (now - since >= timeout)
      throw Error("Tempo de espera esgotado. Origem preservada.");
    if (activity && *activity && now >= nextHeartbeat) {
      (*activity)(writing, 0);
      nextHeartbeat = now + 10000;
    }
    fd_set r, w;
    FD_ZERO(&r);
    FD_ZERO(&w);
    FD_SET(fd, writing ? &w : &r);
    timeval t{0, 0};
    int n = select(fd + 1, &r, &w, nullptr, &t);
    if (n > 0)
      return;
    if (n < 0 && errno != EINTR)
      throw Error("Erro de rede.");
  }
  throw Error("Tempo de espera esgotado. Origem preservada.");
#else
  for (;;) {
    if (!platform::alive() || !platform::pollNetwork())
      throw Error("Cancelado.");
    fd_set r, w;
    FD_ZERO(&r);
    FD_ZERO(&w);
    FD_SET(fd, writing ? &w : &r);
    timeval t{0, 1000};
    int n = select(fd + 1, &r, &w, nullptr, &t);
    if (n > 0)
      return;
    if (n < 0 && errno != EINTR)
      throw Error("Erro de rede.");
    const uint64_t now = platform::milliseconds();
    if (activity && *activity && now >= nextHeartbeat) {
      (*activity)(writing, 0);
      nextHeartbeat = now + 10000;
    }
    if (now - since > timeout)
      throw Error("Tempo de espera esgotado. Origem preservada.");
  }
#endif
}
} // namespace
Connection::Connection(int fd) : fd_(fd) {
  if (fd < 0)
    throw Error("Falha ao criar conexao.");
  try {
    nonblock(fd_);
  } catch (...) {
    close(fd_);
    fd_ = -1;
    throw;
  }
}
Connection::~Connection() { close(fd_); }
Connection::Connection(Connection &&other) noexcept : fd_(other.fd_) {
  other.fd_ = -1;
}
Connection &Connection::operator=(Connection &&other) noexcept {
  if (this != &other) {
    close(fd_);
    fd_ = other.fd_;
    other.fd_ = -1;
  }
  return *this;
}
void Connection::close(int fd) {
  if (fd < 0)
    return;
#ifdef CL_NDS
  closesocket(fd);
#else
  ::close(fd);
#endif
}
Wire Connection::wire(unsigned idleTimeoutMs,
                      std::function<void(bool, size_t)> activity) {
  auto timeout = std::make_shared<unsigned>(idleTimeoutMs);
  return {[this, timeout, activity](void *p, size_t n) {
            exact(p, n, false, *timeout, activity);
          },
          [this, timeout, activity](const void *p, size_t n) {
            exact(const_cast<void *>(p), n, true, *timeout, activity);
          },
          [timeout](unsigned milliseconds) { *timeout = milliseconds; }};
}
void Connection::exact(void *data, size_t n, bool writing,
                       unsigned idleTimeoutMs,
                       const std::function<void(bool, size_t)> &activity) {
  auto *p = static_cast<uint8_t *>(data);
  uint64_t last = platform::milliseconds();
  while (n) {
    if (!platform::alive())
      throw Error("Cancelado.");
#ifdef CL_HOST
    int sendFlags = MSG_NOSIGNAL;
#else
    int sendFlags = 0;
#endif
    int rc = writing ? ::send(fd_, p, n, sendFlags) : ::recv(fd_, p, n, 0);
    if (rc < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) {
      // Drain bytes already queued before yielding a whole screen frame.
      // Cooperative Wi-Fi still runs whenever the nonblocking socket waits.
      ready(fd_, writing, last, idleTimeoutMs, &activity);
      continue;
    }
    if (rc <= 0)
      throw Error("Conexao interrompida. Confira o destino antes de repetir.");
    if (activity)
      activity(writing, static_cast<size_t>(rc));
    p += rc;
    n -= rc;
    last = platform::milliseconds();
  }
}

std::string discoverPCServer(unsigned port, unsigned timeout) {
  if (!port || port > 65535 || !timeout)
    return {};

  const int fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
  if (fd < 0)
    return {};
  try {
    int broadcast = 1;
    if (setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &broadcast,
                   sizeof(broadcast))) {
      Connection::close(fd);
      return {};
    }

    sockaddr_in target{};
#if defined(__NDS__)
    target.sin_len = sizeof(target);
#endif
    target.sin_family = AF_INET;
    target.sin_port = htons(static_cast<uint16_t>(port));
    target.sin_addr.s_addr = htonl(INADDR_BROADCAST);

    static uint32_t sequence = 0;
    const uint32_t nonce =
        (static_cast<uint32_t>(platform::milliseconds()) ^ 0xc1a0d5e3u) +
        (++sequence * 0x9e3779b9u);
    uint8_t request[12] = {'C', 'L', 'D', 'S', 'D', 'I', 'S', 'C'};
    request[8] = static_cast<uint8_t>(nonce >> 24);
    request[9] = static_cast<uint8_t>(nonce >> 16);
    request[10] = static_cast<uint8_t>(nonce >> 8);
    request[11] = static_cast<uint8_t>(nonce);

#ifdef CL_NDS
    // DSWifi's select timeout can remain pending while its cooperative radio
    // thread is starved. Poll nonblocking once per VBlank instead, with a
    // frame-count deadline that cannot turn a three-second search into minutes
    // if the system counter stops advancing.
    nonblock(fd);
    const uint64_t frameLimit =
        (static_cast<uint64_t>(timeout) * 60 + 999) / 1000;
    constexpr uint64_t retryFrames = 21; // about 350 ms at 60 Hz
    uint8_t response[12];
    for (uint64_t frame = 0; frame < frameLimit && platform::alive(); ++frame) {
      if (!platform::pollNetwork())
        throw Error("Cancelado.");
      if (frame % retryFrames == 0)
        (void)sendto(fd, request, sizeof(request), 0,
                     reinterpret_cast<const sockaddr *>(&target),
                     sizeof(target));

      sockaddr_in source{};
      socklen_t sourceLength = sizeof(source);
      const ssize_t received = recvfrom(
          fd, response, sizeof(response), 0,
          reinterpret_cast<sockaddr *>(&source), &sourceLength);
      if (received < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)
          continue;
        break;
      }
      if (received != sizeof(response) ||
          std::memcmp(response, "CLPCDISC", 8) ||
          std::memcmp(response + 8, request + 8, 4) ||
          ntohs(source.sin_port) != port || !source.sin_addr.s_addr)
        continue;

      const uint32_t address = ntohl(source.sin_addr.s_addr);
      const unsigned a = static_cast<unsigned>((address >> 24) & 255u);
      const unsigned b = static_cast<unsigned>((address >> 16) & 255u);
      const unsigned c = static_cast<unsigned>((address >> 8) & 255u);
      const unsigned d = static_cast<unsigned>(address & 255u);
      char text[16];
      std::snprintf(text, sizeof(text), "%u.%u.%u.%u", a, b, c, d);
      Connection::close(fd);
      return text;
    }
    Connection::close(fd);
    return {};
#else
    const uint64_t started = platform::milliseconds();
    uint64_t nextSend = 0;
    while (platform::alive()) {
      const uint64_t now = platform::milliseconds();
      if (now - started >= timeout)
        break;
      if (now >= nextSend) {
        (void)sendto(fd, request, sizeof(request), 0,
                     reinterpret_cast<const sockaddr *>(&target),
                     sizeof(target));
        nextSend = now + 350;
      }
      if (!platform::pollNetwork())
        throw Error("Cancelado.");

      const uint64_t elapsed = platform::milliseconds() - started;
      const uint64_t remaining = elapsed < timeout ? timeout - elapsed : 0;
      timeval wait{static_cast<long>(std::min<uint64_t>(remaining, 100) / 1000),
                   static_cast<long>(std::min<uint64_t>(remaining, 100) % 1000) *
                       1000};
      fd_set readable;
      FD_ZERO(&readable);
      FD_SET(fd, &readable);
      const int ready = select(fd + 1, &readable, nullptr, nullptr, &wait);
      if (ready < 0) {
        if (errno == EINTR)
          continue;
        break;
      }
      if (!ready)
        continue;

      uint8_t response[12];
      sockaddr_in source{};
      socklen_t sourceLength = sizeof(source);
      const ssize_t received = recvfrom(
          fd, response, sizeof(response), 0,
          reinterpret_cast<sockaddr *>(&source), &sourceLength);
      if (received != sizeof(response) ||
          std::memcmp(response, "CLPCDISC", 8) ||
          std::memcmp(response + 8, request + 8, 4) ||
          ntohs(source.sin_port) != port || !source.sin_addr.s_addr)
        continue;

      const uint32_t address = ntohl(source.sin_addr.s_addr);
      const unsigned a = static_cast<unsigned>((address >> 24) & 255u);
      const unsigned b = static_cast<unsigned>((address >> 16) & 255u);
      const unsigned c = static_cast<unsigned>((address >> 8) & 255u);
      const unsigned d = static_cast<unsigned>(address & 255u);
      char text[16];
      std::snprintf(text, sizeof(text), "%u.%u.%u.%u", a, b, c, d);
      Connection::close(fd);
      return text;
    }
    Connection::close(fd);
    return {};
#endif
  } catch (...) {
    Connection::close(fd);
    throw;
  }
}

int Connection::listen(unsigned port) {
  int fd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
  if (fd < 0)
    throw Error("Recepcao: socket (erro " + std::to_string(errno) + ").");
  try {
    nonblock(fd);
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    sockaddr_in a{};
#if defined(__NDS__)
    a.sin_len = sizeof(a);
#endif
    a.sin_family = AF_INET;
    a.sin_port = htons(port);
    a.sin_addr.s_addr = htonl(INADDR_ANY);
    if (bind(fd, reinterpret_cast<sockaddr *>(&a), sizeof(a)))
      throw Error("Recepcao: bind " + std::to_string(port) + " (erro " +
                  std::to_string(errno) + ").");
    if (::listen(fd, 1))
      throw Error("Recepcao: listen " + std::to_string(port) + " (erro " +
                  std::to_string(errno) + ").");
    return fd;
  } catch (...) {
    close(fd);
    throw;
  }
}
std::unique_ptr<Connection> Connection::tryAccept(int server) {
  int fd = ::accept(server, nullptr, nullptr);
  if (fd >= 0)
    return std::make_unique<Connection>(fd);
  if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)
    return {};
  throw Error("Falha ao aceitar conexao.");
}
Connection Connection::accept(int server) {
  uint64_t since = platform::milliseconds();
  for (;;) {
    ready(server, false, since, 10 * 60 * 1000);
    int fd = ::accept(server, nullptr, nullptr);
    if (fd >= 0)
      return Connection(fd);
    if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
      throw Error("Falha ao aceitar conexao.");
  }
}
Connection Connection::connect(const std::string &ip, unsigned port,
                               unsigned timeout) {
  sockaddr_in a{};
#if defined(__NDS__)
  a.sin_len = sizeof(a);
#endif
  a.sin_family = AF_INET;
  a.sin_port = htons(port);
  if (inet_pton(AF_INET, ip.c_str(), &a.sin_addr) != 1)
    throw Error("IP invalido.");
  int fd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
  if (fd < 0)
    throw Error("Nao foi possivel criar socket.");
  try {
    nonblock(fd);
    int n = ::connect(fd, reinterpret_cast<sockaddr *>(&a), sizeof(a));
    if (n < 0 && errno != EINPROGRESS && errno != EWOULDBLOCK &&
        errno != EAGAIN)
      throw Error("Destino nao respondeu. Confira IP e Wi-Fi.");
    if (n < 0) {
      ready(fd, true, platform::milliseconds(), timeout);
      int error = 0;
      socklen_t size = sizeof(error);
      int status = getsockopt(fd, SOL_SOCKET, SO_ERROR, &error, &size);
      const int statusError = errno;
#ifdef CL_3DS
      // The 3DS socket stack can leave its internal EINPROGRESS value (-26)
      // in SO_ERROR after the handshake. lwIP on DS uses standard SO_ERROR.
      if (!status && error == -26) {
        int retry = ::connect(fd, reinterpret_cast<sockaddr *>(&a), sizeof(a));
        const int retryError = errno;
        if (!retry || (retry < 0 && retryError == EISCONN))
          error = 0;
      }
#endif
      if (status || error)
        throw Error("Falha TCP para " + ip + ":" + std::to_string(port) +
                    " (erro " +
                    std::to_string(status ? statusError : error) +
                    "). Confira o IP, o Wi-Fi e se o servico Chest Link esta "
                    "ativo.");
    }
    return Connection(fd);
  } catch (...) {
    close(fd);
    throw;
  }
}

bool sendUpdateTrace(int &socketHandle, const std::string &serverIP,
                     unsigned port, const std::string &jsonRecord) {
  if (!port || port > 65535 || jsonRecord.empty() || jsonRecord.size() > 1100)
    return false;
  if (socketHandle < 0)
    socketHandle = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
  if (socketHandle < 0)
    return false;
  sockaddr_in address{};
#if defined(__NDS__)
  address.sin_len = sizeof(address);
#endif
  address.sin_family = AF_INET;
  address.sin_port = htons(port);
  if (inet_pton(AF_INET, serverIP.c_str(), &address.sin_addr) != 1)
    return false;
  static const char magic[] = "CLUPDLOG";
  std::string packet(magic, 8);
  packet += jsonRecord;
  const ssize_t sent = sendto(socketHandle, packet.data(), packet.size(), 0,
                              reinterpret_cast<sockaddr *>(&address),
                              sizeof(address));
  return sent == static_cast<ssize_t>(packet.size());
}

void closeUpdateTraceSocket(int &socketHandle) {
  if (socketHandle >= 0) {
    Connection::close(socketHandle);
    socketHandle = -1;
  }
}

bool sendUpdateTrace(const std::string &serverIP, unsigned port,
                     const std::string &jsonRecord) {
  int socketHandle = -1;
  const bool sent = sendUpdateTrace(socketHandle, serverIP, port, jsonRecord);
  closeUpdateTraceSocket(socketHandle);
  return sent;
}
} // namespace chestlink
