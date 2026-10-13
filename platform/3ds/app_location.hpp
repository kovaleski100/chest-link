#pragma once
#include <cstdint>
#include <string>

namespace platform_detail {
// Homebrew Launcher passes argv[0] as sdmc:/... or /... . Never interpret
// a 3dslink URL, another device, or traversal as an executable on the SD.
inline std::string sdApplicationPath(std::string path) {
  if (!path.empty() && path.front() == '/') path = "sdmc:" + path;
  if (path.compare(0, 6, "sdmc:/") != 0 || path.size() > 1024 ||
      path.size() < 12 || path.compare(path.size() - 5, 5, ".3dsx") != 0)
    return {};
  std::string normalized = "sdmc:/";
  size_t cursor = 6;
  while (cursor < path.size()) {
    const size_t end = path.find('/', cursor);
    const std::string part = path.substr(cursor, end - cursor);
    if (part.empty() || part == "." || part == ".." ||
        part.find(':') != std::string::npos || part.find('\\') != std::string::npos ||
        part.find('\0') != std::string::npos)
      return {};
    if (normalized.size() > 6) normalized += '/';
    normalized += part;
    if (end == std::string::npos) break;
    cursor = end + 1;
  }
  return normalized;
}

inline std::string applicationDirectory(const std::string &path) {
  const size_t slash = path.find_last_of('/');
  return slash == std::string::npos ? "" : path.substr(0, slash + 1);
}

inline bool sameSDPath(const std::string &a, const std::string &b) {
  if (a.size() != b.size()) return false;
  for (size_t i = 0; i < a.size(); ++i) {
    const char x = a[i] >= 'A' && a[i] <= 'Z' ? a[i] + ('a' - 'A') : a[i];
    const char y = b[i] >= 'A' && b[i] <= 'Z' ? b[i] + ('a' - 'A') : b[i];
    if (x != y) return false;
  }
  return true;
}

inline bool older3DSApp(const std::string &name, uint32_t runningVersion) {
  constexpr char prefix[] = "ChestLink_3DS_v";
  if (name.compare(0, sizeof(prefix) - 1, prefix)) return false;
  size_t cursor = sizeof(prefix) - 1;
  uint32_t parts[3]{};
  for (unsigned i = 0; i < 3; ++i) {
    if (cursor >= name.size() || name[cursor] < '0' || name[cursor] > '9') return false;
    do {
      parts[i] = parts[i] * 10 + unsigned(name[cursor++] - '0');
      if (parts[i] > 255) return false;
    } while (cursor < name.size() && name[cursor] >= '0' && name[cursor] <= '9');
    if (i < 2 && (cursor >= name.size() || name[cursor++] != '.')) return false;
  }
  return name.compare(cursor, std::string::npos, ".3dsx") == 0 &&
         ((parts[0] << 16) | (parts[1] << 8) | parts[2]) < runningVersion;
}
} // namespace platform_detail
