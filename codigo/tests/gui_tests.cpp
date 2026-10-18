#include "core.hpp"
#include "graphics.hpp"
#include "graphics_assets.hpp"
#include "platform.hpp"
#include "pokemon.hpp"
#include <algorithm>
#include <cstring>
#include <filesystem>
#include <iostream>
namespace platform {
void present(const uint16_t *, unsigned, const uint16_t *) {}
} // namespace platform
using namespace chestlink;
static void require(bool v, const char *s) {
  if (!v)
    throw Error(s);
}
int main(int argc, char **argv) {
  try {
    // A binary batch probe is used by test_interface.py to compare the PC and
    // console decoders against independent known field/encryption vectors.
    if (argc == 2 && std::string(argv[1]) == "preview") {
      uint8_t entry[ENTRY];
      while (std::cin.read(reinterpret_cast<char *>(entry), ENTRY)) {
        auto p = previewPokemon(entry);
        std::cout << p.occupied << ' ' << p.valid << ' ' << p.species << ' '
                  << p.form << ' ' << p.generation << ' ' << p.egg << ' '
                  << p.shiny << ' ' << p.sprite << '\n';
      }
      return 0;
    }
    char tmp[] = "/tmp/chest-link-gui-XXXXXX";
    char *dir = mkdtemp(tmp);
    require(dir, "mkdtemp");
    struct Cleanup {
      std::string p;
      ~Cleanup() { std::filesystem::remove_all(p); }
    } clean{dir};
    Store store{"test", std::string(dir) + "/source", 500, PKSM_GENS, {}};
    makeDirs(store.banks());
    writeText(store.registry(), "{\"source\":3}");
    std::string raw(16 + 3 * BOX_BYTES, char(0xff));
    auto *data = reinterpret_cast<uint8_t *>(&raw[0]);
    std::memcpy(data, "PKSMBANK", 8);
    put32(data + 8, 3);
    put32(data + 12, 3);
    for (unsigned b = 0; b < 3; ++b)
      for (unsigned slot : {0u, 2u, 29u}) {
        auto *entry = data + 16 + (b * 30 + slot) * ENTRY;
        put32(entry, 0);
        for (unsigned i = 4; i < ENTRY; ++i)
          entry[i] = uint8_t(b * 31 + slot + i);
      }
    writeText(store.banks() + "/source.bnk", raw);
    std::string names = "[\"Caixa 1\",\"Caixa 2\",\"Caixa 3\"]";
    writeText(store.banks() + "/source.json", names);
    Bank bank(store, {"source", 3});
    auto package = exportSelection(store, bank, {5, 0, 1u << 29});
    validate(package, store);
    require(package.offer.boxes == 2 && package.offer.occupied == 3,
            "selection counters");
    auto result = readText(package.bank);
    for (unsigned b = 0; b < 2; ++b)
      for (unsigned slot = 0; slot < 30; ++slot) {
        bool selected = b == 0 ? (slot == 0 || slot == 2) : slot == 29;
        auto p = result.data() + 16 + (b * 30 + slot) * ENTRY;
        if (selected)
          require(!std::memcmp(p,
                               raw.data() + 16 +
                                   ((b == 0 ? 0 : 2) * 30 + slot) * ENTRY,
                               ENTRY),
                  "raw PKX/padding changed");
        else
          require(std::all_of(p, p + ENTRY,
                              [](char c) { return uint8_t(c) == 255; }),
                  "excluded slot not empty");
      }
    require(readText(package.names) == "[\"Caixa 1\",\"Caixa 3\"]",
            "names order changed");
    Store destination{
        "target", std::string(dir) + "/destination", 500, PKSM_GENS, {}};
    auto imported = importPackage(destination, package);
    require(exists(destination.banks() + "/" + imported + ".bnk"),
            "selected package not imported");
    discard(package);
    require(readText(bank.path()) == raw &&
                readText(store.banks() + "/source.json") == names,
            "source bank changed");
    std::cout << "PASS individual selection preserves records, slot positions, "
                 "names and source\n";
    unsigned rejected = 0;
    for (const std::vector<uint32_t> &bad : std::vector<std::vector<uint32_t>>{
             {}, {1}, {0, 0, 0}, {1u << 30, 0, 0}}) {
      try {
        auto p = exportSelection(store, bank, bad);
        discard(p);
      } catch (const Error &) {
        ++rejected;
      }
    }
    require(rejected == 4, "invalid slot selection accepted");
    bool cancelled = false;
    try {
      auto p = exportSelection(store, bank, {1, 1, 1},
                               [](uint32_t, uint32_t) { return false; });
      discard(p);
    } catch (const Error &) {
      cancelled = true;
    }
    require(cancelled && !exists(store.work() + "/out.bnk.part"),
            "cancelled export kept staging");
    std::cout
        << "PASS invalid/cancelled individual selections keep source intact\n";
    for (unsigned row = 0; row < 5; ++row)
      for (unsigned col = 0; col < 6; ++col) {
        require(gui::boxHit(4 + col * 34 + 17, 45 + row * 30 + 15) ==
                    int(row * 6 + col),
                "slot touch mapping");
      }
    require(gui::boxHit(10, 20) == 30 && gui::boxHit(195, 20) == 31,
            "box arrows mapping");
    for (unsigned i = 0; i < 5; ++i)
      require(gui::boxHit(250, 50 + i * 31) == int(32 + i),
              "action touch mapping");
    require(gui::menuHit(15, 12, 0, 6) == 0 &&
                gui::menuHit(15, 12, 8, 10) == 8 &&
                gui::menuHit(15, 190, 8, 10) == -1,
            "menu pagination touch");
    std::cout << "PASS 30 touch slots, arrows, actions and menu pagination\n";
    gui::BoxScreen screen;
    screen.boxes = 500;
    screen.box = 499;
    screen.cursor = 29;
    screen.mask = (1u << 30) - 1;
    screen.bank = "Banco máximo";
    screen.name = "Caixa áéíóú";
    for (unsigned i = 0; i < 30; ++i) {
      screen.pokemon[i].occupied = true;
      screen.pokemon[i].sprite = i == 29 ? ~0u : 898;
    }
    gui::box(screen);
    gui::menu("Bancos", {"1", "2"}, 1);
    gui::notice("SHA-256", "Cópia verificada", "A/B: voltar", 100);
    gui::numbers("PIN", {9, 9, 9, 9, 9, 9}, 5, false);
    std::vector<uint16_t> controls(gui::bottomPixels(), gui::bottomPixels() + 320 * 240);
    chestlink::NetworkStatus live;
    live.visible = live.connected = live.ipv4Ready = true;
    live.ssid = "TestNetwork"; live.ip = "192.0.2.25";
    live.serverIP = "192.0.2.9";
    live.server = chestlink::ServerAvailability::connected;
    gui::setNetworkStatus(live);
    require(std::equal(controls.begin(), controls.end(), gui::bottomPixels()),
            "network refresh changed controls without input");
    const std::vector<uint16_t> online(gui::topPixels(), gui::topPixels() + gui::TOP_WIDTH * 44);
    live.connected = live.ipv4Ready = false; live.ssid.clear(); live.ip.clear();
    live.serverIP.clear();
    live.server = chestlink::ServerAvailability::unknown;
    gui::setNetworkStatus(live);
    require(!std::equal(online.begin(), online.end(), gui::topPixels()),
            "Wi-Fi loss did not repaint the top status strip");
    std::cout << "PASS live Wi-Fi status redraw preserves current controls\n";
    require(gui::assets::spriteCount >= 900, "missing icon catalogue");
    std::cout << "PASS native renderer handles bounds, UTF-8, unknown sprites "
                 "and numeric fields\n";
    std::cout << "ALL 5 GUI TEST GROUPS PASSED\n";
  } catch (const std::exception &e) {
    std::cerr << "FAIL " << e.what() << '\n';
    return 1;
  }
}
