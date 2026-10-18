// SPDX-License-Identifier: MIT
//
// Copyright (C) 2005-2006 Stephen Stair - sgstair@akkit.org - http://www.akkit.org
// Copyright (C) 2025 Antonio Niño Díaz

#include <limits.h>
#include <string.h>

#include "arm7/access_point.h"
#include "arm7/debug.h"
#include "arm7/ipc.h"
#include "arm7/ntr/mac.h"
#include "arm7/ntr/registers.h"
#include "arm7/ntr/tx_queue.h"
#include "arm7/ntr/ieee_802_11/header.h"
#include "common/common_ntr_defs.h"
#include "common/ieee_defs.h"
#include "common/mac_addresses.h"
#include "common/spinlock.h"
#include "common/wifi_shared.h"

static bool Wifi_IsVendorMicrosoft(u8 *data, size_t len)
{
    if (len >= 14)
    {
        // Microsoft OUI
        if ((data[0] == 0x00) && (data[1] == 0x50) && (data[2] == 0xF2) &&
            (data[3] == 0x01) &&
            // Version number
            (data[4] == 0x01) && (data[5] == 0x00))
        {
            return true;
        }
    }

    return false;
}

static bool Wifi_IsVendorNintendo(u8 *data, size_t len)
{
    if (len >= sizeof(FieVendorNintendo))
    {
        // Nintendo OUI
        if ((data[0] == 0x00) && (data[1] == 0x09) && (data[2] == 0xBF) &&
            (data[3] == 0x00))
        {
            return true;
        }
    }

    return false;
}

static void Wifi_ProcessVendorTag(u8 *data, size_t len, bool *has_nintendo_info,
                                  Wifi_ApSecurityType *sec_type,
                                  Wifi_NintendoVendorInfo *info)
{
    if (Wifi_IsVendorMicrosoft(data, len))
    {
        // WPA IE type 1 version 1

        size_t j = 4 + 2 + 4; // Skip magic, version and multicast cipher suite

        u16 num_uni_ciphers = data[j] + (data[j + 1] << 8);
        j += 2;

        // Check group cipher suites
        while (num_uni_ciphers && (j <= (len - 4)))
        {
            num_uni_ciphers--;

            // Check magic numbers in first 3 bytes
            if (data[j] == 0x00 && data[j + 1] == 0x50 && data[j + 2] == 0xF2)
            {
                j += 3; // Skip magic numbers

                switch (data[j++])
                {
                    case 2: // TKIP
                    case 3: // AES WRAP
                    case 4: // AES CCMP
                        if (*sec_type != AP_SECURITY_WPA2)
                            *sec_type = AP_SECURITY_WPA;
                        break;
                    case 1: // WEP64
                    case 5: // WEP128
                        *sec_type = AP_SECURITY_WEP;
                    default:
                        // Others: Reserved/Ignored
                        break;
                }
            }
        }

        return;
    }

    if (Wifi_IsVendorNintendo(data, len))
    {
        *has_nintendo_info = true;

        FieVendorNintendo *fie = (void *)data;

        info->game_id = (fie->game_id[0] << 24) | (fie->game_id[1] << 16) |
                        (fie->game_id[2] << 8) | (fie->game_id[3] << 0);

        info->players_max = fie->extra_data.players_max;
        info->players_current = fie->extra_data.players_current;
        info->allows_connections = fie->extra_data.allows_connections;

        info->name_len = fie->extra_data.name_len;
        for (u8 i = 0; i < DSWIFI_BEACON_NAME_SIZE / sizeof(u16); i++)
        {
            info->name[i] = fie->extra_data.name[i * 2]
                          | (fie->extra_data.name[(i * 2) + 1] << 8);
        }

        return;
    }
}

