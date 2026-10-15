// SPDX-License-Identifier: MIT
//
// Copyright (C) 2005-2006 Stephen Stair - sgstair@akkit.org - http://www.akkit.org
// Copyright (C) 2025 Antonio Niño Díaz

#include <string.h>

#include "arm7/debug.h"
#include "arm7/ipc.h"
#include "arm7/ntr/mac.h"
#include "arm7/ntr/registers.h"
#include "arm7/ntr/rx_queue.h"
#include "arm7/ntr/update.h"
#include "arm7/ntr/wpa.h"
#include "arm7/ntr/ieee_802_11/process.h"
#include "common/common_ntr_defs.h"
#include "common/ieee_defs.h"
#include "common/mac_addresses.h"

// This function tries to read up to "len" bytes from the RX queue in MAC RAM
// and writes them to the circular RX buffer shared with the ARM9.
//
// It returns -1 if there isn't enough space in the ARM9 buffer, 0 on success.
static int Wifi_RxArm9QueueAdd(u32 base, int size, const u8 *replacement)
{
    // Before the packet we will store a u32 with the total data size, so we
    // need to check that everything fits. Also, we need to ensure that a new
    // size will fit after this packet.
    size_t total_size = sizeof(u32) + round_up_32(size) + sizeof(u32);

    // TODO: Replace this by a mutex?
    int oldIME = enterCriticalSection();

    int alloc_idx = Wifi_RxBufferAllocBuffer(total_size);
    if (alloc_idx == -1)
    {
        WifiData->stats[WSTAT_RXQUEUEDLOST]++;
        leaveCriticalSection(oldIME);
        return -1;
    }

    u32 write_idx = alloc_idx;

    u8 *rxbufData = (u8 *)WifiData->rxbufData;

    // Skip writing the size until we've finished the packet
    u32 size_idx = write_idx;
    write_idx += sizeof(u32);

    // Write data
    if (replacement)
        memcpy(rxbufData + write_idx, replacement, size);
    else
        Wifi_MACRead((u16 *)(rxbufData + write_idx), base, 0, size);
    write_idx += size;

    // Mark the next block as empty, but don't move pointer so that the size of
    // the next block is written here eventually.
    write_idx = round_up_32(write_idx);
    write_u32(rxbufData + write_idx, 0);

    assert(write_idx <= (WIFI_RXBUFFER_SIZE - sizeof(u32)));

    WifiData->rxbufWrite = write_idx;

    // Now that the packet is finished, write real size of data without padding
    // or the size of the size tags
    write_u32(rxbufData + size_idx, size);

    leaveCriticalSection(oldIME);

    WifiData->stats[WSTAT_RXQUEUEDPACKETS]++;
    WifiData->stats[WSTAT_RXQUEUEDBYTES] += size;

    Wifi_CallSyncHandler();

    return 0;
}

static bool rejected_snapshot_seen;
static u32 rejected_snapshot_hash, rejected_snapshot_base;
static int rejected_snapshot_size;

void Wifi_RxQueueResetRejected(void)
{
    rejected_snapshot_seen = false;
}

// Locate a complete on-air frame using the little-endian IEEE CRC-32 trailer.
// This only finds its boundary; CRC is NOT an authentication mechanism.
// CCMP authentication and replay checks remain mandatory afterwards.
static int Wifi_RxFrameSizeFromFCS(const u8 *frame, int available)
{
    u32 crc = 0xFFFFFFFFu;
    for (int i = 0; i + 4 < available; ++i)
    {
        crc ^= frame[i];
        for (int bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1) ? 0xEDB88320u : 0);
        if (i + 1 >= HDR_DATA_MAC_SIZE + 16)
        {
            const u32 fcs = (u32)frame[i + 1] | ((u32)frame[i + 2] << 8) |
                            ((u32)frame[i + 3] << 16) | ((u32)frame[i + 4] << 24);
            if (~crc == fcs)
                return i + 1;
        }
    }
    return 0;
}

