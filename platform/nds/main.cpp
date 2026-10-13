#include "graphics.hpp"
#include "nds_update_cleanup.hpp"
#include "platform.hpp"
extern "C" {
#include <arpa/inet.h>
}
#include <algorithm>
#include <cerrno>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <dirent.h>
#include <dswifi9.h>
#include <fat.h>
#include <nds.h>
#include <nds/arm9/console.h>
#include <nds/arm9/keyboard.h>
#include <nds/system_counter.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/ioctl.h>
#include <string>
#include <vector>

namespace platform {
static unsigned pressed = 0;
static bool running = true, wifi = false;
static uint16_t *topBuffer = nullptr, *bottomBuffer = nullptr;
static Touch lastTouch;
static std::string launchPath, appDirectory;
static bool nativeKeyboard = false;
static chestlink::NetworkStatus networkState;
static chestlink::InternetProbeSchedule internetSchedule;
static int internetSocket = -1;

namespace {
constexpr unsigned MAX_CLEANUP_DEPTH = 16;
constexpr unsigned MAX_CLEANUP_DIRECTORIES = 4096;

void closeInternetProbe() {
  if (internetSocket >= 0) closesocket(internetSocket);
  internetSocket = -1;
}

std::string ipv4Text(uint32_t value) {
  in_addr addr{};
  addr.s_addr = value;
  char text[INET_ADDRSTRLEN]{};
  return inet_ntop(AF_INET, &addr, text, sizeof(text)) ? text : "0.0.0.0";
}

void pollInternetProbe(uint64_t now) {
  if (internetSchedule.due(now)) {
    internetSchedule.begin(now);
    internetSocket = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    int nonblocking = 1;
    if (internetSocket < 0 || ioctl(internetSocket, FIONBIO, &nonblocking) < 0) {
      closeInternetProbe(); internetSchedule.finish(false, now); return;
    }
    // Read-only reachability check to Cloudflare's public HTTPS resolver.
    // No DNS lookup, TLS request, credentials or Pokemon data are sent.
    sockaddr_in peer{};
    peer.sin_len = sizeof(peer);
    peer.sin_family = AF_INET;
    peer.sin_port = htons(443);
    peer.sin_addr.s_addr = inet_addr("1.1.1.1");
    const int result = ::connect(internetSocket,
        reinterpret_cast<sockaddr *>(&peer), sizeof(peer));
    if (!result) {
      closeInternetProbe(); internetSchedule.finish(true, now); return;
    }
    if (errno != EINPROGRESS && errno != EWOULDBLOCK && errno != EAGAIN) {
      closeInternetProbe(); internetSchedule.finish(false, now); return;
    }
  }
  if (!internetSchedule.pending() || internetSocket < 0) return;
  if (internetSchedule.expired(now)) {
    closeInternetProbe(); internetSchedule.finish(false, now); return;
  }
  fd_set writable, errors;
  FD_ZERO(&writable); FD_ZERO(&errors);
  FD_SET(internetSocket, &writable); FD_SET(internetSocket, &errors);
  timeval immediate{0, 0};
  const int result = select(internetSocket + 1, nullptr, &writable, &errors, &immediate);
  if (result < 0 && errno == EINTR) return;
  if (!result) return;
  int error = 0;
  socklen_t length = sizeof(error);
  const bool success = result > 0 &&
      !getsockopt(internetSocket, SOL_SOCKET, SO_ERROR, &error, &length) && !error;
  closeInternetProbe(); internetSchedule.finish(success, now);
}

void refreshNetworkStatus(bool force = false) {
  static bool sampled = false;
  static uint64_t lastSample = 0;
  const uint64_t now = milliseconds();
  if (force || !sampled || now - lastSample >= 1000) {
    sampled = true; lastSample = now;
    networkState.visible = true;
    networkState.connected = networkState.connecting = networkState.ipv4Ready = false;
    networkState.ssid.clear(); networkState.ip.clear();
    if (wifi) {
      const int status = Wifi_AssocStatus();
      Wifi_AccessPoint actual{};
      if (Wifi_GetCurrentAP(&actual)) {
        networkState.ssid.assign(actual.ssid, actual.ssid_len);
        networkState.connected = status == ASSOCSTATUS_ASSOCIATED ||
                                 status == ASSOCSTATUS_ACQUIRINGDHCP;
        networkState.connecting = !networkState.connected;
      }
      networkState.ipv4Ready = networkState.connected && Wifi_IsIPReady();
      if (networkState.ipv4Ready) networkState.ip = ipv4Text(Wifi_GetIP());
    }
    if (internetSchedule.link(networkState.ssid, networkState.ip, networkState.ipv4Ready))
      closeInternetProbe();
  }
  pollInternetProbe(now);
  networkState.internet = internetSchedule.result();
  gui::setNetworkStatus(networkState);
}

bool isStoragePath(const std::string &path) {
  return path.compare(0, 5, "fat:/") == 0 ||
         path.compare(0, 4, "sd:/") == 0;
}

std::string directoryOf(const std::string &path) {
  const size_t slash = path.find_last_of('/');
  return slash == std::string::npos ? std::string() : path.substr(0, slash + 1);
}

std::string joinPath(const std::string &directory, const std::string &name) {
  if (directory.empty() || directory.back() == '/')
    return directory + name;
  return directory + "/" + name;
}

struct CleanupState {
  uint32_t currentVersion;
  const std::string &currentPath;
  unsigned removed = 0;
  unsigned directories = 0;
  bool complete = true;
};

void cleanAppVersions(const std::string &directory, unsigned depth,
                      CleanupState &state) {
  if (depth > MAX_CLEANUP_DEPTH ||
      state.directories >= MAX_CLEANUP_DIRECTORIES) {
    state.complete = false;
    return;
  }
  DIR *handle = opendir(directory.c_str());
  if (!handle) {
    state.complete = false;
    return;
  }
  ++state.directories;

  while (dirent *entry = readdir(handle)) {
    const char *name = entry->d_name;
    if (std::strcmp(name, ".") == 0 || std::strcmp(name, "..") == 0)
      continue;
    const std::string path = joinPath(directory, name);
    struct stat info {};
    if (stat(path.c_str(), &info)) {
      state.complete = false;
      continue;
    }
    if (S_ISDIR(info.st_mode)) {
      cleanAppVersions(path, depth + 1, state);
      continue;
    }
    if (!S_ISREG(info.st_mode))
      continue;

    if (!chestlink::ndsupdate::shouldRemove(path, name, state.currentPath,
                                            state.currentVersion))
      continue;
    if (std::remove(path.c_str()) == 0)
      ++state.removed;
    else
      state.complete = false;
  }
  closedir(handle);
}

std::string cleanupMarkerPath() {
  return appDirectory.empty()
             ? std::string()
             : joinPath(appDirectory, ".chest-link-cleanup-version");
}

std::string wifiPreferencePath() {
  if (chestlink::exists("sd:/"))
    return "sd:/_nds/chest-link/wifi-ssid.txt";
  if (chestlink::exists("fat:/"))
    return "fat:/_nds/chest-link/wifi-ssid.txt";
  throw chestlink::Error("Cartao SD/flashcard nao encontrado.");
}

std::string preferredSsid() {
  try {
    const std::string path = wifiPreferencePath();
    const std::string backup = path + ".previous";
    const std::string selected = chestlink::exists(path)
                                     ? path
                                     : (chestlink::exists(backup) ? backup : "");
    if (selected.empty())
      return {};
    const std::string ssid = chestlink::readText(selected, 32);
    return ssid.size() <= 32 && ssid.find('\0') == std::string::npos ? ssid
                                                                     : "";
  } catch (const chestlink::Error &) {
    return {};
  }
}

bool askWpa2Password(std::string &result,
                     const char *promptTitle = "Rede WPA2") {
  gui::notice(promptTitle, "Digite a senha no teclado da tela inferior.",
              "A senha nao sera salva no cartao SD.", 0);
  nativeKeyboard = true;
  videoSetModeSub(MODE_0_2D | DISPLAY_BG0_ACTIVE | DISPLAY_BG3_ACTIVE);
  consoleDemoInit();
  consolePrintString("Chest Link - WPA2\n");
  keyboardDemoInit();
  keyboardShow();

  char password[64] = {};
  size_t length = 0;
  bool cancelled = false;
  std::string feedback;
  auto redraw = [&]() {
    consoleClear();
    consolePrintString("Chest Link - WPA2\nSenha: 8 a 63 caracteres\n");
    consolePrintString("A: confirmar   B: voltar a lista\n");
    consolePrintString("Toque nas teclas; ENTER tambem confirma.\nSenha: ");
    for (size_t i = 0; i < length; ++i)
      consolePrintChar('*');
    consolePrintString("\nCaracteres: ");
    const std::string count = std::to_string(length);
    consolePrintString(count.c_str());
    consolePrintString("/63");
    if (!feedback.empty()) {
      consolePrintString("\n");
      consolePrintString(feedback.c_str());
    }
  };
  redraw();

  for (;;) {
    frame();
    const unsigned buttons = keysDown();
    if (buttons & KEY_B) {
      cancelled = true;
      break;
    }

    const int key = keyboardUpdate();
    if ((buttons & KEY_A) || key == DVK_ENTER) {
      if (length < 8) {
        feedback = "Senha curta: digite ao menos 8 caracteres.";
        redraw();
        continue;
      }
      result.assign(password, length);
      break;
    }
    if (key == DVK_BACKSPACE) {
      if (length) {
        password[--length] = '\0';
        feedback.clear();
        redraw();
      }
    } else if (key >= 32 && key <= 126 && length < sizeof(password) - 1) {
      password[length++] = static_cast<char>(key);
      feedback.clear();
      redraw();
    }
  }

  keyboardHide();
  keyboardExit();

  videoSetModeSub(MODE_5_2D | DISPLAY_BG3_ACTIVE);
  bottomBuffer =
      bgGetGfxPtr(bgInitSub(3, BgType_Bmp16, BgSize_B16_256x256, 0, 0));
  nativeKeyboard = false;

  if (cancelled) {
    std::memset(password, 0, sizeof(password));
    result.clear();
    return false;
  }
  std::memset(password, 0, sizeof(password));
  return true;
}

void savePreferredSsid(const std::string &ssid) {
  const std::string path = wifiPreferencePath();
  chestlink::makeDirs(path.substr(0, path.find_last_of('/')));
  const std::string temporary = path + ".new";
  const std::string backup = path + ".previous";

  if (chestlink::exists(temporary) && std::remove(temporary.c_str()))
    throw chestlink::Error("Nao foi possivel limpar a configuracao temporaria do Wi-Fi.");
  if (chestlink::exists(backup)) {
    if (chestlink::exists(path)) {
      if (std::remove(backup.c_str()))
        throw chestlink::Error("Nao foi possivel limpar o backup da rede Wi-Fi.");
    } else if (std::rename(backup.c_str(), path.c_str())) {
      throw chestlink::Error("Nao foi possivel recuperar a rede Wi-Fi anterior.");
    }
  }

  try {
    chestlink::writeText(temporary, ssid);
  } catch (...) {
    std::remove(temporary.c_str());
    throw;
  }

  const bool hadPrevious = chestlink::exists(path);
  if (hadPrevious && std::rename(path.c_str(), backup.c_str())) {
    std::remove(temporary.c_str());
    throw chestlink::Error("Nao foi possivel preservar a rede Wi-Fi anterior.");
  }
  if (std::rename(temporary.c_str(), path.c_str())) {
    const bool restored = !hadPrevious || !std::rename(backup.c_str(), path.c_str());
    std::remove(temporary.c_str());
    throw chestlink::Error(restored
                               ? "Nao foi possivel salvar a nova rede Wi-Fi; a configuracao anterior foi mantida."
                               : "Falha ao salvar a rede e recuperar o arquivo anterior. O backup permanece no cartao.");
  }
  // The new preference is already committed. A stale backup is harmless and
  // is ignored while the primary file exists; remove it when possible.
  if (hadPrevious)
    std::remove(backup.c_str());
}

void initializeWifi() {
  if (wifi)
    return;
  if (!Wifi_InitDefault(INIT_ONLY | WIFI_ATTEMPT_DSI_MODE))
    throw chestlink::Error("Não foi possível iniciar o Wi-Fi do console.");
  wifi = true;
}

std::vector<Wifi_AccessPoint>
scanAccessPoints(bool cancellable, const std::string &onlySsid = {},
                 bool restoring = false) {
  if (Wifi_AssocStatus() == ASSOCSTATUS_ASSOCIATED)
    Wifi_DisconnectAP();
  Wifi_ScanMode();
  gui::notice(restoring ? "Restaurando rede anterior" : "Buscando redes Wi-Fi",
              restoring ? "Procurando " + onlySsid + "..."
                        : "Aguarde enquanto o DS procura pontos de acesso.",
              cancellable ? "B: cancelar" : "A/B: aguarde", 0);
  // Bound this UI wait by VBlank frames independently of the system timer.
  constexpr unsigned scanFrameLimit = 8 * 60;
  for (unsigned elapsedFrames = 0; elapsedFrames < scanFrameLimit;
       ++elapsedFrames) {
    frame();
    if (cancellable && (keys() & B))
      return {};
    if (elapsedFrames && elapsedFrames % 60 == 0) {
      const unsigned secondsLeft = 8 - elapsedFrames / 60;
      gui::notice(restoring ? "Restaurando rede anterior"
                            : "Buscando redes Wi-Fi",
                  restoring ? "Procurando " + onlySsid + "... " +
                                  std::to_string(secondsLeft) + " s"
                            : "Busca em andamento: " +
                                  std::to_string(secondsLeft) + " s",
                  cancellable ? "B: cancelar" : "A/B: aguarde", 0);
    }
  }

  std::vector<Wifi_AccessPoint> accessPoints;
  const int count = std::max(0, Wifi_GetNumAP());
  for (int i = 0; i < count; ++i) {
    Wifi_AccessPoint accessPoint{};
    Wifi_GetAPData(i, &accessPoint);
    if (!(accessPoint.flags & WFLAG_APDATA_COMPATIBLE) ||
        !accessPoint.ssid[0])
      continue;
    if (!onlySsid.empty() && onlySsid != accessPoint.ssid)
      continue;
    const bool open = accessPoint.security_type == AP_SECURITY_OPEN;
    const bool supportedWpa2 = accessPoint.security_type == AP_SECURITY_WPA2;
    const bool saved = accessPoint.flags & WFLAG_APDATA_CONFIG_IN_WFC;
    // WPA2-Personal/CCMP is handled by the software supplicant. WEP still
    // needs a compatible credential already stored in the console firmware.
    if (!open && !supportedWpa2 && !saved)
      continue;

    // Mesh nodes and repeaters may advertise the same SSID on different
    // channels. Keep one menu row per name and use the strongest compatible
    // access point; a higher RSSI is stronger in both DS and DSi mode.
    auto sameNetwork = std::find_if(
        accessPoints.begin(), accessPoints.end(), [&](const auto &candidate) {
          return std::strcmp(candidate.ssid, accessPoint.ssid) == 0;
        });
    if (sameNetwork == accessPoints.end())
      accessPoints.push_back(accessPoint);
    else if (accessPoint.rssi > sameNetwork->rssi)
      *sameNetwork = accessPoint;
  }
  return accessPoints;
}

std::string accessPointLabel(const Wifi_AccessPoint &accessPoint) {
  std::string label = chestlink::safeDisplay(accessPoint.ssid, 24);
  label += " - ch " + std::to_string(accessPoint.channel);
  if (accessPoint.security_type == AP_SECURITY_OPEN)
    label += " - aberta";
  else if (accessPoint.security_type == AP_SECURITY_WPA2)
    label += " - WPA2";
  else
    label += " - salva";
  return label;
}

int chooseAccessPoint(const std::vector<Wifi_AccessPoint> &accessPoints) {
  std::vector<std::string> labels;
  labels.reserve(accessPoints.size());
  for (const auto &accessPoint : accessPoints)
    labels.push_back(accessPointLabel(accessPoint));

  unsigned cursor = 0;
  for (;;) {
    gui::menu("Configurar Wi-Fi", labels, cursor,
              "A: conectar   B: voltar");
    frame();
    const unsigned pressed = keys();
    if (pressed & TOUCH) {
      const Touch touch = platform::touch();
      const int hit = gui::menuHit(touch.x, touch.y, cursor, labels.size());
      if (hit >= 0)
        return hit;
    }
    if (pressed & B)
      return -1;
    if (pressed & UP)
      cursor = (cursor + labels.size() - 1) % labels.size();
    if (pressed & DOWN)
      cursor = (cursor + 1) % labels.size();
    if (pressed & L)
      cursor = cursor >= 8 ? cursor - 8 : 0;
    if (pressed & R)
      cursor = std::min<unsigned>(cursor + 8, labels.size() - 1);
    if (pressed & A)
      return cursor;
  }
}

bool connectAccessPoint(Wifi_AccessPoint &accessPoint, bool cancellable,
                        const std::string &password = {},
                        unsigned timeoutMs = 45000,
                        const char *statusTitle = "Conectando ao Wi-Fi") {
  const bool chestLinkHotspot =
      std::strcmp(accessPoint.ssid, "ChestLink-DS") == 0;
  if (chestLinkHotspot) {
    // The host's DHCP server sends an offer, but this DS does not complete the
    // request/ack exchange. The dedicated hotspot uses a stable /24, so give
    // this console an address outside NetworkManager's .10-.254 DHCP pool.
    // lwIP expects network-order IPv4 values. Bare hexadecimal literals on
    // the little-endian DS reverse all four octets, including the netmask.
    const uint32_t consoleIP = inet_addr("10.231.42.2");
    const uint32_t serverIP = inet_addr("10.231.42.1");
    const uint32_t netmask = inet_addr("255.255.255.0");
    Wifi_SetIP(consoleIP, serverIP, netmask, serverIP, 0);
  } else {
    Wifi_SetIP(0, 0, 0, 0, 0); // obtain the address from the AP's DHCP
  }
  int result = 0;
  // An open AP must use its actual advertised settings. A stale WFC entry
  // with the same SSID can contain obsolete WEP/static-IP data, so do not let
  // it override the open network selected by the user.
  if (accessPoint.security_type == AP_SECURITY_OPEN)
    result = Wifi_ConnectSecureAP(&accessPoint, nullptr, 0);
  else if (accessPoint.security_type == AP_SECURITY_WPA2)
    result = Wifi_ConnectSecureAP(&accessPoint, password.data(), password.size());
  else if (accessPoint.flags & WFLAG_APDATA_CONFIG_IN_WFC)
    result = Wifi_ConnectWfcAP(&accessPoint);
  else
    result = Wifi_ConnectSecureAP(&accessPoint, nullptr, 0);
  if (result < 0)
    throw chestlink::Error("O console não conseguiu iniciar a conexão Wi-Fi.");

  const unsigned totalSeconds = (timeoutMs + 999) / 1000;
  const bool ntrDiagnostics = accessPoint.security_type == AP_SECURITY_WPA2 && !isDSiMode();
  auto receptionDetails = [&]() {
    if (!ntrDiagnostics) return std::string();
    return std::string("\nRX cifrados: ") + std::to_string(Wifi_GetStats(WSTAT_NTR_CCMP_RX)) +
           "\nValidos: " + std::to_string(Wifi_GetStats(WSTAT_NTR_CCMP_VALID)) +
           "  MIC rejeitado: " + std::to_string(Wifi_GetStats(WSTAT_NTR_CCMP_MIC_FAILED)) +
           "\nRAM: " + std::to_string(Wifi_GetStats(WSTAT_NTR_RX_RAM_CANDIDATES)) +
           " Radio: " + std::to_string(Wifi_GetStats(WSTAT_NTR_RX_RADIO_REJECTED)) +
           " FCS: " + std::to_string(Wifi_GetStats(WSTAT_NTR_RX_FCS_BOUNDARY)) +
           "\nBytes: " + std::to_string(Wifi_GetStats(WSTAT_NTR_RX_REPORTED_SIZE)) +
           "/" + std::to_string(Wifi_GetStats(WSTAT_NTR_RX_FRAME_SIZE));
  };
  auto connectionBody = [&](int status, unsigned secondsLeft) {
    const char *phase = "Iniciando conexão Wi-Fi...";
    switch (status) {
    case ASSOCSTATUS_SEARCHING:
      phase = "Localizando a rede escolhida...";
      break;
    case ASSOCSTATUS_AUTHENTICATING:
    case ASSOCSTATUS_ASSOCIATING:
      phase = "Autenticando no Wi-Fi...";
      break;
    case ASSOCSTATUS_ACQUIRINGDHCP:
      phase = "Wi-Fi autenticado. Obtendo endereço IP...";
      break;
    case ASSOCSTATUS_ASSOCIATED:
      phase = "Wi-Fi conectado. Validando endereço IP...";
      break;
    case ASSOCSTATUS_CANNOTCONNECT:
      phase = "A conexão Wi-Fi falhou.";
      break;
    }
    return std::string(accessPoint.ssid) + "\n" + phase + "\nRestam " +
           std::to_string(secondsLeft) + " s" + receptionDetails();
  };
  gui::notice(statusTitle,
              connectionBody(ASSOCSTATUS_SEARCHING, totalSeconds),
              cancellable ? "B: cancelar" : "A/B: aguarde", 0);
  const unsigned timeoutFrames =
      std::max(1u, (timeoutMs * 60u + 999u) / 1000u);
  const unsigned failFastFrames = 2 * 60;
  unsigned lastShownSecond = 0;
  int lastShownStatus = ASSOCSTATUS_SEARCHING;
  int finalStatus = ASSOCSTATUS_SEARCHING;
  for (unsigned elapsedFrames = 0; elapsedFrames < timeoutFrames;
       ++elapsedFrames) {
    frame();
    if (cancellable && (keys() & B)) {
      Wifi_DisconnectAP();
      return false;
    }
    finalStatus = Wifi_AssocStatus();
    const uint32_t currentIP = Wifi_GetIP();
    if (finalStatus == ASSOCSTATUS_ASSOCIATED && Wifi_IsIPReady() && currentIP != 0 &&
        currentIP != 0xffffffffu) {
      refreshNetworkStatus(true);
      return true;
    }
    const unsigned elapsedSeconds = elapsedFrames / 60;
    if (elapsedSeconds != lastShownSecond || finalStatus != lastShownStatus) {
      lastShownSecond = elapsedSeconds;
      lastShownStatus = finalStatus;
      const unsigned secondsLeft = totalSeconds > elapsedSeconds
                                       ? totalSeconds - elapsedSeconds
                                       : 0;
      gui::notice(statusTitle, connectionBody(finalStatus, secondsLeft),
                  cancellable ? "B: cancelar" : "A/B: aguarde", 0);
    }
    if (finalStatus == ASSOCSTATUS_CANNOTCONNECT &&
        elapsedFrames > failFastFrames)
      break;
  }
  const uint32_t finalIP = Wifi_GetIP();
  // Keep the candidate's counters before disconnect/rollback changes radios.
  const std::string finalReceptionDetails = receptionDetails();
  Wifi_DisconnectAP();
  if (finalStatus == ASSOCSTATUS_CANNOTCONNECT)
    throw chestlink::Error(
        "A conexão Wi-Fi com " + std::string(accessPoint.ssid) + " foi recusada.");
  if (finalStatus == ASSOCSTATUS_SEARCHING)
    throw chestlink::Error(
        "O DS não localizou " + std::string(accessPoint.ssid) +
        " durante a tentativa de conexão.");
  if (finalStatus == ASSOCSTATUS_ACQUIRINGDHCP ||
      (finalStatus == ASSOCSTATUS_ASSOCIATED &&
       (!finalIP || finalIP == 0xffffffffu)))
    throw chestlink::Error(
        "O Wi-Fi autenticou em " + std::string(accessPoint.ssid) +
        ", mas não obteve um endereço IPv4 por DHCP." + finalReceptionDetails);
  throw chestlink::Error(
      "A autenticação Wi-Fi com " + std::string(accessPoint.ssid) +
      " não terminou no tempo limite. O pedido de IP ainda não foi iniciado.");
}

bool reconnectSavedNetwork(const std::string &ssid, std::string &failure) {
  if (ssid.empty())
    return false;
  try {
    auto accessPoints = scanAccessPoints(true, ssid, true);
    if (accessPoints.empty())
      throw chestlink::Error((keys() & B)
                                 ? "Busca da rede anterior cancelada."
                                 : "A rede salva nao foi encontrada na busca.");

    std::string password;
    try {
      if (accessPoints.front().security_type == AP_SECURITY_WPA2 &&
          !askWpa2Password(password, "Senha da rede anterior"))
        throw chestlink::Error("Entrada da senha da rede salva cancelada.");
      const bool connected = connectAccessPoint(
          accessPoints.front(), true, password, 20000,
          "Restaurando rede anterior");
      std::fill(password.begin(), password.end(), '\0');
      if (!connected)
        throw chestlink::Error("Restauracao da rede anterior cancelada.");
    } catch (...) {
      std::fill(password.begin(), password.end(), '\0');
      throw;
    }
    return true;
  } catch (const std::exception &e) {
    failure = e.what();
    return false;
  }
}

} // namespace

void init() {
  videoSetMode(MODE_5_2D | DISPLAY_BG3_ACTIVE);
  videoSetModeSub(MODE_5_2D | DISPLAY_BG3_ACTIVE);
  vramSetBankA(VRAM_A_MAIN_BG);
  vramSetBankC(VRAM_C_SUB_BG);
  topBuffer = bgGetGfxPtr(bgInit(3, BgType_Bmp16, BgSize_B16_256x256, 0, 0));
  bottomBuffer =
      bgGetGfxPtr(bgInitSub(3, BgType_Bmp16, BgSize_B16_256x256, 0, 0));
  lcdMainOnTop();
  keysSetRepeat(20, 5);
  systemCounterSetup();
  if (!fatInitDefault())
    throw chestlink::Error("SD/flashcard nao encontrado.");

  appDirectory.clear();
  if (isStoragePath(launchPath) && launchPath.size() > 5 &&
      launchPath.compare(launchPath.size() - 4, 4, ".nds") == 0 &&
      chestlink::exists(launchPath))
    appDirectory = directoryOf(launchPath);
  else
    launchPath.clear();
  if (appDirectory.empty()) {
    char *defaultCwd = fatGetDefaultCwd();
    if (defaultCwd) {
      appDirectory = defaultCwd;
      std::free(defaultCwd);
    }
  }
  networkState.visible = true;
  gui::setNetworkStatus(networkState);
}

void setLaunchPath(const char *path) { launchPath = path ? path : ""; }

std::string runningApplicationDirectory() { return appDirectory; }

unsigned removePreviousApplicationVersions(uint32_t currentVersion,
                                            bool &complete) {
  complete = true;
  const std::string marker = cleanupMarkerPath();
  if (!marker.empty() && chestlink::exists(marker)) {
    try {
      const std::string saved = chestlink::readText(marker, 16);
      const unsigned long previous = std::strtoul(saved.c_str(), nullptr, 10);
      if (previous == currentVersion || previous > currentVersion)
        return 0;
    } catch (...) {
      // A damaged marker triggers another cleanup attempt.
    }
  }

  std::string currentPath = launchPath;
  if (currentPath.empty() && !appDirectory.empty()) {
    const std::string versioned =
        "ChestLink_DS_v" +
        std::to_string((currentVersion >> 16) & 0xff) + "." +
        std::to_string((currentVersion >> 8) & 0xff) + "." +
        std::to_string(currentVersion & 0xff) + ".nds";
    const std::string candidate = joinPath(appDirectory, versioned);
    if (chestlink::exists(candidate))
      currentPath = candidate;
    else {
      const std::string legacy =
          joinPath(appDirectory, "ChestLink_DS.nds");
      if (chestlink::exists(legacy))
        currentPath = legacy;
    }
  }

  CleanupState state{currentVersion, currentPath};
  for (const char *root : {"fat:/", "sd:/"}) {
    if (chestlink::exists(root))
      cleanAppVersions(root, 0, state);
  }
  complete = state.complete;
  if (complete && !marker.empty()) {
    try {
      chestlink::writeText(marker, std::to_string(currentVersion));
    } catch (...) {
      complete = false;
    }
  }
  return state.removed;
}
void shutdown() {
  closeInternetProbe();
  if (wifi)
    Wifi_Deinit();
}
bool alive() { return running; }
void frame() {
  // DSWiFi runs its lwIP work in a cooperative thread. Non-blocking socket
  // loops must yield to that thread; merely waiting for VBlank starves it.
  if (wifi)
    cothread_yield_irq(IRQ_VBLANK);
  else
    swiWaitForVBlank();
  scanKeys();
  unsigned k = keysDownRepeat();
  pressed = 0;
  const unsigned from[] = {KEY_UP, KEY_DOWN, KEY_LEFT,  KEY_RIGHT,
                           KEY_A,  KEY_B,    KEY_X,     KEY_Y,
                           KEY_L,  KEY_R,    KEY_START, KEY_SELECT};
  for (unsigned i = 0; i < 12; ++i)
    if (k & from[i])
      pressed |= 1u << i;
  lastTouch.down = (keysHeld() & KEY_TOUCH) != 0;
  if (lastTouch.down) {
    touchPosition pos;
    touchRead(&pos);
    lastTouch.x = pos.px * 320 / 256;
    lastTouch.y = pos.py * 240 / 192;
  }
  if (keysDown() & KEY_TOUCH)
    pressed |= TOUCH;
  refreshNetworkStatus();
}
unsigned keys() { return pressed; }
void clear() {}
Touch touch() { return lastTouch; }
void present(const uint16_t *top, unsigned width, const uint16_t *bottom) {
  if (!topBuffer || !bottomBuffer)
    return;
  for (unsigned y = 0; y < 192; ++y)
    for (unsigned x = 0; x < 256; ++x) {
      topBuffer[y * 256 + x] = top[(y * 240 / 192) * width + x * width / 256];
      if (!nativeKeyboard)
        bottomBuffer[y * 256 + x] = bottom[(y * 240 / 192) * 320 + x * 320 / 256];
    }
}
uint64_t milliseconds() {
  return systemCounterGetTicks() * 1000 / (BUS_CLOCK / 64);
}
bool pollNetwork() {
  frame();
  return !(pressed & B);
}
uint32_t makePin() {
  return uint32_t((systemCounterGetTicks() ^ (uint64_t(time(nullptr)) << 13)) %
                  900000) +
         100000;
}
unsigned maxChestBoxes() { return isDSiMode() ? 500 : 50; }
std::vector<chestlink::Store> stores() {
  std::vector<chestlink::Store> out;
  for (const auto &root : {"sd:/_nds/pkmn-chest", "fat:/_nds/pkmn-chest"})
    if (chestlink::exists(root))
      out.push_back(
          {root[0] == 's' ? "Chest (SD interno)" : "Chest (flashcard)",
           root,
           root[0] == 's' && isDSiMode() ? 500u : 50u,
           chestlink::CHEST_GENS,
           {}});
  if (out.empty()) {
    if (chestlink::exists("sd:/"))
      out.push_back({"Chest (SD interno)",
                     "sd:/_nds/pkmn-chest",
                     isDSiMode() ? 500u : 50u,
                     chestlink::CHEST_GENS,
                     {}});
    else if (chestlink::exists("fat:/"))
      out.push_back({"Chest (flashcard)",
                     "fat:/_nds/pkmn-chest",
                     50,
                     chestlink::CHEST_GENS,
                     {}});
    else
      out.push_back(
          {"Pokemon Chest", "/_nds/pkmn-chest", 50, chestlink::CHEST_GENS, {}});
  }
  return out;
}
void network() {
  if (wifi && Wifi_AssocStatus() == ASSOCSTATUS_ASSOCIATED && Wifi_IsIPReady()) {
    const uint32_t currentIP = Wifi_GetIP();
    if (currentIP != 0 && currentIP != 0xffffffffu) {
      refreshNetworkStatus(true);
      return;
    }
  }
  const std::string ssid = preferredSsid();
  if (ssid.empty())
    throw chestlink::Error("Escolhe Configurar Wi-Fi no menu para conectar.");
  initializeWifi();
  auto accessPoints = scanAccessPoints(false, ssid);
  if (accessPoints.empty())
    throw chestlink::Error(
        "Rede salva indisponivel. Usa Configurar Wi-Fi para trocar.");
  std::string password;
  if (accessPoints.front().security_type == AP_SECURITY_WPA2 &&
      !askWpa2Password(password))
    throw chestlink::Error("Conexao com a rede salva cancelada.");
  bool connected = false;
  try {
    connected = connectAccessPoint(accessPoints.front(), false, password);
  } catch (...) {
    std::fill(password.begin(), password.end(), '\0');
    throw;
  }
  std::fill(password.begin(), password.end(), '\0');
  if (!connected)
    throw chestlink::Error("Nao foi possivel conectar a rede salva.");
}
std::string configureNetwork() {
  initializeWifi();
  const std::string previousSsid = preferredSsid();
  std::string selectedSsid;
  std::string failure;
  bool cancelled = false;

  try {
    auto accessPoints = scanAccessPoints(true);
    if (accessPoints.empty()) {
      if (keys() & B)
        cancelled = true;
      else
        throw chestlink::Error(
            "Nenhuma rede compativel encontrada. Inicia ChestLink-DS no PC e tenta novamente.");
    }

    while (!cancelled && selectedSsid.empty()) {
      const int selected = chooseAccessPoint(accessPoints);
      if (selected < 0) {
        cancelled = true;
        continue;
      }

      Wifi_AccessPoint accessPoint = accessPoints[selected];
      const std::string candidateSsid = accessPoint.ssid;
      std::string password;
      if (accessPoint.security_type == AP_SECURITY_WPA2 &&
          !askWpa2Password(password))
        continue;

      bool connected = false;
      try {
        connected = connectAccessPoint(accessPoint, true, password, 25000);
      } catch (...) {
        std::fill(password.begin(), password.end(), '\0');
        throw;
      }
      std::fill(password.begin(), password.end(), '\0');
      if (!connected)
        continue; // B during connection returns to the access point list.

      // Association plus a usable IP (DHCP for ordinary APs, the configured
      // static address for ChestLink-DS) is the commit point. Until it
      // succeeds, the old preference remains untouched.
      savePreferredSsid(candidateSsid);
      selectedSsid = candidateSsid;
    }
  } catch (const std::exception &e) {
    failure = e.what();
  }

  if (cancelled) {
    if (previousSsid.empty())
      return {};
    std::string restoreFailure;
    if (reconnectSavedNetwork(previousSsid, restoreFailure))
      return previousSsid;
    throw chestlink::Error(
        "Configuracao cancelada, mas nao foi possivel reconectar a rede anterior (" +
        previousSsid + "): " + restoreFailure +
        ". A rede anterior continua salva no cartao.");
  }

  if (!failure.empty()) {
    if (previousSsid.empty())
      throw chestlink::Error(
          failure +
          "\nNao havia uma rede anterior salva; a nova rede nao foi confirmada.");
    std::string restoreFailure;
    if (reconnectSavedNetwork(previousSsid, restoreFailure))
      throw chestlink::Error(failure + "\nA rede anterior (" + previousSsid +
                             ") foi restaurada; a nova nao foi salva.");
    throw chestlink::Error(
        failure + "\nNao foi possivel reconectar a rede anterior (" +
        previousSsid + "): " + restoreFailure +
        ". A configuracao anterior continua salva no cartao.");
  }

  return selectedSsid;
}
std::string ip() {
  return Wifi_IsIPReady() ? ipv4Text(Wifi_GetIP()) : "0.0.0.0";
}
const chestlink::NetworkStatus &networkStatus() { return networkState; }
bool usingChestLinkHotspot() {
  Wifi_AccessPoint actual{};
  return wifi && Wifi_GetCurrentAP(&actual) &&
         std::strcmp(actual.ssid, "ChestLink-DS") == 0;
}
std::string chestLinkHotspotServerIP() {
  if (!usingChestLinkHotspot() || !Wifi_IsIPReady())
    return {};
  in_addr gateway{}, subnet{}, dns1{}, dns2{};
  Wifi_GetIPInfo(&gateway, &subnet, &dns1, &dns2);
  if (!gateway.s_addr)
    return {};
  return ipv4Text(gateway.s_addr);
}
} // namespace platform
int runApp();
int main(int argc, char **argv) {
  platform::setLaunchPath(argc > 0 ? argv[0] : nullptr);
  return runApp();
}
