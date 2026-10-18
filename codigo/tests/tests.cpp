#include "core.hpp"
#include "network.hpp"
#include "save_source.hpp"
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <iterator>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <thread>
#include <unistd.h>
using namespace chestlink;
namespace fs = std::filesystem;
namespace {
unsigned passed = 0;
void require(bool ok, const std::string &text) {
  if (!ok)
    throw std::runtime_error(text);
}
void rejects(std::function<void()> f) {
  bool bad = false;
  try {
    f();
  } catch (const Error &) {
    bad = true;
  }
  require(bad, "Expected an explicit rejection");
}
void test(const char *name, std::function<void()> f) {
  f();
  ++passed;
  std::cout << "PASS " << name << '\n';
}
struct Temp {
  std::string path;
  Temp() {
    char p[] = "/tmp/chestlink-test-XXXXXX";
    char *out = mkdtemp(p);
    if (!out)
      throw std::runtime_error("mkdtemp");
    path = out;
  }
  ~Temp() { fs::remove_all(path); }
  Store store(const std::string &suffix = "", unsigned max = 500,
              uint32_t gens = PKSM_GENS) const {
    return {"Test", path + suffix, max, gens, {}};
  }
};
std::string bytes(const std::string &p) { return readText(p, 8 * 1024 * 1024); }
void fixture(const Store &s, const std::string &name, unsigned boxes,
             unsigned version = 3, uint32_t gen = 0) {
  makeDirs(s.banks());
  Json reg;
  if (exists(s.registry()))
    reg = Json::parse(readText(s.registry()));
  reg.object[name] = Json::integer(boxes);
  writeText(s.registry(), reg.dump());
  Json names;
  names.kind = Json::ARRAY;
  unsigned stride = version == 3 ? ENTRY : 264, head = version == 1 ? 12 : 16;
  std::string data(head + boxes * SLOTS * stride, char(0xff));
  auto *p = reinterpret_cast<uint8_t *>(&data[0]);
  std::memcpy(p, "PKSMBANK", 8);
  put32(p + 8, version);
  if (head == 16)
    put32(p + 12, boxes);
  for (unsigned b = 0; b < boxes; ++b) {
    names.array.push_back(
        Json::text("Caixa " + std::to_string(b + 1) + " \xc3\xa9"));
    for (unsigned slot = 0; slot < 5; ++slot) {
      uint8_t *e = p + head + (b * SLOTS + slot) * stride;
      put32(e, gen);
      for (unsigned j = 4; j < stride; ++j)
        e[j] = (b * 13 + slot * 7 + j) % 251;
    }
  }
  writeText(s.banks() + "/" + name + ".bnk", data);
  writeText(s.banks() + "/" + name + ".json", names.dump());
}
bool hasBank(const Store &s, const std::string &name) {
  for (const auto &b : listBanks(s))
    if (b.name == name)
      return true;
  return false;
}
Digest hash(const std::string &s) {
  Sha256 h;
  h.update(s.data(), s.size());
  return h.finish();
}
struct NetworkResult {
  std::string sender, receiver, sendError, receiveError;
};
NetworkResult transfer(const Store &dst, const Package &p,
                       uint32_t sentPin = 123456, uint32_t pin = 123456,
                       Accept accept = {}, int fault = 0) {
  int server = Connection::listen(0);
  sockaddr_in address{};
  socklen_t n = sizeof(address);
  require(!getsockname(server, reinterpret_cast<sockaddr *>(&address), &n),
          "getsockname");
  unsigned port = ntohs(address.sin_port);
  NetworkResult result;
  std::thread receiver([&] {
    try {
      auto conn = Connection::accept(server);
      auto w = conn.wire();
      auto write = w.write;
      unsigned replies = 0;
      if (fault == 3)
        w.write = [&](const void *data, size_t size) {
          if (size == 8 && ++replies >= 3)
            throw Error("Lost final ACK");
          write(data, size);
        };
      result.receiver = receivePackage(
          w, pin, dst,
          accept ? accept : Accept([](const Offer &) { return true; }));
    } catch (const std::exception &e) {
      result.receiveError = e.what();
    }
    Connection::close(server);
  });
  try {
    auto conn = Connection::connect("127.0.0.1", port);
    auto w = conn.wire();
    auto write = w.write;
    bool changed = false;
    if (fault == 1)
      w.write = [&](const void *data, size_t size) {
        if (size == 4096 && !changed) {
          std::string b(static_cast<const char *>(data), size);
          b[123] ^= 0x40;
          changed = true;
          write(b.data(), size);
        } else
          write(data, size);
      };
    Progress cancel;
    if (fault == 2)
      cancel = [](uint32_t, uint32_t) { return false; };
    result.sender = sendPackage(w, sentPin, p, cancel);
  } catch (const std::exception &e) {
    result.sendError = e.what();
  }
  receiver.join();
  return result;
}
} // namespace
int main() {
  std::cout.setf(std::ios::unitbuf);
  try {
    test("Update trace sends a bounded redacted UDP record", [] {
      int receiver = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
      require(receiver >= 0, "create UDP trace receiver");
      sockaddr_in address{};
      address.sin_family = AF_INET;
      address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
      require(bind(receiver, reinterpret_cast<sockaddr *>(&address),
                   sizeof(address)) == 0,
              "bind UDP trace receiver");
      socklen_t size = sizeof(address);
      require(getsockname(receiver, reinterpret_cast<sockaddr *>(&address),
                          &size) == 0,
              "read UDP trace port");
      const std::string record =
          "{\"event\":\"download_progress\",\"radio\":\"security=WPA2\"}";
      int sender = -1;
      require(sendUpdateTrace(sender, "127.0.0.1", ntohs(address.sin_port),
                              record),
              "send first UDP trace record");
      const int reused = sender;
      require(sendUpdateTrace(sender, "127.0.0.1", ntohs(address.sin_port),
                              record),
              "send second UDP trace record");
      require(sender == reused, "reuse the UDP socket for later records");
      char packet[1200]{};
      const ssize_t received = recv(receiver, packet, sizeof(packet), 0);
      const ssize_t receivedAgain = recv(receiver, packet, sizeof(packet), 0);
      closeUpdateTraceSocket(sender);
      Connection::close(receiver);
      require(received == static_cast<ssize_t>(record.size() + 8),
              "receive first complete UDP trace packet");
      require(receivedAgain == static_cast<ssize_t>(record.size() + 8),
              "receive second complete UDP trace packet");
      require(std::string(packet, 8) == "CLUPDLOG" &&
                  std::string(packet + 8, record.size()) == record,
              "trace magic and JSON record preserved");
      require(sender == -1, "close and clear the UDP trace socket");
    });
    test("SHA-256 standard vectors and chunk boundaries", [] {
      require(hex(hash("")) == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934"
                               "ca495991b7852b855",
              "empty hash");
      require(hex(hash("abc")) == "ba7816bf8f01cfea414140de5dae2223b00361a39617"
                                  "7a9cb410ff61f20015ad",
              "abc hash");
      std::string million(1000000, 'a');
      Sha256 sha;
      for (size_t i = 0; i < million.size(); i += 37)
        sha.update(million.data() + i,
                   std::min<size_t>(37, million.size() - i));
      require(hex(sha.finish()) == "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a49"
                                   "7200e046d39ccc7112cd0",
              "million a");
    });
    test("Raw save source hashes one binary read without changing the file", [] {
      Temp t;
      const std::string path = t.path + "/source.sav";
      std::string original;
      original.push_back('\0');
      original.push_back('\1');
      original.push_back(static_cast<char>(0xFE));
      original.push_back(static_cast<char>(0xFF));
      original += "native-save";
      {
        std::ofstream file(path, std::ios::binary);
        require(bool(file), "create raw save fixture");
        file.write(original.data(), static_cast<std::streamsize>(original.size()));
        require(bool(file), "write raw save fixture");
      }
      RawFileSaveSource source(path);
      const SaveReadResult result = source.read();
      require(std::string(result.bytes.begin(), result.bytes.end()) == original,
              "raw bytes preserved");
      Sha256 expected;
      expected.update(original.data(), original.size());
      require(result.sha256 == hex(expected.finish()), "raw source SHA-256");
      require(result.source.kind == SaveSourceKind::RawFile &&
                  result.source.sizeBytes == original.size(),
              "raw source metadata");
      std::ifstream file(path, std::ios::binary);
      const std::string after((std::istreambuf_iterator<char>(file)), {});
      require(after == original, "source file remains byte-for-byte unchanged");
    });
    test("Raw save source explicitly rejects empty, missing, and oversized files", [] {
      Temp t;
      const std::string empty = t.path + "/empty.sav";
      { std::ofstream file(empty, std::ios::binary); }
      rejects([&] { RawFileSaveSource(empty).read(); });
      rejects([&] { RawFileSaveSource(t.path + "/missing.sav").read(); });
      const std::string full = t.path + "/full.sav";
      { std::ofstream file(full, std::ios::binary); file << "1234"; }
      rejects([&] { RawFileSaveSource(full, 3).read(); });
    });
    test("JSON unicode, PKSM NUL, duplicate and malformed input", [] {
      auto j = Json::parse("[\"a\\n\\u00e9\\ud83d\\ude00\",123]");
      require(j.array[0].string == "a\n\xc3\xa9\xf0\x9f\x98\x80",
              "unicode decode");
      require(Json::parse(j.dump()).dump() == j.dump(), "JSON round trip");
      require(Json::parse(std::string("{\"bank\":50}\0", 12))
                      .object.at("bank")
                      .number == 50,
              "PKSM terminating NUL");
      for (const auto &bad :
           {"{\"x\":1,\"x\":2}", "[01]", "[4294967296]", "[\"\\ud800\"]",
            "[\"\\u0000\"]", "[]garbage", "{\"x\":-1}", "[true]", "[\"a\n\"]"})
        rejects([&] { Json::parse(bad); });
    });
    for (unsigned version = 1; version <= 3; ++version) {
      std::string name = "Bank v" + std::to_string(version) +
                         " migration and selected-box byte preservation";
      test(name.c_str(), [version] {
        Temp tmp;
        Store src = tmp.store("/src"), dst = tmp.store("/dst");
        fixture(src, "source", 3, version);
        fixture(dst, "existing", 2);
        std::string original = bytes(src.banks() + "/source.bnk"),
                    existing = bytes(dst.banks() + "/existing.bnk"),
                    names = readText(src.banks() + "/source.json");
        Bank bank(src, {"source", 3});
        Package p = exportBoxes(src, bank, {2, 0});
        require(p.offer.occupied == 10 && p.offer.boxes == 2,
                "selected counts");
        auto target = importPackage(dst, p);
        Bank copied(dst, {target, 2});
        uint8_t a[BOX_BYTES], b[BOX_BYTES];
        bank.readBox(2, a);
        copied.readBox(0, b);
        require(!std::memcmp(a, b, BOX_BYTES), "selected box 3 bytes");
        bank.readBox(0, a);
        copied.readBox(1, b);
        require(!std::memcmp(a, b, BOX_BYTES), "selected box 1 bytes");
        require(copied.boxName(0) == bank.boxName(2), "box label");
        require(bytes(src.banks() + "/source.bnk") == original &&
                    readText(src.banks() + "/source.json") == names,
                "source unchanged");
        require(bytes(dst.banks() + "/existing.bnk") == existing,
                "existing destination unchanged");
        require(hasBank(dst, "existing"), "existing registration preserved");
        discard(p);
      });
    }
    test("Header truncation, registry mismatch, version and generation "
         "rejection",
         [] {
           Temp tmp;
           auto s = tmp.store();
           fixture(s, "bank", 2);
           rejects([&] { Bank b(s, {"bank", 1}); });
           std::string p = s.banks() + "/bank.bnk", data = bytes(p);
           writeText(p, data.substr(0, data.size() - 1));
           rejects([&] { Bank b(s, {"bank", 2}); });
           writeText(p, data);
           data[8] = 4;
           writeText(p, data);
           rejects([&] { Bank b(s, {"bank", 2}); });
           fixture(s, "bank", 2, 3, 9);
           Bank b(s, {"bank", 2});
           rejects([&] { b.inspect(0); });
           rejects([&] { Bank bad(s, {"../bank", 2}); });
         });
    test("Destination name collision and orphan protection", [] {
      Temp tmp;
      auto src = tmp.store("/s"), dst = tmp.store("/d");
      fixture(src, "s", 1);
      fixture(dst, "LINK0001", 1);
      writeText(dst.banks() + "/link0002.json", "[]");
      Bank b(src, {"s", 1});
      auto p = exportBoxes(src, b, {0});
      require(importPackage(dst, p) == "link0003", "unique name");
      require(readText(dst.banks() + "/link0002.json") == "[]",
              "orphan preserved");
      discard(p);
    });
    test("Unsupported generation refuses Chest import", [] {
      Temp tmp;
      auto src = tmp.store("/s"), dst = tmp.store("/d", 50, CHEST_GENS);
      fixture(src, "s", 1, 3, 7);
      fixture(dst, "old", 1);
      Bank b(src, {"s", 1});
      auto p = exportBoxes(src, b, {0});
      auto before = readText(dst.registry());
      rejects([&] { importPackage(dst, p); });
      require(readText(dst.registry()) == before, "destination unchanged");
      discard(p);
    });
    test("DS 50-box limit rejects oversized bank", [] {
      Temp tmp;
      auto src = tmp.store("/s"), dst = tmp.store("/d", 50);
      fixture(src, "s", 51);
      Bank b(src, {"s", 51});
      std::vector<unsigned> boxes;
      for (unsigned i = 0; i < 51; ++i)
        boxes.push_back(i);
      auto p = exportBoxes(src, b, boxes);
      rejects([&] { importPackage(dst, p); });
      require(!exists(dst.registry()), "no registration");
      discard(p);
    });
    test("Digest corruption and metadata mismatch never import", [] {
      Temp tmp;
      auto src = tmp.store("/s"), dst = tmp.store("/d");
      fixture(src, "s", 1);
      Bank b(src, {"s", 1});
      auto p = exportBoxes(src, b, {0});
      std::string data = bytes(p.bank);
      data[42] ^= 1;
      writeText(p.bank, data);
      rejects([&] { importPackage(dst, p); });
      require(!exists(dst.registry()), "no corrupt import");
      data[42] ^= 1;
      writeText(p.bank, data);
      ++p.offer.occupied;
      rejects([&] { importPackage(dst, p); });
      discard(p);
    });
    test("Selection bounds, duplication and cancellation", [] {
      Temp tmp;
      auto s = tmp.store();
      fixture(s, "s", 2);
      Bank b(s, {"s", 2});
      rejects([&] { exportBoxes(s, b, {}); });
      rejects([&] { exportBoxes(s, b, {0, 0}); });
      rejects([&] { exportBoxes(s, b, {2}); });
      std::string original = bytes(s.banks() + "/s.bnk");
      rejects([&] {
        exportBoxes(s, b, {0, 1}, [](uint32_t, uint32_t) { return false; });
      });
      require(bytes(s.banks() + "/s.bnk") == original,
              "source unchanged after cancel");
      require(!exists(s.work() + "/out.bnk.part"), "stage removed");
    });
    test("Power interruption at every transaction barrier with existing "
         "registry",
         [] {
           for (unsigned stop = 1; stop <= 10; ++stop) {
             Temp tmp;
             auto src = tmp.store("/s"), dst = tmp.store("/d");
             fixture(src, "s", 2);
             fixture(dst, "old", 1);
             std::string old = bytes(dst.banks() + "/old.bnk");
             Bank b(src, {"s", 2});
             auto p = exportBoxes(src, b, {0, 1});
             unsigned calls = 0;
             dst.commit = [&] {
               if (++calls == stop)
                 throw Error("Power cut");
             };
             try {
               importPackage(dst, p);
             } catch (const Error &) {
             }
             dst.commit = {};
             recover(dst);
             recover(dst);
             require(hasBank(dst, "old") &&
                         bytes(dst.banks() + "/old.bnk") == old,
                     "existing bank after recovery");
             if (hasBank(dst, "link0001")) {
               Bank copied(dst, {"link0001", 2});
               require(copied.inspect(0).occupied == 5,
                       "complete imported bank");
             }
             require(!exists(dst.work() + "/journal.json"), "journal resolved");
             discard(p);
           }
         });
    test("Power interruption with initially absent registry", [] {
      for (unsigned stop = 1; stop <= 10; ++stop) {
        Temp tmp;
        auto src = tmp.store("/s"), dst = tmp.store("/d");
        fixture(src, "s", 1);
        Bank b(src, {"s", 1});
        auto p = exportBoxes(src, b, {0});
        unsigned calls = 0;
        dst.commit = [&] {
          if (++calls == stop)
            throw Error("Power cut");
        };
        try {
          importPackage(dst, p);
        } catch (const Error &) {
        }
        dst.commit = {};
        recover(dst);
        recover(dst);
        if (exists(dst.registry()))
          require(hasBank(dst, "link0001"),
                  "absent registry must be restored or complete");
        discard(p);
      }
    });
    test("Missing and partially replaced registry recover from journal", [] {
      for (unsigned variant = 0; variant < 2; ++variant) {
        Temp tmp;
        auto src = tmp.store("/s"), dst = tmp.store("/d");
        fixture(src, "s", 1);
        fixture(dst, "old", 1);
        std::string before = readText(dst.registry());
        Bank b(src, {"s", 1});
        auto p = exportBoxes(src, b, {0});
        unsigned calls = 0;
        dst.commit = [&] {
          if (++calls == 8)
            throw Error("Power cut");
        };
        rejects([&] { importPackage(dst, p); });
        dst.commit = {};
        if (variant == 0)
          std::remove(dst.registry().c_str());
        else
          writeText(dst.registry(), "{\"link0001\":");
        recover(dst);
        require(readText(dst.registry()) == before,
                "registry restored exactly");
        require(!hasBank(dst, "link0001"), "incomplete registration removed");
        discard(p);
      }
    });
    test("Truncated box names and malformed registry refuse import", [] {
      Temp tmp;
      auto src = tmp.store("/s"), dst = tmp.store("/d");
      fixture(src, "s", 2);
      Bank b(src, {"s", 2});
      auto p = exportBoxes(src, b, {0, 1});
      writeText(p.names, "[]");
      rejects([&] { importPackage(dst, p); });
      require(!exists(dst.registry()), "names failure left destination alone");
      discard(p);
      writeText(src.registry(), "{\"../escape\":2}");
      rejects([&] { listBanks(src); });
    });
    test("TCP unsupported generations rejected before receiving payload", [] {
      Temp tmp;
      auto src = tmp.store("/s"), dst = tmp.store("/d", 50, CHEST_GENS);
      fixture(src, "s", 1, 3, 7);
      Bank b(src, {"s", 1});
      auto p = exportBoxes(src, b, {0});
      auto r = transfer(dst, p);
      require(!r.sendError.empty() && !r.receiveError.empty(),
              "generation rejected");
      require(!exists(dst.work()), "no incoming files created");
      discard(p);
    });
    test("TCP oversized metadata rejected before receiving payload", [] {
      Temp tmp;
      auto src = tmp.store("/s"), dst = tmp.store("/d");
      fixture(src, "s", 1);
      Bank b(src, {"s", 1});
      auto p = exportBoxes(src, b, {0});
      p.offer.namesBytes = 0xffffffff;
      auto r = transfer(dst, p);
      require(!r.sendError.empty() && !exists(dst.work()),
              "oversized offer rejected");
      discard(p);
    });
    test("Damaged recovery backup stops without rewriting registry", [] {
      Temp tmp;
      auto src = tmp.store("/s"), dst = tmp.store("/d");
      fixture(src, "s", 1);
      fixture(dst, "old", 1);
      std::string before = readText(dst.registry());
      Bank b(src, {"s", 1});
      auto p = exportBoxes(src, b, {0});
      unsigned calls = 0;
      dst.commit = [&] {
        if (++calls == 3)
          throw Error("Power cut");
      };
      rejects([&] { importPackage(dst, p); });
      dst.commit = {};
      auto journal = Json::parse(readText(dst.work() + "/journal.json"));
      writeText(dst.work() + "/" + journal.object.at("backup").string,
                "damaged");
      rejects([&] { recover(dst); });
      require(readText(dst.registry()) == before,
              "registry protected from damaged backup");
      discard(p);
    });
    test("Fixed-size output allocator covers staging, backup and registry", [] {
      Temp tmp;
      auto src = tmp.store("/s"), dst = tmp.store("/d");
      fixture(src, "s", 2);
      fixture(dst, "old", 1);
      std::map<std::string, unsigned> allocated;
      outputAllocator = [&](const std::string &p, uint32_t n) {
        allocated[p] = n;
        std::ofstream f(p, std::ios::binary | std::ios::trunc);
        std::string data(n, char(0xa5));
        f.write(data.data(), data.size());
        return true;
      };
      try {
        Bank b(src, {"s", 2});
        auto p = exportBoxes(src, b, {0, 1});
        require(importPackage(dst, p) == "link0001", "fixed-size import");
        Bank copy(dst, {"link0001", 2});
        require(copy.inspect(1).occupied == 5, "fixed-size content");
        require(allocated.at(src.work() + "/out.bnk.part") ==
                    16 + 2 * BOX_BYTES,
                "full bank allocation");
        discard(p);
        outputAllocator = {};
      } catch (...) {
        outputAllocator = {};
        throw;
      }
    });
    test("TCP Chest to PKSM and PKSM to Chest", [] {
      Temp tmp;
      auto a = tmp.store("/chest", 50, CHEST_GENS), b = tmp.store("/pksm");
      fixture(a, "a", 3, 3, 6);
      Bank bank(a, {"a", 3});
      auto p = exportBoxes(a, bank, {2, 0});
      auto first = transfer(b, p);
      require(first.sendError.empty() && first.receiveError.empty() &&
                  first.sender == first.receiver,
              "first direction");
      Bank received(b, {first.receiver, 2});
      auto back = exportBoxes(b, received, {1, 0});
      auto second = transfer(a, back);
      require(second.sendError.empty() && second.receiveError.empty(),
              "reverse direction");
      Bank returned(a, {second.receiver, 2});
      uint8_t x[BOX_BYTES], y[BOX_BYTES];
      bank.readBox(0, x);
      returned.readBox(0, y);
      require(!std::memcmp(x, y, BOX_BYTES), "reverse bytes");
      discard(p);
      discard(back);
    });
    test("TCP wrong PIN refuses without changing destination", [] {
      Temp t;
      auto s = t.store("/s"), d = t.store("/d");
      fixture(s, "s", 1);
      fixture(d, "old", 1);
      Bank b(s, {"s", 1});
      auto p = exportBoxes(s, b, {0});
      auto before = readText(d.registry());
      auto r = transfer(d, p, 123455);
      require(!r.sendError.empty() && !r.receiveError.empty(), "PIN rejected");
      require(readText(d.registry()) == before, "PIN destination unchanged");
      discard(p);
    });
    test("TCP receiver refusal preserves destination", [] {
      Temp t;
      auto s = t.store("/s"), d = t.store("/d");
      fixture(s, "s", 1);
      Bank b(s, {"s", 1});
      auto p = exportBoxes(s, b, {0});
      auto r =
          transfer(d, p, 123456, 123456, [](const Offer &) { return false; });
      require(!r.sendError.empty() && !exists(d.registry()),
              "receiver refused");
      discard(p);
    });
    test("TCP changed byte rejected by SHA-256", [] {
      Temp t;
      auto s = t.store("/s"), d = t.store("/d");
      fixture(s, "s", 2);
      Bank b(s, {"s", 2});
      auto p = exportBoxes(s, b, {0, 1});
      auto r = transfer(d, p, 123456, 123456, {}, 1);
      require(!r.sendError.empty() &&
                  r.receiveError.find("SHA-256") != std::string::npos,
              "transport hash rejected");
      require(!exists(d.registry()), "no corrupt bank registered");
      discard(p);
    });
    test("TCP mid-stream disconnect never imports incomplete bank", [] {
      Temp t;
      auto s = t.store("/s"), d = t.store("/d");
      fixture(s, "s", 2);
      Bank b(s, {"s", 2});
      auto p = exportBoxes(s, b, {0, 1});
      auto r = transfer(d, p, 123456, 123456, {}, 2);
      require(!r.sendError.empty() && !r.receiveError.empty() &&
                  !exists(d.registry()),
              "disconnect safe");
      require(!exists(d.work() + "/receive.bnk.part"), "partial removed");
      discard(p);
    });
    test("TCP lost final ACK keeps verified receiver copy and source", [] {
      Temp t;
      auto s = t.store("/s"), d = t.store("/d");
      fixture(s, "s", 1);
      auto original = bytes(s.banks() + "/s.bnk");
      Bank b(s, {"s", 1});
      auto p = exportBoxes(s, b, {0});
      auto r = transfer(d, p, 123456, 123456, {}, 3);
      require(!r.sendError.empty() && hasBank(d, "link0001"),
              "ACK lost after commit");
      Bank copy(d, {"link0001", 1});
      require(copy.inspect(0).occupied == 5, "verified bank remains");
      require(bytes(s.banks() + "/s.bnk") == original, "source remains");
      discard(p);
    });
    test("TCP maximum 500-box streaming import", [] {
      Temp t;
      auto s = t.store("/s"), d = t.store("/d");
      fixture(s, "s", 500);
      Bank b(s, {"s", 500});
      std::vector<unsigned> boxes;
      for (unsigned i = 0; i < 500; ++i)
        boxes.push_back(i);
      auto p = exportBoxes(s, b, boxes);
      auto r = transfer(d, p);
      require(r.sendError.empty() && r.receiveError.empty(),
              "500-box transfer");
      Bank copy(d, {r.receiver, 500});
      uint8_t a[BOX_BYTES], z[BOX_BYTES];
      b.readBox(499, a);
      copy.readBox(499, z);
      require(!std::memcmp(a, z, BOX_BYTES), "last box intact");
      discard(p);
    });
    std::cout << "ALL " << passed << " TEST GROUPS PASSED\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << "FAIL " << e.what() << '\n';
    return 1;
  }
}
