#pragma once
#include "core.hpp"
#include <memory>
#include <string>
namespace chestlink {
class Connection {
  int fd_ = -1;

public:
  explicit Connection(int fd);
  ~Connection();
  Connection(const Connection &) = delete;
  Connection &operator=(const Connection &) = delete;
  Wire wire();
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
  void exact(void *, size_t, bool write);
};
} // namespace chestlink
