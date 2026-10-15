#include "platform.hpp"
#include <chrono>
#include <thread>
namespace platform {
void init() {}
void shutdown() {}
bool alive() { return true; }
void frame() { std::this_thread::sleep_for(std::chrono::milliseconds(1)); }
unsigned keys() { return 0; }
void clear() {}
void network() {}
std::string ip() { return "127.0.0.1"; }
uint64_t milliseconds() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::steady_clock::now().time_since_epoch())
      .count();
}
uint32_t makePin() { return 123456; }
bool pollNetwork() {
  frame();
  return true;
}
unsigned maxChestBoxes() { return 50; }
std::vector<chestlink::Store> stores() { return {}; }
} // namespace platform
