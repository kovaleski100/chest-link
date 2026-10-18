// Independent implementation of SHA-256 (FIPS 180-4).
#include "core.hpp"
#include <cstring>
namespace chestlink {
static uint32_t rr(uint32_t x, unsigned n) {
  return (x >> n) | (x << (32 - n));
}
Sha256::Sha256() {
  const uint32_t iv[] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                         0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
  std::memcpy(h, iv, sizeof(h));
}
void Sha256::transform() {
  static const uint32_t k[] = {
      0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
      0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
      0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
      0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
      0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
      0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
      0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
      0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
      0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
      0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
      0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
  uint32_t w[64];
  for (unsigned i = 0; i < 16; ++i) {
    auto p = block + i * 4;
    w[i] = (uint32_t(p[0]) << 24) | (uint32_t(p[1]) << 16) |
           (uint32_t(p[2]) << 8) | p[3];
  }
  for (unsigned i = 16; i < 64; ++i) {
    uint32_t a = w[i - 15], b = w[i - 2];
    w[i] = w[i - 16] + (rr(a, 7) ^ rr(a, 18) ^ (a >> 3)) + w[i - 7] +
           (rr(b, 17) ^ rr(b, 19) ^ (b >> 10));
  }
  uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6],
           v = h[7];
  for (unsigned i = 0; i < 64; ++i) {
    uint32_t t = v + (rr(e, 6) ^ rr(e, 11) ^ rr(e, 25)) + ((e & f) ^ (~e & g)) +
                 k[i] + w[i];
    uint32_t u =
        (rr(a, 2) ^ rr(a, 13) ^ rr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
    v = g;
    g = f;
    f = e;
    e = d + t;
    d = c;
    c = b;
    b = a;
    a = t + u;
  }
  uint32_t vals[] = {a, b, c, d, e, f, g, v};
  for (unsigned i = 0; i < 8; ++i)
    h[i] += vals[i];
}
void Sha256::update(const void *data, size_t n) {
  const auto *p = static_cast<const uint8_t *>(data);
  length += n;
  while (n) {
    size_t k = 64 - used;
    if (k > n)
      k = n;
    std::memcpy(block + used, p, k);
    p += k;
    n -= k;
    used += k;
    if (used == 64) {
      transform();
      used = 0;
    }
  }
}
Digest Sha256::finish() {
  uint64_t bits = length * 8;
  block[used++] = 0x80;
  if (used > 56) {
    while (used < 64)
      block[used++] = 0;
    transform();
    used = 0;
  }
  while (used < 56)
    block[used++] = 0;
  for (unsigned i = 0; i < 8; ++i)
    block[63 - i] = uint8_t(bits >> (8 * i));
  transform();
  Digest out{};
  for (unsigned i = 0; i < 8; ++i)
    for (unsigned j = 0; j < 4; ++j)
      out[i * 4 + j] = uint8_t(h[i] >> (24 - 8 * j));
  return out;
}
std::string hex(const Digest &d) {
  const char *h = "0123456789abcdef";
  std::string s;
  for (uint8_t b : d) {
    s += h[b >> 4];
    s += h[b & 15];
  }
  return s;
}
uint32_t le32(const uint8_t *p) {
  return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) |
         (uint32_t(p[3]) << 24);
}
void put32(uint8_t *p, uint32_t v) {
  for (unsigned i = 0; i < 4; ++i)
    p[i] = uint8_t(v >> (8 * i));
}
} // namespace chestlink
