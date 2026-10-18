#include "mailbox.hpp"
#include "protocol_io.hpp"
#include <algorithm>
#include <cstring>

namespace chestlink {
namespace {
using namespace wireio;
void targetCheck(uint32_t target, bool allowUnassigned = false) {
  if (target != TARGET_DS && target != TARGET_3DS &&
      !(allowUnassigned && target == 0))
    throw Error("Destino da caixa postal invalido.");
}
void hello(Wire &w, uint32_t pin, uint32_t command) {
  if (pin > 999999)
    throw Error("PIN invalido.");
  uint8_t h[20];
  std::memcpy(h, "CLMAIL01", 8);
  put32(h + 8, 1);
  put32(h + 12, pin);
  put32(h + 16, command);
  w.write(h, sizeof(h));
  result(w);
}
bool validHex(const std::string &s, unsigned size) {
  if (s.size() != size)
    return false;
  for (char c : s)
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')))
      return false;
  return true;
}
const Json &field(const Json &j, const char *name, Json::Kind kind) {
  auto i = j.object.find(name);
  if (j.kind != Json::OBJECT || i == j.object.end() || i->second.kind != kind)
    throw Error("Lista do servidor invalida.");
  return i->second;
}
std::string existingCopy(const Store &s, const Package &p, Progress progress) {
  // Content-based receipts also survive a power cut between import and ACK.
  // Restrict reuse to banks created by Chest Link; never mutate these banks.
  auto banks = listBanks(s);
  std::reverse(banks.begin(), banks.end());
  for (const auto &b : banks) {
    unsigned total = p.offer.bankBytes + p.offer.namesBytes;
    if (progress && !progress(total, total))
      throw Error("Cancelado.");
    if (b.boxes != p.offer.boxes || b.name.size() != 8 ||
        b.name.substr(0, 4) != "link")
      continue;
    bool digits = true;
    for (unsigned i = 4; i < 8; ++i)
      digits = digits && b.name[i] >= '0' && b.name[i] <= '9';
    if (!digits)
      continue;
    Package candidate{p.offer, s.banks() + "/" + b.name + ".bnk",
                      s.banks() + "/" + b.name + ".json"};
    try {
      validate(candidate, s);
      return b.name;
    } catch (const Error &) {
      // Different, edited, or incomplete bank: preserve it and keep looking.
    }
  }
  return {};
}
} // namespace
std::string mailboxId(uint32_t target, const Digest &digest) {
  targetCheck(target, true);
  Sha256 sha;
  uint8_t b[4];
  put32(b, target);
  sha.update(b, 4);
  sha.update(digest.data(), digest.size());
  return hex(sha.finish()).substr(0, 32);
}
std::string uploadMailbox(Wire &w, uint32_t pin, uint32_t target,
                          const std::string &label, const Package &p,
                          Progress progress) {
  targetCheck(target, true);
  std::string display = safeDisplay(label, 63);
  if (display.empty())
    display = "Banco";
  hello(w, pin, 1);
  uint8_t h[8], meta[52];
  put32(h, target);
  put32(h + 4, display.size());
  w.write(h, sizeof(h));
  w.write(display.data(), display.size());
  encode(p.offer, meta);
  w.write(meta, sizeof(meta));
  std::string id = mailboxId(target, p.offer.digest), state = result(w);
  if (state == "STORED " + id)
    return id;
  if (state != "READY")
    throw Error("Resposta de envio do PC invalida.");
  unsigned done = 0, total = p.offer.bankBytes + p.offer.namesBytes;
  streamOut(w, p.bank, p.offer.bankBytes, done, total, progress);
  streamOut(w, p.names, p.offer.namesBytes, done, total, progress);
  if (result(w) != id)
    throw Error(
        "Confirmacao do PC invalida. Consulte a fila antes de repetir.");
  return id;
}
MailboxPage listMailbox(Wire &w, uint32_t pin, uint32_t target,
                        bool includeDelivered, uint32_t offset) {
  if (target)
    targetCheck(target);
  if (!target && !includeDelivered)
    throw Error("Lista de backups deve incluir todas as copias.");
  hello(w, pin, 2);
  uint8_t h[12];
  put32(h, target);
  put32(h + 4, includeDelivered ? 1 : 0);
  put32(h + 8, offset);
  w.write(h, sizeof(h));
  result(w);
  w.read(h, 4);
  unsigned n = le32(h);
  if (!n || n > 64 * 1024)
    throw Error("Lista do PC grande demais ou vazia.");
  std::string text(n, '\0');
  w.read(&text[0], n);
  Json j = Json::parse(text);
  MailboxPage page;
  page.next = field(j, "next", Json::NUMBER).number;
  page.total = field(j, "total", Json::NUMBER).number;
  const auto &items = field(j, "items", Json::ARRAY).array;
  if (items.size() > 32 || page.total > 10000 ||
      (page.next && (page.next <= offset || page.next > page.total)))
    throw Error("Paginacao do PC invalida.");
  for (const auto &item : items) {
    MailboxItem i;
    i.id = field(item, "id", Json::STRING).string;
    i.label = field(item, "label", Json::STRING).string;
    i.target = field(item, "target", Json::NUMBER).number;
    targetCheck(i.target, true);
    if (target && i.target != target)
      throw Error("Fila do PC pertence ao outro console.");
    i.offer.boxes = field(item, "boxes", Json::NUMBER).number;
    i.offer.occupied = field(item, "occupied", Json::NUMBER).number;
    i.offer.generations = field(item, "generations", Json::NUMBER).number;
    i.offer.bankBytes = field(item, "bankBytes", Json::NUMBER).number;
    i.offer.namesBytes = field(item, "namesBytes", Json::NUMBER).number;
    std::string hash = field(item, "hash", Json::STRING).string;
    unsigned delivered = field(item, "delivered", Json::NUMBER).number;
    if (!validHex(i.id, 32) || !validHex(hash, 64) || i.label.size() > 63 ||
        delivered > 1)
      throw Error("Entrada da caixa postal invalida.");
    for (unsigned b = 0; b < 32; ++b) {
      auto digit = [](char c) { return c <= '9' ? c - '0' : c - 'a' + 10; };
      i.offer.digest[b] = digit(hash[2 * b]) * 16 + digit(hash[2 * b + 1]);
    }
    preflight(i.offer, Store{"PC", "", MAX_BOXES, PKSM_GENS, {}});
    if (i.id != mailboxId(i.target, i.offer.digest))
      throw Error("Identificador da copia invalido.");
    i.delivered = delivered != 0;
    page.items.push_back(i);
  }
  return page;
}
MailboxReceipt fetchMailbox(Wire &w, uint32_t pin, uint32_t target,
                            const std::string &id, const Store &s,
                            Accept accept, Progress progress,
                            bool markDelivered) {
  targetCheck(target);
  if (!validHex(id, 32))
    throw Error("Identificador da copia invalido.");
  Package p;
  MailboxReceipt receipt;
  bool authenticated = false;
  try {
    recover(s);
    hello(w, pin, 3);
    authenticated = true;
    uint8_t h[52];
    put32(h, target);
    w.write(h, 4);
    w.write(id.data(), id.size());
    put32(h, markDelivered ? 0 : 1);
    w.write(h, 4);
    result(w);
    w.read(h, sizeof(h));
    p.offer = decode(h);
    preflight(p.offer, s);
    if (id != mailboxId(target, p.offer.digest))
      throw Error("Identificador difere do pacote recebido.");
    if (!accept || !accept(p.offer))
      throw Error("Recebimento cancelado.");
    makeDirs(s.work());
    p.bank = s.work() + "/mailbox.bnk.part";
    p.names = s.work() + "/mailbox.json.part";
    reply(w, true, "READY");
    unsigned done = 0, total = p.offer.bankBytes + p.offer.namesBytes;
    streamIn(w, p.bank, p.offer.bankBytes, done, total, progress);
    streamIn(w, p.names, p.offer.namesBytes, done, total, progress);
    validate(p, s);
    reply(w, true, "VERIFY");
    receipt.bank =
        existingCopy(s, p, [&w, progress](uint32_t done, uint32_t total) {
          // Many large banks can take time to hash on a DS. Tell the PC we are
          // still verifying, without treating that as a delivery confirmation.
          reply(w, true, "VERIFY");
          return !progress || progress(done, total);
        });
    receipt.reused = !receipt.bank.empty();
    if (!receipt.reused)
      receipt.bank = importPackage(s, p);
    discard(p);
  } catch (const std::exception &e) {
    discard(p);
    if (authenticated) {
      try {
        reply(w, false, e.what());
      } catch (...) {
      }
    }
    throw;
  }
  // Local durability is independent of whether the PC receives the ACK.
  // A retry reuses an unchanged, hash-verified linkNNNN bank.
  try {
    reply(w, true, receipt.bank);
    receipt.confirmed = result(w) == (markDelivered ? "DELIVERED" : "BACKUP");
  } catch (const std::exception &) {
    receipt.confirmed = false;
  }
  return receipt;
}
} // namespace chestlink
