#pragma once
#include "core.hpp"

namespace chestlink {
struct GameSaveInfo {
  std::string path, title;
  unsigned generation = 0; // PKSM generation index (Gen I = 7, Gen II = 8).
  unsigned boxes = 0;
};

struct GameSaveBox {
  std::string name;
  std::array<uint8_t, BOX_BYTES> entries{};
};

struct GameSave {
  GameSaveInfo info;
  std::vector<GameSaveBox> boxes;
};

// Searches mounted SD/flashcard storage for raw .sav files, then only returns
// files whose layout and save checksums identify a supported Pokémon game.
std::vector<GameSaveInfo> discoverGameSaves();
// Opens a selected save read-only and normalizes its stored boxes to PKSM bank
// records. The source file is never changed.
GameSave readGameSave(const GameSaveInfo &);
} // namespace chestlink
