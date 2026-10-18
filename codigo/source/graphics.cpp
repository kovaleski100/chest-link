// Chest Link's adapted PKSM storage layout. Original visual resources:
// PKSM copyright (C) 2016-2022 Bernardo Giordano, Admiral Fish, piepie62,
// contributors. GPL-3.0-or-later with section 7(b)/(c); see THIRD_PARTY.md.
#include "graphics.hpp"
#include "graphics_assets.hpp"
#include "platform.hpp"
#include "version.hpp"
#include <algorithm>
#include <cstdio>
namespace gui {
namespace {
uint16_t topData[TOP_WIDTH * HEIGHT], bottomData[BOTTOM_WIDTH * HEIGHT];
chestlink::NetworkStatus networkState;
bool screenReady = false, boxScreen = false;
constexpr uint16_t color(unsigned r, unsigned g, unsigned b) {
  return 0x8000 | (r >> 3) | (g >> 3) << 5 | (b >> 3) << 10;
}
constexpr auto BLACK = color(32, 43, 35), WHITE = color(255, 255, 255),
               GREEN = color(61, 131, 52), SELECTED = color(212, 242, 141),
               BORDER = color(55, 127, 48);
struct Canvas {
  uint16_t *p;
  unsigned w;
  void pixel(int x, int y, uint16_t c) {
    if (x >= 0 && y >= 0 && unsigned(x) < w && y < 240)
      p[y * w + x] = c;
  }
  void rect(int x, int y, int width, int height, uint16_t c) {
    int x0 = std::max(0, x), x1 = std::min(int(w), x + width),
        y0 = std::max(0, y), y1 = std::min(240, y + height);
    if (x1 <= x0 || y1 <= y0)
      return;
    for (int yy = y0; yy < y1; ++yy)
      std::fill(p + yy * w + x0, p + yy * w + x1, c);
  }
  void outline(int x, int y, int width, int height, uint16_t c) {
    rect(x, y, width, 2, c);
    rect(x, y + height - 2, width, 2, c);
    rect(x, y, 2, height, c);
    rect(x + width - 2, y, 2, height, c);
  }
  void image(const assets::Image &a, int x, int y, int width = 0,
             int height = 0) {
    if (!width)
      width = a.width;
    if (!height)
      height = a.height;
    if (width <= 0 || height <= 0 || !a.width || !a.height)
      return;
    // DS CPUs have no hardware integer division. Keep the exact nearest
    // neighbour coordinates without dividing twice for every screen pixel.
    const unsigned xStep = a.width / width, xRemainder = a.width % width;
    const unsigned yStep = a.height / height, yRemainder = a.height % height;
    unsigned sourceY = 0, yError = 0;
    for (int yy = 0; yy < height; ++yy) {
      const auto *row = a.pixels + sourceY * a.width;
      unsigned sourceX = 0, xError = 0;
      for (int xx = 0; xx < width; ++xx) {
        const uint16_t c = row[sourceX];
        if (c & 0x8000)
          pixel(x + xx, y + yy, c);
        sourceX += xStep;
        xError += xRemainder;
        if (xError >= unsigned(width)) {
          ++sourceX;
          xError -= width;
        }
      }
      sourceY += yStep;
      yError += yRemainder;
      if (yError >= unsigned(height)) {
        ++sourceY;
        yError -= height;
      }
    }
  }
  void text(const std::string &s, int x, int y, uint16_t c = BLACK,
            unsigned maxChars = 100, unsigned charSpacing = 7) {
    unsigned n = 0;
    for (size_t i = 0; i < s.size() && n < maxChars; ++i, ++n) {
      unsigned ch = uint8_t(s[i]);
      if (ch >= 0xc2 && ch <= 0xc3 && i + 1 < s.size() &&
          (uint8_t(s[i + 1]) & 0xc0) == 0x80)
        ch = ((ch & 31) << 6) | (uint8_t(s[++i]) & 63);
      else if (ch >= 0xe0 && ch <= 0xef && i + 2 < s.size() &&
               (uint8_t(s[i + 1]) & 0xc0) == 0x80 &&
               (uint8_t(s[i + 2]) & 0xc0) == 0x80) {
        unsigned code = ((ch & 15) << 12) | ((uint8_t(s[i + 1]) & 63) << 6) |
                        (uint8_t(s[i + 2]) & 63);
        i += 2;
        ch = code == 0x2640 ? 128 : code == 0x2642 ? 129 : '?';
      } else if (ch >= 128 && ch != 0xc2 && ch != 0xc3) {
        while (i + 1 < s.size() && (uint8_t(s[i + 1]) & 0xc0) == 0x80)
          ++i;
        ch = '?';
      }
      if (ch == '\n') {
        y += 15;
        x = 0;
        continue;
      }
      if (ch < 32 || ch > 255)
        ch = '?';
#ifdef CL_NDS
      // Text uses the DS's physical pixel grid, so downscaling the shared
      // 320x240 layout cannot drop one-pixel strokes from small glyphs.
      for (unsigned row = 0; row < 10; ++row)
        for (unsigned bit = 0; bit < 6; ++bit)
          if (assets::fontSmall[ch - 32][row] & (1u << bit))
            pixel(((x * 4 / 5 + int(bit)) * 5 / 4),
                  ((y * 4 / 5 + int(row)) * 5 / 4), c);
#else
      for (unsigned row = 0; row < 12; ++row)
        for (unsigned bit = 0; bit < 8; ++bit)
          if (assets::font[ch - 32][row] & (1u << bit))
            pixel(x + bit, y + row, c);
#endif
      x += charSpacing;
    }
  }
  void centered(const std::string &s, int x, int y, int width,
                uint16_t c = BLACK, unsigned maxChars = 30) {
    unsigned n = 0;
    for (unsigned char v : s)
      if ((v & 0xc0) != 0x80)
        ++n;
    n = std::min(n, maxChars);
    text(s, x + std::max(0, (width - int(n) * 7) / 2), y, c, maxChars);
  }
  void sprite(unsigned index, int x, int y, bool dim = false, int scale = 1) {
    if (index >= assets::spriteCount)
      index = 0;
    const auto *pal = assets::spritePalette + index * 16;
    const auto *data = assets::spritePixels + index * 510;
    for (unsigned i = 0; i < 34 * 30; ++i) {
      unsigned n = (data[i / 2] >> ((i & 1) * 4)) & 15;
      if (!n)
        continue;
      uint16_t c = pal[n];
      if (dim) {
        unsigned r = (c & 31), g = (c >> 5) & 31, b = (c >> 10) & 31;
        c = 0x8000 | ((r + 20) / 2) | ((g + 24) / 2) << 5 |
            ((b + 20) / 2) << 10;
      }
      rect(x + (i % 34) * scale, y + (i / 34) * scale, scale, scale, c);
    }
  }
};
Canvas top() { return {topData, TOP_WIDTH}; }
Canvas bottom() { return {bottomData, BOTTOM_WIDTH}; }
void background() {
  screenReady = true;
  boxScreen = false;
  top().image(assets::top, 0, 0, TOP_WIDTH, 240);
  bottom().image(assets::bottom, 0, 0);
}
void networkStrip() {
  if (!networkState.visible) return;
  auto c = top();
  const int width = boxScreen ? TOP_WIDTH - 143 : TOP_WIDTH;
  c.rect(0, 0, width, boxScreen ? 20 : 29, color(231, 244, 224));
  const uint16_t ink = networkState.connected ? color(28, 129, 73) :
      networkState.connecting ? color(175, 111, 22) : color(173, 45, 45);
  // Compact Wi-Fi arcs, with a slash when the radio is disconnected.
  c.rect(12, 16, 3, 3, ink);
  for (int i = 0; i < 5; ++i) {
    c.pixel(7 + i, 12 - i / 2, ink); c.pixel(15 + i, 10 + i / 2, ink);
    c.pixel(4 + i, 8 - i / 2, ink); c.pixel(18 + i, 6 + i / 2, ink);
  }
  c.rect(9, 6, 9, 2, ink); c.rect(11, 10, 5, 2, ink);
  if (!networkState.connected && !networkState.connecting)
    for (int i = 0; i < 17; ++i) c.rect(5 + i, 18 - i, 2, 2, ink);
  const std::string state = networkState.connected ? "ON " :
                            networkState.connecting ? "... " : "OFF ";
  c.text(state + (networkState.ssid.empty() ? "Sem rede" : networkState.ssid),
         28, 3, ink, (width - 32) / 7);
  if (boxScreen) return;
  const char *server = "Servidor: não encontrado";
  switch (networkState.server) {
  case chestlink::ServerAvailability::searching:
    server = "Servidor: procurando"; break;
  case chestlink::ServerAvailability::connected:
    server = "Servidor: conectado"; break;
  case chestlink::ServerAvailability::notFound:
    server = "Servidor: não encontrado"; break;
  default:
    if (networkState.connected && !networkState.ipv4Ready)
      server = "Servidor: aguardando IP";
    break;
  }
  const unsigned spacing = TOP_WIDTH == 320 ? 6 : 7;
  c.text("ip-server: " +
             (networkState.serverIP.empty() ? "--" : networkState.serverIP),
         6, 16, BLACK, (TOP_WIDTH / 2 - 3) / spacing, spacing);
  c.text(server, TOP_WIDTH / 2 + 3, 16, BLACK,
         (TOP_WIDTH / 2 - 7) / spacing, spacing);
}
void show() { networkStrip(); platform::present(topData, TOP_WIDTH, bottomData); }
void button(Canvas c, int x, int y, const std::string &label,
            bool active = false, int width = 108) {
  c.image(assets::button, x, y, width, 28);
  if (active)
    c.outline(x, y, width, 28, BORDER);
  c.centered(label, x, y + 7, width, BLACK, (width - 8) / 7);
}
void wrapped(Canvas c, const std::string &s, int x, int y, unsigned cols,
             unsigned lines) {
  std::string line;
  unsigned used = 0;
  for (size_t i = 0; i <= s.size(); ++i) {
    char ch = i < s.size() ? s[i] : '\n';
    if (ch == '\n' || line.size() >= cols) {
      c.text(line, x, y, BLACK, cols);
      y += 16;
      line.clear();
      if (++used == lines)
        return;
      if (ch == '\n')
        continue;
    }
    line += ch;
  }
}
void header(const std::string &heading) {
  top().text("CHEST LINK v" + chestlink::appVersionText(chestlink::APP_VERSION_CODE),
             12, 6, BLACK);
  top().centered(heading, 8, 33, TOP_WIDTH - 16, BLACK, (TOP_WIDTH - 16) / 7);
}
void grid(Canvas c, const BoxScreen &s, int x, int y, bool preview) {
  c.outline(x - 2, y - 2, 208, 154, GREEN);
  for (unsigned i = 0; i < 30; ++i) {
    int xx = x + (i % 6) * 34, yy = y + (i / 6) * 30;
    if (s.mask & (1u << i))
      c.rect(xx, yy, 34, 30, SELECTED);
    if (s.pokemon[i].occupied)
      c.sprite(s.pokemon[i].sprite, xx, yy,
               preview && !s.view && !(s.mask & (1u << i)));
    if (i == s.cursor) {
      c.outline(xx, yy, 34, 30, BORDER);
      if (!preview)
        c.image(assets::pointer, xx + 8, yy - 16, 14, 21);
    }
  }
}
void drawPokemonGrid(Canvas c,
                     const std::array<chestlink::PokemonPreview, 30> &pokemon,
                     int x, int y, unsigned cursor) {
  c.outline(x - 2, y - 2, 208, 154, GREEN);
  for (unsigned i = 0; i < 30; ++i) {
    int xx = x + (i % 6) * 34, yy = y + (i / 6) * 30;
    if (pokemon[i].occupied) c.sprite(pokemon[i].sprite, xx, yy);
    if (i == cursor) c.outline(xx, yy, 34, 30, BORDER);
  }
}
unsigned firstGameTab(const GameBoxesScreen &s) {
  if (s.games.size() <= 3) return 0;
  unsigned first = s.gameIndex ? s.gameIndex - 1 : 0;
  if (first + 3 > s.games.size()) first = unsigned(s.games.size()) - 3;
  return first;
}
} // namespace
const uint16_t *topPixels() { return topData; }
const uint16_t *bottomPixels() { return bottomData; }
void setNetworkStatus(const chestlink::NetworkStatus &state) {
  if (state == networkState) return;
  networkState = state;
  if (screenReady) show();
}
void notice(const std::string &heading, const std::string &body,
            const std::string &footer, int percent) {
  background();
  header(heading);
  wrapped(top(), body, 15, 65, (TOP_WIDTH - 30) / 7, 10);
  bottom().centered(heading, 8, 25, 304, BLACK, 43);
  wrapped(bottom(), footer, 15, 66, 41, 7);
  if (percent >= 0) {
    percent = std::clamp(percent, 0, 100);
    bottom().rect(20, 151, 280, 20, WHITE);
    bottom().rect(22, 153, 276 * percent / 100, 16, GREEN);
    bottom().centered(std::to_string(percent) + "%", 20, 177, 280);
  } else {
    button(bottom(), 16, 172, "A: confirmar", false, 140);
    button(bottom(), 164, 172, "B: voltar", false, 140);
  }
  bottom().text("Chest Link | Visual PKSM / FlagBrew", 8, 218, BLACK, 43);
  show();
}
void menu(const std::string &heading, const std::vector<std::string> &items,
          unsigned cursor, const std::string &status) {
  background();
  header(heading);
  top().sprite(25, TOP_WIDTH / 2 - 34, 72, false, 2);
  top().centered(status.empty() ? "Bancos e transferencias por Wi-Fi" : status,
                 5, 147, TOP_WIDTH - 10, BLACK, (TOP_WIDTH - 10) / 7);
  top().centered(status.empty() ? "A: abrir    B: voltar"
                                : "A: abrir    B: sair",
                 10, 183, TOP_WIDTH - 20);
  if (!status.empty())
    top().centered("Receber: exige confirmacao", 10, 202, TOP_WIDTH - 20);
  unsigned first = cursor / 8 * 8;
  for (unsigned i = first; i < std::min<unsigned>(first + 8, items.size()); ++i)
    button(bottom(), 8, 8 + (i - first) * 24, items[i], i == cursor, 304);
  bottom().text(std::to_string(cursor + 1) + " / " +
                    std::to_string(items.size()),
                10, 216, BLACK);
  bottom().text("Toque para abrir", 164, 216, BLACK);
  show();
}
int menuHit(int x, int y, unsigned cursor, unsigned count) {
  if (x < 8 || x >= 312 || y < 8 || y >= 200)
    return -1;
  unsigned i = cursor / 8 * 8 + (y - 8) / 24;
  return i < count ? int(i) : -1;
}
void numbers(const std::string &heading, const std::vector<unsigned> &values,
             unsigned cursor, bool ip) {
  background();
  header(heading);
  wrapped(top(),
          "Esquerda/direita: escolher\nCima/baixo: alterar\nL/R: -10/+10 "
          "(IP)\nA: confirmar   B: voltar",
          16, 82, (TOP_WIDTH - 32) / 7, 7);
  int width = ip ? 70 : 44, start = ip ? 20 : 28;
  for (unsigned i = 0; i < values.size(); ++i) {
    button(bottom(), start + i * width, 80, std::to_string(values[i]),
           i == cursor, width - 4);
  }
  button(bottom(), 26, 130, "+", false, 128);
  button(bottom(), 166, 130, "-", false, 128);
  button(bottom(), 26, 172, "Confirmar", false, 128);
  button(bottom(), 166, 172, "Voltar", false, 128);
  bottom().text("IP e PIN ficam salvos neste console", 6, 218, BLACK, 44);
  show();
}
void box(const BoxScreen &s) {
  background();
  boxScreen = true;
  int gx = TOP_WIDTH == 400 ? 45 : 4, info = TOP_WIDTH == 400 ? 264 : 214,
      iw = TOP_WIDTH - info - 6;
  top().text("BANCO LOCAL", 8, 6, BLACK);
  top().rect(TOP_WIDTH - 143, 3, 143, 19, color(59, 99, 51));
  top().text(s.bank, TOP_WIDTH - 138, 6, WHITE, 19);
  top().image(assets::bar, gx, 22, 204, 26);
  top().centered(s.name, gx + 22, 28, 160, BLACK, 22);
  grid(top(), s, gx, 66, false);
  const auto &p = s.pokemon[s.cursor];
  top().rect(info, 43, iw, 171, color(225, 243, 216));
  if (p.occupied) {
    top().sprite(p.sprite, info + (iw - 68) / 2, 53, false, 2);
    top().centered(p.valid ? chestlink::speciesName(p.species) : "Registro",
                   info, 117, iw, BLACK, iw / 7);
    top().text("#" + std::to_string(p.species), info + 6, 135);
    top().text(std::string("Gen ") + chestlink::generationName(p.generation),
               info + 6, 151);
    top().text(p.egg ? "Ovo" : p.shiny ? "Shiny" : "Pokemon", info + 6, 167);
    if (p.form)
      top().text("Forma " + std::to_string(p.form), info + 6, 184);
  } else {
    top().centered("Vazio", info, 100, iw);
  }
  top().text("Box " + std::to_string(s.box + 1) + "/" + std::to_string(s.boxes),
             gx, 219, BLACK);
  top().text("Slot " + std::to_string(s.cursor + 1), info, 219, BLACK);
  bottom().image(assets::bar, 7, 15);
  bottom().centered(s.name, 26, 21, 162, BLACK, 22);
  grid(bottom(), s, 4, 45, true);
  std::string labels[] = {"A: Marcar", "Y: Box", "X: Todas", "START: Enviar",
                          "B: Voltar"};
  if (s.consult) {
    labels[1] = "Enviar PC";
    labels[2] = s.directLabel;
    labels[3].clear();
  }
  const char *viewLabels[] = {"A: Resumo", "L: Anterior", "R: Proxima", "",
                              "B: Voltar"};
  for (int i = 0; i < 5; ++i) {
    const std::string &label = s.view ? std::string(viewLabels[i]) : labels[i];
    if (!label.empty())
      button(bottom(), 212, 47 + i * 31, label);
  }
  bottom().image(assets::wireless, 3, 211);
  bottom().text(s.view ? "Modo de consulta"
                       : std::to_string(s.marked) + " slots / " +
                             std::to_string(s.markedBoxes) + " boxes",
                38, 211, BLACK, 33);
  bottom().text("L/R: trocar box", 38, 224, BLACK, 29);
  bottom().image(assets::back, 283, 211);
  show();
}
int boxHit(int x, int y) {
  if (x < 0 || y < 0 || x >= 320 || y >= 240)
    return -1;
  if (y >= 45 && y < 195 && x >= 4 && x < 208)
    return ((y - 45) / 30) * 6 + (x - 4) / 34;
  if (y >= 15 && y < 41 && x >= 7 && x < 29)
    return 30;
  if (y >= 15 && y < 41 && x >= 183 && x < 207)
    return 31;
  if (x >= 212 && y >= 47 && y < 202) {
    int i = (y - 47) / 31;
    if ((y - 47) % 31 < 28)
      return 32 + i;
  }
  if (x >= 283 && y >= 211)
    return 36;
  return -1;
}
void gameBoxes(const GameBoxesScreen &s) {
  background();
  header("COPIAR POKEMON DO SAVE");
  top().text("NOVA BOX DO CHEST LINK", 8, 49, BLACK,
             (TOP_WIDTH - 16) / 7);
  const int gx = TOP_WIDTH == 400 ? 45 : 4;
  drawPokemonGrid(top(), s.target, gx, 72, s.targetCursor);
  top().text(std::to_string(s.targetCount) + " Pokemon copiados",
             gx, 225, BLACK, 29);

  unsigned first = firstGameTab(s);
  for (unsigned i = first; i < std::min<unsigned>(first + 3, s.games.size()); ++i)
    button(bottom(), 8 + (i - first) * 68, 7, s.games[i], i == s.gameIndex, 64);
  bottom().image(assets::bar, 7, 37);
  bottom().centered(s.game, 28, 40, 175, BLACK, 24);
  bottom().centered(s.boxName + " " + std::to_string(s.box + 1) + "/" +
                        std::to_string(s.boxes),
                    28, 53, 175, BLACK, 24);
  drawPokemonGrid(bottom(), s.source, 4, 66, s.cursor);
  button(bottom(), 212, 66, "A: Copiar");
  button(bottom(), 212, 99, "Y: Box toda");
  button(bottom(), 212, 132, "START: Salvar");
  button(bottom(), 212, 165, "B: Voltar");
  bottom().text("L/R: box  X: jogo", 214, 213, BLACK, 15);
  bottom().text(s.status.empty() ? "Origem preservada" : s.status,
                8, 218, BLACK, 28);
  show();
}
int gameBoxesHit(const GameBoxesScreen &s, int x, int y) {
  if (x < 0 || y < 0 || x >= 320 || y >= 240) return -1;
  if (y >= 7 && y < 35 && x >= 8 && x < 212) {
    const unsigned first = firstGameTab(s);
    const unsigned tab = first + unsigned(x - 8) / 68;
    return tab < s.games.size() && unsigned(x - 8) / 68 < 3
               ? 40 + int(tab) : -1;
  }
  if (y >= 66 && y < 216 && x >= 4 && x < 208)
    return ((y - 66) / 30) * 6 + (x - 4) / 34;
  if (x >= 212 && y >= 66 && y < 193) {
    const int row = (y - 66) / 33;
    return row >= 0 && row < 4 && (y - 66) % 33 < 28 ? 30 + row : -1;
  }
  return -1;
}
} // namespace gui
