#include "game_saves.hpp"
#include "platform.hpp"
#include "pokemon.hpp"
#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstring>
#include <dirent.h>
#include <set>
#include <sys/stat.h>

namespace chestlink {
namespace {
constexpr unsigned GEN1 = 7, GEN2 = 8, GEN3 = 6, GEN4 = 0;
constexpr unsigned GB_SAVE_SIZE = 0x8000, GB_JP_SAVE_SIZE = 0x10000;
constexpr unsigned GEN3_SAVE_SIZE = 0x20000, GEN4_SAVE_SIZE = 0x80000;
constexpr unsigned GEN3_SECTOR = 0x1000, GEN3_PAYLOAD = 0xF80;
constexpr unsigned GEN3_SECTORS = 14, GEN3_SLOTS = 2;
constexpr uint32_t GEN3_MAGIC = 0x08012025;
constexpr unsigned GEN4_PARTITION = 0x40000;
constexpr uint32_t GEN4_MAGIC_A = 0x20060623, GEN4_MAGIC_B = 0x20070903;
constexpr unsigned MAX_SCAN_DIRS = 512, MAX_SCAN_FILES = 512,
                   MAX_FOUND_SAVES = 64, MAX_SCAN_DEPTH = 8;

struct G12Layout {
  const char *key;
  unsigned party, currentBox, capacity, boxes, split, stringLength;
  unsigned checksum, checksumEnd, checksum2;
  bool gen2, japanese;
};

const G12Layout gen1Layouts[] = {
    {"international", 0x2F2C, 0x30C0, 20, 12, 6, 11, 0x3523, 0, 0, false, false},
    {"japanese", 0x2ED5, 0x302D, 30, 8, 4, 6, 0x3594, 0, 0, false, true},
};
const G12Layout gen2Layouts[] = {
    {"gs-int", 0x288A, 0x2D6C, 20, 14, 7, 11, 0x2D69, 0x2D68, 0x7E6D, true, false},
    {"crystal-int", 0x2865, 0x2D10, 20, 14, 7, 11, 0x2D0D, 0x2B82, 0x1F0D, true, false},
    {"gs-jpn", 0x283E, 0x2D10, 30, 9, 6, 6, 0x2D0D, 0x2C8B, 0x7F0D, true, true},
    {"crystal-jpn", 0x281A, 0x2D10, 30, 9, 6, 6, 0x2D0D, 0x2AE2, 0x7F0D, true, true},
    {"gs-kor", 0x28CC, 0x2DAE, 20, 14, 7, 11, 0x2DAB, 0x2DAA, 0x7E6B, true, false},
};

uint16_t u16le(const uint8_t *p) { return uint16_t(p[0]) | uint16_t(p[1]) << 8; }
uint32_t u32le(const uint8_t *p) {
  return uint32_t(p[0]) | uint32_t(p[1]) << 8 | uint32_t(p[2]) << 16 |
         uint32_t(p[3]) << 24;
}
void put32le(uint8_t *p, uint32_t v) {
  p[0] = uint8_t(v); p[1] = uint8_t(v >> 8);
  p[2] = uint8_t(v >> 16); p[3] = uint8_t(v >> 24);
}
bool allZero(const uint8_t *p, unsigned n) {
  for (unsigned i = 0; i < n; ++i) if (p[i]) return false;
  return true;
}
std::string lower(std::string s) {
  for (char &c : s) c = char(std::tolower(static_cast<unsigned char>(c)));
  return s;
}
bool hasToken(const std::string &path, const char *token) {
  return lower(path).find(token) != std::string::npos;
}
bool isSupportedSize(uint32_t size) {
  return size == GB_SAVE_SIZE || size == GB_JP_SAVE_SIZE ||
         size == GEN3_SAVE_SIZE || size == GEN4_SAVE_SIZE;
}
bool isSav(const std::string &name) {
  return name.size() >= 4 && lower(name.substr(name.size() - 4)) == ".sav";
}

std::vector<uint8_t> readRawSave(const std::string &path) {
  struct stat before{};
  if (stat(path.c_str(), &before) || !S_ISREG(before.st_mode) ||
      before.st_size < 0 || !isSupportedSize(uint32_t(before.st_size)))
    throw Error("Arquivo .sav indisponivel ou com tamanho nao suportado.");
  FILE *f = std::fopen(path.c_str(), "rb");
  if (!f) throw Error("Nao foi possivel abrir o save para leitura.");
  std::vector<uint8_t> data(static_cast<size_t>(before.st_size));
  const size_t got = std::fread(data.data(), 1, data.size(), f);
  const bool readError = got != data.size() || std::ferror(f);
  std::fclose(f);
  struct stat after{};
  if (readError || stat(path.c_str(), &after) || before.st_size != after.st_size ||
      before.st_mtime != after.st_mtime)
    throw Error("O save mudou ou falhou durante a leitura; tente novamente.");
  return data;
}

bool listValid(const uint8_t *data, size_t size, unsigned offset,
               unsigned maximum) {
  return offset < size && data[offset] <= maximum &&
         uint64_t(offset) + 1 + data[offset] < size &&
         data[offset + 1 + data[offset]] == 0xFF;
}
bool gen1Checksum(const std::vector<uint8_t> &d, const G12Layout &l) {
  if (l.checksum >= d.size() || l.checksum < 0x2598) return false;
  uint8_t sum = 0;
  for (unsigned i = 0x2598; i < l.checksum; ++i) sum += d[i];
  return d[l.checksum] == uint8_t(~sum);
}
bool gen2Checksum(const std::vector<uint8_t> &d, const G12Layout &l) {
  if (l.checksumEnd >= d.size() || l.checksum + 2 > d.size() ||
      l.checksum2 + 2 > d.size()) return false;
  uint32_t sum = 0;
  for (unsigned i = 0x2009; i <= l.checksumEnd; ++i) sum += d[i];
  const uint16_t expected = uint16_t(sum);
  if (u16le(d.data() + l.checksum) != expected) return false;
  if (std::strcmp(l.key, "gs-kor") != 0)
    return u16le(d.data() + l.checksum2) == expected;
  uint32_t koreanSum = 0;
  for (const auto &range : {std::pair<unsigned, unsigned>{0x106B, 0x1533},
                            {0x1534, 0x1A12}, {0x1A13, 0x1C38},
                            {0x3DD8, 0x3F79}, {0x7E39, 0x7E6A}})
    for (unsigned i = range.first; i < range.second; ++i)
      koreanSum += d[i];
  return u16le(d.data() + l.checksum2) == uint16_t(koreanSum);
}
unsigned boxListSize(const G12Layout &l, unsigned monSize) {
  return ((2 * l.stringLength + monSize + 1) * l.capacity) + 2;
}
unsigned rawBoxOffset(const G12Layout &l, unsigned box, unsigned monSize) {
  const unsigned start = box < l.split ? 0x4000 : 0x6000;
  return start + (box < l.split ? box : box - l.split) * boxListSize(l, monSize);
}
void emptyBox(std::array<uint8_t, BOX_BYTES> &box) {
  box.fill(0xFF);
}
bool validEntry(const uint8_t *entry) {
  const PokemonPreview p = previewPokemon(entry);
  return p.occupied && p.valid;
}
void makePKXEntry(uint8_t *entry, unsigned generation, const uint8_t *record,
                  unsigned recordSize, unsigned partySize,
                  const uint8_t *ot, const uint8_t *nickname,
                  unsigned stringLength, uint8_t listSpecies) {
  std::memset(entry, 0xFF, ENTRY);
  put32le(entry, generation);
  uint8_t *p = entry + 4;
  p[0] = 1;
  p[1] = listSpecies;
  p[2] = 0xFF;
  std::memcpy(p + 3, record, recordSize);
  std::memset(p + 3 + recordSize, 0, partySize - recordSize);
  std::memcpy(p + 3 + partySize, ot, stringLength);
  std::memcpy(p + 3 + partySize + stringLength, nickname, stringLength);
}
std::string gen1Name(const std::string &path, const std::vector<uint8_t> &d,
                     const G12Layout &l) {
  if (hasToken(path, "yellow")) return "Yellow";
  if (hasToken(path, "red")) return "Red";
  if (hasToken(path, "blue")) return "Blue";
  const unsigned starter = l.japanese ? 0x29B9 : 0x29C3;
  const unsigned friendship = l.japanese ? 0x2712 : 0x271C;
  if (starter < d.size() &&
      (d[starter] == 0x54 || (d[starter] == 0 && d[friendship] != 0)))
    return "Yellow";
  return l.japanese ? "Red / Green / Blue / Yellow (JP)" : "Red / Blue / Yellow";
}
std::string gen2Name(const std::string &path, const G12Layout &l) {
  if (l.key[0] == 'c') return "Crystal";
  if (hasToken(path, "gold")) return "Gold";
  if (hasToken(path, "silver")) return "Silver";
  return "Gold / Silver";
}

bool parseGBBox(const uint8_t *raw, size_t size, const G12Layout &l,
                unsigned generation, unsigned recordSize, unsigned partySize,
                std::array<uint8_t, BOX_BYTES> &out) {
  emptyBox(out);
  if (!listValid(raw, size, 0, l.capacity)) return false;
  const unsigned count = raw[0];
  const unsigned records = l.capacity + 2;
  const unsigned namesOT = records + l.capacity * recordSize;
  const unsigned namesNick = namesOT + l.capacity * l.stringLength;
  const unsigned required = namesNick + l.capacity * l.stringLength;
  if (required > size) return false;
  unsigned slot = 0;
  for (unsigned i = 0; i < count && slot < SLOTS; ++i) {
    const uint8_t species = raw[1 + i];
    const uint8_t *mon = raw + records + i * recordSize;
    if (!species || species == 0xFF || (species != 0xFD && mon[0] != species))
      continue;
    uint8_t *entry = out.data() + slot * ENTRY;
    makePKXEntry(entry, generation, mon, recordSize, partySize,
                 raw + namesOT + i * l.stringLength,
                 raw + namesNick + i * l.stringLength, l.stringLength, species);
    if (validEntry(entry)) ++slot;
    else std::memset(entry, 0xFF, ENTRY);
  }
  return true;
}

GameSave parseGen12(const std::vector<uint8_t> &d, const std::string &path) {
  const G12Layout *selected = nullptr;
  unsigned generation = 0;
  if (d.size() == GB_SAVE_SIZE) {
    for (const auto &l : gen1Layouts) {
      if (!listValid(d.data(), d.size(), l.party, 6) ||
          !listValid(d.data(), d.size(), l.currentBox, l.capacity) ||
          !gen1Checksum(d, l)) continue;
      if (selected) throw Error("Layout Gen I ambiguo; save nao importado.");
      selected = &l;
    }
    generation = GEN1;
  } else {
    std::vector<const G12Layout *> candidates;
    for (const auto &l : gen2Layouts) {
      const bool japanese = std::strstr(l.key, "jpn") != nullptr;
      if (japanese != (d.size() == GB_JP_SAVE_SIZE) ||
          !listValid(d.data(), d.size(), l.party, 6) ||
          !listValid(d.data(), d.size(), l.currentBox, l.capacity) ||
          !gen2Checksum(d, l)) continue;
      candidates.push_back(&l);
    }
    if (candidates.size() == 1) selected = candidates.front();
    else if (!candidates.empty()) {
      const bool crystal = hasToken(path, "crystal");
      const bool goldSilver = hasToken(path, "gold") || hasToken(path, "silver");
      if (!crystal && !goldSilver)
        throw Error("Layout Gen II ambiguo sem nome de jogo reconhecivel.");
      for (const auto *candidate : candidates)
        if ((candidate->key[0] == 'c') == crystal) {
          if (selected) throw Error("Layout Gen II ambiguo; save nao importado.");
          selected = candidate;
        }
    }
    generation = GEN2;
  }
  if (!selected) throw Error("Save Gen I/II nao reconhecido ou checksum invalido.");

  GameSave save;
  save.info.path = path;
  save.info.generation = generation;
  save.info.boxes = selected->boxes;
  save.info.title = generation == GEN1 ? gen1Name(path, d, *selected)
                                        : gen2Name(path, *selected);
  save.boxes.resize(selected->boxes);
  const unsigned storedSize = boxListSize(*selected, generation == GEN1 ? 33 : 32);
  if (generation == GEN1) {
    const unsigned currentIndex = selected->japanese ? 0x2842 : 0x284C;
    if (currentIndex >= d.size()) throw Error("Indice da box Gen I ausente.");
    const uint8_t indexFlags = d[currentIndex];
    const unsigned activeBox = indexFlags & 0x7F;
    if (activeBox >= selected->boxes) throw Error("Box ativa Gen I invalida.");
    const bool initialized = (indexFlags & 0x80) != 0;
    for (unsigned box = 0; box < selected->boxes; ++box) {
      auto &destination = save.boxes[box];
      destination.name = "Box " + std::to_string(box + 1);
      emptyBox(destination.entries);
      if (box == activeBox) {
        if (!parseGBBox(d.data() + selected->currentBox,
                        d.size() - selected->currentBox, *selected, generation,
                        33, 44, destination.entries))
          throw Error("Box ativa Gen I invalida.");
      } else if (initialized) {
        const unsigned source = rawBoxOffset(*selected, box, 33);
        if (!parseGBBox(d.data() + source, d.size() - source, *selected,
                        generation, 33, 44, destination.entries))
          throw Error("Box Gen I invalida.");
      }
    }
  } else {
    for (unsigned box = 0; box < selected->boxes; ++box) {
      const unsigned source = rawBoxOffset(*selected, box, 32);
      if (source + storedSize > d.size()) throw Error("Box Gen II truncada.");
      auto &destination = save.boxes[box];
      destination.name = "Box " + std::to_string(box + 1);
      if (!parseGBBox(d.data() + source, d.size() - source, *selected,
                      generation, 32, 48, destination.entries))
        throw Error("Box Gen II invalida.");
    }
  }
  return save;
}

uint16_t gen3Checksum(const uint8_t *data, unsigned size) {
  if (size % 4) return 0xFFFF;
  uint32_t sum = 0;
  for (unsigned i = 0; i < size; i += 4) sum += u32le(data + i);
  return uint16_t((sum >> 16) + (sum & 0xFFFF));
}
struct Gen3Slot {
  bool valid = false;
  uint32_t counter = 0;
  std::array<std::vector<uint8_t>, GEN3_SECTORS> sections;
};
const std::array<unsigned, GEN3_SECTORS> &gen3Lengths(unsigned variant) {
  static const std::array<unsigned, GEN3_SECTORS> frlg = {
      0xF24, 0xF80, 0xF80, 0xF80, 0xEE8, 0xF80, 0xF80,
      0xF80, 0xF80, 0xF80, 0xF80, 0xF80, 0xF80, 0x7D0};
  static const std::array<unsigned, GEN3_SECTORS> rs = {
      0x890, 0xF80, 0xF80, 0xF80, 0xC40, 0xF80, 0xF80,
      0xF80, 0xF80, 0xF80, 0xF80, 0xF80, 0xF80, 0x7D0};
  static const std::array<unsigned, GEN3_SECTORS> emerald = {
      0xF2C, 0xF80, 0xF80, 0xF80, 0xF08, 0xF80, 0xF80,
      0xF80, 0xF80, 0xF80, 0xF80, 0xF80, 0xF80, 0x7D0};
  return variant == 0 ? rs : variant == 1 ? emerald : frlg;
}
Gen3Slot parseGen3Slot(const std::vector<uint8_t> &d, unsigned slot,
                       unsigned variant) {
  Gen3Slot out;
  std::set<unsigned> ids;
  const auto &lengths = gen3Lengths(variant);
  bool haveCounter = false;
  for (unsigned sector = 0; sector < GEN3_SECTORS; ++sector) {
    const unsigned offset = (slot * GEN3_SECTORS + sector) * GEN3_SECTOR;
    const uint8_t *raw = d.data() + offset;
    const unsigned id = u16le(raw + 0xFF4);
    const unsigned checksum = u16le(raw + 0xFF6);
    const uint32_t magic = u32le(raw + 0xFF8), counter = u32le(raw + 0xFFC);
    if (id >= GEN3_SECTORS || !ids.insert(id).second || magic != GEN3_MAGIC ||
        gen3Checksum(raw, lengths[id]) != checksum ||
        (haveCounter && counter != out.counter)) return out;
    out.sections[id].assign(raw, raw + lengths[id]);
    out.counter = counter;
    haveCounter = true;
  }
  out.valid = ids.size() == GEN3_SECTORS;
  return out;
}
bool newerCounter(uint32_t left, uint32_t right) {
  uint32_t difference = left - right;
  return difference && difference < 0x80000000;
}
uint32_t generation3VariantHint(const std::string &path) {
  if (hasToken(path, "firered") || hasToken(path, "leafgreen")) return 2;
  if (hasToken(path, "emerald")) return 1;
  if (hasToken(path, "ruby") || hasToken(path, "sapphire")) return 0;
  return 99;
}
std::vector<uint8_t> gen3Storage(const Gen3Slot &slot) {
  std::vector<uint8_t> data;
  for (unsigned i = 5; i < GEN3_SECTORS; ++i)
    data.insert(data.end(), slot.sections[i].begin(), slot.sections[i].end());
  return data;
}
bool validGen3Record(const uint8_t *record) {
  if (allZero(record, 80)) return false;
  uint8_t entry[ENTRY];
  std::memset(entry, 0xFF, sizeof(entry));
  put32le(entry, GEN3);
  std::memcpy(entry + 4, record, 80);
  return validEntry(entry);
}
std::string gen3Title(unsigned variant, const std::string &path) {
  if (variant == 1) return "Emerald";
  if (variant == 0) {
    if (hasToken(path, "ruby")) return "Ruby";
    if (hasToken(path, "sapphire")) return "Sapphire";
    return "Ruby / Sapphire";
  }
  if (hasToken(path, "firered")) return "FireRed";
  if (hasToken(path, "leafgreen")) return "LeafGreen";
  return "FireRed / LeafGreen";
}
GameSave parseGen3(const std::vector<uint8_t> &d, const std::string &path) {
  if (d.size() != GEN3_SAVE_SIZE) throw Error("Tamanho Gen III invalido.");
  struct Candidate { unsigned variant; std::vector<Gen3Slot> slots; };
  std::vector<Candidate> candidates;
  for (unsigned variant = 0; variant < 3; ++variant) {
    Candidate c{variant, {}};
    for (unsigned slot = 0; slot < GEN3_SLOTS; ++slot) {
      Gen3Slot parsed = parseGen3Slot(d, slot, variant);
      if (parsed.valid) c.slots.push_back(std::move(parsed));
    }
    if (!c.slots.empty()) candidates.push_back(std::move(c));
  }
  if (candidates.empty()) throw Error("Save Gen III nao reconhecido ou checksum invalido.");
  unsigned hinted = generation3VariantHint(path);
  if (candidates.size() > 1) {
    auto it = std::find_if(candidates.begin(), candidates.end(),
                           [&](const Candidate &c) { return c.variant == hinted; });
    if (it == candidates.end()) throw Error("Save Gen III ambiguo sem nome de jogo reconhecivel.");
    Candidate chosen = std::move(*it);
    candidates.clear();
    candidates.push_back(std::move(chosen));
  }
  Candidate &candidate = candidates.front();
  Gen3Slot *active = &candidate.slots.front();
  for (auto &slot : candidate.slots)
    if (newerCounter(slot.counter, active->counter)) active = &slot;
  const std::vector<uint8_t> storage = gen3Storage(*active);
  if (storage.size() < 0x83D0 || storage[0] >= 14)
    throw Error("Boxes Gen III incompletas ou invalidadas.");
  unsigned offset = 1, best = 0;
  for (unsigned start : {1u, 4u}) {
    unsigned valid = 0;
    for (unsigned i = 0; i < 14 * 30; ++i) {
      const unsigned pos = start + i * 80;
      if (pos + 80 <= storage.size() && validGen3Record(storage.data() + pos)) ++valid;
    }
    if (valid > best || (valid == best && start == 1)) {
      best = valid;
      offset = start;
    }
  }
  GameSave save;
  save.info.path = path;
  save.info.generation = GEN3;
  save.info.boxes = 14;
  save.info.title = gen3Title(candidate.variant, path);
  save.boxes.resize(14);
  for (unsigned box = 0; box < 14; ++box) {
    auto &out = save.boxes[box];
    out.name = "Box " + std::to_string(box + 1);
    emptyBox(out.entries);
    for (unsigned slot = 0; slot < SLOTS; ++slot) {
      const uint8_t *record = storage.data() + offset + (box * SLOTS + slot) * 80;
      if (!validGen3Record(record)) continue;
      uint8_t *entry = out.entries.data() + slot * ENTRY;
      put32le(entry, GEN3);
      std::memcpy(entry + 4, record, 80);
    }
  }
  return save;
}

uint16_t crc16(const uint8_t *data, unsigned size) {
  uint8_t top = 0xFF, bot = 0xFF;
  for (unsigned i = 0; i < size; ++i) {
    uint8_t value = uint8_t(data[i] ^ top);
    value ^= value >> 4;
    top = uint8_t(bot ^ (value >> 3) ^ (value << 4));
    bot = uint8_t(value ^ (value << 5));
  }
  return uint16_t(top << 8) | bot;
}
bool gen4Magic(uint32_t value) {
  return value == GEN4_MAGIC_A || value == GEN4_MAGIC_B;
}
unsigned compareGen4Counters(uint32_t left, uint32_t right) {
  if (left == 0xFFFFFFFF && right != 0xFFFFFFFE) return 1;
  if (right == 0xFFFFFFFF && left != 0xFFFFFFFE) return 0;
  if (left > right) return 0;
  if (left < right) return 1;
  return 2;
}
struct Gen4Block {
  unsigned offset = 0, size = 0, partition = 0;
  uint32_t major = 0, minor = 0;
};
bool activeGen4Block(const std::vector<uint8_t> &d, unsigned start,
                     unsigned length, Gen4Block &out) {
  Gen4Block copy[2];
  bool allUninitialized = true;
  for (unsigned i = 0; i < 2; ++i) {
    const unsigned offset = i * GEN4_PARTITION + start;
    if (offset + length > d.size() || length < 0x20) return false;
    const uint8_t *p = d.data() + offset;
    const unsigned footer = length - 0x14;
    copy[i] = {offset, length, i, u32le(p + footer), u32le(p + footer + 4)};
    if (copy[i].major != 0xFFFFFFFF || copy[i].minor != 0xFFFFFFFF)
      allUninitialized = false;
  }
  if (allUninitialized) return false;
  unsigned selected = compareGen4Counters(copy[0].major, copy[1].major);
  if (selected == 2)
    selected = compareGen4Counters(copy[0].minor, copy[1].minor);
  if (selected == 2) selected = 0;
  const uint8_t *p = d.data() + copy[selected].offset;
  if (!gen4Magic(u32le(p + length - 8)) ||
      u16le(p + length - 2) != crc16(p, length - 0x10)) return false;
  out = copy[selected];
  return true;
}
bool anyGen4Magic(const std::vector<uint8_t> &d, unsigned start,
                  unsigned length) {
  for (unsigned partition : {0u, GEN4_PARTITION})
    if (partition + start + length <= d.size() &&
        gen4Magic(u32le(d.data() + partition + start + length - 8))) return true;
  return false;
}
std::string gen4Title(unsigned type, const std::string &path,
                      const uint8_t *general) {
  if (type == 2) {
    const unsigned code = general[0x64 + 0x1C];
    return code == 0x47 ? "HeartGold" : "SoulSilver";
  }
  if (type == 1) return "Platinum";
  if (hasToken(path, "diamond")) return "Diamond";
  if (hasToken(path, "pearl")) return "Pearl";
  return "Diamond / Pearl";
}
GameSave parseGen4(const std::vector<uint8_t> &d, const std::string &path) {
  if (d.size() != GEN4_SAVE_SIZE) throw Error("Tamanho Gen IV invalido.");
  struct Layout { unsigned type, general, storage, storageStart, boxStride; };
  const Layout layouts[] = {
      {0, 0xC100, 0x121E0, 0xC100, 30 * 0x88},
      {1, 0xCF2C, 0x121E4, 0xCF2C, 30 * 0x88},
      {2, 0xF628, 0x12310, 0xF700, 0x1000},
  };
  for (const auto &layout : layouts) {
    if (!anyGen4Magic(d, 0, layout.general) ||
        !anyGen4Magic(d, layout.storageStart, layout.storage)) continue;
    Gen4Block general, storage;
    if (!activeGen4Block(d, 0, layout.general, general) ||
        !activeGen4Block(d, layout.storageStart, layout.storage, storage)) continue;
    if (layout.type == 2) {
      const uint8_t version = d[general.offset + 0x64 + 0x1C];
      if (version != 0x47 && version != 0x53) continue;
    }
    GameSave save;
    save.info.path = path;
    save.info.generation = GEN4;
    save.info.boxes = 18;
    save.info.title = gen4Title(layout.type, path, d.data() + general.offset);
    save.boxes.resize(18);
    for (unsigned box = 0; box < 18; ++box) {
      auto &out = save.boxes[box];
      out.name = "Box " + std::to_string(box + 1);
      emptyBox(out.entries);
      const unsigned start = layout.type == 2 ? box * layout.boxStride
                                               : 4 + box * layout.boxStride;
      for (unsigned slot = 0; slot < SLOTS; ++slot) {
        const uint8_t *record = d.data() + storage.offset + start + slot * 0x88;
        if (allZero(record, 0x88)) continue;
        uint8_t entry[ENTRY];
        std::memset(entry, 0xFF, sizeof(entry));
        put32le(entry, GEN4);
        std::memcpy(entry + 4, record, 0x88);
        if (validEntry(entry))
          std::memcpy(out.entries.data() + slot * ENTRY, entry, ENTRY);
      }
    }
    return save;
  }
  throw Error("Save Gen IV nao reconhecido ou checksum invalido.");
}

GameSave parseSave(const std::vector<uint8_t> &data, const std::string &path) {
  if (data.size() == GB_SAVE_SIZE || data.size() == GB_JP_SAVE_SIZE)
    return parseGen12(data, path);
  if (data.size() == GEN3_SAVE_SIZE) return parseGen3(data, path);
  if (data.size() == GEN4_SAVE_SIZE) return parseGen4(data, path);
  throw Error("Formato de save nao suportado.");
}

void scanDirectory(const std::string &root, unsigned depth,
                   std::set<std::string> &visited,
                   std::vector<std::string> &files, unsigned &directoryCount) {
  if (depth > MAX_SCAN_DEPTH || directoryCount >= MAX_SCAN_DIRS ||
      files.size() >= MAX_SCAN_FILES || !visited.insert(root).second) return;
  DIR *dir = opendir(root.c_str());
  if (!dir) return;
  ++directoryCount;
  std::vector<std::string> children;
  while (dirent *entry = readdir(dir)) {
    const std::string name = entry->d_name;
    if (name == "." || name == "..") continue;
    const std::string path = root.back() == '/' ? root + name : root + "/" + name;
    struct stat info{};
    if (stat(path.c_str(), &info)) continue;
    if (S_ISDIR(info.st_mode)) children.push_back(path);
    else if (S_ISREG(info.st_mode) && isSav(name) &&
             isSupportedSize(uint32_t(info.st_size))) {
      files.push_back(path);
      if (files.size() >= MAX_SCAN_FILES) break;
    }
  }
  closedir(dir);
  // Prefer conventional save and ROM folders over large photo/title trees.
  std::stable_sort(children.begin(), children.end(), [](const std::string &a,
                                                         const std::string &b) {
    auto rank = [](const std::string &p) {
      const std::string n = lower(p);
      if (n.find("/saves") != std::string::npos) return 0;
      if (n.find("/roms") != std::string::npos) return 1;
      if (n.find("/checkpoint") != std::string::npos) return 2;
      if (n.find("/pksm") != std::string::npos) return 3;
      return 4;
    };
    return rank(a) < rank(b);
  });
  for (const auto &child : children) {
    if (files.size() >= MAX_SCAN_FILES || directoryCount >= MAX_SCAN_DIRS) break;
    scanDirectory(child, depth + 1, visited, files, directoryCount);
  }
}
} // namespace

std::vector<GameSaveInfo> discoverGameSaves() {
  std::set<std::string> visited, uniqueFiles;
  std::vector<std::string> files;
  unsigned dirs = 0;
  for (const std::string &root : platform::gameSaveSearchRoots())
    scanDirectory(root, 0, visited, files, dirs);
  std::vector<GameSaveInfo> saves;
  for (const auto &path : files) {
    if (!uniqueFiles.insert(path).second) continue;
    try {
      GameSave parsed = parseSave(readRawSave(path), path);
      saves.push_back(parsed.info);
      if (saves.size() >= MAX_FOUND_SAVES) break;
    } catch (const Error &) {
      // Most .sav files on a card belong to unrelated games or are old copies.
    }
  }
  std::stable_sort(saves.begin(), saves.end(), [](const GameSaveInfo &a,
                                                  const GameSaveInfo &b) {
    const std::string left = lower(a.title), right = lower(b.title);
    return left == right ? lower(a.path) < lower(b.path) : left < right;
  });
  return saves;
}

GameSave readGameSave(const GameSaveInfo &info) {
  GameSave save = parseSave(readRawSave(info.path), info.path);
  if (save.info.generation != info.generation || save.info.boxes != info.boxes)
    throw Error("O save mudou desde a busca; atualize a lista de jogos.");
  return save;
}
} // namespace chestlink
