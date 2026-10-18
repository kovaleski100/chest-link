#include "core.hpp"
#include "game_saves.hpp"
#include "graphics.hpp"
#include "mailbox.hpp"
#include "network.hpp"
#include "platform.hpp"
#include "pokemon.hpp"
#include "update.hpp"
#include "listener_schedule.hpp"
#include "version.hpp"
#include <algorithm>
#include <exception>
#include <cstdio>
#include <cstring>
#include <memory>
using namespace chestlink;
namespace {
class UpdateTrace {
  std::string path_, session_, phase_ = "startup";
  std::string peerIP_;
  unsigned peerPort_ = 0;
  int remoteSocket_ = -1;
  FILE *file_ = nullptr;
  uint64_t started_ = platform::milliseconds();
  uint64_t lastWireActivityAt_ = started_;
  uint32_t sent_ = 0, received_ = 0, nextWireCheckpoint_ = 64 * 1024;
  uint32_t nextDownloadCheckpoint_ = 64 * 1024;
  uint32_t remoteSent_ = 0, remoteFailed_ = 0;

public:
  explicit UpdateTrace(const std::string &directory) {
    static uint32_t sequence = 0;
    session_ = std::to_string(started_) + "-" + std::to_string(++sequence);
    if (!directory.empty()) {
      path_ = directory;
      if (path_.back() != '/') path_ += '/';
      path_ += "ChestLink_update_" + session_ + ".jsonl";
      file_ = std::fopen(path_.c_str(), "ab");
      if (!file_) path_.clear();
    }
    event("logger_started", {{"session", session_},
                              {"app_version", appVersionText(APP_VERSION_CODE)}});
  }

  ~UpdateTrace() {
    if (file_) std::fclose(file_);
    closeUpdateTraceSocket(remoteSocket_);
  }

  const std::string &path() const { return path_; }

  void enableRemote(const std::string &ip, unsigned port) {
    peerIP_ = ip;
    peerPort_ = port;
    event("remote_logging_enabled", {{"server_ip", ip},
                                      {"server_port", std::to_string(port)}});
  }

  void phase(const std::string &name) {
    phase_ = name;
    event("phase", {{"name", name}});
  }

  void event(const std::string &name,
             std::initializer_list<std::pair<std::string, std::string>> fields = {}) noexcept {
    if (!file_ && (peerIP_.empty() || !peerPort_)) return;
    try {
      Json entry;
      entry.object["elapsed_ms"] = Json::integer(static_cast<uint32_t>(
          platform::milliseconds() - started_));
      entry.object["event"] = Json::text(name);
      entry.object["phase"] = Json::text(phase_);
      entry.object["session"] = Json::text(session_);
      entry.object["tcp_sent_bytes"] = Json::integer(sent_);
      entry.object["tcp_received_bytes"] = Json::integer(received_);
      entry.object["local_log_open"] = Json::text(file_ ? "true" : "false");
      entry.object["radio"] = Json::text(platform::updateNetworkDiagnostics());
      entry.object["udp_logs_sent"] = Json::integer(remoteSent_);
      entry.object["udp_logs_failed"] = Json::integer(remoteFailed_);
      for (const auto &field : fields)
        entry.object[field.first] = Json::text(field.second);
      const std::string line = entry.dump() + "\n";
      if (file_) {
        const bool written =
            std::fwrite(line.data(), 1, line.size(), file_) == line.size();
        const bool flushed = std::fflush(file_) == 0;
        const bool closed = std::fclose(file_) == 0;
        file_ = nullptr;
        if (written && flushed && closed) {
          file_ = std::fopen(path_.c_str(), "ab");
          if (!file_) path_.clear();
        } else {
          path_.clear();
        }
      }
      if (!peerIP_.empty() && peerPort_) {
        if (sendUpdateTrace(remoteSocket_, peerIP_, peerPort_, line)) ++remoteSent_;
        else ++remoteFailed_;
      }
    } catch (...) {
      // Diagnostics must never interrupt the update itself.
    }
  }

