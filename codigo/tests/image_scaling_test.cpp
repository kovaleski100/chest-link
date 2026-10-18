// Compare the renderer's sampling against its original integer formula.
#include "../source/graphics.cpp"
#include <cassert>
#include <iostream>
#include <vector>

int main() {
  unsigned cases = 0;
  for (const auto &size : {std::pair{7, 5}, {400, 240}, {320, 240}, {16, 28}}) {
    std::vector<uint16_t> source(size.first * size.second);
    for (size_t i = 0; i < source.size(); ++i)
      source[i] = uint16_t((i * 37) & 0x7FFF) | (i % 5 ? 0x8000 : 0);
    const gui::assets::Image image{unsigned(size.first), unsigned(size.second), source.data()};
    for (const auto &scale : {std::pair{1, 1}, {12, 7}, {320, 240}, {400, 240}, {68, 60}}) {
      for (const auto &origin : {std::pair{0, 0}, {-3, -2}, {390, 235}}) {
        std::vector<uint16_t> expected(400 * 240, 0x9234), actual = expected;
        for (int y = 0; y < scale.second; ++y)
          for (int x = 0; x < scale.first; ++x) {
            const uint16_t color = source[(y * size.second / scale.second) * size.first +
                                           x * size.first / scale.first];
            const int dx = x + origin.first, dy = y + origin.second;
            if ((color & 0x8000) && dx >= 0 && dx < 400 && dy >= 0 && dy < 240)
              expected[dy * 400 + dx] = color;
          }
        gui::Canvas{actual.data(), 400}.image(image, origin.first, origin.second,
                                            scale.first, scale.second);
        assert(actual == expected);
        ++cases;
      }
    }
  }
  std::cout << "PASS image scaling: " << cases << " pixel-identical size/clip/transparency cases\n";
}
