// SPDX-License-Identifier: MIT
// WPA2-Personal support for the legacy NTR radio path.

#ifndef DSWIFI_ARM7_NTR_WPA_H__
#define DSWIFI_ARM7_NTR_WPA_H__

#include <stdbool.h>
#include <stddef.h>

#include <nds/ndstypes.h>
#include <dswifi_common.h>

// Each byte gives the number of halfwords removed from the RX size field:
// low byte for clear frames, high byte for Protected frames. Software CCMP
// needs its IV and MIC intact; only the four-byte hardware FCS is excluded.
static inline u16 Wifi_NTR_RxCropForSecurity(Wifi_ApSecurityType security)
{
    return security == AP_SECURITY_WPA2 ? 0x0202 : 0x0602;
}

void Wifi_NTR_WpaReset(void);
bool Wifi_NTR_WpaPrepareConnection(void);
void Wifi_NTR_WpaAssociationComplete(void);
bool Wifi_NTR_WpaIsReady(void);
bool Wifi_NTR_WpaEncryptTx(u8 *frame, size_t frame_len);
// Size probe only. Its result is untrusted until WpaProcessRx validates MIC.
size_t Wifi_NTR_WpaProbeRxSize(const u8 *frame, size_t available);
bool Wifi_NTR_WpaProcessRx(const u8 *frame, size_t frame_len,
                           u8 *output, size_t output_capacity,
                           size_t *output_len);

#endif
