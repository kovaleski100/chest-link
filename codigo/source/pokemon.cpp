// Read-only PKX decoding based on PKSM-Core's PK1/2/3/4/5/6/8 and
// utils/crypto.hpp. Copyright (C) 2016-2022 Bernardo Giordano, Admiral Fish,
// piepie62. Adapted for Chest Link: summaries only, never writes raw PKX data.
// GPL-3.0-or-later, including upstream section 7(b)/(c) notices.
#include "pokemon.hpp"
#include "catalog.hpp"
#include <algorithm>
#include <cstring>
namespace chestlink {
namespace {
uint16_t u16(const uint8_t *p) { return p[0] | uint16_t(p[1]) << 8; }
uint16_t checksum(const uint8_t *p, unsigned n) {
  uint16_t out = 0;
  for (unsigned i = 0; i < n; i += 2)
    out += u16(p + i);
  return out;
}
void shuffle(uint8_t *p, unsigned block, unsigned index) {
  uint8_t temp[320];
  std::memcpy(temp, p, block * 4);
  const auto *order = catalog::blockPositions + (index % 24) * 4;
  for (unsigned i = 0; i < 4; ++i)
    std::memcpy(p + i * block, temp + order[i] * block, block);
}
bool uncrypt(uint8_t *p, unsigned start, unsigned n, uint32_t seed,
             unsigned block, unsigned index, uint16_t sum) {
  if (checksum(p + start, n) == sum)
    return true;
  for (unsigned i = start; i < start + n; i += 2) {
    seed = seed * 0x41c64e6d + 0x6073;
    p[i] ^= seed >> 16;
    p[i + 1] ^= seed >> 24;
  }
  shuffle(p + start, block, index);
  return checksum(p + start, n) == sum;
}
} // namespace
const char *speciesName(unsigned species) {
  return species < sizeof(catalog::names) / sizeof(*catalog::names)
             ? catalog::names[species]
             : "Registro desconhecido";
}
const char *generationName(unsigned gen) {
  const char *s[] = {"IV", "V", "VI", "VII", "LGPE", "VIII", "III", "I", "II"};
  return gen < 9 ? s[gen] : "?";
}
PokemonPreview previewPokemon(const uint8_t *entry) {
  PokemonPreview out;
  out.generation = le32(entry);
  if (out.generation == 0xffffffff)
    return out;
  out.occupied = true;
  if (out.generation > 8)
    return out;
  uint8_t p[328];
  std::memcpy(p, entry + 4, sizeof(p));
  unsigned gen = out.generation, tid = 0, sid = 0, pid = 0, limit = 898;
  if (gen == 7 || gen == 8) {
    unsigned id = p[3];
    if (gen == 7) {
      if (id >= sizeof(catalog::g1ToSpecies) / sizeof(uint16_t))
        return out;
      out.species = catalog::g1ToSpecies[id];
      limit = 151;
    } else {
      out.species = id;
      limit = 251;
      out.egg = p[1] == 0xfd;
      if (out.species == 201) {
        unsigned a = p[3 + 21] >> 4, d = p[3 + 21] & 15;
        unsigned speed = p[3 + 22] >> 4, sp = p[3 + 22] & 15;
        out.form = (((a & 6) << 5) | ((d & 6) << 3) | ((speed & 6) << 1) |
                    ((sp & 6) >> 1)) /
                   10;
      }
    }
    // PKSM's GB records have a three-byte list header. Do not read names or
    // assume Japanese/international name lengths when identifying a species.
    if (!out.egg && p[1] != p[3])
      return out;
    unsigned dv = gen == 7 ? 30 : 24;
    out.shiny = (p[dv] & 15) == 10 && (p[dv + 1] >> 4) == 10 &&
                (p[dv + 1] & 15) == 10 && ((p[dv] >> 4) & 2);
  } else if (gen == 6) {
    if (checksum(p + 32, 48) != u16(p + 28)) {
      uint32_t key = le32(p) ^ le32(p + 4);
      for (unsigned i = 32; i < 80; ++i)
        p[i] ^= key >> ((i & 3) * 8);
      shuffle(p + 32, 12, le32(p) % 24);
      if (checksum(p + 32, 48) != u16(p + 28))
        return out;
    }
    unsigned id = u16(p + 32);
    if (id >= sizeof(catalog::g3ToSpecies) / sizeof(uint16_t))
      return out;
    out.species = catalog::g3ToSpecies[id];
    limit = 386;
    out.egg = (le32(p + 72) >> 30) & 1;
    pid = le32(p);
    tid = u16(p + 4);
    sid = u16(p + 6);
    if (out.species == 201)
      out.form = (((pid & 0x3000000) >> 18) | ((pid & 0x30000) >> 12) |
                  ((pid & 0x300) >> 6) | (pid & 3)) %
                 28;
  } else {
    unsigned length = gen <= 1 ? 128 : gen == 5 ? 320 : 224;
    uint32_t seed = gen <= 1 ? u16(p + 6) : le32(p);
    if (!uncrypt(p, 8, length, seed, length / 4, (le32(p) >> 13) & 31,
                 u16(p + 6)))
      return out;
    out.species = u16(p + 8);
    tid = u16(p + 12);
    sid = u16(p + 14);
    if (gen <= 1) {
      out.form = p[0x40] >> 3;
      out.egg = (le32(p + 0x38) >> 30) & 1;
      pid = le32(p);
      limit = gen == 0 ? 493 : 649;
    } else if (gen == 5) {
      out.form = u16(p + 0x24);
      out.egg = (le32(p + 0x8c) >> 30) & 1;
      pid = le32(p + 0x1c);
    } else {
      out.form = p[0x1d] >> 3;
      out.egg = (le32(p + 0x74) >> 30) & 1;
      pid = le32(p + 0x18);
      limit = gen == 2 ? 721 : 809;
    }
  }
  out.valid = out.species > 0 && out.species <= limit;
  if (!out.valid) {
    out.species = 0;
    out.form = 0;
    return out;
  }
  if (gen < 7)
    out.shiny = (tid ^ sid ^ (pid & 65535) ^ (pid >> 16)) <
                (gen <= 1 || gen == 6 ? 8u : 16u);
  out.sprite = pokemonSprite(out.species, out.form, gen, out.egg);
  return out;
}
} // namespace chestlink
