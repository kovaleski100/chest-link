#include "core.hpp"
#include <cctype>
#include <cstdio>

namespace chestlink {
namespace {
struct Parser {
  const std::string &s;
  size_t p = 0;
  unsigned nodes = 0;
  void ws() {
    while (p < s.size() &&
           (s[p] == ' ' || s[p] == '\n' || s[p] == '\r' || s[p] == '\t'))
      ++p;
  }
  [[noreturn]] void bad() {
    throw Error("JSON invalido; arquivo original preservado.");
  }
  bool eat(char c) {
    ws();
    if (p < s.size() && s[p] == c) {
      ++p;
      return true;
    }
    return false;
  }
  unsigned digit() {
    if (p >= s.size())
      bad();
    char c = s[p++];
    if (c >= '0' && c <= '9')
      return c - '0';
    if (c >= 'a' && c <= 'f')
      return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
      return c - 'A' + 10;
    bad();
  }
  unsigned u16() {
    unsigned v = 0;
    for (int i = 0; i < 4; ++i)
      v = (v << 4) | digit();
    return v;
  }
  void utf8(std::string &out, unsigned c) {
    if (!c)
      bad();
    if (c < 128)
      out += char(c);
    else if (c < 2048) {
      out += char(0xc0 | (c >> 6));
      out += char(0x80 | (c & 63));
    } else if (c < 65536) {
      out += char(0xe0 | (c >> 12));
      out += char(0x80 | ((c >> 6) & 63));
      out += char(0x80 | (c & 63));
    } else {
      out += char(0xf0 | (c >> 18));
      out += char(0x80 | ((c >> 12) & 63));
      out += char(0x80 | ((c >> 6) & 63));
      out += char(0x80 | (c & 63));
    }
  }
  std::string str() {
    if (!eat('"'))
      bad();
    std::string out;
    while (p < s.size()) {
      unsigned char c = s[p++];
      if (c == '"')
        return out;
      if (c < 32)
        bad();
      if (c != '\\')
        out += char(c);
      else {
        if (p >= s.size())
          bad();
        char e = s[p++];
        switch (e) {
        case '"':
        case '\\':
        case '/':
          out += e;
          break;
        case 'b':
          out += '\b';
          break;
        case 'f':
          out += '\f';
          break;
        case 'n':
          out += '\n';
          break;
        case 'r':
          out += '\r';
          break;
        case 't':
          out += '\t';
          break;
        case 'u': {
          unsigned u = u16();
          if (u >= 0xd800 && u <= 0xdbff) {
            if (p + 2 > s.size() || s[p] != '\\' || s[p + 1] != 'u')
              bad();
            p += 2;
            unsigned l = u16();
            if (l < 0xdc00 || l > 0xdfff)
              bad();
            u = 0x10000 + ((u - 0xd800) << 10) + (l - 0xdc00);
          } else if (u >= 0xdc00 && u <= 0xdfff)
            bad();
          utf8(out, u);
          break;
        }
        default:
          bad();
        }
      }
      if (out.size() > 4096)
        bad();
    }
    bad();
  }
  Json value(unsigned depth = 0) {
    if (depth > 8 || ++nodes > 2048)
      bad();
    ws();
    if (p >= s.size())
      bad();
    Json j;
    if (eat('{')) {
      j.kind = Json::OBJECT;
      if (eat('}'))
        return j;
      do {
        std::string k = str();
        if (!eat(':'))
          bad();
        Json v = value(depth + 1);
        if (!j.object.emplace(k, std::move(v)).second)
          bad();
      } while (eat(','));
      if (!eat('}'))
        bad();
    } else if (eat('[')) {
      j.kind = Json::ARRAY;
      if (eat(']'))
        return j;
      do {
        j.array.push_back(value(depth + 1));
      } while (eat(','));
      if (!eat(']'))
        bad();
    } else if (s[p] == '"') {
      j.kind = Json::STRING;
      j.string = str();
    } else {
      j.kind = Json::NUMBER;
      size_t first = p;
      uint64_t n = 0;
      while (p < s.size() && s[p] >= '0' && s[p] <= '9') {
        n = n * 10 + (s[p++] - '0');
        if (n > 0xffffffffULL)
          bad();
      }
      if (p == first || (p > first + 1 && s[first] == '0'))
        bad();
      j.number = uint32_t(n);
    }
    return j;
  }
};
std::string quote(const std::string &s) {
  std::string out = "\"";
  char b[7];
  for (unsigned char c : s) {
    if (c == '"' || c == '\\') {
      out += '\\';
      out += char(c);
    } else if (c < 32) {
      std::snprintf(b, sizeof(b), "\\u%04x", c);
      out += b;
    } else
      out += char(c);
  }
  return out + '"';
}
} // namespace
Json Json::parse(const std::string &s) {
  if (s.size() > 256 * 1024)
    throw Error("JSON grande demais.");
  Parser p{s};
  Json j = p.value();
  p.ws();
  // PKSM writes one terminating NUL in its registry.
  if (p.p < s.size() && s[p.p] == 0)
    ++p.p;
  if (p.p != s.size())
    p.bad();
  return j;
}
Json Json::text(const std::string &s) {
  Json j;
  j.kind = STRING;
  j.string = s;
  return j;
}
Json Json::integer(uint32_t n) {
  Json j;
  j.kind = NUMBER;
  j.number = n;
  return j;
}
std::string Json::dump() const {
  if (kind == STRING)
    return quote(string);
  if (kind == NUMBER)
    return std::to_string(number);
  std::string out = kind == OBJECT ? "{" : "[";
  bool first = true;
  if (kind == OBJECT)
    for (const auto &kv : object) {
      if (!first)
        out += ',';
      first = false;
      out += quote(kv.first) + ':' + kv.second.dump();
    }
  else
    for (const auto &v : array) {
      if (!first)
        out += ',';
      first = false;
      out += v.dump();
    }
  return out + (kind == OBJECT ? "}" : "]");
}
} // namespace chestlink
