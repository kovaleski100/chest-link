#include "core.hpp"
#include "graphics.hpp"
#include "mailbox.hpp"
#include "network.hpp"
#include "platform.hpp"
#include "pokemon.hpp"
#include <algorithm>
#include <cstdio>
#include <memory>
using namespace chestlink;
namespace {
enum class TransferAction { cancel, pc, direct };
struct DirectListener {
  int server = -1;
  uint32_t pin = 0;
  std::string ip;
  std::string status = "Recepcao direta indisponivel";
  uint64_t lastMailboxPoll = 0;
};
DirectListener directListener;
bool handlingIncoming = false;

void serviceIncoming();

void title(const char *s) { gui::notice(s, "Aguarde...", "B: cancelar", 0); }
unsigned waitKey() {
  while (platform::alive()) {
    platform::frame();
    serviceIncoming();
    unsigned k = platform::keys();
    if (k)
      return k;
  }
  throw Error("Encerrado.");
}
unsigned dialogKey() {
  unsigned k = waitKey();
  if (k & platform::TOUCH) {
    auto t = platform::touch();
    if (t.y >= 172 && t.y < 202)
      return t.x < 160 ? platform::A : platform::B;
  }
  return k;
}
void message(const std::string &s) {
  gui::notice("Mensagem", s, "A/B: voltar");
  while (!(dialogKey() & (platform::A | platform::B))) {
  }
}
bool confirm(const char *heading, const std::string &s) {
  gui::notice(heading, s);
  for (;;) {
    unsigned k = dialogKey();
    if (k & platform::B)
      return false;
    if (k & platform::A)
      return true;
  }
}
int choose(const char *heading, const std::vector<std::string> &items,
           bool mainMenu = false) {
  if (items.empty())
    throw Error("Nenhuma opcao disponivel.");
  unsigned cursor = 0;
  for (;;) {
    gui::menu(heading, items, cursor,
              mainMenu ? directListener.status : std::string());
    unsigned k = waitKey();
    if (k & platform::TOUCH) {
      auto t = platform::touch();
      int hit = gui::menuHit(t.x, t.y, cursor, items.size());
      if (hit >= 0)
        return hit;
    }
    if (k & platform::B)
      return -1;
    if (k & platform::UP)
      cursor = (cursor + items.size() - 1) % items.size();
    if (k & platform::DOWN)
      cursor = (cursor + 1) % items.size();
    if (k & platform::L)
      cursor = cursor >= 8 ? cursor - 8 : 0;
    if (k & platform::R)
      cursor = std::min<unsigned>(cursor + 8, items.size() - 1);
    if (k & platform::A)
      return cursor;
  }
}
Store chooseStore() {
  auto stores = platform::stores();
  int n = 0;
  if (stores.size() > 1) {
    std::vector<std::string> names;
    for (const auto &s : stores)
      names.push_back(s.label);
    n = choose("Escolha o armazenamento", names);
    if (n < 0)
      throw Error("Cancelado.");
  }
  recover(stores[n]);
  return stores[n];
}
std::string generations(uint32_t mask) {
  const char *labels[] = {"4", "5", "6", "7", "LGPE", "8", "3", "1", "2"};
  std::string s;
  for (unsigned i = 0; i < 9; ++i)
    if (mask & (1u << i)) {
      if (!s.empty())
        s += ',';
      s += labels[i];
    }
  return s.empty() ? "boxes vazias" : s;
}
const char *otherConsole();
std::string settingsRoot(const Store &store) {
  // ExtData commits can fail while persisting disposable connection settings.
  // Keep these preferences on SD; bank imports still commit ExtData durably.
  return store.commit ? "sdmc:/3ds/ChestLink" : store.work();
}
struct SelectionResult {
  TransferAction action = TransferAction::cancel;
  std::vector<uint32_t> masks;
};

SelectionResult chooseSelection(const Bank &bank, const std::string &bankName) {
  constexpr uint32_t ALL = (1u << SLOTS) - 1;
  std::vector<uint32_t> masks(bank.boxes(), 0);
  gui::BoxScreen screen;
  screen.bank = bankName;
  screen.boxes = bank.boxes();
  screen.consult = true;
  screen.directLabel = otherConsole();
  unsigned loaded = ~0u;
  auto bytes = std::make_unique<uint8_t[]>(BOX_BYTES);
  for (;;) {
    if (loaded != screen.box) {
      bank.readBox(screen.box, bytes.get());
      for (unsigned i = 0; i < SLOTS; ++i)
        screen.pokemon[i] = previewPokemon(bytes.get() + i * ENTRY);
      screen.name = bank.boxName(screen.box);
      loaded = screen.box;
    }
    screen.mask = masks[screen.box];
    screen.marked = screen.markedBoxes = 0;
    for (uint32_t m : masks) {
      screen.marked += __builtin_popcount(m);
      if (m)
        ++screen.markedBoxes;
    }
    gui::box(screen);
    unsigned k = waitKey();
    int touchAction = -1;
    if (k & platform::TOUCH) {
      auto t = platform::touch();
      touchAction = gui::boxHit(t.x, t.y);
      if (touchAction >= 0 && touchAction < 30) {
        screen.cursor = touchAction;
        k = platform::A;
      } else if (touchAction == 30)
        k = platform::L;
      else if (touchAction == 31)
        k = platform::R;
      else if (touchAction == 32)
        k = platform::A;
      else if (touchAction == 36)
        k = platform::B;
    }
    if (k & platform::B)
      return {};
    if (k & platform::LEFT)
      screen.cursor = (screen.cursor + 29) % 30;
    if (k & platform::RIGHT)
      screen.cursor = (screen.cursor + 1) % 30;
    if (k & platform::UP)
      screen.cursor = (screen.cursor + 24) % 30;
    if (k & platform::DOWN)
      screen.cursor = (screen.cursor + 6) % 30;
    if (k & platform::L)
      screen.box = (screen.box + bank.boxes() - 1) % bank.boxes();
    if (k & platform::R)
      screen.box = (screen.box + 1) % bank.boxes();
    if ((k & platform::A) && screen.pokemon[screen.cursor].occupied)
      masks[screen.box] ^= 1u << screen.cursor;
    if (k & platform::Y)
      masks[screen.box] = masks[screen.box] == ALL ? 0 : ALL;
    if (k & platform::X) {
      bool all = std::all_of(masks.begin(), masks.end(),
                             [](uint32_t m) { return m == ALL; });
      std::fill(masks.begin(), masks.end(), all ? 0 : ALL);
    }
    auto has = [&] {
      return std::any_of(masks.begin(), masks.end(),
                         [](uint32_t m) { return m != 0; });
    };
    if (touchAction == 33 && has())
      return {TransferAction::pc, masks};
    if (touchAction == 34 && has())
      return {TransferAction::direct, masks};
    if (k & platform::START) {
      if (!has()) {
        message("A: marcar um Pokemon.\nY: marcar a box inteira.\nX: marcar "
                "todas as boxes.");
      } else {
        int selected = choose("Enviar selecao", {"Enviar ao PC",
                                                  "Enviar ao outro console"});
        if (selected == 0)
          return {TransferAction::pc, masks};
        if (selected == 1)
          return {TransferAction::direct, masks};
      }
    }
  }
}
unsigned numberTouch(unsigned k, unsigned &cursor, unsigned count, bool ip) {
  if (!(k & platform::TOUCH))
    return k;
  auto t = platform::touch();
  if (t.y >= 80 && t.y < 108) {
    int start = ip ? 20 : 28, width = ip ? 70 : 44;
    if (t.x >= start && t.x < start + int(count) * width)
      cursor = (t.x - start) / width;
    return 0;
  }
  if (t.y >= 130 && t.y < 158)
    return t.x < 160 ? platform::UP : platform::DOWN;
  if (t.y >= 172 && t.y < 200)
    return t.x < 160 ? platform::A : platform::B;
  return 0;
}
std::string inputIP(const Store &store, bool pc = false) {
  unsigned octet[4] = {192, 168, 1, 100};
  std::string filename = pc ? "/server-ip.txt" : "/last-ip.txt";
  std::string path = settingsRoot(store) + filename;
  std::string previousPath = store.work() + filename;
  std::string readPath = exists(path) ? path : previousPath;
  if (exists(readPath)) {
    try {
      std::string s = readText(readPath, 32);
      unsigned a, b, c, d;
      char extra;
      if (std::sscanf(s.c_str(), "%u.%u.%u.%u%c", &a, &b, &c, &d, &extra) ==
              4 &&
          a < 256 && b < 256 && c < 256 && d < 256) {
        octet[0] = a;
        octet[1] = b;
        octet[2] = c;
        octet[3] = d;
      }
    } catch (const Error &) {
    }
  }
  unsigned cursor = 0;
  for (;;) {
    gui::numbers(pc ? "IP exibido no PC" : "IP do console que recebe",
                 {octet[0], octet[1], octet[2], octet[3]}, cursor, true);
    unsigned k = numberTouch(waitKey(), cursor, 4, true);
    if (k & platform::B)
      throw Error("Cancelado.");
    if (k & platform::LEFT)
      cursor = (cursor + 3) % 4;
    if (k & platform::RIGHT)
      cursor = (cursor + 1) % 4;
    if (k & platform::UP)
      octet[cursor] = (octet[cursor] + 1) % 256;
    if (k & platform::DOWN)
      octet[cursor] = (octet[cursor] + 255) % 256;
    if (k & platform::L)
      octet[cursor] = octet[cursor] >= 10 ? octet[cursor] - 10 : 0;
    if (k & platform::R)
      octet[cursor] = std::min(255u, octet[cursor] + 10);
    if (k & platform::A) {
      char ip[32];
      std::snprintf(ip, sizeof(ip), "%u.%u.%u.%u", octet[0], octet[1], octet[2],
                    octet[3]);
      makeDirs(settingsRoot(store));
      writeText(path, ip);
      return ip;
    }
  }
}
uint32_t inputPIN(const Store *pcStore = nullptr) {
  unsigned digits[6] = {0, 0, 0, 0, 0, 0}, cursor = 0;
  std::string path = pcStore ? settingsRoot(*pcStore) + "/server-pin.txt" : "";
  std::string previousPath = pcStore ? pcStore->work() + "/server-pin.txt" : "";
  std::string readPath = !path.empty() && exists(path) ? path : previousPath;
  if (!readPath.empty() && exists(readPath)) {
    try {
      std::string saved = readText(readPath, 6);
      if (saved.size() == 6 &&
          saved.find_first_not_of("0123456789") == std::string::npos)
        for (unsigned i = 0; i < 6; ++i)
          digits[i] = saved[i] - '0';
    } catch (const Error &) {
    }
  }
  for (;;) {
    gui::numbers(
        pcStore ? "PIN exibido no PC" : "PIN exibido no destino",
        {digits[0], digits[1], digits[2], digits[3], digits[4], digits[5]},
        cursor, false);
    unsigned k = numberTouch(waitKey(), cursor, 6, false);
    if (k & platform::B)
      throw Error("Cancelado.");
    if (k & platform::LEFT)
      cursor = (cursor + 5) % 6;
    if (k & platform::RIGHT)
      cursor = (cursor + 1) % 6;
    if (k & platform::UP)
      digits[cursor] = (digits[cursor] + 1) % 10;
    if (k & platform::DOWN)
      digits[cursor] = (digits[cursor] + 9) % 10;
    if (k & platform::A) {
      uint32_t pin = 0;
      for (unsigned n : digits)
        pin = pin * 10 + n;
      if (pcStore) {
        char text[8];
        std::snprintf(text, sizeof(text), "%06u", unsigned(pin));
        makeDirs(settingsRoot(*pcStore));
        writeText(path, text);
      }
      return pin;
    }
  }
}
Progress progress(const char *heading) {
  auto previous = std::make_shared<int>(-1);
  return [heading, previous](uint32_t done, uint32_t total) {
    int pct = total ? uint64_t(done) * 100 / total : 0;
    if (pct != *previous) {
      *previous = pct;
      gui::notice(heading, std::to_string(done) + " / " + std::to_string(total),
                  done == total
                      ? "Verificando / aguardando confirmacao do destino..."
                      : "B: cancelar",
                  pct);
    }
    // File preparation also pumps events; sockets already poll cancellation.
    platform::frame();
    return platform::alive() && !(platform::keys() & platform::B);
  };
}
const char *otherConsole() {
#ifdef CL_NDS
  return "3DS / PKSM";
#else
  return "DS / Pokemon Chest";
#endif
}

void transferSelection(Store &, const Bank &, const std::string &,
                       SelectionResult);

void consult() {
  Store store = chooseStore();
  auto banks = listBanks(store);
  if (banks.empty())
    throw Error("Nenhum banco cadastrado. Guarde os Pokemon no banco do "
                "Chest/PKSM e salve antes de abrir este app.");
  std::vector<std::string> names;
  for (const auto &b : banks)
    names.push_back(b.name + " (" + std::to_string(b.boxes) + " boxes)");
  int n = choose("Escolha um banco", names);
  if (n < 0)
    return;
  Bank bank(store, banks[n]);
  SelectionResult result = chooseSelection(bank, banks[n].name);
  if (result.action != TransferAction::cancel)
    transferSelection(store, bank, banks[n].name, std::move(result));
}

void transferSelection(Store &store, const Bank &bank,
                        const std::string &bankName, SelectionResult result) {
  Package p = exportSelection(store, bank, result.masks,
                              progress("Preparando envio"));
  try {
    std::string desc =
        std::to_string(p.offer.boxes) + " boxes / " +
        std::to_string(p.offer.occupied) +
        " Pokemon\nGeracoes: " + generations(p.offer.generations) +
        (result.action == TransferAction::pc
             ? "\n\nA origem permanece intacta.\nDeixe o servidor do PC aberto."
             : "\n\nA origem permanece intacta.\nO outro console fica "
               "escutando automaticamente.");
    if (!confirm("Enviar estas boxes?", desc)) {
      discard(p);
      return;
    }
    if (result.action == TransferAction::pc) {
      int destination = choose("Guardar no PC para qual console?",
                               {"DS / Pokemon Chest", "3DS / PKSM"});
      if (destination < 0) {
        discard(p);
        return;
      }
      uint32_t target = destination == 0 ? TARGET_DS : TARGET_3DS;
      platform::network();
      std::string ip = inputIP(store, true);
      uint32_t pin = inputPIN(&store);
      title("Conectando...");
      auto conn = Connection::connect(ip, MAILBOX_PORT);
      auto wire = conn.wire();
      std::string id = uploadMailbox(wire, pin, target,
                                      store.label + ": " + bankName, p,
                                      progress("Enviando ao PC"));
      discard(p);
      message("PC confirmou a copia.\nID: " + id.substr(0, 8) +
              "\n\nDepois, no console de destino, abra Chest Link.\n"
              "A copia continua na origem.");
      return;
    }
    platform::network();
    std::string ip = inputIP(store, false);
    uint32_t pin = inputPIN(nullptr);
    title("Conectando...");
    auto conn = Connection::connect(ip, PORT);
    auto wire = conn.wire();
    std::string name = sendPackage(wire, pin, p, progress("Enviando boxes"));
    discard(p);
    message("Destino confirmou a copia.\n\nBanco novo: " + name +
            "\n\nAbra Chest/PKSM no destino\ne selecione esse banco.");
  } catch (...) {
    discard(p);
    throw;
  }
}
void receiveConnection(Connection &conn) {
  Store store = chooseStore();
  auto wire = conn.wire();
  auto accept = [&store](const Offer &o) {
    std::string s =
        std::to_string(o.boxes) + " boxes / " + std::to_string(o.occupied) +
        " Pokemon\nGeracoes: " + generations(o.generations) +
        "\n\nDestino: " + store.label + "\nVai criar um banco novo.";
    return confirm("Receber estas boxes?", s);
  };
  std::string name = receivePackage(wire, directListener.pin, store, accept,
                                    progress("Recebendo boxes"));
  message("Copia conferida e gravada.\n\nBanco novo: " + name +
          "\n\nO banco já está disponível no armazenamento escolhido.");
}

bool savedPCConnection(const Store &store, std::string &ip, uint32_t &pin) {
  std::string ipPath = settingsRoot(store) + "/server-ip.txt";
  std::string pinPath = settingsRoot(store) + "/server-pin.txt";
  std::string oldIPPath = store.work() + "/server-ip.txt";
  std::string oldPINPath = store.work() + "/server-pin.txt";
  if (!exists(ipPath))
    ipPath = oldIPPath;
  if (!exists(pinPath))
    pinPath = oldPINPath;
  if (!exists(ipPath) || !exists(pinPath))
    return false;
  try {
    std::string ipText = readText(ipPath, 32), pinText = readText(pinPath, 6);
    unsigned a, b, c, d;
    char extra;
    if (std::sscanf(ipText.c_str(), "%u.%u.%u.%u%c", &a, &b, &c, &d,
                    &extra) != 4 || a > 255 || b > 255 || c > 255 || d > 255 ||
        pinText.size() != 6 ||
        pinText.find_first_not_of("0123456789") != std::string::npos)
      return false;
    ip = ipText;
    pin = 0;
    for (char digit : pinText)
      pin = pin * 10 + unsigned(digit - '0');
    return true;
  } catch (const Error &) {
    return false;
  }
}

void serviceMailbox() {
  uint64_t now = platform::milliseconds();
  if (now - directListener.lastMailboxPoll < 3000)
    return;
  directListener.lastMailboxPoll = now;
#ifdef CL_NDS
  constexpr uint32_t target = TARGET_DS;
#else
  constexpr uint32_t target = TARGET_3DS;
#endif
  for (const auto &store : platform::stores()) {
    std::string ip;
    uint32_t pin = 0;
    if (!savedPCConnection(store, ip, pin))
      continue;
    try {
      auto connection = Connection::connect(ip, MAILBOX_PORT, 500);
      auto wire = connection.wire();
      MailboxPage page = listMailbox(wire, pin, target, false);
      if (page.items.empty())
        continue;
      const MailboxItem &item = page.items.front();
      std::string description =
          item.label + "\n" + std::to_string(item.offer.boxes) +
          " boxes / " + std::to_string(item.offer.occupied) +
          " Pokemon\n\nAceitar esta transferencia?";
      if (!confirm("Transferencia recebida", description))
        return;
      auto incoming = Connection::connect(ip, MAILBOX_PORT);
      auto incomingWire = incoming.wire();
      auto accept = [](const Offer &) { return true; };
      MailboxReceipt receipt = fetchMailbox(
          incomingWire, pin, target, item.id, store, accept,
          progress("Recebendo do PC"));
      std::string name = receipt.bank;
      message("Copia conferida e gravada.\n\nBanco novo: " + name +
              "\n\nO banco já está disponível no armazenamento escolhido.");
      return;
    } catch (const Error &) {
      // A saved PC may be offline. The next poll retries silently.
    }
  }
}

void serviceIncoming() {
  if (handlingIncoming || directListener.server < 0)
    return;
  auto conn = Connection::tryAccept(directListener.server);
  if (!conn) {
    serviceMailbox();
    return;
  }
  handlingIncoming = true;
  try {
    receiveConnection(*conn);
  } catch (const std::exception &e) {
    message(e.what());
  }
  handlingIncoming = false;
}

void startListener() {
  try {
    platform::network();
    directListener.server = Connection::listen();
    directListener.pin = platform::makePin();
    directListener.ip = platform::ip();
    char pinText[8];
    std::snprintf(pinText, sizeof(pinText), "%06u", unsigned(directListener.pin));
    directListener.status = "IP " + directListener.ip + " PIN " + pinText;
  } catch (const std::exception &e) {
    directListener.server = -1;
    directListener.status = "Recepcao direta indisponivel";
  }
}
} // namespace
int runApp() {
  try {
    platform::init();
    for (const auto &store : platform::stores())
      recover(store);
    startListener();
    while (platform::alive()) {
      int n = choose("Chest Link",
                     {"Consultar bancos", "Creditos", "Sair"}, true);
      if (n < 0 || n == 2)
        break;
      try {
        if (n == 0)
          consult();
        else
          message(
              "Chest Link: app independente.\nVisual PKSM / "
              "FlagBrew.\nBernardo Giordano, Admiral Fish,\npiepie62 e "
              "colaboradores.\nLeitura PKX: PKSM-Core.\nSprites: PokeAPI; "
              "Pokemon pertence\na Nintendo, Creatures, GAME FREAK.\nGPL-3.0+: "
              "atribuicao/origem mantidas.\nFontes e licencas no pacote.");
      } catch (const std::exception &e) {
        message(e.what());
      }
    }
    Connection::close(directListener.server);
    directListener.server = -1;
    platform::shutdown();
    return 0;
  } catch (const std::exception &e) {
    Connection::close(directListener.server);
    directListener.server = -1;
    message(e.what());
    platform::shutdown();
    return 1;
  }
}
