#pragma once
#include "core.hpp"
#include "network_status.hpp"
namespace platform {
enum Key {
  UP = 1,
  DOWN = 2,
  LEFT = 4,
  RIGHT = 8,
  A = 16,
  B = 32,
  X = 64,
  Y = 128,
  L = 256,
  R = 512,
  START = 1024,
  SELECT = 2048,
  TOUCH = 4096
};
void init();
void shutdown();
void frame();
unsigned keys();
bool alive();
void clear();
struct Touch {
  int x = 0, y = 0;
  bool down = false;
};
Touch touch(); // Virtual 320x240 coordinates on the bottom screen.
void present(const uint16_t *top, unsigned topWidth, const uint16_t *bottom);
void network();
#if defined(CL_NDS) || defined(CL_3DS)
void setLaunchPath(const char *path);
std::string runningApplicationDirectory();
unsigned removePreviousApplicationVersions(uint32_t currentVersion,
                                            bool &complete);
const chestlink::NetworkStatus &networkStatus();
#endif
#ifdef CL_3DS
std::string runningApplicationPath();
#endif
#ifdef CL_NDS
// Scan nearby networks, connect to the user's selected supported access point,
// and remember it so later launches reconnect to that same network. Calling
// this again lets the user switch networks.
std::string configureNetwork();
bool usingChestLinkHotspot();
std::string chestLinkHotspotServerIP();
#endif
std::string ip();
uint32_t makePin();
uint64_t milliseconds();
std::vector<chestlink::Store> stores();
unsigned maxChestBoxes();
// Polls system events while sockets are waiting. Returns false for B/cancel.
bool pollNetwork();
} // namespace platform
