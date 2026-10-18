#pragma once
#include <cstdint>
using u32 = uint32_t;
using Result = int32_t;
#define R_SUCCEEDED(result) ((result) >= 0)
#define R_FAILED(result) ((result) < 0)
Result acInit();
void acExit();
Result socInit(u32 *, u32);
void socExit();
Result ACU_GetStatus(u32 *);
Result ACU_GetWifiStatus(u32 *);
Result ACU_GetSSIDLength(u32 *);
Result ACU_GetSSID(char *);
