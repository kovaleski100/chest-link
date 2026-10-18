#pragma once
#include "core.hpp"

namespace chestlink {
constexpr unsigned UPDATE_DOWNLOAD_IDLE_TIMEOUT_MS = 30000;
enum class UpdateState { current, cancelled, installed };
struct UpdateResult {
  UpdateState state = UpdateState::current;
  uint32_t version = 0;
  uint32_t bytes = 0;
};

// Downloads one authenticated-by-PIN update and verifies SHA-256 before
// installing it. The NDS caller chooses a versioned path beside the running
// ROM when its launcher exposes that path.
UpdateResult update3DS(Wire &, uint32_t pin, uint32_t currentVersion,
                       const std::string &installPath,
                       std::function<bool(uint32_t, uint32_t, uint32_t)> accept,
                       Progress progress = {});
UpdateResult updateNDS(Wire &, uint32_t pin, uint32_t currentVersion,
                       const std::string &installPath,
                       std::function<bool(uint32_t, uint32_t, uint32_t)> accept,
                       Progress progress = {});
// Remove only backups with an update receipt matching this newly launched
// executable's version AND SHA-256. Unknown/manual copies are not inferred.
unsigned removePrevious3DSUpdates(const std::string &runningPath,
                                 uint32_t currentVersion, bool &complete);
} // namespace chestlink
