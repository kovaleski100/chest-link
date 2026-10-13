#pragma once
#include <nds/ndstypes.h>
#include <nds/sha1.h>
extern u32 test_reg_ime;
#define REG_IME test_reg_ime
int enterCriticalSection(void);
void leaveCriticalSection(int state);
void libndsCrash(const char *message);
void timerStop(unsigned timer);
#define LIBNDS_DEFAULT_TIMER_WIFI 3
typedef int cosema_t;
typedef int cothread_t;
typedef int comutex_t;