// Experimental NTR receive recovery. A rejected protected frame may have
// reached MAC RAM without committing WRCSR or raising RX_COMPLETE. This is
// NOT a documented raw-RX mode: actual byte delivery must be tested on a DS.
// Read only the uncommitted tail, never move either FIFO cursor, and require
// an unchanged snapshot plus the normal CCMP MIC/replay validation. If the
// chip did not store intact ciphertext, nothing is admitted to the IP stack.
static void Wifi_RxQueueRecoverRejected(void)
{
    if (WifiData->curAp.security_type != AP_SECURITY_WPA2 ||
        !Wifi_NTR_WpaIsReady() || (WifiData->reqFlags & WFLAG_REQ_PROMISC))
        return;

    const u32 cursor = W_RXBUF_WRCSR;
    if (cursor != W_RXBUF_READCSR)
        return; // Leave pending committed frames to the ordinary queue.
    const u32 base = cursor << 1;
    const u32 begin = W_RXBUF_BEGIN & 0x1FFE;
    const u32 end = W_RXBUF_END & 0x1FFE;
    if (end <= begin || base < begin || base >= end)
        return;

    // Rejected frames have NOT committed their hardware header. Its length
    // can still belong to the last accepted frame, or include FCS. First
    // inspect the fixed IEEE/CCMP header, then read a bounded RAM window and
    // look for an intact wire checksum, independent of that stale length.
    const int reported_size = Wifi_MACReadHWord(base, HDR_RX_IEEE_FRAME_SIZE);
    u8 frame[2504] __attribute__((aligned(4)));
    int available = end - begin - HDR_RX_SIZE - 4;
    if (available < HDR_DATA_MAC_SIZE + 20)
        return;
    if (available > (int)sizeof(frame))
        available = sizeof(frame);
    available &= ~1;

    // Direct halfword reads avoid DMA and don't alter the hardware read port.
    u16 *words = (u16 *)frame;
    for (int i = 0; i < (HDR_DATA_MAC_SIZE + 8) / 2; ++i)
        words[i] = Wifi_MACReadHWord(base, HDR_RX_SIZE + i * 2);

    const u16 fc = frame[0] | ((u16)frame[1] << 8);
    if ((fc & FC_TYPE_SUBTYPE_MASK) != TYPE_DATA ||
        !(fc & FC_PROTECTED_FRAME) ||
        (fc & (FC_FROM_DS | FC_TO_DS)) != FC_FROM_DS ||
        !Wifi_CmpMacAddr(frame + 10, WifiData->curAp.bssid) ||
        (!(frame[4] & 1) && !Wifi_CmpMacAddr(frame + 4, WifiData->MacAddr)))
        return;

    for (int i = (HDR_DATA_MAC_SIZE + 8) / 2; i < available / 2; ++i)
        words[i] = Wifi_MACReadHWord(base, HDR_RX_SIZE + i * 2);
    const int fcs_size = Wifi_RxFrameSizeFromFCS(frame, available);
    // Some receivers don't preserve FCS in RAM. In that case a fixed CTR
    // prefix can suggest a protocol length; it cannot authorize any data.
    // Only the subsequent full CCMP MIC/replay validation can do that.
    const int probed_size = fcs_size ? 0 : Wifi_NTR_WpaProbeRxSize(frame, available);
    const int size = fcs_size ? fcs_size : (probed_size ? probed_size : reported_size);
    WifiData->stats[WSTAT_NTR_RX_REPORTED_SIZE] = reported_size;
    WifiData->stats[WSTAT_NTR_RX_FRAME_SIZE] = size;
    if (size < HDR_DATA_MAC_SIZE + 16 || size > available - 4)
        return;

    // The radio runs independently of the CPU interrupt mask. Reject a
    // snapshot that changed while it was being copied, including wraparound.
    const int snapshot_size = size + (fcs_size ? 4 : 0);
    for (int i = 0; i < (snapshot_size + 1) / 2; ++i)
    {
        const u16 mask = (i * 2 + 1 < snapshot_size) ? 0xFFFF : 0x00FF;
        if ((Wifi_MACReadHWord(base, HDR_RX_SIZE + i * 2) & mask) != (words[i] & mask))
            return;
    }
    if (W_RXBUF_WRCSR != cursor || W_RXBUF_READCSR != cursor ||
        Wifi_MACReadHWord(base, HDR_RX_IEEE_FRAME_SIZE) != reported_size)
        return;

    // Avoid repeatedly decrypting an unchanged stale/partial RAM image.
    // This is only a work limiter, not an authentication decision.
    u32 hash = 2166136261u;
    for (int i = 0; i < size; ++i)
        hash = (hash ^ frame[i]) * 16777619u;
    if (rejected_snapshot_seen && rejected_snapshot_base == base &&
        rejected_snapshot_size == size && rejected_snapshot_hash == hash)
        return;
    rejected_snapshot_seen = true;
    rejected_snapshot_base = base;
    rejected_snapshot_size = size;
    rejected_snapshot_hash = hash;

    WifiData->stats[WSTAT_NTR_RX_RAM_CANDIDATES]++;
    if (fcs_size)
        WifiData->stats[WSTAT_NTR_RX_FCS_BOUNDARY]++;
    size_t plain_size = 0;
    if (!Wifi_NTR_WpaProcessRx(frame, size, frame, sizeof(frame), &plain_size))
        return;
    if (Wifi_RxArm9QueueAdd(0, plain_size, frame) == 0)
        Wifi_NTR_KeepaliveCountReset();
}

