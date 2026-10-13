/* The NTR WPA2 supplicant runs in DS mode. Its crypto routines must be in
 * the normal ARM7 image; TWL sections are only loaded in DSi mode. */
ASSERT(wpa_mbedtls_init >= __arm7_start__ && wpa_mbedtls_init < __arm7_end__,
       "DS WPA2: crypto allocator is in a DSi-only section");
ASSERT(wpa_calc_pmk >= __arm7_start__ && wpa_calc_pmk < __arm7_end__,
       "DS WPA2: password derivation is in a DSi-only section");
ASSERT(wpa_calc_ptk >= __arm7_start__ && wpa_calc_ptk < __arm7_end__,
       "DS WPA2: pairwise key derivation is in a DSi-only section");
ASSERT(wpa_calc_mic >= __arm7_start__ && wpa_calc_mic < __arm7_end__,
       "DS WPA2: handshake authentication is in a DSi-only section");
ASSERT(wpa_decrypt_gtk >= __arm7_start__ && wpa_decrypt_gtk < __arm7_end__,
       "DS WPA2: group key decryption is in a DSi-only section");
ASSERT(mbedtls_sha1_starts >= __arm7_start__ && mbedtls_sha1_starts < __arm7_end__,
       "DS WPA2: SHA-1 is in a DSi-only section");
ASSERT(mbedtls_aes_crypt_ecb >= __arm7_start__ && mbedtls_aes_crypt_ecb < __arm7_end__,
       "DS WPA2: AES is in a DSi-only section");
ASSERT(Wifi_NTR_CcmpProbePayloadLength >= __arm7_start__ && Wifi_NTR_CcmpProbePayloadLength < __arm7_end__,
       "DS WPA2: RX length probe is in a DSi-only section");
