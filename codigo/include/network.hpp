#pragma once
#include "core.hpp"
#include <memory>
#include <string>
namespace chestlink {
constexpr unsigned DEFAULT_WIRE_IDLE_TIMEOUT_MS = 180000;
constexpr unsigned UPDATE_WIRE_IDLE_TIMEOUT_MS = 600000;
class Connection {
  int fd_ = -1;

public:
  explicit Connection(int fd);
  ~Connection();
  Connection(const Connection &) = delete;
  Connection &operator=(const Connection &) = delete;
  Connection(Connection &&other) noexcept;
  Connection &operator=(Connection &&other) noexcept;
  Wire wire(unsigned idleTimeoutMs = DEFAULT_WIRE_IDLE_TIMEOUT_MS,
            std::function<void(bool, size_t)> activity = {});
  static int listen(unsigned port = PORT);
  // Poll a listening socket without taking ownership of the main UI loop.
  // The console can therefore keep showing its storage screen while waiting
  // for a direct transfer.
  static std::unique_ptr<Connection> tryAccept(int server);
  static Connection accept(int server);
  static Connection connect(const std::string &ip, unsigned port = PORT,
                            unsigned timeout = 20000);
  static void close(int fd);

private:
  void exact(void *, size_t, bool write, unsigned idleTimeoutMs,
             const std::function<void(bool, size_t)> &activity);
};

// Locate the Chest Link PC server on the local IPv4 network using UDP
// broadcast. Returns the replying host address, or an empty string on timeout.
std::string discoverPCServer(unsigned port, unsigned timeout = 3000);

// Best-effort local update diagnostics sent over UDP. The data is a redacted
// JSON event record, not protocol payload or credentials.
bool sendUpdateTrace(int &socket, const std::string &serverIP, unsigned port,
                     const std::string &jsonRecord);
void closeUpdateTraceSocket(int &socket);
bool sendUpdateTrace(const std::string &serverIP, unsigned port,
                     const std::string &jsonRecord);
} // namespace chestlink
