#pragma once
#include "pokemon.hpp"
namespace gui {
constexpr unsigned HEIGHT = 240, BOTTOM_WIDTH = 320;
#ifdef CL_NDS
constexpr unsigned TOP_WIDTH = 320;
#else
constexpr unsigned TOP_WIDTH = 400;
#endif
// Software RGB555 renderer shared by the native apps and host visual checks.
void notice(const std::string &heading, const std::string &body,
            const std::string &footer = "A: confirmar    B: voltar",
            int percent = -1);
void menu(const std::string &heading, const std::vector<std::string> &,
          unsigned cursor, const std::string &status = {});
int menuHit(int x, int y, unsigned cursor, unsigned count);
void numbers(const std::string &heading, const std::vector<unsigned> &,
             unsigned cursor, bool ip);
struct BoxScreen {
  std::string bank, name;
  unsigned box = 0, boxes = 0, cursor = 0, markedBoxes = 0, marked = 0;
  uint32_t mask = 0;
  bool view = false, consult = false;
  std::string directLabel = "Enviar outro";
  std::array<chestlink::PokemonPreview, 30> pokemon{};
};
void box(const BoxScreen &);
// 0..29 slots; 30 previous,31 next; 32 mark,33 box,34 all,35 send,36 back.
int boxHit(int x, int y);
const uint16_t *topPixels();
const uint16_t *bottomPixels();
} // namespace gui
