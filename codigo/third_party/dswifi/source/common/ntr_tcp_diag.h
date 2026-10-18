// SPDX-License-Identifier: MIT
// NTR transport diagnostics: counters and TCP headers only, never payloads.
#ifndef DSWIFI_COMMON_NTR_TCP_DIAG_H__
#define DSWIFI_COMMON_NTR_TCP_DIAG_H__

#include <string.h>
#include "common/wifi_shared.h"
#include "common/ieee_defs.h"

typedef struct
{
    u32 seq, ack;
    u16 src, dst, payload;
    u8 flags;
} Wifi_NTR_TcpInfo;

static inline u32 Wifi_NTR_ReadNetwork32(const u8 *p)
{
    return ((u32)p[0] << 24) | ((u32)p[1] << 16) | ((u32)p[2] << 8) | p[3];
}

// These are observations of headers, not checksum/admission decisions.
static inline bool Wifi_NTR_TcpFromIP(const u8 *ip, size_t size,
                                     Wifi_NTR_TcpInfo *info)
{
    if (size < 40 || (ip[0] >> 4) != 4 || ip[9] != 6 ||
        (ip[6] & 0x3F) || ip[7])
        return false;
    const size_t ihl = (ip[0] & 15) * 4;
    const size_t total = ((u16)ip[2] << 8) | ip[3];
    if (ihl < 20 || total > size || total < ihl + 20)
        return false;
    const u8 *tcp = ip + ihl;
    const size_t thl = (tcp[12] >> 4) * 4;
    if (thl < 20 || thl > total - ihl)
        return false;
    info->src = ((u16)tcp[0] << 8) | tcp[1];
    info->dst = ((u16)tcp[2] << 8) | tcp[3];
    info->seq = Wifi_NTR_ReadNetwork32(tcp + 4);
    info->ack = Wifi_NTR_ReadNetwork32(tcp + 8);
    info->flags = tcp[13];
    info->payload = total - ihl - thl;
    return true;
}

static inline bool Wifi_NTR_TcpFromWifi(const u8 *frame, size_t size,
                                       bool tx_ccmp_space, Wifi_NTR_TcpInfo *info)
{
    if (size < 24)
        return false;
    const u16 fc = frame[0] | ((u16)frame[1] << 8);
    const bool qos = Wifi_IsQosDataFrame(fc);
    const size_t header = 24 + (qos ? 2 : 0) +
                          (qos && (fc & FC_ORDER) ? 4 : 0) +
                          (tx_ccmp_space ? 8 : 0);
    static const u8 snap[] = {0xAA, 0xAA, 3, 0, 0, 0, 8, 0};
    if (!Wifi_IsDataPayloadFrame(fc) || size < header + sizeof(snap) ||
        memcmp(frame + header, snap, sizeof(snap)))
        return false;
    return Wifi_NTR_TcpFromIP(frame + header + sizeof(snap),
                              size - header - sizeof(snap), info);
}

static inline bool Wifi_NTR_TcpIsTrackedAck(volatile Wifi_MainStruct *wifi,
                                           const Wifi_NTR_TcpInfo *info)
{
    return info->payload == 0 && (info->flags & 0x17) == 0x10 &&
           info->src == wifi->stats[WSTAT_NTR_TCP_LOCAL_PORT] &&
           info->dst == wifi->stats[WSTAT_NTR_TCP_REMOTE_PORT];
}
#endif