  void wireActivity(bool writing, size_t bytes) noexcept {
    if (bytes == 0) {
      event("tcp_idle_checkpoint", {
          {"idle_ms", std::to_string(platform::milliseconds() - lastWireActivityAt_)}});
      return;
    }
    lastWireActivityAt_ = platform::milliseconds();
    uint32_t &counter = writing ? sent_ : received_;
    counter += static_cast<uint32_t>(bytes);
    if (sent_ + received_ >= nextWireCheckpoint_) {
      nextWireCheckpoint_ = sent_ + received_ + 64 * 1024;
      event("tcp_checkpoint");
    }
  }

  void downloadProgress(uint32_t done, uint32_t total) noexcept {
    if (done < nextDownloadCheckpoint_ && done != total) return;
    nextDownloadCheckpoint_ = done + 64 * 1024;
    event("download_progress", {{"bytes_written", std::to_string(done)},
                                 {"total_bytes", std::to_string(total)}});
  }
};

enum class TransferAction { cancel, pc, direct };
struct DirectListener {
  bool enabled = false;
  int server = -1;
  uint32_t pin = 0;
  ListenerSchedule schedule;
  std::string ip;
  std::string status = "Escolha Configurar Wi-Fi";
};
DirectListener directListener;
bool handlingIncoming = false;

void serviceIncoming();

void title(const char *s) { gui::notice(s, "Aguarde...", "B: cancelar", 0); }
unsigned waitKey(const std::function<void()> &idle = {}) {
  while (platform::alive()) {
    platform::frame();
    serviceIncoming();
    if (idle) idle();
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
    std::string paintedStatus = directListener.status;
    unsigned k = waitKey([&]() {
      if (mainMenu && paintedStatus != directListener.status) {
        gui::menu(heading, items, cursor, directListener.status);
        paintedStatus = directListener.status;
      }
    });
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
  // Keep 3DS connection preferences on SD, independent of which PKSM bank is
  // open. Bank reads/writes still use the explicitly selected store.
#ifdef CL_3DS
  (void)store;
  return "sdmc:/3ds/ChestLink";
#else
  return store.work();
#endif
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
std::string inputIP(const Store &store, bool pc = false, bool persist = true,
                    const char *heading = nullptr) {
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
    gui::numbers(heading ? heading :
                     (pc ? "Definir IP do PC" : "IP do console que recebe"),
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
      if (persist) {
        makeDirs(settingsRoot(store));
        writeText(path, ip);
      }
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
  auto previous = std::make_shared<uint32_t>(UINT32_MAX);
  return [heading, previous](uint32_t done, uint32_t total) {
    int pct = total ? uint64_t(done) * 100 / total : 0;
    if (done != *previous) {
      *previous = done;
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
               "escutando; a confirmacao aparece quando ele receber.");
    if (!confirm("Enviar estas boxes?", desc)) {
      discard(p);
      return;
    }
    if (result.action == TransferAction::pc) {
      platform::network();
      std::string ip = inputIP(store, true);
      uint32_t pin = inputPIN(&store);
      title("Conectando...");
      auto conn = Connection::connect(ip, MAILBOX_PORT);
      auto wire = conn.wire();
      // The recipient is chosen later from the PC interface. Zero keeps the
      // copy unassigned until a DS/3DS send action validates its generations.
      std::string id = uploadMailbox(wire, pin, 0,
                                      store.label + ": " + bankName, p,
                                      progress("Enviando ao PC"));
      discard(p);
      message("PC guardou a copia.\nID: " + id.substr(0, 8) +
              "\n\nEscolhe DS ou 3DS na interface do PC para encaminhar.\n"
              "A origem continua intacta.");
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
unsigned previewCount(const std::array<uint8_t, BOX_BYTES> &box,
                      std::array<PokemonPreview, SLOTS> *previews = nullptr) {
  unsigned count = 0;
  for (unsigned slot = 0; slot < SLOTS; ++slot) {
    PokemonPreview pokemon = previewPokemon(box.data() + slot * ENTRY);
    if (previews) (*previews)[slot] = pokemon;
    if (pokemon.occupied && pokemon.valid) ++count;
  }
  return count;
}
std::string gameBoxLabel(const GameSaveInfo &save, unsigned box) {
  return save.title + " Box " + std::to_string(box + 1);
}
void importGameSaves() {
  Store store = chooseStore();
  title("Procurando saves...");
  const auto found = discoverGameSaves();
  std::vector<GameSaveInfo> saves;
  for (const auto &save : found)
    if (save.generation < 32 && (store.generations & (1u << save.generation)))
      saves.push_back(save);
  if (saves.empty()) {
    message(found.empty()
                ? "Nenhum .sav valido de Pokemon das Geracoes I a IV foi encontrado no SD/flashcard."
                : "Os saves Pokemon encontrados nao sao compativeis com este armazenamento.\nGen I/II exigem o banco PKSM do 3DS.");
    return;
  }

  GameSave loaded = readGameSave(saves.front());
  std::array<uint8_t, BOX_BYTES> destination{};
  destination.fill(0xFF);
  std::string destinationName = "Pokemon importados";
  std::string firstSource;
  bool hasCopied = false;
  gui::GameBoxesScreen screen;
  std::map<std::string, unsigned> duplicateCounts, duplicateIndices;
  for (const auto &save : saves) ++duplicateCounts[save.title];
  for (const auto &save : saves) {
    std::string label = save.title;
    if (label == "HeartGold") label = "HG";
    else if (label == "SoulSilver") label = "SS";
    else if (label == "Diamond / Pearl") label = "D/P";
    else if (label == "Ruby / Sapphire") label = "R/S";
    else if (label == "FireRed / LeafGreen") label = "FR/LG";
    else if (label == "Red / Blue / Yellow") label = "Gen I";
    else if (label == "Red / Green / Blue / Yellow (JP)") label = "Gen I JP";
    if (duplicateCounts[save.title] > 1)
      label += std::to_string(++duplicateIndices[save.title]);
    screen.games.push_back(safeDisplay(label, 8));
  }
  unsigned gameIndex = 0, boxIndex = 0;
  auto updateScreen = [&]() {
    screen.gameIndex = gameIndex;
    screen.game = loaded.info.title;
    screen.box = boxIndex;
    screen.boxes = static_cast<unsigned>(loaded.boxes.size());
    screen.boxName = loaded.boxes.at(boxIndex).name;
    screen.targetCount = previewCount(destination, &screen.target);
    screen.targetCursor = SLOTS;
    for (unsigned slot = 0; slot < SLOTS; ++slot)
      if (!screen.target[slot].occupied) {
        screen.targetCursor = slot;
        break;
      }
    if (screen.targetCursor == SLOTS) screen.targetCursor = SLOTS - 1;
    for (unsigned slot = 0; slot < SLOTS; ++slot)
      screen.source[slot] = previewPokemon(
          loaded.boxes[boxIndex].entries.data() + slot * ENTRY);
  };
  updateScreen();

  for (;;) {
    gui::gameBoxes(screen);
    unsigned k = waitKey();
    int touchAction = -1;
    if (k & platform::TOUCH) {
      const auto t = platform::touch();
      touchAction = gui::gameBoxesHit(screen, t.x, t.y);
      if (touchAction >= 0 && touchAction < int(SLOTS)) {
        screen.cursor = unsigned(touchAction);
        k = platform::A;
      } else if (touchAction >= 30 && touchAction <= 33) {
        k = 0;
      } else if (touchAction >= 40) {
        gameIndex = unsigned(touchAction - 40);
        loaded = readGameSave(saves.at(gameIndex));
        boxIndex = 0;
        screen.cursor = 0;
        screen.status.clear();
        updateScreen();
        continue;
      }
    }
    if (k & platform::B || touchAction == 33) return;
    if (k & platform::LEFT) screen.cursor = (screen.cursor + 29) % 30;
    if (k & platform::RIGHT) screen.cursor = (screen.cursor + 1) % 30;
    if (k & platform::UP) screen.cursor = (screen.cursor + 24) % 30;
    if (k & platform::DOWN) screen.cursor = (screen.cursor + 6) % 30;
    if (k & platform::L) boxIndex = (boxIndex + loaded.boxes.size() - 1) % loaded.boxes.size();
    if (k & platform::R) boxIndex = (boxIndex + 1) % loaded.boxes.size();
    if (k & platform::X) {
      gameIndex = (gameIndex + 1) % saves.size();
      loaded = readGameSave(saves.at(gameIndex));
      boxIndex = 0;
      screen.cursor = 0;
      screen.status.clear();
    }

    const int action = touchAction >= 30 && touchAction <= 33
                           ? touchAction - 30
                           : (k & platform::A) ? 0
                           : (k & platform::Y) ? 1
                           : (k & platform::START) ? 2 : -1;
    if (action == 0) {
      const unsigned sourceSlot = screen.cursor;
      if (sourceSlot >= SLOTS || !screen.source[sourceSlot].occupied ||
          !screen.source[sourceSlot].valid) {
        screen.status = "Escolha um Pokemon valido";
      } else {
        unsigned targetSlot = SLOTS;
        for (unsigned slot = 0; slot < SLOTS; ++slot)
          if (!previewPokemon(destination.data() + slot * ENTRY).occupied) {
            targetSlot = slot;
            break;
          }
        if (targetSlot == SLOTS) {
          screen.status = "A box de destino esta cheia";
        } else {
          std::memcpy(destination.data() + targetSlot * ENTRY,
                      loaded.boxes[boxIndex].entries.data() + sourceSlot * ENTRY,
                      ENTRY);
          const std::string sourceName = gameBoxLabel(saves[gameIndex], boxIndex);
          if (!hasCopied) {
            firstSource = sourceName;
            destinationName = sourceName;
            hasCopied = true;
          } else if (sourceName != firstSource) {
            destinationName = "Pokemon de varios saves";
          }
          screen.status = "Pokemon copiado para o rascunho";
        }
      }
    } else if (action == 1) {
      const auto &source = loaded.boxes[boxIndex].entries;
      const unsigned count = previewCount(source);
      if (!count) {
        screen.status = "Esta box nao tem Pokemon validos";
      } else if (!screen.targetCount ||
                 confirm("Copiar box inteira?",
                         "A box selecionada substituira o rascunho atual.\n"
                         "O save do jogo permanecera intacto.")) {
        destination = source;
        firstSource = gameBoxLabel(saves[gameIndex], boxIndex);
        destinationName = firstSource;
        hasCopied = true;
        screen.status = "Box copiada para o rascunho";
      }
    } else if (action == 2) {
      const unsigned count = previewCount(destination);
      if (!count) {
        screen.status = "Copie um Pokemon ou uma box primeiro";
      } else {
        if (confirm("Salvar no Chest Link?",
                    std::to_string(count) + " Pokemon serao salvos como um banco novo.\n\n"
                    "O save do jogo e os bancos atuais nao serao alterados.")) {
          Package package = packageFromBoxes(store, {destination}, {destinationName});
          try {
            const std::string bank = importPackage(store, package);
            discard(package);
            message("Copia salva em " + store.label + ".\nBanco novo: " + bank +
                    "\n\nAgora consulte esse banco para enviar ao PC.\n"
                    "O .sav original permanece intacto.");
          } catch (...) {
            discard(package);
            throw;
          }
          return;
        }
      }
    }
    updateScreen();
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
    std::string ipText = readText(ipPath, 32);
    std::string pinText = readText(pinPath, 6);
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

void updateApplication() {
  std::string ip;
  uint32_t pin = 0;
  std::string installPath;
  bool discoveredAddress = false;
  bool haveConnection = false;
  std::string device;
  std::string logDirectory = platform::runningApplicationDirectory();
#ifdef CL_3DS
  auto stores = platform::stores();
  if (stores.empty())
    throw Error("Nenhum armazenamento disponivel para as configuracoes.");
  Store settings = stores.front();
  for (const auto &store : stores) {
    if (savedPCConnection(store, ip, pin)) {
      settings = store;
      haveConnection = true;
      break;
    }
  }
  // Reuses old per-store preferences as a fallback, but writes new settings
  // to the dedicated SD config path. Updating never asks which bank to open.
  installPath = platform::runningApplicationPath();
  if (logDirectory.empty()) logDirectory = settingsRoot(settings);
#else
  auto stores = platform::stores();
  if (stores.empty())
    throw Error("Nenhum armazenamento disponivel para instalar a atualizacao.");
  unsigned selected = 0;
  if (stores.size() > 1) {
    std::vector<std::string> options;
    for (const auto &store : stores)
      options.push_back(store.label);
    int choice = choose("Configuracoes do servidor", options);
    if (choice < 0)
      return;
    selected = static_cast<unsigned>(choice);
  }
  Store settings = stores[selected];
  device = logDirectory;
  if (device.empty()) {
    device = "/";
    auto mount = settings.root.find(":/");
    if (mount != std::string::npos)
      device = settings.root.substr(0, mount + 2);
  }
  logDirectory = device;
  haveConnection = savedPCConnection(settings, ip, pin);
#endif
  UpdateTrace trace(logDirectory);
  trace.event("update_started", {{"network", platform::updateNetworkDiagnostics()},
                                  {"saved_server_ip", haveConnection ? ip : "none"}});
  try {
    platform::network();
    trace.event("network_ready", {{"network", platform::updateNetworkDiagnostics()}});
    bool usingHotspot = false;
#ifdef CL_NDS
    usingHotspot = platform::usingChestLinkHotspot();
    if (usingHotspot) {
      const std::string hotspotIP = platform::chestLinkHotspotServerIP();
      if (hotspotIP.empty())
        throw Error("Nao consegui ler o endereco do PC na rede ChestLink-DS.");
      ip = hotspotIP;
    }
#endif
    std::unique_ptr<Connection> connection;
    std::string connectionError;
    auto tryConnect = [&](unsigned timeout) {
      trace.event("tcp_connect_started", {{"server_ip", ip},
                                           {"port", std::to_string(MAILBOX_PORT)},
                                           {"timeout_ms", std::to_string(timeout)}});
      try {
        connection = std::make_unique<Connection>(
            Connection::connect(ip, MAILBOX_PORT, timeout));
        trace.event("tcp_connect_succeeded", {{"server_ip", ip}});
        return true;
      } catch (const Error &error) {
        if (std::string(error.what()) == "Cancelado.")
          throw;
        connectionError = error.what();
        trace.event("tcp_connect_failed", {{"server_ip", ip},
                                            {"error", error.what()}});
        return false;
      }
    };
    if (!usingHotspot && haveConnection) {
      // Keep the familiar fast path, but let a changed PC address fall through
      // to discovery after a bounded attempt.
      title("Conectando ao PC salvo...");
      (void)tryConnect(1500);
    }
    if (!usingHotspot && !connection) {
      title("Procurando o PC na rede...");
      trace.phase("server_discovery");
      const std::string discovered = discoverPCServer(MAILBOX_PORT);
      trace.event("server_discovery_finished", {{"server_ip", discovered.empty() ? "not_found" : discovered}});
      if (!discovered.empty()) {
        ip = discovered;
        discoveredAddress = true;
        title("Conectando ao PC encontrado...");
        (void)tryConnect(3000);
      }
    }
    if (!usingHotspot && !connection) {
      ip = inputIP(settings, true, false,
                    discoveredAddress ? "PC sem resposta: informe IP"
                                      : "PC nao encontrado: informe IP");
      discoveredAddress = true;
      title("Conectando ao IP informado...");
      if (!tryConnect(3000))
        throw Error("Servidor Chest Link nao encontrado no IP informado. "
                    "Confira o IP e o Wi-Fi.");
    }
    if (usingHotspot && !connection) {
      title("Conectando ao servidor...");
      if (!tryConnect(3000))
        throw Error(connectionError);
    }
    if (!haveConnection) {
      trace.event("pin_prompt_started");
      pin = inputPIN(&settings);
      trace.event("pin_entered");
    }
    trace.phase("update_protocol");
    auto wire = connection->wire(UPDATE_WIRE_IDLE_TIMEOUT_MS,
                                 [&trace](bool writing, size_t bytes) {
                                   trace.wireActivity(writing, bytes);
                                 });
    auto accept = [&installPath, &trace, &ip
#ifndef CL_3DS
                   , &device
#endif
    ](uint32_t remote, uint32_t bytes, uint32_t local) {
      trace.enableRemote(ip, MAILBOX_PORT);
      trace.event("update_offer_received", {{"current_version", appVersionText(local)},
                                            {"offered_version", appVersionText(remote)},
                                            {"file_bytes", std::to_string(bytes)}});
#ifndef CL_3DS
      installPath = device;
      if (!installPath.empty() && installPath.back() != '/')
        installPath += '/';
      installPath += "ChestLink_DS_v" + appVersionText(remote) + ".nds";
#endif
      std::string details = "Versao instalada: " + appVersionText(local) +
                           "\nNova versao: " + appVersionText(remote) +
                           "\nTamanho: " + std::to_string(bytes / 1024) +
                           " KiB\n\nDestino: " + installPath +
                           "\n\nBaixar e instalar agora?";
      if (!confirm("Atualizacao disponivel", details)) {
        trace.event("update_offer_declined");
        return false;
      }
      trace.phase("download");
      trace.event("update_offer_accepted", {{"destination", installPath}});
      gui::notice("Baixando atualizacao",
                  "Aguardando o PC iniciar o envio...", "Aguarde nesta tela.",
                  0);
      return true;
    };
    auto uiProgress = progress("Baixando atualizacao");
    auto tracedProgress = [&trace, &uiProgress](uint32_t done, uint32_t total) {
      trace.downloadProgress(done, total);
      return uiProgress(done, total);
    };
#ifdef CL_3DS
    UpdateResult update = update3DS(wire, pin, APP_VERSION_CODE, installPath,
                                    accept, tracedProgress);
#else
    UpdateResult update = updateNDS(wire, pin, APP_VERSION_CODE, installPath,
                                    accept, tracedProgress);
#endif
    trace.event("update_result", {{"state", update.state == UpdateState::installed ? "installed" :
                                             update.state == UpdateState::cancelled ? "cancelled" : "current"},
                                   {"version", appVersionText(update.version)},
                                   {"file_bytes", std::to_string(update.bytes)}});
    // Persist a new address only after the PIN-authenticated update exchange has
    // completed, so a different Chest Link server on the LAN cannot replace it.
    if (discoveredAddress) {
      makeDirs(settingsRoot(settings));
      writeText(settingsRoot(settings) + "/server-ip.txt", ip);
    }
    if (update.state == UpdateState::current) {
      message("Chest Link ja esta atualizado.\nVersao no servidor: " +
              appVersionText(update.version) +
              (trace.path().empty() ? "" : "\n\nLog: " + trace.path()));
    } else if (update.state == UpdateState::installed) {
#ifdef CL_3DS
      message("Atualizacao " + appVersionText(update.version) +
              " instalada e conferida.\n\nSaia do Homebrew Launcher e abra "
              "o Chest Link novamente.\nA versao anterior foi preservada ao "
              "lado do app e sera removida depois que a nova versao iniciar." +
              (trace.path().empty() ? "" : "\n\nLog: " + trace.path()));
#else
      message("Atualizacao " + appVersionText(update.version) +
              " instalada e conferida.\n\nNova copia: " + installPath +
              "\nAbra esse arquivo pelo menu da flashcard/SD. Ao iniciar a nova "
              "versao, as copias antigas do Chest Link serao removidas." +
              (trace.path().empty() ? "" : "\n\nLog: " + trace.path()));
#endif
    }
  } catch (const std::exception &error) {
    trace.event("update_failed", {{"error", error.what()}});
    const std::string logLine = trace.path().empty()
                                    ? std::string()
                                    : "\n\nLog: " + trace.path();
    throw Error(std::string(error.what()) + logLine);
  }
}

void serviceIncoming() {
  // Startup/cleanup dialogs pump this function before the receiver is enabled.
  if (!directListener.enabled)
    return;
#if defined(CL_NDS) || defined(CL_3DS)
  // The receiver endpoint follows the live Wi-Fi/IP, not a startup snapshot.
  if (!handlingIncoming) {
    auto &listenerSchedule = directListener.schedule;
    const auto &status = platform::networkStatus();
    const bool changed = listenerSchedule.link(status);
    if (changed || !listenerSchedule.ready()) {
      Connection::close(directListener.server);
      directListener.server = -1;
      directListener.ip.clear();
    }
    if (!listenerSchedule.ready()) {
      directListener.status = status.connected ? "Aguardando IP da rede atual" :
#ifdef CL_3DS
                                                "Wi-Fi desconectado; veja definicoes do 3DS";
#else
                                                "Wi-Fi desconectado; Configurar Wi-Fi";
#endif
    } else {
      const uint64_t now = platform::milliseconds();
      if (directListener.server < 0 &&
          listenerSchedule.due(now)) {
        listenerSchedule.attempted(now);
        try {
          platform::network();
          directListener.server = Connection::listen();
          if (!directListener.pin) directListener.pin = platform::makePin();
        } catch (const std::exception &e) {
          Connection::close(directListener.server);
          directListener.server = -1;
          directListener.ip.clear();
          directListener.status = e.what();
        }
      }
      if (directListener.server >= 0) {
        directListener.ip = status.ip;
        char pinText[8];
        std::snprintf(pinText, sizeof(pinText), "%06u", unsigned(directListener.pin));
        directListener.status = "IP " + status.ip + " PIN " + pinText;
      }
    }
  }
#endif
  if (handlingIncoming || directListener.server < 0)
    return;
  auto conn = Connection::tryAccept(directListener.server);
  if (!conn)
    return;
  handlingIncoming = true;
  try {
    receiveConnection(*conn);
  } catch (const std::exception &e) {
    message(e.what());
  }
  handlingIncoming = false;
}

void startListener() {
  directListener.enabled = true;
  // Never overwrite an owned socket with a second bind to the same port.
  if (directListener.server >= 0)
    return;
  try {
    platform::network();
#if defined(CL_NDS) || defined(CL_3DS)
    directListener.schedule.link(platform::networkStatus());
    directListener.schedule.attempted(platform::milliseconds());
#endif
    directListener.server = Connection::listen();
    if (!directListener.pin)
      directListener.pin = platform::makePin();
    directListener.ip = platform::ip();
#if defined(CL_NDS) || defined(CL_3DS)
    // ip() refreshes the native snapshot; seed the retry state from it so the
    // first menu frame does not close the socket we have just opened.
    directListener.schedule.link(platform::networkStatus());
    directListener.schedule.attempted(platform::milliseconds());
#endif
    char pinText[8];
    std::snprintf(pinText, sizeof(pinText), "%06u", unsigned(directListener.pin));
    directListener.status = "IP " + directListener.ip + " PIN " + pinText;
  } catch (const std::exception &e) {
    Connection::close(directListener.server);
    directListener.server = -1;
    directListener.ip.clear();
#ifdef CL_NDS
    directListener.status = platform::networkStatus().ipv4Ready ? e.what() :
        std::string(e.what()).find("Rede salva") != std::string::npos
            ? "Rede salva indisponivel; Configurar Wi-Fi"
            : "Wi-Fi nao conectado; Configurar Wi-Fi";
#else
    directListener.status = e.what();
#endif
  }
}
void stopListener() {
  directListener.enabled = false;
  Connection::close(directListener.server);
  directListener.server = -1;
  directListener.pin = 0;
  directListener.schedule = {};
  directListener.ip.clear();
  directListener.status = "Escolha Configurar Wi-Fi";
}
} // namespace
int runApp() {
  try {
    platform::init();
#if defined(CL_NDS) || defined(CL_3DS)
    bool cleanupComplete = true;
    const unsigned oldApps =
        platform::removePreviousApplicationVersions(APP_VERSION_CODE,
                                                    cleanupComplete);
    if (oldApps || !cleanupComplete) {
      std::string status = "Versoes anteriores removidas: " +
                           std::to_string(oldApps) + ".";
      if (!cleanupComplete)
        status += " Algumas pastas nao puderam ser limpas.";
      message(status);
    }
#endif
    for (const auto &store : platform::stores())
      recover(store);
    startListener();
    while (platform::alive()) {
#ifdef CL_3DS
      int n = choose("Chest Link",
                     {"Atualizar pelo PC", "Consultar bancos",
                      "Ler saves Pokemon", "Creditos", "Sair"}, true);
      if (n < 0 || n == 4)
        break;
#elif defined(CL_NDS)
      int n = choose("Chest Link",
                     {"Configurar Wi-Fi", "Atualizar pelo PC", "Consultar bancos",
                      "Ler saves Pokemon", "Creditos", "Sair"}, true);
      if (n < 0 || n == 5)
        break;
#else
      int n = choose("Chest Link",
                     {"Consultar bancos", "Ler saves Pokemon", "Creditos", "Sair"}, true);
      if (n < 0 || n == 3)
        break;
#endif
      try {
#ifdef CL_3DS
        if (n == 0)
          updateApplication();
        else if (n == 1)
          consult();
        else if (n == 2)
          importGameSaves();
        else
          message(
              "Versao " + appVersionText(APP_VERSION_CODE) +
              "\nChest Link: app independente.\nVisual PKSM / "
              "FlagBrew.\nBernardo Giordano, Admiral Fish,\npiepie62 e "
              "colaboradores.\nLeitura PKX: PKSM-Core.\nSprites: PokeAPI; "
              "Pokemon pertence\na Nintendo, Creatures, GAME FREAK.\nGPL-3.0+: "
              "atribuicao/origem mantidas.\nFontes e licencas no pacote.");
#elif defined(CL_NDS)
        if (n == 0) {
          stopListener();
          std::string ssid;
          try {
            ssid = platform::configureNetwork();
          } catch (...) {
            startListener();
            throw;
          }
          startListener();
          if (!ssid.empty()) {
            message("Conectado a " + ssid + "\nIP do DS: " + platform::ip() +
                    "\nA recepção direta fica ativa enquanto estiver nesta rede.");
          }
        } else if (n == 1)
          updateApplication();
        else if (n == 2)
          consult();
        else if (n == 3)
          importGameSaves();
        else
          message(
              "Versao " + appVersionText(APP_VERSION_CODE) +
              "\nChest Link: app independente.\nVisual PKSM / "
              "FlagBrew.\nBernardo Giordano, Admiral Fish,\npiepie62 e "
              "colaboradores.\nLeitura PKX: PKSM-Core.\nSprites: PokeAPI; "
              "Pokemon pertence\na Nintendo, Creatures, GAME FREAK. GPL-3.0+: "
              "atribuicao/origem mantidas. Fontes e licencas no pacote.");
#else
        if (n == 0)
          consult();
        else if (n == 1)
          importGameSaves();
        else
          message(
              "Chest Link: app independente.\nVisual PKSM / "
              "FlagBrew.\nBernardo Giordano, Admiral Fish,\npiepie62 e "
              "colaboradores.\nLeitura PKX: PKSM-Core.\nSprites: PokeAPI; "
              "Pokemon pertence\na Nintendo, Creatures, GAME FREAK.\nGPL-3.0+: "
              "atribuicao/origem mantidas.\nFontes e licencas no pacote.");
#endif
      } catch (const std::exception &e) {
        message(e.what());
      }
    }
    stopListener();
    platform::shutdown();
    return 0;
  } catch (const std::exception &e) {
    stopListener();
    message(e.what());
    platform::shutdown();
    return 1;
  }
}
