#include "graphics.hpp"
#include "platform.hpp"
extern "C" {
#include <arpa/inet.h>
}
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <dswifi9.h>
#include <fat.h>
#include <nds.h>
#include <nds/system_counter.h>
#include <string>
#include <vector>

namespace platform {
static unsigned pressed = 0;
static bool running = true, wifi = false;
static uint16_t *topBuffer = nullptr, *bottomBuffer = nullptr;
static Touch lastTouch;

namespace {
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
    if (!chestlink::exists(path))
      return {};
    const std::string ssid = chestlink::readText(path, 32);
    return ssid.size() <= 32 && ssid.find('\0') == std::string::npos ? ssid
                                                                     : "";
  } catch (const chestlink::Error &) {
    return {};
  }
}

void savePreferredSsid(const std::string &ssid) {
  const std::string path = wifiPreferencePath();
  chestlink::makeDirs(path.substr(0, path.find_last_of('/')));
  chestlink::writeText(path, ssid);
}

void initializeWifi() {
  if (wifi)
    return;
  if (!Wifi_InitDefault(INIT_ONLY | WIFI_ATTEMPT_DSI_MODE))
    throw chestlink::Error("Não foi possível iniciar o Wi-Fi do console.");
  wifi = true;
}

std::vector<Wifi_AccessPoint>
scanAccessPoints(bool cancellable, const std::string &onlySsid = {}) {
  if (Wifi_AssocStatus() == ASSOCSTATUS_ASSOCIATED)
    Wifi_DisconnectAP();
  Wifi_ScanMode();
  gui::notice("Buscando redes Wi-Fi",
              "Aguarde enquanto o DS procura pontos de acesso.",
              cancellable ? "B: cancelar" : "A/B: aguarde", 0);
  const uint64_t started = milliseconds();
  while (milliseconds() - started < 8000) {
    frame();
    if (cancellable && (keys() & B))
      return {};
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
    const bool saved = accessPoint.flags & WFLAG_APDATA_CONFIG_IN_WFC;
    // The DS can connect directly to open networks. Secured networks must
    // already have a compatible credential saved in the console firmware.
    if (!open && !saved)
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

bool connectAccessPoint(Wifi_AccessPoint &accessPoint, bool cancellable) {
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
  else if (accessPoint.flags & WFLAG_APDATA_CONFIG_IN_WFC)
    result = Wifi_ConnectWfcAP(&accessPoint);
  else
    result = Wifi_ConnectSecureAP(&accessPoint, nullptr, 0);
  if (result < 0)
    throw chestlink::Error("O console não conseguiu iniciar a conexão Wi-Fi.");

  gui::notice("Conectando ao Wi-Fi",
              std::string(accessPoint.ssid) + "\nAguardando endereço IP...",
              cancellable ? "B: cancelar" : "A/B: aguarde", 0);
  const uint64_t started = milliseconds();
  while (milliseconds() - started < 45000) {
    frame();
    if (cancellable && (keys() & B)) {
      Wifi_DisconnectAP();
      return false;
    }
    const uint32_t currentIP = Wifi_GetIP();
    if (Wifi_AssocStatus() == ASSOCSTATUS_ASSOCIATED && currentIP != 0 &&
        currentIP != 0xffffffffu)
      return true;
    if (Wifi_AssocStatus() == ASSOCSTATUS_CANNOTCONNECT &&
        milliseconds() - started > 2000)
      break;
  }
  const int finalStatus = Wifi_AssocStatus();
  const uint32_t finalIP = Wifi_GetIP();
  Wifi_DisconnectAP();
  if (finalStatus == ASSOCSTATUS_CANNOTCONNECT)
    throw chestlink::Error(
        "O DS não conseguiu se associar ao ponto de acesso. Confere se a rede continua ativa.");
  if (finalStatus == ASSOCSTATUS_ACQUIRINGDHCP || !finalIP ||
      finalIP == 0xffffffffu)
    throw chestlink::Error(
        "O DS encontrou e associou à rede, mas não recebeu um IP via DHCP.");
  throw chestlink::Error("A conexão Wi-Fi expirou. Tenta novamente sem reiniciar o console.");
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
}
void shutdown() {
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
  if (wifi && Wifi_AssocStatus() == ASSOCSTATUS_ASSOCIATED) {
    const uint32_t currentIP = Wifi_GetIP();
    if (currentIP != 0 && currentIP != 0xffffffffu)
      return;
  }
  const std::string ssid = preferredSsid();
  if (ssid.empty())
    throw chestlink::Error("Escolhe Configurar Wi-Fi no menu para conectar.");
  initializeWifi();
  auto accessPoints = scanAccessPoints(false, ssid);
  if (accessPoints.empty())
    throw chestlink::Error(
        "Rede salva indisponivel. Usa Configurar Wi-Fi para trocar.");
  if (!connectAccessPoint(accessPoints.front(), false))
    throw chestlink::Error("Nao foi possivel conectar a rede salva.");
}
std::string configureNetwork() {
  initializeWifi();
  auto accessPoints = scanAccessPoints(true);
  if (accessPoints.empty()) {
    if (keys() & B) {
      return {};
    }
    throw chestlink::Error(
        "Nenhuma rede compatível encontrada. Inicia ChestLink-DS no PC e tenta novamente.");
  }
  const int selected = chooseAccessPoint(accessPoints);
  if (selected < 0)
    return {};
  const std::string ssid = accessPoints[selected].ssid;
  if (!connectAccessPoint(accessPoints[selected], true))
    return {};
  savePreferredSsid(ssid);
  return ssid;
}
std::string ip() {
  in_addr a{};
  a.s_addr = Wifi_GetIP();
  const char *p = inet_ntoa(a);
  return p ? p : "0.0.0.0";
}
bool usingChestLinkHotspot() {
  return preferredSsid() == "ChestLink-DS";
}
std::string chestLinkHotspotServerIP() {
  if (!usingChestLinkHotspot())
    return {};
  in_addr gateway{}, subnet{}, dns1{}, dns2{};
  Wifi_GetIPInfo(&gateway, &subnet, &dns1, &dns2);
  if (!gateway.s_addr)
    return {};
  const char *address = inet_ntoa(gateway);
  return address ? address : "";
}
} // namespace platform
int runApp();
int main() { return runApp(); }
