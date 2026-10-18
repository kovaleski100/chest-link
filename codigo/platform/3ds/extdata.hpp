#pragma once
#include <cstdint>
#include <string>
bool mountPKSM();
void unmountPKSM();
void commitPKSM();
bool allocatePKSM(const std::string &, uint32_t);
