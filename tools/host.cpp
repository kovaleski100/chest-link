// Diagnostic CLI for development. Console transfers do not require this tool.
#include "core.hpp"
#include "mailbox.hpp"
#include "network.hpp"
#include <cstdio>
#include <cstdlib>
#include <sstream>
using namespace chestlink;
int main(int argc, char **argv) {
  try {
    if (argc < 3)
      throw Error(
          "Uso:\n  chest-link-cli list RAIZ\n  chest-link-cli recover "
          "RAIZ\n  chest-link-cli receive RAIZ PIN [PORTA]\n  "
          "chest-link-cli send RAIZ BANCO BOXES IP PIN [PORTA]\nBOXES: "
          "numeros separados por virgula, comecando em 1.\n"
          "  chest-link-cli mail-send RAIZ BANCO BOXES IP PIN DESTINO [PORTA]\n"
          "  chest-link-cli mail-list RAIZ IP PIN DESTINO [TODAS] [OFFSET] "
          "[PORTA]\n"
          "  chest-link-cli mail-fetch RAIZ IP PIN DESTINO ID [PORTA] "
          "[MAXBOXES]\n"
          "DESTINO: 1=DS, 2=3DS. TODAS: 0=pendentes, 1=todas.");
    Store store{"Host", argv[2], 500, PKSM_GENS, {}};
    std::string command = argv[1];
    recover(store);
    if (command == "list") {
      for (const auto &b : listBanks(store))
        std::printf("%s\t%u boxes\n", b.name.c_str(), b.boxes);
      return 0;
    }
    if (command == "recover")
      return 0;
    if (command == "mail-list" || command == "mail-fetch") {
      if (argc < 6)
        throw Error("Informe IP, PIN e destino.");
      uint32_t target = std::stoul(argv[5]), pin = std::stoul(argv[4]);
      if (command == "mail-list") {
        auto conn = Connection::connect(argv[3], argc > 8 ? std::stoul(argv[8])
                                                          : MAILBOX_PORT);
        auto w = conn.wire();
        auto page =
            listMailbox(w, pin, target, argc > 6 && std::stoul(argv[6]) != 0,
                        argc > 7 ? std::stoul(argv[7]) : 0);
        std::printf("PAGE %u %u\n", unsigned(page.next), unsigned(page.total));
        for (const auto &i : page.items)
          std::printf("ITEM %s %u %u %u %s\n", i.id.c_str(),
                      unsigned(i.offer.boxes), unsigned(i.offer.occupied),
                      unsigned(i.delivered), i.label.c_str());
      } else {
        if (argc < 7)
          throw Error("Informe o ID da copia.");
        store.generations = target == TARGET_DS ? CHEST_GENS : PKSM_GENS;
        store.maxBoxes = argc > 8 ? std::stoul(argv[8]) : MAX_BOXES;
        auto conn = Connection::connect(argv[3], argc > 7 ? std::stoul(argv[7])
                                                          : MAILBOX_PORT);
        auto w = conn.wire();
        auto receipt = fetchMailbox(w, pin, target, argv[6], store,
                                    [](const Offer &) { return true; });
        std::printf("%s %s ACK %u\n", receipt.reused ? "REUSED" : "IMPORTED",
                    receipt.bank.c_str(), unsigned(receipt.confirmed));
      }
      return 0;
    }
    if (command == "receive") {
      if (argc < 4)
        throw Error("Informe o PIN.");
      unsigned port = argc > 4 ? std::stoul(argv[4]) : PORT;
      int fd = Connection::listen(port);
      std::printf("LISTENING %u\n", port);
      std::fflush(stdout);
      try {
        auto conn = Connection::accept(fd);
        Connection::close(fd);
        fd = -1;
        auto w = conn.wire();
        auto name =
            receivePackage(w, std::stoul(argv[3]), store, [](const Offer &o) {
              std::printf("OFFER %u boxes %u records\n", unsigned(o.boxes),
                          unsigned(o.occupied));
              return true;
            });
        std::printf("IMPORTED %s\n", name.c_str());
      } catch (...) {
        Connection::close(fd);
        throw;
      }
      return 0;
    }
    if (command == "send" || command == "mail-send") {
      if (argc < 7)
        throw Error("Informe banco, boxes, IP e PIN.");
      BankInfo info;
      bool found = false;
      for (auto b : listBanks(store))
        if (b.name == argv[3]) {
          info = b;
          found = true;
        }
      if (!found)
        throw Error("Banco nao encontrado.");
      Bank bank(store, info);
      std::vector<unsigned> selected;
      std::stringstream ss(argv[4]);
      std::string item;
      while (std::getline(ss, item, ',')) {
        unsigned n = std::stoul(item);
        if (!n)
          throw Error("Boxes comecam em 1.");
        selected.push_back(n - 1);
      }
      Package p = exportBoxes(store, bank, selected);
      try {
        if (command == "mail-send") {
          if (argc < 8)
            throw Error("Informe destino 1=DS ou 2=3DS.");
          auto conn = Connection::connect(
              argv[5], argc > 8 ? std::stoul(argv[8]) : MAILBOX_PORT);
          auto w = conn.wire();
          auto id = uploadMailbox(w, std::stoul(argv[6]), std::stoul(argv[7]),
                                  info.name, p);
          discard(p);
          std::printf("STORED %s\n", id.c_str());
          return 0;
        }
        auto conn =
            Connection::connect(argv[5], argc > 7 ? std::stoul(argv[7]) : PORT);
        auto w = conn.wire();
        auto name = sendPackage(w, std::stoul(argv[6]), p);
        discard(p);
        std::printf("CONFIRMED %s\n", name.c_str());
      } catch (...) {
        discard(p);
        throw;
      }
      return 0;
    }
    throw Error("Comando desconhecido.");
  } catch (const std::exception &e) {
    std::fprintf(stderr, "%s\n", e.what());
    return 1;
  }
}
