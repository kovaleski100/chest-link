#include "core.hpp"
#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <memory>
#include <set>
#include <sys/stat.h>
#ifdef CL_HOST
#include <unistd.h>
#endif

namespace chestlink {
namespace {
class File {
  FILE *f;

public:
  File(const std::string &p, const char *mode, uint32_t bytes = 0)
      : f(mode[0] == 'w' ? openOutput(p, bytes) : std::fopen(p.c_str(), mode)) {
    if (!f)
      throw Error("Nao foi possivel abrir: " + p);
  }
  ~File() {
    if (f)
      std::fclose(f);
  }
  void read(void *p, size_t n) {
    if (std::fread(p, 1, n, f) != n)
      throw Error("Arquivo incompleto ou erro de leitura.");
  }
  void write(const void *p, size_t n) {
    if (std::fwrite(p, 1, n, f) != n)
      throw Error("Falha de gravacao. Confira o espaco no SD.");
  }
  void seek(uint32_t n) {
    if (std::fseek(f, n, SEEK_SET))
      throw Error("Falha ao acessar uma box.");
  }
  uint32_t size() {
    if (std::fseek(f, 0, SEEK_END))
      throw Error("Falha de leitura.");
    long n = std::ftell(f);
    if (n < 0 || uint64_t(n) > 8 * 1024 * 1024)
      throw Error("Tamanho de banco invalido.");
    seek(0);
    return uint32_t(n);
  }
  void close() {
    if (!f)
      return;
    if (std::fflush(f)) {
      std::fclose(f);
      f = nullptr;
      throw Error("Falha ao finalizar arquivo.");
    }
#ifdef CL_HOST
    if (fsync(fileno(f))) {
      std::fclose(f);
      f = nullptr;
      throw Error("Falha ao sincronizar arquivo.");
    }
#endif
    FILE *old = f;
    f = nullptr;
    if (std::fclose(old))
      throw Error("Falha ao fechar arquivo.");
  }
};
bool safeName(const std::string &s) {
  if (s.empty() || s.size() > 63 || s == "." || s == "..")
    return false;
  for (unsigned char c : s)
    if (c < 32 || c == '/' || c == '\\' || c == ':' || c == 127)
      return false;
  return true;
}
void durable(const Store &s) {
  if (s.commit)
    s.commit();
}
Json registry(const Store &s) {
  Json j;
  if (exists(s.registry()))
    j = Json::parse(readText(s.registry()));
  if (j.kind != Json::OBJECT || j.object.size() > 256)
    throw Error("Cadastro de bancos invalido.");
  for (const auto &kv : j.object)
    if (!safeName(kv.first) || kv.second.kind != Json::NUMBER ||
        kv.second.number > MAX_BOXES)
      throw Error("Entrada invalida em banks.json.");
  return j;
}
void copyFile(const std::string &src, const std::string &dst) {
  File in(src, "rb");
  uint32_t left = in.size();
  File out(dst, "wb", left);
  uint8_t b[4096];
  while (left) {
    unsigned n = std::min<unsigned>(left, sizeof(b));
    in.read(b, n);
    out.write(b, n);
    left -= n;
  }
  out.close();
}
Digest digestFiles(const std::string &bank, const std::string &names) {
  Sha256 sha;
  uint8_t b[4096];
  for (const auto &p : {bank, names}) {
    File f(p, "rb");
    uint32_t left = f.size();
    while (left) {
      unsigned n = std::min<unsigned>(left, sizeof(b));
      f.read(b, n);
      sha.update(b, n);
      left -= n;
    }
  }
  return sha.finish();
}
std::string numbered(const std::string &base, unsigned n,
                     const std::string &ext) {
  char num[16];
  std::snprintf(num, sizeof(num), "%04u", n);
  return base + num + ext;
}
void renameNew(const std::string &from, const std::string &to) {
  if (exists(to))
    throw Error("Destino ja existe; nenhum banco foi substituido.");
  if (std::rename(from.c_str(), to.c_str()))
    throw Error("Nao foi possivel registrar arquivo novo.");
}
void replaceRegistry(const std::string &src, const std::string &dst) {
  if (!std::rename(src.c_str(), dst.c_str()))
    return;
  // FAT implementations may reject replacement. A durable recovery journal
  // and a checked backup exist before reaching this fallback.
  if (exists(dst) && std::remove(dst.c_str()))
    throw Error("Falha ao atualizar cadastro.");
  if (std::rename(src.c_str(), dst.c_str()))
    throw Error("Cadastro pendente: reabra Chest Link para recuperar.");
}
uint32_t checkEntry(const uint8_t *p) {
  uint32_t g = le32(p);
  if (g == 0xffffffff)
    return 0;
  if (g > 8)
    throw Error("Geracao desconhecida no banco. Transferencia cancelada.");
  return 1u << g;
}
std::vector<std::string> boxNames(const std::string &path, unsigned boxes,
                                  bool optional) {
  std::vector<std::string> out;
  if (!exists(path) && optional) {
    for (unsigned i = 0; i < boxes; ++i)
      out.push_back("Box " + std::to_string(i + 1));
    return out;
  }
  Json j = Json::parse(readText(path));
  if (j.kind != Json::ARRAY || j.array.size() != boxes)
    throw Error("Quantidade de nomes nao corresponde as boxes.");
  for (const auto &v : j.array) {
    if (v.kind != Json::STRING || v.string.size() > 512)
      throw Error("Nome de box invalido ou grande demais.");
    out.push_back(v.string);
  }
  return out;
}
struct Header {
  unsigned version, boxes, stride, offset;
};
Header header(const std::string &path) {
  File f(path, "rb");
  unsigned size = f.size();
  uint8_t h[16];
  if (size < 12)
    throw Error("Banco truncado.");
  f.read(h, std::min<unsigned>(size, 16));
  if (std::memcmp(h, "PKSMBANK", 8))
    throw Error("Formato de banco desconhecido.");
  Header out{le32(h + 8), 0, 0, 0};
  if (out.version == 1) {
    out.stride = 264;
    out.offset = 12;
    out.boxes = (size - 12) / (264 * 30);
  } else if (out.version == 2 || out.version == 3) {
    if (size < 16)
      throw Error("Cabecalho truncado.");
    out.boxes = le32(h + 12);
    out.stride = out.version == 3 ? 336 : 264;
    out.offset = 16;
  } else
    throw Error("Versao de banco ainda nao suportada.");
  if (!out.boxes || out.boxes > MAX_BOXES ||
      uint64_t(size) != out.offset + uint64_t(out.boxes) * 30 * out.stride)
    throw Error("Tamanho do banco nao corresponde as boxes.");
  return out;
}
} // namespace
bool exists(const std::string &p) {
  struct stat st;
  return !stat(p.c_str(), &st);
}
std::function<bool(const std::string &, uint32_t)> outputAllocator;
FILE *openOutput(const std::string &p, uint32_t bytes) {
  bool allocated = outputAllocator && outputAllocator(p, bytes);
  return std::fopen(p.c_str(), allocated ? "r+b" : "wb");
}
void makeDirs(const std::string &p) {
  if (p.empty())
    throw Error("Caminho vazio.");
  for (size_t i = 1; i <= p.size(); ++i)
    if (i == p.size() || p[i] == '/') {
      std::string q = p.substr(0, i);
      if (q.empty() || q.back() == ':')
        continue;
      if (mkdir(q.c_str(), 0777) && errno != EEXIST)
        throw Error("Nao foi possivel criar pasta: " + q);
      struct stat st;
      if (stat(q.c_str(), &st) || !S_ISDIR(st.st_mode))
        throw Error("Caminho nao e uma pasta: " + q);
    }
}
std::string readText(const std::string &p, size_t limit) {
  File f(p, "rb");
  unsigned n = f.size();
  if (n > limit)
    throw Error("Arquivo de texto grande demais.");
  std::string s(n, '\0');
  if (n)
    f.read(&s[0], n);
  return s;
}
void writeText(const std::string &p, const std::string &s) {
  File f(p, "wb", s.size());
  if (!s.empty())
    f.write(s.data(), s.size());
  f.close();
}
std::string safeDisplay(const std::string &s, unsigned limit) {
  std::string o;
  for (unsigned char c : s) {
    if (o.size() == limit)
      break;
    o += c >= 32 && c < 127 ? char(c) : '?';
  }
  return o;
}
Bank::Bank(const Store &s, const BankInfo &info) {
  if (!safeName(info.name))
    throw Error("Nome de banco invalido.");
  path_ = s.banks() + "/" + info.name + ".bnk";
  auto h = header(path_);
  version_ = h.version;
  boxes_ = h.boxes;
  stride_ = h.stride;
  offset_ = h.offset;
  if (boxes_ != info.boxes)
    throw Error(
        "banks.json diverge do banco. Restaure o backup antes de transferir.");
  names_ = boxNames(s.banks() + "/" + info.name + ".json", boxes_, true);
}
std::vector<BankInfo> listBanks(const Store &s) {
  Json j = registry(s);
  std::vector<BankInfo> out;
  for (const auto &kv : j.object)
    if (kv.second.number)
      out.push_back({kv.first, kv.second.number});
  return out;
}
void Bank::readBox(unsigned box, uint8_t *out) const {
  if (box >= boxes_)
    throw Error("Box fora do banco.");
  File f(path_, "rb");
  f.seek(offset_ + box * 30 * stride_);
  for (unsigned slot = 0; slot < SLOTS; ++slot) {
    uint8_t *p = out + slot * ENTRY;
    std::memset(p, 0xff, ENTRY);
    f.read(p, stride_);
    checkEntry(p);
  }
}
BoxInfo Bank::inspect(unsigned box) const {
  auto data = std::make_unique<uint8_t[]>(BOX_BYTES);
  readBox(box, data.get());
  BoxInfo info{boxName(box), 0, 0};
  for (unsigned i = 0; i < SLOTS; ++i) {
    uint32_t g = checkEntry(data.get() + i * ENTRY);
    if (g)
      ++info.occupied;
    info.generations |= g;
  }
  return info;
}
static Package exportSelectedOrdered(const Store &, const Bank &,
                                     const std::vector<uint32_t> &,
                                     const std::vector<unsigned> &, Progress);
Package exportBoxes(const Store &store, const Bank &bank,
                    const std::vector<unsigned> &selected, Progress progress) {
  if (selected.empty() || selected.size() > MAX_BOXES)
    throw Error("Escolha ao menos uma box.");
  std::set<unsigned> seen;
  for (unsigned n : selected)
    if (n >= bank.boxes() || !seen.insert(n).second)
      throw Error("Selecao de boxes invalida.");
  std::vector<uint32_t> masks(bank.boxes(), 0);
  for (unsigned box : selected)
    masks[box] = (1u << SLOTS) - 1;
  // Retain the caller's order, including non-ascending CLI selections.
  // exportSelection uses ascending order, so use a shared ordered helper below.
  return exportSelectedOrdered(store, bank, masks, selected, progress);
}
Package exportSelection(const Store &store, const Bank &bank,
                        const std::vector<uint32_t> &masks, Progress progress) {
  if (masks.size() != bank.boxes())
    throw Error("Selecao de Pokemon invalida.");
  std::vector<unsigned> boxes;
  for (unsigned i = 0; i < masks.size(); ++i) {
    if (masks[i] & ~((1u << SLOTS) - 1))
      throw Error("Slot fora da box.");
    if (masks[i])
      boxes.push_back(i);
  }
  if (boxes.empty())
    throw Error("Marque Pokemon ou uma box antes de enviar.");
  return exportSelectedOrdered(store, bank, masks, boxes, progress);
}
Package packageFromBoxes(
    const Store &store,
    const std::vector<std::array<uint8_t, BOX_BYTES>> &boxes,
    const std::vector<std::string> &names) {
  if (boxes.empty() || boxes.size() != names.size() ||
      boxes.size() > store.maxBoxes || boxes.size() > MAX_BOXES)
    throw Error("Quantidade de boxes invalida para importar.");
  makeDirs(store.work());
  Package p;
  p.bank = store.work() + "/out.bnk.part";
  p.names = store.work() + "/out.json.part";
  p.offer.boxes = static_cast<uint32_t>(boxes.size());
  p.offer.bankBytes = 16 + p.offer.boxes * BOX_BYTES;
  try {
    File out(p.bank, "wb", p.offer.bankBytes);
    uint8_t headerBytes[16];
    std::memcpy(headerBytes, "PKSMBANK", 8);
    put32(headerBytes + 8, 3);
    put32(headerBytes + 12, p.offer.boxes);
    out.write(headerBytes, sizeof(headerBytes));
    Json jsonNames;
    jsonNames.kind = Json::ARRAY;
    for (unsigned box = 0; box < boxes.size(); ++box) {
      out.write(boxes[box].data(), BOX_BYTES);
      jsonNames.array.push_back(Json::text(names[box]));
      for (unsigned slot = 0; slot < SLOTS; ++slot) {
        const uint32_t generation = checkEntry(boxes[box].data() + slot * ENTRY);
        if (generation) ++p.offer.occupied;
        p.offer.generations |= generation;
      }
    }
    out.close();
    const std::string serializedNames = jsonNames.dump();
    p.offer.namesBytes = static_cast<uint32_t>(serializedNames.size());
    writeText(p.names, serializedNames);
    p.offer.digest = digestFiles(p.bank, p.names);
    validate(p, store);
    return p;
  } catch (...) {
    discard(p);
    throw;
  }
}
static Package exportSelectedOrdered(const Store &store, const Bank &bank,
                                     const std::vector<uint32_t> &masks,
                                     const std::vector<unsigned> &selected,
                                     Progress progress) {
  makeDirs(store.work());
  Package p;
  p.bank = store.work() + "/out.bnk.part";
  p.names = store.work() + "/out.json.part";
  p.offer.boxes = selected.size();
  p.offer.bankBytes = 16 + p.offer.boxes * BOX_BYTES;
  try {
    File out(p.bank, "wb", p.offer.bankBytes);
    uint8_t h[16];
    std::memcpy(h, "PKSMBANK", 8);
    put32(h + 8, 3);
    put32(h + 12, p.offer.boxes);
    out.write(h, 16);
    Json names;
    names.kind = Json::ARRAY;
    auto b = std::make_unique<uint8_t[]>(BOX_BYTES);
    unsigned done = 0;
    for (unsigned box : selected) {
      bank.readBox(box, b.get());
      for (unsigned slot = 0; slot < SLOTS; ++slot)
        if (!(masks[box] & (1u << slot)))
          std::memset(b.get() + slot * ENTRY, 0xff, ENTRY);
      out.write(b.get(), BOX_BYTES);
      names.array.push_back(Json::text(bank.boxName(box)));
      for (unsigned i = 0; i < SLOTS; ++i) {
        uint32_t g = checkEntry(b.get() + i * ENTRY);
        if (g)
          ++p.offer.occupied;
        p.offer.generations |= g;
      }
      if (progress && !progress(++done, p.offer.boxes))
        throw Error("Cancelado.");
    }
    out.close();
    std::string json = names.dump();
    p.offer.namesBytes = json.size();
    writeText(p.names, json);
    // These are disposable staging files. On 3DS ExtData, forcing an archive
    // commit here can fail even though the source bank was read correctly and
    // the files are immediately consumed by the network transfer. Durable
    // commits remain mandatory for importPackage(), where the bank registry is
    // changed.
    p.offer.digest = digestFiles(p.bank, p.names);
    return p;
  } catch (...) {
    discard(p);
    throw;
  }
}
void discard(const Package &p) {
  if (!p.bank.empty())
    std::remove(p.bank.c_str());
  if (!p.names.empty())
    std::remove(p.names.c_str());
}
void validate(const Package &p, const Store &s) {
  const Offer &o = p.offer;
  if (!o.boxes || o.boxes > s.maxBoxes || o.boxes > MAX_BOXES)
    throw Error("Mais boxes que o limite do destino. Envie em grupos menores.");
  if (o.bankBytes != 16 + o.boxes * BOX_BYTES || !o.namesBytes ||
      o.namesBytes > 256 * 1024 || o.occupied > o.boxes * SLOTS ||
      (o.generations & ~s.generations))
    throw Error("Banco incompativel com o destino.");
  auto h = header(p.bank);
  if (h.version != 3 || h.boxes != o.boxes)
    throw Error("Cabecalho recebido invalido.");
  File names(p.names, "rb");
  if (names.size() != o.namesBytes)
    throw Error("Nomes recebidos incompletos.");
  boxNames(p.names, o.boxes, false);
  if (digestFiles(p.bank, p.names) != o.digest)
    throw Error("SHA-256 diferente. Nenhum banco foi importado.");
  File f(p.bank, "rb");
  f.seek(16);
  uint8_t entry[ENTRY];
  uint32_t occupied = 0, gens = 0;
  for (unsigned i = 0; i < o.boxes * SLOTS; ++i) {
    f.read(entry, ENTRY);
    uint32_t g = checkEntry(entry);
    if (g)
      ++occupied;
    gens |= g;
  }
  if (occupied != o.occupied || gens != o.generations)
    throw Error("Conteudo difere da descricao recebida.");
}
void recover(const Store &s) {
  std::string path = s.work() + "/journal.json";
  if (!exists(path))
    return;
  Json j = Json::parse(readText(path));
  if (j.kind != Json::OBJECT || j.object.size() != 6)
    throw Error("Diario de recuperacao invalido. Preserve os backups.");
  auto field = [&](const char *key, Json::Kind kind) -> const Json & {
    auto i = j.object.find(key);
    if (i == j.object.end() || i->second.kind != kind)
      throw Error("Diario invalido.");
    return i->second;
  };
  std::string name = field("bank", Json::STRING).string,
              backup = field("backup", Json::STRING).string;
  if (name.size() != 8 || name.substr(0, 4) != "link" || backup.size() < 13 ||
      backup.substr(0, 8) != "registry" || !safeName(name) || !safeName(backup))
    throw Error("Caminho invalido no diario.");
  unsigned boxes = field("boxes", Json::NUMBER).number,
           old = field("old", Json::NUMBER).number;
  std::string hash = field("hash", Json::STRING).string,
              oldhash = field("oldhash", Json::STRING).string;
  if (old > 1 || !boxes || boxes > MAX_BOXES || hash.size() != 64 ||
      oldhash.size() != 64)
    throw Error("Diario invalido.");
  bool committed = false;
  try {
    Json r = registry(s);
    auto i = r.object.find(name);
    if (i != r.object.end() && i->second.number == boxes) {
      Bank b(s, {name, boxes});
      (void)b;
      committed = hex(digestFiles(s.banks() + "/" + name + ".bnk",
                                  s.banks() + "/" + name + ".json")) == hash;
    }
  } catch (const Error &) {
  }
  if (!committed) {
    std::string before = readText(s.work() + "/" + backup);
    Sha256 sha;
    sha.update(before.data(), before.size());
    if (hex(sha.finish()) != oldhash)
      throw Error("Backup do cadastro falhou na verificacao. Preserve o SD.");
    Json::parse(before);
    if (old) {
      std::string tmp = s.work() + "/restore.json.part";
      writeText(tmp, before);
      durable(s);
      replaceRegistry(tmp, s.registry());
    } else if (exists(s.registry()) && std::remove(s.registry().c_str()))
      throw Error("Falha na recuperacao.");
    durable(s);
    for (const auto &ext : {".bnk", ".json", ".bnk.part", ".json.part"})
      std::remove((s.banks() + "/" + name + ext).c_str());
  }
  std::remove((s.work() + "/registry.next").c_str());
  if (std::remove(path.c_str()))
    throw Error("Nao foi possivel concluir recuperacao.");
  durable(s);
}
std::string importPackage(const Store &s, const Package &p) {
  recover(s);
  validate(p, s);
  Json r = registry(s);
  makeDirs(s.banks());
  makeDirs(s.work());
  std::string name;
  for (unsigned n = 1; n <= 9999; ++n) {
    auto candidate = numbered("link", n, "");
    bool free = true;
    for (const auto &kv : r.object) {
      std::string key = kv.first;
      for (char &c : key)
        if (c >= 'A' && c <= 'Z')
          c += 'a' - 'A';
      if (key == candidate) {
        free = false;
        break;
      }
    }
    for (const auto &ext : {".bnk", ".json", ".bnk.part", ".json.part"})
      free = free && !exists(s.banks() + "/" + candidate + ext);
    if (free) {
      name = candidate;
      break;
    }
  }
  if (name.empty())
    throw Error("Sem nome livre para banco novo.");
  // Both applications limit the bank selector to roughly 90 entries.
  if (r.object.size() >= 89)
    throw Error("Muitos bancos no destino. Libere um banco vazio primeiro.");
  std::string backup;
  for (unsigned n = 1; n < 1000000; ++n) {
    auto candidate = numbered("registry", n, ".json");
    if (!exists(s.work() + "/" + candidate)) {
      backup = candidate;
      break;
    }
  }
  if (backup.empty())
    throw Error("Sem nome livre para backup.");
  bool old = exists(s.registry());
  std::string before = old ? readText(s.registry()) : "{}";
  writeText(s.work() + "/" + backup, before);
  durable(s);
  Sha256 oldsha;
  oldsha.update(before.data(), before.size());
  Json journal;
  journal.object["bank"] = Json::text(name);
  journal.object["backup"] = Json::text(backup);
  journal.object["boxes"] = Json::integer(p.offer.boxes);
  journal.object["old"] = Json::integer(old ? 1 : 0);
  journal.object["hash"] = Json::text(hex(p.offer.digest));
  journal.object["oldhash"] = Json::text(hex(oldsha.finish()));
  std::string temp = s.work() + "/journal.part";
  writeText(temp, journal.dump());
  durable(s);
  renameNew(temp, s.work() + "/journal.json");
  durable(s);
  for (const auto &pair : std::vector<std::pair<std::string, std::string>>{
           {p.bank, ".bnk"}, {p.names, ".json"}}) {
    std::string dst = s.banks() + "/" + name + pair.second;
    copyFile(pair.first, dst + ".part");
    durable(s);
    renameNew(dst + ".part", dst);
    durable(s);
  }
  if (digestFiles(s.banks() + "/" + name + ".bnk",
                  s.banks() + "/" + name + ".json") != p.offer.digest)
    throw Error("Erro ao conferir gravacao. Reabra para recuperar.");
  r.object[name] = Json::integer(p.offer.boxes);
  std::string next = s.work() + "/registry.next";
  writeText(next, r.dump());
  durable(s);
  replaceRegistry(next, s.registry());
  durable(s);
  // A lost final ACK leaves a verified copy on the receiver; source is
  // untouched.
  if (std::remove((s.work() + "/journal.json").c_str()))
    throw Error("Importacao gravada; diario pendente. Reabra o app.");
  durable(s);
  return name;
}
} // namespace chestlink
