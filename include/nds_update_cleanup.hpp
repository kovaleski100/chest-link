#pragma once
#include <cstdint>
#include <string>

namespace chestlink::ndsupdate {
struct AppFile {
  uint32_t version = 0;
  bool legacy = false;
};

inline bool parseAppFilename(const std::string &name, AppFile &file) {
  if (name == "ChestLink_DS.nds") {
    file = {0, true};
    return true;
  }

  constexpr char prefix[] = "ChestLink_DS_v";
  if (name.compare(0, sizeof(prefix) - 1, prefix) != 0)
    return false;
  size_t cursor = sizeof(prefix) - 1;
  uint32_t parts[3] = {};
  for (unsigned i = 0; i < 3; ++i) {
    if (cursor >= name.size() || name[cursor] < '0' || name[cursor] > '9')
      return false;
    do {
      parts[i] = parts[i] * 10 + unsigned(name[cursor] - '0');
      if (parts[i] > 255)
        return false;
      ++cursor;
    } while (cursor < name.size() && name[cursor] >= '0' &&
             name[cursor] <= '9');
    if (i < 2) {
      if (cursor >= name.size() || name[cursor++] != '.')
        return false;
    }
  }
  if (name.compare(cursor, std::string::npos, ".nds") != 0)
    return false;
  file = {(parts[0] << 16) | (parts[1] << 8) | parts[2], false};
  return true;
}

inline bool shouldRemove(const std::string &path, const std::string &name,
                         const std::string &runningPath,
                         uint32_t runningVersion) {
  if (path == runningPath)
    return false;
  AppFile file;
  if (!parseAppFilename(name, file))
    return false;
  if (file.legacy)
    return !runningPath.empty();
  return file.version < runningVersion ||
         (!runningPath.empty() && file.version == runningVersion);
}
} // namespace chestlink::ndsupdate
