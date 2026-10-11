#pragma once
#include "core.hpp"
namespace chestlink {
// Read-only summary. A failed preview never edits or rejects a transferable raw
// record: unsupported/corrupt PKX content is displayed as an unknown record.
struct PokemonPreview {
  bool occupied = false, valid = false, egg = false, shiny = false;
  uint16_t species = 0, form = 0;
  uint32_t generation = 0;
  unsigned sprite = 0;
};
PokemonPreview previewPokemon(const uint8_t *entry);
const char *speciesName(unsigned);
const char *generationName(unsigned);
unsigned pokemonSprite(unsigned species, unsigned form, unsigned generation,
                       bool egg);
} // namespace chestlink
