#pragma once
#include "network_status.hpp"
namespace platform_detail {
void refresh3DSNetworkStatus(bool force = false);
void require3DSNetwork();
void shutdown3DSNetwork();
const chestlink::NetworkStatus &network3DSStatus();
} // namespace platform_detail
