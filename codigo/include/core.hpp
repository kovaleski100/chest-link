#pragma once
#include <array>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace chestlink {
constexpr unsigned MAX_BOXES = 500, SLOTS = 30, ENTRY = 336;
constexpr unsigned BOX_BYTES = SLOTS * ENTRY, PORT = 40991;
constexpr uint32_t CHEST_GENS = 0x7f, PKSM_GENS = 0x1ff;
struct Error : std::runtime_error {
  using std::runtime_error::runtime_error;
};
struct Json {
  enum Kind { OBJECT, ARRAY, STRING, NUMBER } kind = OBJECT;
  std::map<std::string, Json> object;
  std::vector<Json> array;
  std::string string;
  uint32_t number = 0;
  static Json parse(const std::string &);
  std::string dump() const;
  static Json text(const std::string &);
  static Json integer(uint32_t);
};
struct Sha256 {
  uint32_t h[8];
  uint64_t length = 0;
  unsigned used = 0;
  uint8_t block[64];
  Sha256();
  void update(const void *, size_t);
  std::array<uint8_t, 32> finish();

private:
  void transform();
};
using Digest = std::array<uint8_t, 32>;
std::string hex(const Digest &);
uint32_t le32(const uint8_t *);
void put32(uint8_t *, uint32_t);
std::string readText(const std::string &, size_t limit = 256 * 1024);
void writeText(const std::string &, const std::string &);
bool exists(const std::string &);
void makeDirs(const std::string &);
// ExtData files have a fixed size. A native adapter may preallocate them and
// return true, causing the core to open them without O_TRUNC.
extern std::function<bool(const std::string &, uint32_t)> outputAllocator;
FILE *openOutput(const std::string &, uint32_t bytes);
std::string safeDisplay(const std::string &, unsigned limit = 28);

// commit is called after each durable transaction step (3DS extdata needs it).
struct Store {
  std::string label, root;
  unsigned maxBoxes = MAX_BOXES;
  uint32_t generations = PKSM_GENS;
  std::function<void()> commit;
  std::string banks() const { return root + "/banks"; }
  std::string registry() const { return root + "/banks.json"; }
  std::string work() const { return root + "/chest-link"; }
};
struct BankInfo {
  std::string name;
  unsigned boxes;
};
struct BoxInfo {
  std::string name;
  unsigned occupied;
  uint32_t generations;
};
class Bank {
  std::string path_;
  unsigned version_, boxes_, stride_, offset_;
  std::vector<std::string> names_;

public:
  Bank(const Store &, const BankInfo &);
  unsigned boxes() const { return boxes_; }
  const std::string &path() const { return path_; }
  const std::string &boxName(unsigned i) const { return names_.at(i); }
  BoxInfo inspect(unsigned) const;
  void readBox(unsigned, uint8_t *) const;
};
std::vector<BankInfo> listBanks(const Store &);
void recover(const Store &);
struct Offer {
  uint32_t boxes = 0, occupied = 0, generations = 0, bankBytes = 0,
           namesBytes = 0;
  Digest digest{};
};
struct Package {
  Offer offer;
  std::string bank, names;
};
using Progress = std::function<bool(uint32_t, uint32_t)>;
Package exportBoxes(const Store &, const Bank &, const std::vector<unsigned> &,
                    Progress = {});
// One 30-bit slot mask per source box. Preserve the original positions and raw
// records in each included box; excluded slots become canonical empty entries.
Package exportSelection(const Store &, const Bank &,
                        const std::vector<uint32_t> &, Progress = {});
// Build a checked local package from already-normalized 30-slot boxes. Used by
// read-only save importers; importing the package always creates a new bank.
Package packageFromBoxes(const Store &,
                         const std::vector<std::array<uint8_t, BOX_BYTES>> &,
                         const std::vector<std::string> &names);
void validate(const Package &, const Store &);
std::string importPackage(const Store &, const Package &);
void discard(const Package &);
// Exact reads/writes must throw on disconnect, cancellation or timeout.
struct Wire {
  std::function<void(void *, size_t)> read;
  std::function<void(const void *, size_t)> write;
  // Optional for transports that distinguish a human prompt from data stalls.
  std::function<void(unsigned)> setIdleTimeout = {};
};
using Accept = std::function<bool(const Offer &)>;
std::string sendPackage(Wire &, uint32_t pin, const Package &, Progress = {});
std::string receivePackage(Wire &, uint32_t pin, const Store &, Accept,
                           Progress = {});
} // namespace chestlink
