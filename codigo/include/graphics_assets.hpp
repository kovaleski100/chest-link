#pragma once
#include <cstdint>
namespace gui::assets {
struct Image {
  unsigned width, height;
  const uint16_t *pixels;
};
extern const Image top, bottom, bar, button, back, wireless, pointer;
extern const uint8_t font[224][12];
extern const uint8_t fontSmall[224][10];
extern const uint16_t spritePalette[];
extern const uint8_t
    spritePixels[]; // 4bpp, 34x30; transparent palette index zero.
extern const unsigned spriteCount;
} // namespace gui::assets
