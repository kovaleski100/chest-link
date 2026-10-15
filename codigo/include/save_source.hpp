#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace chestlink {

// Identifies where a save image came from. These values describe provenance;
// they do not imply that the bytes have been recognized or validated.
enum class SaveSourceKind {
  RawFile,
  NDSCartridge,
  CTRGame,
  LegacyPKSMBank,
  LegacyChestBank,
};

struct SaveSourceMetadata {
  SaveSourceKind kind = SaveSourceKind::RawFile;
  std::string locator;
  uint64_t sizeBytes = 0;
};

struct SaveReadResult {
  std::vector<uint8_t> bytes;
  SaveSourceMetadata source;
  // Lowercase hexadecimal SHA-256 of exactly the bytes returned above.
  std::string sha256;
};

// Acquisition is kept separate from game detection and parsing. Implementors
// provide a read snapshot of the source plus its provenance.
class SaveSource {
public:
  virtual ~SaveSource() = default;
  virtual SaveReadResult read() const = 0;
};

// Host-side source for a save file supplied directly by the user. It opens the
// input in binary read-only mode and never writes to, renames, or deletes it.
class RawFileSaveSource final : public SaveSource {
public:
  static constexpr uint64_t DEFAULT_MAX_BYTES = 64u * 1024u * 1024u;

  explicit RawFileSaveSource(
      std::string path, uint64_t maxBytes = DEFAULT_MAX_BYTES);
  SaveReadResult read() const override;

private:
  std::string path_;
  uint64_t maxBytes_;
};

} // namespace chestlink
