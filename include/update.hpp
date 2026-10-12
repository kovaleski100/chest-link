#pragma once
#include "core.hpp"

namespace chestlink {
enum class UpdateState { current, cancelled, installed };
struct UpdateResult {
  UpdateState state = UpdateState::current;
  uint32_t version = 0;
  uint32_t bytes = 0;
};

// Downloads one authenticated-by-PIN update, verifies SHA-256, then replaces
// installPath while preserving the previous file beside it. NDS may install
// to a new file because the running .nds path is not reliably exposed.
UpdateResult update3DS(Wire &, uint32_t pin, uint32_t currentVersion,
                       const std::string &installPath,
                       std::function<bool(uint32_t, uint32_t, uint32_t)> accept,
                       Progress progress = {});
UpdateResult updateNDS(Wire &, uint32_t pin, uint32_t currentVersion,
                       const std::string &installPath,
                       std::function<bool(uint32_t, uint32_t, uint32_t)> accept,
                       Progress progress = {});
} // namespace chestlink
