// Exercise the real NTR transmit-completion retry path with mocked MAC RAM.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "arm7/ipc.h"
#include "arm7/ntr/registers.h"

static u16 registers[0x8000 / 2];
static u16 *reg_address(unsigned offset)
{
    if ((offset & 1) || offset / 2 >= sizeof(registers) / sizeof(registers[0]))
        abort();
    return &registers[offset / 2];
}

#undef WIFI_REG
#define WIFI_REG(ofs) (*reg_address((ofs) & 0x7FFF))
#include "../third_party/dswifi/source/arm7/ntr/tx_queue.c"

volatile Wifi_MainStruct wifi;
volatile Wifi_MainStruct *WifiData = &wifi;

static unsigned checks, failures;
#define CHECK(condition) do { \
    ++checks; \
    if (!(condition)) { \
        fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
        ++failures; \
    } \
} while (0)

static void setup_frame(bool tracked_ack)
{
    memset(registers, 0, sizeof(registers));
    memset((void *)&wifi, 0, sizeof(wifi));
    W_MACMEM(MAC_TXBUF_START_OFFSET + HDR_TX_SIZE + HDR_DATA_FRAME_CONTROL) =
        TYPE_DATA | FC_PROTECTED_FRAME;
    Wifi_NTR_TxNotifyStart(true, tracked_ack);
}

static void test_ack_retry_limit(void)
{
    setup_frame(true);
    for (unsigned retry = 1; retry <= 2; ++retry)
    {
        W_MACMEM(MAC_TXBUF_START_OFFSET + HDR_TX_STATUS) = 5;
        W_TXSTAT = 0xA500 | retry;
        CHECK(Wifi_NTR_TxOnComplete());
        CHECK(W_MACMEM(MAC_TXBUF_START_OFFSET + HDR_TX_STATUS) == 0);
        CHECK(W_MACMEM(MAC_TXBUF_START_OFFSET + HDR_TX_SIZE +
                       HDR_DATA_FRAME_CONTROL) & FC_RETRY);
        CHECK(W_TXBUF_LOC3 ==
              (TXBUF_LOCN_ENABLE | (MAC_TXBUF_START_OFFSET >> 1)));
        CHECK(W_TXREQ_SET == (TXBIT_LOC3 | TXBIT_LOC2 | TXBIT_LOC1));
        CHECK(WifiData->stats[WSTAT_NTR_ACK_TX_RETRIES] == retry);
    }

    // The known NTR failure code is retried twice in software; after that,
    // release the queue instead of retrying forever.
    W_MACMEM(MAC_TXBUF_START_OFFSET + HDR_TX_STATUS) = 5;
    W_TXSTAT = 0xA503;
    CHECK(!Wifi_NTR_TxOnComplete());
    CHECK(WifiData->stats[WSTAT_NTR_TX_COMPLETIONS] == 3);
    CHECK(WifiData->stats[WSTAT_NTR_TX_HEADER_STATUS] == 5);
    CHECK(WifiData->stats[WSTAT_NTR_TX_RAW_STATUS] == 0xA503);
    CHECK(WifiData->stats[WSTAT_NTR_ACK_TX_FAILURES] == 3);
    CHECK(WifiData->stats[WSTAT_NTR_ACK_TX_RETRIES] == 2);
    CHECK(WifiData->stats[WSTAT_NTR_ACK_TX_RETRY_LIMIT] == 1);
    CHECK(!Wifi_NTR_TxOnComplete()); // A retired frame is never replayed.
}

static void test_untracked_and_non_wpa2(void)
{
    setup_frame(false);
    W_MACMEM(MAC_TXBUF_START_OFFSET + HDR_TX_STATUS) = 5;
    CHECK(Wifi_NTR_TxOnComplete());
    CHECK(WifiData->stats[WSTAT_NTR_ACK_TX_FAILURES] == 0);

    Wifi_NTR_TxNotifyStart(false, true);
    W_MACMEM(MAC_TXBUF_START_OFFSET + HDR_TX_STATUS) = 5;
    CHECK(!Wifi_NTR_TxOnComplete());
    CHECK(WifiData->stats[WSTAT_NTR_ACK_TX_RETRIES] == 0);
}

int main(void)
{
    test_ack_retry_limit();
    test_untracked_and_non_wpa2();
    printf("NTR WPA2 TX retry: %u checks, %u failures\n", checks, failures);
    return failures ? 1 : 0;
}
