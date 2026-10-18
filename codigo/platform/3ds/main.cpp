#include "extdata.hpp"
#include "graphics.hpp"
#include "pksm_storage.hpp"
#include "platform.hpp"
#include "app_location.hpp"
#include "network_state.hpp"
#include "update.hpp"
#include <3ds.h>
#include <3ds/archive.h>
#include <arpa/inet.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dirent.h>
#include <sys/stat.h>
#include <unistd.h>
namespace platform {
static unsigned pressed = 0;
static bool initialized = false, extMounted = false;
static Touch lastTouch;
static std::string launchPath;
void setLaunchPath(const char *path) {
  launchPath = platform_detail::sdApplicationPath(path ? path : "");
}
std::string runningApplicationPath() {
  if (!launchPath.empty()) return launchPath;
  // Older launchers/3dslink may omit argv[0]. The confirmation screen shows
  // this fallback, but cleanup never assumes it was the running executable.
  return "sdmc:/3ds/ChestLink_3DS/ChestLink_3DS.3dsx";
}
std::string runningApplicationDirectory() {
  return platform_detail::applicationDirectory(runningApplicationPath());
}
unsigned removePreviousApplicationVersions(uint32_t version, bool &complete) {
  complete = true;
  if (launchPath.empty()) return 0; // Cannot prove which copy to preserve.
  unsigned removed = chestlink::removePrevious3DSUpdates(launchPath, version, complete);
  const std::string directory = platform_detail::applicationDirectory(launchPath);
  DIR *handle = opendir(directory.c_str());
  if (!handle) { complete = false; return removed; }
  while (dirent *entry = readdir(handle)) {
    const std::string name = entry->d_name;
    const std::string path = directory + name;
    if (platform_detail::sameSDPath(path, launchPath) ||
        !platform_detail::older3DSApp(name, version)) continue;
    struct stat info{};
    if (stat(path.c_str(), &info)) { complete = false; continue; }
    if (!S_ISREG(info.st_mode)) continue;
    if (!std::remove(path.c_str())) ++removed;
    else complete = false;
  }
  closedir(handle);
  return removed;
}
void init() {
  gfxInitDefault();
  gfxSetDoubleBuffering(GFX_TOP, false);
  gfxSetDoubleBuffering(GFX_BOTTOM, false);
  initialized = true;
  if (!chestlink::exists("sdmc:/"))
    throw chestlink::Error("Cartao SD nao encontrado.");
  if (!launchPath.empty() && !chestlink::exists(launchPath)) launchPath.clear();
  platform_detail::refresh3DSNetworkStatus(true);
  extMounted = mountPKSM();
  if (extMounted)
    chestlink::outputAllocator = allocatePKSM;
}
void shutdown() {
  chestlink::outputAllocator = {};
  platform_detail::shutdown3DSNetwork();
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
  platform_detail::refresh3DSNetworkStatus();
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
uint64_t milliseconds() {
  const uint64_t ticks = static_cast<uint64_t>(svcGetSystemTick());
  return (ticks / SYSCLOCK_ARM11) * 1000 +
         (ticks % SYSCLOCK_ARM11) * 1000 / SYSCLOCK_ARM11;
}
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
std::vector<std::string> gameSaveSearchRoots() {
  return {"sdmc:/3ds/PKSM", "sdmc:/3ds/Checkpoint", "sdmc:/gm9/out",
          "sdmc:/roms", "sdmc:/saves", "sdmc:/pokemon", "sdmc:/"};
}
void network() {
  platform_detail::require3DSNetwork();
}
const chestlink::NetworkStatus &networkStatus() {
  return platform_detail::network3DSStatus();
}
std::string ip() {
  platform_detail::refresh3DSNetworkStatus(true);
  const auto &status = networkStatus();
  return status.ipv4Ready ? status.ip : "0.0.0.0";
}
std::string updateNetworkDiagnostics() {
  const auto &status = networkStatus();
  return std::string("driver=3DS-native connected=") +
         (status.connected ? "yes" : "no") +
         " ipv4_ready=" + (status.ipv4Ready ? "yes" : "no");
}
} // namespace platform
int runApp();
int main(int argc, char **argv) {
  platform::setLaunchPath(argc > 0 ? argv[0] : nullptr);
  return runApp();
}
