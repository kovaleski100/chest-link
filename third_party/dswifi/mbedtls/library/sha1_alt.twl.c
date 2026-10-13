// SPDX-License-Identifier: MIT
//
// Copyright (C) 2026 Adrian "asie" Siekierka

#include "common.h"
#include <mbedtls/sha1.h>
#include <string.h>

#if defined(MBEDTLS_SHA1_ALT)

#include "arm7/ipc.h"

static bool sha1_use_dsi_bios(void)
{
    return WifiData && (WifiData->reqFlags & WFLAG_REQ_DSI_MODE);
}

static u32 sha1_rotate_left(u32 value, unsigned count)
{
    return (value << count) | (value >> (32 - count));
}

static void sha1_software_process(mbedtls_sha1_context *ctx, const u8 data[64])
{
    u32 words[80];
    for (size_t i = 0; i < 16; ++i)
    {
        const size_t offset = i * 4;
        words[i] = ((u32)data[offset] << 24) |
                   ((u32)data[offset + 1] << 16) |
                   ((u32)data[offset + 2] << 8) | data[offset + 3];
    }
    for (size_t i = 16; i < 80; ++i)
        words[i] = sha1_rotate_left(words[i - 3] ^ words[i - 8] ^
                                    words[i - 14] ^ words[i - 16], 1);

    u32 a = ctx->state[0];
    u32 b = ctx->state[1];
    u32 c = ctx->state[2];
    u32 d = ctx->state[3];
    u32 e = ctx->state[4];
    for (size_t i = 0; i < 80; ++i)
    {
        u32 function, constant;
        if (i < 20)
        {
            function = (b & c) | (~b & d);
            constant = 0x5A827999;
        }
        else if (i < 40)
        {
            function = b ^ c ^ d;
            constant = 0x6ED9EBA1;
        }
        else if (i < 60)
        {
            function = (b & c) | (b & d) | (c & d);
            constant = 0x8F1BBCDC;
        }
        else
        {
            function = b ^ c ^ d;
            constant = 0xCA62C1D6;
        }

        const u32 next = sha1_rotate_left(a, 5) + function + e + constant + words[i];
        e = d;
        d = c;
        c = sha1_rotate_left(b, 30);
        b = a;
        a = next;
    }

    ctx->state[0] += a;
    ctx->state[1] += b;
    ctx->state[2] += c;
    ctx->state[3] += d;
    ctx->state[4] += e;
}

static int sha1_software_update(mbedtls_sha1_context *ctx,
                                const unsigned char *input, size_t length)
{
    if (length == 0)
        return 0;

    const u32 previous = ctx->total[0];
    ctx->total[0] += (u32)length;
    if (ctx->total[0] < previous)
        ctx->total[1]++;

    size_t left = previous & 0x3F;
    if (left)
    {
        const size_t fill = 64 - left;
        const size_t count = length < fill ? length : fill;
        memcpy(ctx->buffer + left, input, count);
        input += count;
        length -= count;
        if (count == fill)
        {
            sha1_software_process(ctx, ctx->buffer);
            left = 0;
        }
    }

    while (length >= 64)
    {
        sha1_software_process(ctx, input);
        input += 64;
        length -= 64;
    }
    if (length)
        memcpy(ctx->buffer + left, input, length);
    return 0;
}

void mbedtls_sha1_init(mbedtls_sha1_context *ctx) {
    ctx->sha_block = NULL;
}

void mbedtls_sha1_free(mbedtls_sha1_context *ctx) {
    if (!ctx)
        return;
    volatile u8 *bytes = (volatile u8 *)ctx;
    for (size_t i = 0; i < sizeof(*ctx); ++i)
        bytes[i] = 0;
}

void mbedtls_sha1_clone(mbedtls_sha1_context *dst,
                        const mbedtls_sha1_context *src) {
    memcpy(dst, src, sizeof(mbedtls_sha1_context));
}

int mbedtls_sha1_starts(mbedtls_sha1_context *ctx) {
    if (sha1_use_dsi_bios())
    {
        swiSHA1Init(ctx);
        return 0;
    }

    ctx->state[0] = 0x67452301;
    ctx->state[1] = 0xEFCDAB89;
    ctx->state[2] = 0x98BADCFE;
    ctx->state[3] = 0x10325476;
    ctx->state[4] = 0xC3D2E1F0;
    ctx->total[0] = 0;
    ctx->total[1] = 0;
    ctx->fragment_size = 0;
    ctx->sha_block = NULL;
    return 0;
}

int mbedtls_sha1_update(mbedtls_sha1_context *ctx,
                        const unsigned char *input,
                        size_t ilen) {
    if (sha1_use_dsi_bios())
        swiSHA1Update(ctx, input, ilen);
    else
        return sha1_software_update(ctx, input, ilen);
    return 0;
}

int mbedtls_sha1_finish(mbedtls_sha1_context *ctx,
                        unsigned char output[20]) {
    if (sha1_use_dsi_bios())
    {
        swiSHA1Final(output, ctx);
        return 0;
    }

    const u32 high = (ctx->total[0] >> 29) | (ctx->total[1] << 3);
    const u32 low = ctx->total[0] << 3;
    const size_t last = ctx->total[0] & 0x3F;
    const size_t padding_length = last < 56 ? 56 - last : 120 - last;
    const u8 padding[64] = {0x80};
    u8 bit_length[8];
    sha1_software_update(ctx, padding, padding_length);
    bit_length[0] = high >> 24;
    bit_length[1] = high >> 16;
    bit_length[2] = high >> 8;
    bit_length[3] = high;
    bit_length[4] = low >> 24;
    bit_length[5] = low >> 16;
    bit_length[6] = low >> 8;
    bit_length[7] = low;
    sha1_software_update(ctx, bit_length, sizeof(bit_length));

    for (size_t i = 0; i < 5; ++i)
    {
        output[i * 4] = ctx->state[i] >> 24;
        output[i * 4 + 1] = ctx->state[i] >> 16;
        output[i * 4 + 2] = ctx->state[i] >> 8;
        output[i * 4 + 3] = ctx->state[i];
    }
    return 0;
}


#endif // MBEDTLS_SHA1_ALT