void Wifi_ProcessBeaconOrProbeResponse(Wifi_RxHeader *packetheader, int macbase)
{
    u8 data[512];

    //WLOG_PUTS("W: [R] Beacon/ProbeResp\n");

    u32 datalen = packetheader->byteLength;
    if (datalen > 512)
        datalen = 512;

    // Read IEEE frame, right after the hardware RX header
    Wifi_MACRead((u16 *)data, macbase, HDR_RX_SIZE, (datalen + 1) & ~1);

    // Information about the data rates
    bool compatible = true; // Assume that the AP is compatible

    Wifi_ApSecurityType sec_type = AP_SECURITY_OPEN;
    Wifi_ApCryptType group_crypt_type = AP_CRYPT_NONE;
    Wifi_ApCryptType pair_crypt_type = AP_CRYPT_NONE;
    Wifi_ApAuthType auth_type = AP_AUTH_NONE;
    // RSN IE advertised by this client. Never echo the AP's beacon IE: its
    // capabilities describe the AP (and may claim PMF support we do not have).
    static const u8 client_rsn_ie[] = {
        MGT_FIE_ID_RSN, 20,
        0x01, 0x00,                         // RSN version
        0x00, 0x0F, 0xAC, 0x04,             // Group cipher: CCMP
        0x01, 0x00, 0x00, 0x0F, 0xAC, 0x04,// Pairwise cipher: CCMP
        0x01, 0x00, 0x00, 0x0F, 0xAC, 0x02,// AKM: PSK
        0x00, 0x00                          // Capabilities: no PMF
    };
    u8 rsn_ie[sizeof(client_rsn_ie)] = {0};
    size_t rsn_ie_len = 0;
    bool rsn_supported = false;

    Wifi_NintendoVendorInfo nintendo_info;
    bool has_nintendo_info = false;

    // Capability info, WEP bit. It goes after the 8 byte timestamp and the 2
    // byte beacon interval.
    u32 caps_index = HDR_MGT_MAC_SIZE + 8 + 2;
    if (*(u16 *)(data + caps_index) & CAPS_PRIVACY)
        sec_type = AP_SECURITY_WEP;

    u16 ptr_ssid = 0;

    // Assume that the channel of the AP is the current one
    u8 channel = WifiData->curChannel;

    // Pointer we're going to use to iterate through the frame. Get a pointer to
    // the field right after the capabilities field.
    u32 curloc = caps_index + 2;

    while (1)
    {
        if (curloc >= datalen)
            break;

        u32 segtype = data[curloc++];
        u32 seglen  = data[curloc++];

        if (seglen > datalen - curloc)
            break;

        switch (segtype)
        {
            case MGT_FIE_ID_SSID: // SSID element
                ptr_ssid = curloc - 2;
                break;

            case MGT_FIE_ID_SUPPORTED_RATES: // Rate set
            {
                compatible = false;

                // Read the list of rates and look for some specific frequencies
                for (unsigned int i = 0; i < seglen; i++)
                {
                    u8 thisrate = data[curloc + i];

                    if ((thisrate == (RATE_MANDATORY | RATE_1_MBPS)) ||
                        (thisrate == (RATE_MANDATORY | RATE_2_MBPS)))
                    {
                        // 1, 2 Mbit: Fully compatible
                        compatible = true;
                    }
                    else if ((thisrate == (RATE_MANDATORY | RATE_5_5_MBPS)) ||
                             (thisrate == (RATE_MANDATORY | RATE_11_MBPS)))
                    {
                        // 5.5, 11 Mbit: This will be present in an AP
                        // compatible with the 802.11b standard. We can still
                        // try to connect to this AP, but we need to be lucky
                        // and hope that the AP uses the NDS rates.
                        compatible = true;
                    }
                    else if (thisrate & RATE_MANDATORY)
                    {
                        compatible = false;
                        break;
                    }
                }
                break;
            }

            case MGT_FIE_ID_DS_PARAM_SET: // DS set (current channel)
                channel = data[curloc];
                break;

            case MGT_FIE_ID_RSN: // RSN(A) field- WPA enabled.
            {
                // Parse the WPA2-Personal/CCMP subset supported by the NTR
                // supplicant and retain the exact RSN IE for the handshake.
                const u8 *rsn = data + curloc;
                size_t pos = 0;
                bool group_ccmp = false;
                bool pair_ccmp = false;
                bool psk = false;

                if (seglen >= 8 && rsn[0] == 1 && rsn[1] == 0)
                {
                    pos = 2;
                    group_ccmp = rsn[pos] == 0x00 && rsn[pos + 1] == 0x0F &&
                                 rsn[pos + 2] == 0xAC && rsn[pos + 3] == 4;
                    pos += 4;

                    const size_t pair_count = rsn[pos] | ((size_t)rsn[pos + 1] << 8);
                    pos += 2;
                    if (pair_count <= (seglen - pos) / 4)
                    {
                        for (size_t i = 0; i < pair_count; ++i)
                        {
                            const u8 *suite = rsn + pos + i * 4;
                            if (suite[0] == 0x00 && suite[1] == 0x0F &&
                                suite[2] == 0xAC && suite[3] == 4)
                                pair_ccmp = true;
                        }
                        pos += pair_count * 4;

                        if (pos + 2 <= seglen)
                        {
                            const size_t auth_count = rsn[pos] |
                                ((size_t)rsn[pos + 1] << 8);
                            pos += 2;
                            if (auth_count <= (seglen - pos) / 4)
                            {
                                for (size_t i = 0; i < auth_count; ++i)
                                {
                                    const u8 *suite = rsn + pos + i * 4;
                                    if (suite[0] == 0x00 && suite[1] == 0x0F &&
                                        suite[2] == 0xAC && suite[3] == 2)
                                        psk = true;
                                }
                                pos += auth_count * 4;

                                bool pmf_required = false;
                                if (pos + 2 <= seglen)
                                {
                                    const u16 capabilities = rsn[pos] |
                                        ((u16)rsn[pos + 1] << 8);
                                    pmf_required = (capabilities & BIT(6)) != 0;
                                }

                                sec_type = AP_SECURITY_WPA2;
                                group_crypt_type = group_ccmp ? AP_CRYPT_AES : AP_CRYPT_NONE;
                                pair_crypt_type = pair_ccmp ? AP_CRYPT_AES : AP_CRYPT_NONE;
                                auth_type = psk ? AP_AUTH_PSK : AP_AUTH_8021X;
                                rsn_supported = group_ccmp && pair_ccmp && psk && !pmf_required;

                                if (rsn_supported)
                                {
                                    memcpy(rsn_ie, client_rsn_ie,
                                           sizeof(client_rsn_ie));
                                    rsn_ie_len = sizeof(client_rsn_ie);
                                }
                            }
                        }
                    }
                }
                break;
            }

            case MGT_FIE_ID_VENDOR: // Vendor specific
            {
                Wifi_ProcessVendorTag(data + curloc, seglen, &has_nintendo_info,
                                      &sec_type, &nintendo_info);
                break;
            }

            default:
                // Don't care about the others.
                break;
        }

        curloc += seglen;
    }

    if (sec_type == AP_SECURITY_WEP)
    {
        group_crypt_type = AP_CRYPT_WEP;
        pair_crypt_type = AP_CRYPT_WEP;
        auth_type = AP_AUTH_NONE;
    }
    else if ((sec_type == AP_SECURITY_WPA) || (sec_type == AP_SECURITY_WPA2))
    {
        if (sec_type != AP_SECURITY_WPA2 || !rsn_supported || !rsn_ie_len)
            compatible = false;
    }

    // Apply filters to the AP list
    {
        bool keep = false;

        if (compatible)
        {
            if (WifiData->curApScanFlags & WSCAN_LIST_AP_COMPATIBLE)
                keep = true;
        }
        else
        {
            if (WifiData->curApScanFlags & WSCAN_LIST_AP_INCOMPATIBLE)
                keep = true;
        }

        if (has_nintendo_info)
        {
            if (WifiData->curApScanFlags & WSCAN_LIST_NDS_HOSTS)
                keep = true;
            else
                keep = false;
        }

        if (!keep)
            return;
    }

    const u8 *ssid_ptr = NULL;
    size_t ssid_len = 0;

    if (ptr_ssid)
    {
        ssid_len = data[ptr_ssid + 1];
        ssid_ptr = &data[ptr_ssid + 2];
    }

    int rssi = INT_MIN;
    // Only use the RSSI value when we're on the same channel
    if (WifiData->curChannel == channel)
        rssi = packetheader->rssi_ & 255;

    Wifi_AccessPointAdd(data + HDR_MGT_BSSID, data + HDR_MGT_SA,
                        ssid_ptr, ssid_len, channel, rssi, sec_type,
                        group_crypt_type, pair_crypt_type, auth_type,
                        compatible, has_nintendo_info ? &nintendo_info : NULL,
                        rsn_ie_len ? rsn_ie : NULL, rsn_ie_len);

    //WLOG_FLUSH();
}
