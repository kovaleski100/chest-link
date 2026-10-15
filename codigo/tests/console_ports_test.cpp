#include "../platform/3ds/app_location.hpp"
#include "../platform/3ds/network_snapshot.hpp"
#include "listener_schedule.hpp"
#include "update.hpp"
#include <algorithm>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <iostream>

using namespace chestlink;
namespace fs = std::filesystem;

int main() {
  using namespace platform_detail;
  assert(sdApplicationPath("/3ds/custom/boot.3dsx") == "sdmc:/3ds/custom/boot.3dsx");
  assert(sdApplicationPath("sdmc:/3ds/custom/ChestLink_3DS.3dsx") ==
         "sdmc:/3ds/custom/ChestLink_3DS.3dsx");
  for (const char *path : {"3dslink:/app.3dsx", "fat:/app.3dsx", "app.3dsx",
                           "sdmc:/../app.3dsx", "sdmc:/3ds/./app.3dsx",
                           "sdmc:/3ds//app.3dsx", "sdmc:/app.3dsx.previous"})
    assert(sdApplicationPath(path).empty());
  assert(applicationDirectory("sdmc:/3ds/custom/boot.3dsx") == "sdmc:/3ds/custom/");
  assert(sameSDPath("sdmc:/3DS/custom/ChestLink_3DS_v0.4.25.3dsx",
                    "sdmc:/3ds/custom/CHESTLINK_3DS_v0.4.25.3dsx"));
  assert(!sameSDPath("sdmc:/3ds/custom/old.3dsx", "sdmc:/3ds/custom/new.3dsx"));
  assert(older3DSApp("ChestLink_3DS_v0.4.25.3dsx", 0x41a));
  for (const char *name : {"ChestLink_3DS_v0.4.26.3dsx", "ChestLink_3DS_v0.4.27.3dsx",
                           "ChestLink_3DS_v0.4.256.3dsx", "Other_v0.4.25.3dsx",
                           "ChestLink_3DS_v0.4.25.3dsx.previous", "ChestLink_3DS.3dsx"})
    assert(!older3DSApp(name, 0x41a));
  auto live = nativeNetworkSnapshot(true, 3, true, "Matheus", 7, "10.0.0.147");
  assert(live.connected && live.ipv4Ready && live.ssid == "Matheus" && live.ip == "10.0.0.147");
  for (uint32_t status : {1, 2, 3, 4, 8}) {
    auto connected = nativeNetworkSnapshot(true, status, true, "Matheus", 7, live.ip);
    assert(connected.connected && connected.ipv4Ready && connected.ip == live.ip);
  }
  auto lost = nativeNetworkSnapshot(true, 0, true, "Matheus", 7, live.ip);
  assert(!lost.connected && !lost.ipv4Ready && lost.ip.empty() && lost.ssid.empty());
  assert(!nativeNetworkSnapshot(false, 3, true, "Matheus", 7, live.ip).connected);
  for (const char *ip : {"", "0.0.0.0", "255.255.255.255"}) {
    auto waiting = nativeNetworkSnapshot(true, 3, true, "Matheus", 7, ip);
    assert(waiting.connected && !waiting.ipv4Ready && waiting.ip.empty());
  }
  std::string fullSSID(32, 's');
  assert(nativeNetworkSnapshot(true, 3, true, fullSSID.data(), 32, live.ip).ssid == fullSSID);
  assert(nativeNetworkSnapshot(true, 3, true, fullSSID.data(), 33, live.ip).ssid.empty());
  assert(nativeNetworkSnapshot(true, 3, false, fullSSID.data(), 32, live.ip).ssid.empty());
  ListenerSchedule listener;
  assert(!listener.ready() && !listener.due(0));
  assert(listener.link(live) && listener.ready() && listener.due(0));
  listener.attempted(0);
  assert(!listener.due(999) && listener.due(1000));
  assert(!listener.link(live));
  live.ip = "10.0.0.148";
  assert(listener.link(live) && listener.due(100));
  listener.attempted(100);
  live.ssid = "Other network";
  assert(listener.link(live) && listener.due(101));
  live.connected = false; live.ipv4Ready = false; live.ip.clear();
  assert(listener.link(live) && !listener.ready() && !listener.due(100000));
  live.connected = live.ipv4Ready = true; live.ip = "10.0.0.149";
  assert(listener.link(live) && listener.ready() && listener.due(102));

  char pattern[] = "/tmp/chest-link-3ds-ports-XXXXXX";
  const char *folder = mkdtemp(pattern);
  assert(folder);
  const std::string install = std::string(folder) + "/custom.3dsx";
  const std::string old = "original app", updated = "new verified app";
  writeText(install, old);
  std::vector<uint8_t> input(16 + 48 + 8, 0); // hello, availability, manifest, ready.
  std::memcpy(input.data() + 16, "CLUPD001", 8);
  put32(input.data() + 24, 0x41a);
  put32(input.data() + 28, updated.size());
  Sha256 hash; hash.update(updated.data(), updated.size());
  const auto expected = hash.finish();
  std::memcpy(input.data() + 32, expected.data(), expected.size());
  input.insert(input.end(), updated.begin(), updated.end());
  size_t cursor = 0;
  Wire wire{[&](void *out, size_t bytes) {
    assert(cursor + bytes <= input.size());
    std::memcpy(out, input.data() + cursor, bytes); cursor += bytes;
  }, [](const void *, size_t) {}};
  auto result = update3DS(wire, 123456, 0x419, install,
                         [](uint32_t, uint32_t, uint32_t) { return true; });
  assert(result.state == UpdateState::installed && readText(install) == updated);
  assert(readText(install + ".previous") == old);
  bool complete;
  assert(!removePrevious3DSUpdates(install, 0x419, complete) && complete);
  assert(exists(install + ".previous")); // Old process must not clean its backup.
  writeText(install + ".previous", "externally changed backup");
  assert(!removePrevious3DSUpdates(install, 0x41a, complete) && !complete);
  assert(exists(install + ".previous")); // Never delete a modified/unverified file.
  writeText(install + ".previous", old);
  writeText(install, "wrong installed binary");
  assert(!removePrevious3DSUpdates(install, 0x41a, complete) && complete);
  assert(exists(install + ".previous")); // Version alone cannot authorize deletion.
  writeText(install, updated);
  assert(removePrevious3DSUpdates(install, 0x41a, complete) == 1 && complete);
  assert(!exists(install + ".previous") && !exists(install + ".previous.cleanup.json"));
  assert(readText(install) == updated);
  writeText(install + ".previous", "manual backup without receipt");
  assert(!removePrevious3DSUpdates(install, 0x41a, complete) && complete);
  assert(exists(install + ".previous"));
  assert(!removePrevious3DSUpdates("", 0x41a, complete));
  fs::remove_all(folder); // Only this test's freshly allocated temporary folder.
  std::cout << "PASS 3DS launch path, native Wi-Fi state, listener recovery and verified cleanup\n";
}
