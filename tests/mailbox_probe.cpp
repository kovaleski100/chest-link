// Fault injection against the real PC server and the native portable client.
#include "mailbox.hpp"
#include "network.hpp"
#include <cstdio>
#include <cstdlib>
#include <cstring>
using namespace chestlink;
int main(int argc, char **argv) {
  try {
    if (argc != 8)
      throw Error("ROOT IP PIN TARGET ID PORT FAULT");
    uint32_t target = std::stoul(argv[4]);
    Store s{"Probe",
            argv[1],
            MAX_BOXES,
            target == TARGET_DS ? CHEST_GENS : PKSM_GENS,
            {}};
    std::string fault = argv[7];
    if (fault == "power9") {
      s.commit = [count = 0]() mutable {
        if (++count == 9)
          std::_Exit(23);
      };
    }
    if (fault == "fixed") {
      outputAllocator = [](const std::string &path, uint32_t n) {
        FILE *f = std::fopen(path.c_str(), "wb");
        if (!f)
          throw Error("Falha de prealocacao.");
        if (n && (std::fseek(f, n - 1, SEEK_SET) || std::fputc(0, f) == EOF)) {
          std::fclose(f);
          throw Error("Falha de prealocacao.");
        }
        if (std::fclose(f))
          throw Error("Falha de prealocacao.");
        return true;
      };
    }
    auto conn = Connection::connect(argv[2], std::stoul(argv[6]));
    auto wire = conn.wire();
    if (fault == "dropack") {
      auto write = wire.write;
      wire.write = [write](const void *data, size_t n) {
        if (n == 8 && !std::memcmp(data, "link", 4))
          throw Error("Simulated lost ACK");
        write(data, n);
      };
    }
    if (fault == "corrupt") {
      auto read = wire.read;
      wire.read = [read, body = false, changed = false](void *data,
                                                        size_t n) mutable {
        read(data, n);
        if (body && !changed && n >= 100) {
          static_cast<uint8_t *>(data)[99] ^= 1;
          changed = true;
        }
        if (n == 52)
          body = true;
      };
    }
    auto receipt = fetchMailbox(
        wire, std::stoul(argv[3]), target, argv[5], s,
        [fault](const Offer &) { return fault != "refuse"; },
        [fault](uint32_t done, uint32_t total) {
          return fault != "cancel" || done == total;
        },
        fault != "backup");
    std::printf("%s %s ACK %u\n", receipt.reused ? "REUSED" : "IMPORTED",
                receipt.bank.c_str(), unsigned(receipt.confirmed));
    return 0;
  } catch (const std::exception &e) {
    std::fprintf(stderr, "%s\n", e.what());
    return 1;
  }
}
