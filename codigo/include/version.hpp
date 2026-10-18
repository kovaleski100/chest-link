#pragma once
#include <cstdint>
#include <string>

#define CHEST_LINK_VERSION_MAJOR 0
#define CHEST_LINK_VERSION_MINOR 5
#define CHEST_LINK_VERSION_PATCH 14

namespace chestlink {
constexpr uint32_t APP_VERSION_CODE =
    (CHEST_LINK_VERSION_MAJOR << 16) | (CHEST_LINK_VERSION_MINOR << 8) |
    CHEST_LINK_VERSION_PATCH;
inline std::string appVersionText(uint32_t version) {
  return std::to_string((version >> 16) & 0xff) + "." +
         std::to_string((version >> 8) & 0xff) + "." +
         std::to_string(version & 0xff);
}
} // namespace chestlink
