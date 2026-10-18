#pragma once
#include <optional>
#include <string_view>

namespace platform_detail {
inline void skipWhitespace(std::string_view json, size_t &position) {
  while (position < json.size() &&
         (json[position] == ' ' || json[position] == '\n' ||
          json[position] == '\r' || json[position] == '\t'))
    ++position;
}

inline bool skipString(std::string_view json, size_t &position,
                       std::string_view *contents = nullptr) {
  if (position >= json.size() || json[position] != '"')
    return false;
  const size_t start = ++position;
  while (position < json.size()) {
    const unsigned char c = json[position];
    if (c == '"') {
      if (contents)
        *contents = json.substr(start, position - start);
      ++position;
      return true;
    }
    if (c == '\\') {
      if (position + 1 >= json.size())
        return false;
      position += 2;
    } else {
      if (c < 0x20)
        return false;
      ++position;
    }
  }
  return false;
}

inline bool skipValue(std::string_view json, size_t &position) {
  if (position >= json.size())
    return false;
  if (json[position] == '"')
    return skipString(json, position);
  if (json[position] == '{' || json[position] == '[') {
    char closers[16];
    size_t depth = 0;
    closers[depth++] = json[position++] == '{' ? '}' : ']';
    while (position < json.size() && depth) {
      if (json[position] == '"') {
        if (!skipString(json, position))
          return false;
      } else if (json[position] == '{' || json[position] == '[') {
        if (depth == sizeof(closers))
          return false;
        closers[depth++] = json[position++] == '{' ? '}' : ']';
      } else if (json[position] == '}' || json[position] == ']') {
        if (json[position++] != closers[--depth])
          return false;
      } else {
        ++position;
      }
    }
    return depth == 0;
  }
  const size_t start = position;
  while (position < json.size() && json[position] != ',' &&
         json[position] != '}' && json[position] != ']' &&
         json[position] != ' ' && json[position] != '\n' &&
         json[position] != '\r' && json[position] != '\t')
    ++position;
  return position > start;
}

inline bool literalBoundary(std::string_view json, size_t position) {
  if (position == json.size())
    return true;
  const char c = json[position];
  return c == ',' || c == '}' || c == ' ' || c == '\n' || c == '\r' ||
         c == '\t';
}

// Read only PKSM's top-level Use ExtData setting; no other config fields are
// interpreted or modified by Chest Link.
inline std::optional<bool> pksmUseExtData(std::string_view json) {
  size_t position = 0;
  skipWhitespace(json, position);
  if (position >= json.size() || json[position++] != '{')
    return std::nullopt;
  for (;;) {
    skipWhitespace(json, position);
    if (position >= json.size() || json[position] == '}')
      return std::nullopt;
    std::string_view key;
    if (!skipString(json, position, &key))
      return std::nullopt;
    skipWhitespace(json, position);
    if (position >= json.size() || json[position++] != ':')
      return std::nullopt;
    skipWhitespace(json, position);
    if (key == "useExtData") {
      if (json.substr(position, 4) == "true" &&
          literalBoundary(json, position + 4))
        return true;
      if (json.substr(position, 5) == "false" &&
          literalBoundary(json, position + 5))
        return false;
      return std::nullopt;
    }
    if (!skipValue(json, position))
      return std::nullopt;
    skipWhitespace(json, position);
    if (position >= json.size())
      return std::nullopt;
    if (json[position] == ',') {
      ++position;
      continue;
    }
    return std::nullopt;
  }
}
} // namespace platform_detail
