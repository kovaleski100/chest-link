#pragma once
#include "network_status.hpp"
#include <cstddef>

namespace platform_detail {
inline chestlink::NetworkStatus nativeNetworkSnapshot(
    bool statusOK, uint32_t wifiStatus, bool ssidOK, const char *ssid,
    size_t ssidLength, const std::string &ip) {
  chestlink::NetworkStatus snapshot;
  snapshot.visible = true;
  // ACU_GetWifiStatus identifies the current AP. Any nonzero AP flags are
  // usable; they are not the separate GetStatus connection-state enum.
  snapshot.connected = statusOK && wifiStatus != 0;
  if (!snapshot.connected) return snapshot; // Discard stale SSID and IP.
  if (ssidOK && ssid && ssidLength <= 32)
    snapshot.ssid.assign(ssid, ssidLength);
  snapshot.ipv4Ready = !ip.empty() && ip != "0.0.0.0" && ip != "255.255.255.255";
  if (snapshot.ipv4Ready) snapshot.ip = ip;
  return snapshot;
}
} // namespace platform_detail
