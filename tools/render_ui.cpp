// Render the real native graphics implementation on a host for visual checks.
#include "graphics.hpp"
#include "platform.hpp"
#include <fstream>
#include <string>
namespace platform {
void present(const uint16_t *, unsigned, const uint16_t *) {}
} // namespace platform
static void save(const std::string &path, const uint16_t *p, unsigned w) {
  std::ofstream f(path, std::ios::binary);
  f << "P6\n" << w << " 240\n255\n";
  for (unsigned i = 0; i < w * 240; ++i) {
    unsigned v = p[i];
    char c[] = {char((v & 31) * 255 / 31), char(((v >> 5) & 31) * 255 / 31),
                char(((v >> 10) & 31) * 255 / 31)};
    f.write(c, 3);
  }
}
int main(int argc, char **argv) {
  if (argc != 2)
    return 1;
  std::string prefix = argv[1];
  gui::BoxScreen s;
  s.bank = "SoulSilver";
  s.name = "Box 1";
  s.boxes = 18;
  s.cursor = 2;
  s.mask = 7;
  s.marked = 3;
  s.markedBoxes = 1;
  const unsigned species[] = {152, 155, 158, 25,  133, 94,  249, 250, 1,   4,
                              7,   131, 143, 149, 150, 151, 179, 181, 196, 197,
                              245, 246, 282, 350, 448, 479, 492, 493, 809, 898};
  for (unsigned i = 0; i < 30; ++i) {
    auto &p = s.pokemon[i];
    p.occupied = p.valid = true;
    p.species = species[i];
    p.generation = 0;
    p.sprite = chestlink::pokemonSprite(p.species, 0, 0, false);
  }
  gui::box(s);
  save(prefix + "-top.ppm", gui::topPixels(), gui::TOP_WIDTH);
  save(prefix + "-bottom.ppm", gui::bottomPixels(), 320);
  gui::menu("Transferir bancos por Wi-Fi",
            {"Enviar ao console", "Receber do console", "Enviar ao PC",
             "Buscar no PC", "Consultar bancos", "Sair"},
            2);
  save(prefix + "-menu-top.ppm", gui::topPixels(), gui::TOP_WIDTH);
  save(prefix + "-menu-bottom.ppm", gui::bottomPixels(), 320);
  gui::notice("Enviar estas boxes?",
              "2 boxes / 24 Pokemon\nGeracoes: 4\n\nA origem permanece "
              "intacta.\nDeixe o servidor do PC aberto.");
  save(prefix + "-dialog-top.ppm", gui::topPixels(), gui::TOP_WIDTH);
  save(prefix + "-dialog-bottom.ppm", gui::bottomPixels(), 320);
  gui::numbers("IP exibido no PC", {192, 168, 1, 100}, 2, true);
  save(prefix + "-numbers-bottom.ppm", gui::bottomPixels(), 320);
}
