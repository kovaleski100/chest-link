#include "nds_update_cleanup.hpp"
#include <cstdlib>
#include <iostream>

namespace {
void require(bool condition, const char *message) {
  if (!condition) {
    std::cerr << "FAIL " << message << '\n';
    std::exit(1);
  }
}
} // namespace

int main() {
  using chestlink::ndsupdate::AppFile;
  using chestlink::ndsupdate::parseAppFilename;
  using chestlink::ndsupdate::shouldRemove;
  AppFile file;

  require(parseAppFilename("ChestLink_DS_v0.4.14.nds", file) &&
              file.version == 0x0000040e && !file.legacy,
          "parses a versioned Chest Link filename");
  require(parseAppFilename("ChestLink_DS.nds", file) && file.legacy,
          "recognizes the legacy app filename");
  require(!parseAppFilename("Other_DS_v0.4.14.nds", file) &&
              !parseAppFilename("ChestLink_DS_v0.4.999.nds", file) &&
              !parseAppFilename("ChestLink_DS_v0.4.14.nds.previous", file),
          "rejects unrelated, malformed, and backup filenames");

  const uint32_t current = 0x0000040f;
  const std::string running = "fat:/apps/ChestLink_DS_v0.4.15.nds";
  require(shouldRemove("sd:/ChestLink_DS_v0.4.14.nds",
                       "ChestLink_DS_v0.4.14.nds", running, current),
          "removes an older app even on another mounted storage");
  require(!shouldRemove("fat:/apps/ChestLink_DS_v0.4.15.nds",
                        "ChestLink_DS_v0.4.15.nds", running, current),
          "preserves the running app");
  require(shouldRemove("sd:/apps/ChestLink_DS_v0.4.15.nds",
                       "ChestLink_DS_v0.4.15.nds", running, current),
          "removes a duplicate of the current version");
  require(!shouldRemove("fat:/apps/ChestLink_DS_v0.4.16.nds",
                        "ChestLink_DS_v0.4.16.nds", running, current),
          "preserves a newer version");
  require(shouldRemove("sd:/ChestLink_DS.nds", "ChestLink_DS.nds", running,
                       current),
          "removes a different legacy app copy when current path is known");
  require(!shouldRemove("fat:/ChestLink_DS.nds", "ChestLink_DS.nds", "",
                        current),
          "preserves legacy filenames if launcher path is unknown");
  require(shouldRemove("fat:/ChestLink_DS_v0.4.14.nds",
                       "ChestLink_DS_v0.4.14.nds", "", current),
          "removes older versioned files if launcher path is unknown");

  std::cout << "PASS DS update cleanup filename and preservation rules\n";
}
