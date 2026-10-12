#include "extdata.hpp"
#include "graphics.hpp"
#include "pksm_storage.hpp"
#include "platform.hpp"
#include <3ds.h>
#include <3ds/archive.h>
#include <arpa/inet.h>
#include <cstdio>
#include <cstdlib>
#include <malloc.h>
#include <unistd.h>
namespace platform {
static unsigned pressed = 0;
static bool initialized = false, networkReady = false, extMounted = false;
static void *socBuffer = nullptr;
static Touch lastTouch;
void init() {
  gfxInitDefault();
  gfxSetDoubleBuffering(GFX_TOP, false);
  gfxSetDoubleBuffering(GFX_BOTTOM, false);
  initialized = true;
  if (!chestlink::exists("sdmc:/"))
    throw chestlink::Error("Cartao SD nao encontrado.");
  extMounted = mountPKSM();
  if (extMounted)
    chestlink::outputAllocator = allocatePKSM;
}
void shutdown() {
  chestlink::outputAllocator = {};
  if (networkReady) {
    socExit();
    networkReady = false;
  }
  if (socBuffer) {
    free(socBuffer);
    socBuffer = nullptr;
  }
  if (extMounted) {
    unmountPKSM();
    extMounted = false;
  }
  if (initialized) {
    gfxExit();
    initialized = false;
  }
}
bool alive() { return aptMainLoop(); }
void frame() {
  hidScanInput();
  uint32_t k = hidKeysDownRepeat();
  pressed = 0;
  const uint32_t from[] = {KEY_DUP, KEY_DDOWN, KEY_DLEFT, KEY_DRIGHT,
                           KEY_A,   KEY_B,     KEY_X,     KEY_Y,
                           KEY_L,   KEY_R,     KEY_START, KEY_SELECT};
  for (unsigned i = 0; i < 12; ++i)
    if (k & from[i])
      pressed |= 1u << i;
  lastTouch.down = (hidKeysHeld() & KEY_TOUCH) != 0;
  if (lastTouch.down) {
    touchPosition p;
    hidTouchRead(&p);
    lastTouch.x = p.px;
    lastTouch.y = p.py;
  }
  if (hidKeysDown() & KEY_TOUCH)
    pressed |= TOUCH;
  gfxFlushBuffers();
  gfxSwapBuffers();
  gspWaitForVBlank();
}
unsigned keys() { return pressed; }
void clear() {}
Touch touch() { return lastTouch; }
void present(const uint16_t *top, unsigned width, const uint16_t *bottom) {
  if (!initialized)
    return;
  auto copy = [](const uint16_t *src, unsigned w, uint8_t *dst) {
    for (unsigned x = 0; x < w; ++x)
      for (unsigned y = 0; y < 240; ++y) {
        uint16_t c = src[y * w + x];
        unsigned i = (x * 240 + 239 - y) * 3;
        dst[i] = ((c >> 10) & 31) * 255 / 31;
        dst[i + 1] = ((c >> 5) & 31) * 255 / 31;
        dst[i + 2] = (c & 31) * 255 / 31;
      }
  };
  copy(top, width, gfxGetFramebuffer(GFX_TOP, GFX_LEFT, nullptr, nullptr));
  copy(bottom, 320, gfxGetFramebuffer(GFX_BOTTOM, GFX_LEFT, nullptr, nullptr));
  gfxFlushBuffers();
}
bool pollNetwork() {
  frame();
  return !(pressed & B);
}
uint64_t milliseconds() { return osGetTime(); }
uint32_t makePin() {
  return uint32_t((svcGetSystemTick() ^ osGetTime()) % 900000) + 100000;
}
unsigned maxChestBoxes() { return 500; }
std::vector<chestlink::Store> stores() {
  std::vector<chestlink::Store> out;
  bool useExtData = extMounted;
  bool configured = false;
  if (extMounted && chestlink::exists("pksm:/config.json")) {
    try {
      auto setting = platform_detail::pksmUseExtData(
          chestlink::readText("pksm:/config.json", 64 * 1024));
      if (setting) {
        useExtData = *setting;
        configured = true;
      }
    } catch (const chestlink::Error &) {
    }
  }
  if (!configured) {
    const bool hasExtDataBanks =
        extMounted && (chestlink::exists("pksm:/banks.json") ||
                       chestlink::exists("pksm:/banks") ||
                       chestlink::exists("pksm:/chest-link/journal.json"));
    const bool hasSDBanks =
        chestlink::exists("sdmc:/3ds/PKSM/banks.json") ||
        chestlink::exists("sdmc:/3ds/PKSM/banks");
    if (hasExtDataBanks != hasSDBanks)
      useExtData = hasExtDataBanks;
  }
  if (useExtData && extMounted)
    out.push_back(
        {"PKSM (ExtData)", "pksm:", 500, chestlink::PKSM_GENS, commitPKSM});
  else
    out.push_back(
        {"PKSM (SD)", "sdmc:/3ds/PKSM", 500, chestlink::PKSM_GENS, {}});
  if (chestlink::exists("sdmc:/_nds/pkmn-chest"))
    out.push_back({"Chest (SD)",
                   "sdmc:/_nds/pkmn-chest",
                   500,
                   chestlink::CHEST_GENS,
                   {}});
  return out;
}
void network() {
  if (!networkReady) {
    socBuffer = memalign(0x1000, 1024 * 1024);
    if (!socBuffer)
      throw chestlink::Error("Memoria insuficiente para Wi-Fi.");
    Result r = socInit(static_cast<uint32_t *>(socBuffer), 1024 * 1024);
    if (R_FAILED(r)) {
      free(socBuffer);
      socBuffer = nullptr;
      throw chestlink::Error("Wi-Fi indisponivel. Ative-o e configure uma "
                             "conexao nas definicoes do 3DS.");
    }
    networkReady = true;
  }
  if (!gethostid())
    throw chestlink::Error(
        "3DS sem IP. Conecte-o a mesma rede Wi-Fi do DS/DSi.");
}
std::string ip() {
  in_addr a{};
  a.s_addr = gethostid();
  const char *p = inet_ntoa(a);
  return p ? p : "0.0.0.0";
}
} // namespace platform
int runApp();
int main() { return runApp(); }
