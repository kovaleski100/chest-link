#pragma once
#include <nds/ndstypes.h>
typedef struct swiSHA1context {
    u32 state[5];
    u32 total[2];
    u8 buffer[64];
    u32 fragment_size;
    void (*sha_block)(struct swiSHA1context *, const void *, size_t);
} swiSHA1context_t;
void swiSHA1Init(swiSHA1context_t *ctx);
void swiSHA1Update(swiSHA1context_t *ctx, const void *input, size_t size);
void swiSHA1Final(void *digest, swiSHA1context_t *ctx);
