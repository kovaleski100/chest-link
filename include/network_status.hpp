#pragma once
#include <cstdint>
#include <string>

namespace chestlink {
enum class InternetAccess { unknown, checking, reachable, unconfirmed };
struct NetworkStatus {
  bool visible = false, connected = false, connecting = false, ipv4Ready = false;
  std::string ssid, ip;
  InternetAccess internet = InternetAccess::unknown;
  bool operator==(const NetworkStatus &o) const {
    return visible == o.visible && connected == o.connected &&
           connecting == o.connecting && ipv4Ready == o.ipv4Ready &&
           ssid == o.ssid && ip == o.ip && internet == o.internet;
  }
};

// Scheduling only: socket work is nonblocking and supplied by each adapter.
// A changed SSID/IP invalidates results from the preceding network.
class InternetProbeSchedule {
  bool ready_ = false, pending_ = false, attempted_ = false;
  std::string ssid_, ip_;
  uint64_t started_ = 0, finished_ = 0;
  InternetAccess result_ = InternetAccess::unknown;
public:
  static constexpr uint64_t INTERVAL_MS = 30000, TIMEOUT_MS = 4000;
  bool link(const std::string &ssid, const std::string &ip, bool ready) {
    if (ssid == ssid_ && ip == ip_ && ready == ready_) return false;
    ssid_ = ssid; ip_ = ip; ready_ = ready;
    pending_ = attempted_ = false;
    result_ = InternetAccess::unknown;
    return true;
  }
  bool due(uint64_t now) const {
    return ready_ && !pending_ && (!attempted_ || now - finished_ >= INTERVAL_MS);
  }
  void begin(uint64_t now) {
    if (!ready_) return;
    pending_ = true; started_ = now; result_ = InternetAccess::checking;
  }
  bool expired(uint64_t now) const { return pending_ && now - started_ >= TIMEOUT_MS; }
  void finish(bool success, uint64_t now) {
    if (!pending_) return;
    pending_ = false; attempted_ = true; finished_ = now;
    result_ = success ? InternetAccess::reachable : InternetAccess::unconfirmed;
  }
  bool pending() const { return pending_; }
  InternetAccess result() const { return result_; }
};
} // namespace chestlink