void Wifi_RxQueueFlush(void)
{
    int oldIME = enterCriticalSection();

    int cut = 0;

    while (W_RXBUF_WRCSR != W_RXBUF_READCSR)
    {
        int base           = W_RXBUF_READCSR << 1;

        int packetlen      = Wifi_MACReadHWord(base, HDR_RX_IEEE_FRAME_SIZE);
        int full_packetlen = HDR_RX_SIZE + round_up_32(packetlen);

        WifiData->stats[WSTAT_RXPACKETS]++;
        WifiData->stats[WSTAT_RXBYTES] += full_packetlen;
        WifiData->stats[WSTAT_RXDATABYTES] += full_packetlen - HDR_RX_SIZE;

        // First, process the received frame in the ARM7. In some cases the ARM7
        // can handle the frame type by itself (e.g. frames of beacon type,
        // WFLAG_PACKET_BEACON).
        //
        // We need to pass the hardware header to this function, not just the
        // IEEE 802.11 header.
        int type = Wifi_ProcessReceivedFrame(base, full_packetlen);
        // Normally, only send data packets to the ARM9. If promiscuous mode is
        // enabled, send everything. WPA2 frames are authenticated/decrypted
        // here because the NTR radio has no CCMP engine.
        bool forward = (type & WFLAG_PACKET_DATA) != 0;
        const bool promiscuous = (WifiData->reqFlags & WFLAG_REQ_PROMISC) != 0;
        u8 frame[2500] __attribute__((aligned(4)));
        const u8 *replacement = NULL;
        int forwarded_size = packetlen;

        if (promiscuous)
            forward = true;
        else if (forward && WifiData->curAp.security_type == AP_SECURITY_WPA2)
        {
            if (packetlen <= (int)sizeof(frame))
            {
                Wifi_MACRead((u16 *)frame, base, HDR_RX_SIZE, packetlen);
                size_t plain_size = 0;
                forward = Wifi_NTR_WpaProcessRx(frame, packetlen, frame,
                                                sizeof(frame), &plain_size);
                if (forward)
                {
                    replacement = frame;
                    forwarded_size = plain_size;
                }
            }
            else
            {
                forward = false;
            }
        }

        if (forward || promiscuous)
        {
            // If the packet type is requested by the ARM9 (or promiscous mode
            // is enabled), forward it to the ARM9 RX queue. In this case we can
            // skip the hardware RX header.
            Wifi_NTR_KeepaliveCountReset();
            if (Wifi_RxArm9QueueAdd(base + HDR_RX_SIZE, forwarded_size,
                                    replacement) == -1)
            {
                // Failed, ignore for now.
                // TODO: Handle this somehow
            }
        }

        base += full_packetlen;
        if (base >= (W_RXBUF_END & 0x1FFE))
            base -= (W_RXBUF_END & 0x1FFE) - (W_RXBUF_BEGIN & 0x1FFE);
        W_RXBUF_READCSR = base >> 1;

        // Don't handle too many packets in one go
        if (cut++ > WIFI_RX_PACKETS_PER_INTERRUPT)
            break;
    }

    Wifi_RxQueueRecoverRejected();
    leaveCriticalSection(oldIME);
}
