#pragma once
#include "network_status.hpp"

namespace chestlink {
// Keep the receiver PIN outside this object. Wi-Fi/IP changes invalidate the
// socket and retry delay, but never authorize receiving or rotate the PIN.
class ListenerSchedule {
  std::string ssid_, ip_;
  bool ready_ = false, attempted_ = false;
  uint64_t lastAttempt_ = 0;
public:
  bool link(const NetworkStatus &status) {
    const bool ready = status.connected && status.ipv4Ready && !status.ip.empty();
    if (ready == ready_ && status.ssid == ssid_ && status.ip == ip_) return false;
    ready_ = ready; ssid_ = status.ssid; ip_ = status.ip; attempted_ = false;
    return true;
  }
  bool ready() const { return ready_; }
  bool due(uint64_t now) const {
    return ready_ && (!attempted_ || now - lastAttempt_ >= 1000);
  }
  void attempted(uint64_t now) { attempted_ = true; lastAttempt_ = now; }
};
} // namespace chestlink
