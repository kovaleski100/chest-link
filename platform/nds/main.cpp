#include "graphics.hpp"
#include "platform.hpp"
extern "C" {
#include <arpa/inet.h>
}
#include <cstdio>
#include <cstring>
#include <ctime>
#include <dswifi9.h>
#include <fat.h>
#include <nds.h>
#include <nds/system_counter.h>

namespace platform {
static unsigned pressed = 0;
static bool running = true, wifi = false;
static uint16_t *topBuffer = nullptr, *bottomBuffer = nullptr;
static Touch lastTouch;
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
  if (!fatInitDefault())
    throw chestlink::Error("SD/flashcard nao encontrado.");
}
void shutdown() {
  if (wifi)
    Wifi_Deinit();
}
bool alive() { return running; }
void frame() {
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
  if (!wifi) {
    if (!Wifi_InitDefault(INIT_ONLY | WIFI_ATTEMPT_DSI_MODE))
      throw chestlink::Error("Nao foi possivel iniciar Wi-Fi.");
    wifi = true;
  }
  if (Wifi_AssocStatus() == ASSOCSTATUS_ASSOCIATED && Wifi_GetIP())
    return;
  gui::notice("Conectando ao Wi-Fi",
              "Use uma rede configurada nas definicoes do console.",
              "B: cancelar", 0);
  Wifi_AutoConnect();
  uint64_t start = milliseconds();
  while (Wifi_AssocStatus() != ASSOCSTATUS_ASSOCIATED || !Wifi_GetIP()) {
    frame();
    if (pressed & B) {
      Wifi_DisconnectAP();
      throw chestlink::Error("Cancelado.");
    }
    if (Wifi_AssocStatus() == ASSOCSTATUS_CANNOTCONNECT ||
        milliseconds() - start > 45000) {
      Wifi_DisconnectAP();
      throw chestlink::Error("Wi-Fi falhou. DS/Lite precisa de rede "
                             "aberta/WEP; DSi em modo DSi pode usar WPA2.");
    }
  }
}
std::string ip() {
  in_addr a{};
  a.s_addr = Wifi_GetIP();
  const char *p = inet_ntoa(a);
  return p ? p : "0.0.0.0";
}
} // namespace platform
int runApp();
int main() { return runApp(); }
