#include "network.hpp"
#include "platform.hpp"
extern "C" {
#include <arpa/inet.h>
}
#include <cerrno>
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
    throw Error("Nao foi possivel configurar socket.");
}
void ready(int fd, bool writing, uint64_t since, unsigned timeout = 180000) {
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
    if (platform::milliseconds() - since > timeout)
      throw Error("Tempo de espera esgotado. Origem preservada.");
  }
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
void Connection::close(int fd) {
  if (fd < 0)
    return;
#ifdef CL_NDS
  closesocket(fd);
#else
  ::close(fd);
#endif
}
Wire Connection::wire() {
  return {[this](void *p, size_t n) { exact(p, n, false); },
          [this](const void *p, size_t n) {
            exact(const_cast<void *>(p), n, true);
          }};
}
void Connection::exact(void *data, size_t n, bool writing) {
  auto *p = static_cast<uint8_t *>(data);
  uint64_t last = platform::milliseconds();
  while (n) {
    ready(fd_, writing, last);
#ifdef CL_HOST
    int sendFlags = MSG_NOSIGNAL;
#else
    int sendFlags = 0;
#endif
    int rc = writing ? ::send(fd_, p, n, sendFlags) : ::recv(fd_, p, n, 0);
    if (rc < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR))
      continue;
    if (rc <= 0)
      throw Error("Conexao interrompida. Confira o destino antes de repetir.");
    p += rc;
    n -= rc;
    last = platform::milliseconds();
  }
}
int Connection::listen(unsigned port) {
  int fd = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
  if (fd < 0)
    throw Error("Nao foi possivel abrir servidor.");
  try {
    nonblock(fd);
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    sockaddr_in a{};
#ifdef CL_NDS
    a.sin_len = sizeof(a);
#endif
    a.sin_family = AF_INET;
    a.sin_port = htons(port);
    a.sin_addr.s_addr = htonl(INADDR_ANY);
    if (bind(fd, reinterpret_cast<sockaddr *>(&a), sizeof(a)) ||
        ::listen(fd, 1))
      throw Error("Nao foi possivel usar a porta 40991.");
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
#ifdef CL_NDS
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
} // namespace chestlink
