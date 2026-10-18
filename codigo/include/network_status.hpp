#pragma once
#include <cstdint>
#include <string>

namespace chestlink {
enum class ServerAvailability { unknown, searching, connected, notFound };
struct NetworkStatus {
  bool visible = false, connected = false, connecting = false, ipv4Ready = false;
  std::string ssid, ip, serverIP;
  ServerAvailability server = ServerAvailability::unknown;
  bool operator==(const NetworkStatus &o) const {
    return visible == o.visible && connected == o.connected &&
           connecting == o.connecting && ipv4Ready == o.ipv4Ready &&
           ssid == o.ssid && ip == o.ip && serverIP == o.serverIP &&
           server == o.server;
  }
};

// Scheduling only: socket work is nonblocking and supplied by each adapter.
// A changed SSID/IP invalidates results from the preceding network.
class ServerProbeSchedule {
  bool ready_ = false, pending_ = false, attempted_ = false;
  std::string ssid_, ip_;
  uint64_t started_ = 0, finished_ = 0;
  std::string serverIP_;
  ServerAvailability result_ = ServerAvailability::unknown;
public:
  static constexpr uint64_t INTERVAL_MS = 30000, TIMEOUT_MS = 3000;
  bool link(const std::string &ssid, const std::string &ip, bool ready) {
    if (ssid == ssid_ && ip == ip_ && ready == ready_) return false;
    ssid_ = ssid; ip_ = ip; ready_ = ready;
    pending_ = attempted_ = false;
    serverIP_.clear();
    result_ = ServerAvailability::unknown;
    return true;
  }
  bool due(uint64_t now) const {
    return ready_ && !pending_ && (!attempted_ || now - finished_ >= INTERVAL_MS);
  }
  void begin(uint64_t now) {
    if (!ready_) return;
    pending_ = true; started_ = now;
    if (result_ != ServerAvailability::connected)
      result_ = ServerAvailability::searching;
  }
  bool expired(uint64_t now) const { return pending_ && now - started_ >= TIMEOUT_MS; }
  void finish(const std::string &serverIP, uint64_t now) {
    if (!pending_) return;
    pending_ = false; attempted_ = true; finished_ = now;
    serverIP_ = serverIP;
    result_ = serverIP.empty() ? ServerAvailability::notFound
                               : ServerAvailability::connected;
  }
  bool pending() const { return pending_; }
  ServerAvailability result() const { return result_; }
  const std::string &serverIP() const { return serverIP_; }
};
} // namespace chestlink
