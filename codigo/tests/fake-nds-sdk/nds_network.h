#pragma once

#include <unistd.h>

#define closesocket(fd) ::close(fd)
