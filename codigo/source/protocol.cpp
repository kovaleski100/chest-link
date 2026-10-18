#include "core.hpp"
#include "protocol_io.hpp"
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <memory>
namespace chestlink {
namespace wireio {
constexpr uint32_t VERSION = 1;
void reply(Wire &w, bool ok, const std::string &message) {
  std::string s = message.substr(0, 384);
  uint8_t h[8];
  put32(h, ok ? 0 : 1);
  put32(h + 4, s.size());
  w.write(h, 8);
  if (!s.empty())
    w.write(s.data(), s.size());
}
std::string result(Wire &w) {
  uint8_t h[8];
  w.read(h, 8);
  unsigned n = le32(h + 4);
  if (n > 384 || le32(h) > 1)
    throw Error("Resposta de rede invalida.");
  std::string s(n, '\0');
  if (n)
    w.read(&s[0], n);
  if (le32(h))
    throw Error(s);
  return s;
}
void encode(const Offer &o, uint8_t *b) {
  put32(b, o.boxes);
  put32(b + 4, o.occupied);
  put32(b + 8, o.generations);
  put32(b + 12, o.bankBytes);
  put32(b + 16, o.namesBytes);
  std::memcpy(b + 20, o.digest.data(), 32);
}
Offer decode(const uint8_t *b) {
  Offer o;
  o.boxes = le32(b);
  o.occupied = le32(b + 4);
  o.generations = le32(b + 8);
  o.bankBytes = le32(b + 12);
  o.namesBytes = le32(b + 16);
  std::memcpy(o.digest.data(), b + 20, 32);
  return o;
}
void preflight(const Offer &o, const Store &s) {
  if (!o.boxes || o.boxes > s.maxBoxes || o.boxes > MAX_BOXES)
    throw Error("Limite de boxes do destino excedido. Divida o envio.");
  if (o.bankBytes != 16 + o.boxes * BOX_BYTES || !o.namesBytes ||
      o.namesBytes > 256 * 1024 || o.occupied > o.boxes * SLOTS ||
      (o.generations & ~s.generations))
    throw Error("Geracao ou tamanho incompativel com o destino.");
}
void streamOut(Wire &w, const std::string &path, unsigned bytes, unsigned &done,
               unsigned total, Progress progress) {
  FILE *f = std::fopen(path.c_str(), "rb");
  if (!f)
    throw Error("Pacote de envio nao encontrado.");
  try {
    uint8_t b[4096];
    while (bytes) {
      unsigned n = std::min<unsigned>(bytes, sizeof(b));
      if (std::fread(b, 1, n, f) != n)
        throw Error("Falha ao ler pacote.");
      w.write(b, n);
      bytes -= n;
      done += n;
      if (progress && !progress(done, total))
        throw Error("Cancelado.");
    }
    std::fclose(f);
  } catch (...) {
    std::fclose(f);
    throw;
  }
}
void streamIn(Wire &w, const std::string &path, unsigned bytes, unsigned &done,
              unsigned total, Progress progress) {
  FILE *f = openOutput(path, bytes);
  if (!f)
    throw Error("Nao foi possivel preparar recebimento.");
  try {
    uint8_t b[4096];
    while (bytes) {
      unsigned n = std::min<unsigned>(bytes, sizeof(b));
      w.read(b, n);
      if (std::fwrite(b, 1, n, f) != n)
        throw Error("Falha de gravacao no destino.");
      bytes -= n;
      done += n;
      if (progress && !progress(done, total))
        throw Error("Cancelado.");
    }
    int rc = std::fclose(f);
    f = nullptr;
    if (rc)
      throw Error("Falha ao finalizar recebimento.");
  } catch (...) {
    if (f)
      std::fclose(f);
    throw;
  }
}
} // namespace wireio
using namespace wireio;
std::string sendPackage(Wire &w, uint32_t pin, const Package &p,
                        Progress progress) {
  if (pin > 999999)
    throw Error("PIN invalido.");
  uint8_t h[16];
  std::memcpy(h, "CHESTLNK", 8);
  put32(h + 8, VERSION);
  put32(h + 12, pin);
  w.write(h, 16);
  result(w);
  uint8_t meta[52];
  encode(p.offer, meta);
  w.write(meta, 52);
  result(w);
  unsigned done = 0, total = p.offer.bankBytes + p.offer.namesBytes;
  streamOut(w, p.bank, p.offer.bankBytes, done, total, progress);
  streamOut(w, p.names, p.offer.namesBytes, done, total, progress);
  return result(w);
}
std::string receivePackage(Wire &w, uint32_t pin, const Store &s, Accept accept,
                           Progress progress) {
  Package p;
  bool authenticated = false;
  try {
    uint8_t h[16];
    w.read(h, 16);
    if (std::memcmp(h, "CHESTLNK", 8) || le32(h + 8) != VERSION ||
        pin > 999999 || le32(h + 12) != pin)
      throw Error("PIN incorreto ou versao incompativel.");
    authenticated = true;
    reply(w, true, "");
    uint8_t meta[52];
    w.read(meta, 52);
    p.offer = decode(meta);
    preflight(p.offer, s);
    if (!accept || !accept(p.offer))
      throw Error("Recebimento recusado no destino.");
    recover(s);
    makeDirs(s.work());
    p.bank = s.work() + "/receive.bnk.part";
    p.names = s.work() + "/receive.json.part";
    reply(w, true, "");
    unsigned done = 0, total = p.offer.bankBytes + p.offer.namesBytes;
    streamIn(w, p.bank, p.offer.bankBytes, done, total, progress);
    streamIn(w, p.names, p.offer.namesBytes, done, total, progress);
    std::string name = importPackage(s, p);
    discard(p);
    reply(w, true, name);
    return name;
  } catch (const std::exception &e) {
    // Authentication failures also get an explicit reply. Never delete a
    // source bank and never import an incomplete stream.
    (void)authenticated;
    discard(p);
    try {
      reply(w, false, e.what());
    } catch (...) {
    }
    throw;
  }
}
} // namespace chestlink
