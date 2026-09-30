#include "core/sha256.h"

#include "core/arith.h"
#include "core/bytes.h"

/* FIPS 180-4 section 4.2.2: first 32 bits of the fractional parts of the
 * cube roots of the first 64 primes. */
static const uint32_t dfi_sha256_k[64] = {
    UINT32_C(0x428a2f98), UINT32_C(0x71374491), UINT32_C(0xb5c0fbcf), UINT32_C(0xe9b5dba5),
    UINT32_C(0x3956c25b), UINT32_C(0x59f111f1), UINT32_C(0x923f82a4), UINT32_C(0xab1c5ed5),
    UINT32_C(0xd807aa98), UINT32_C(0x12835b01), UINT32_C(0x243185be), UINT32_C(0x550c7dc3),
    UINT32_C(0x72be5d74), UINT32_C(0x80deb1fe), UINT32_C(0x9bdc06a7), UINT32_C(0xc19bf174),
    UINT32_C(0xe49b69c1), UINT32_C(0xefbe4786), UINT32_C(0x0fc19dc6), UINT32_C(0x240ca1cc),
    UINT32_C(0x2de92c6f), UINT32_C(0x4a7484aa), UINT32_C(0x5cb0a9dc), UINT32_C(0x76f988da),
    UINT32_C(0x983e5152), UINT32_C(0xa831c66d), UINT32_C(0xb00327c8), UINT32_C(0xbf597fc7),
    UINT32_C(0xc6e00bf3), UINT32_C(0xd5a79147), UINT32_C(0x06ca6351), UINT32_C(0x14292967),
    UINT32_C(0x27b70a85), UINT32_C(0x2e1b2138), UINT32_C(0x4d2c6dfc), UINT32_C(0x53380d13),
    UINT32_C(0x650a7354), UINT32_C(0x766a0abb), UINT32_C(0x81c2c92e), UINT32_C(0x92722c85),
    UINT32_C(0xa2bfe8a1), UINT32_C(0xa81a664b), UINT32_C(0xc24b8b70), UINT32_C(0xc76c51a3),
    UINT32_C(0xd192e819), UINT32_C(0xd6990624), UINT32_C(0xf40e3585), UINT32_C(0x106aa070),
    UINT32_C(0x19a4c116), UINT32_C(0x1e376c08), UINT32_C(0x2748774c), UINT32_C(0x34b0bcb5),
    UINT32_C(0x391c0cb3), UINT32_C(0x4ed8aa4a), UINT32_C(0x5b9cca4f), UINT32_C(0x682e6ff3),
    UINT32_C(0x748f82ee), UINT32_C(0x78a5636f), UINT32_C(0x84c87814), UINT32_C(0x8cc70208),
    UINT32_C(0x90befffa), UINT32_C(0xa4506ceb), UINT32_C(0xbef9a3f7), UINT32_C(0xc67178f2),
};

/* FIPS 180-4 section 5.3.3: initial hash value. */
static const uint32_t dfi_sha256_h0[8] = {
    UINT32_C(0x6a09e667), UINT32_C(0xbb67ae85), UINT32_C(0x3c6ef372), UINT32_C(0xa54ff53a),
    UINT32_C(0x510e527f), UINT32_C(0x9b05688c), UINT32_C(0x1f83d9ab), UINT32_C(0x5be0cd19),
};

/* One 512-bit block (FIPS 180-4 section 6.2.2). All word additions are
 * intentionally modulo 2^32 (uint32_t does not promote; see platform.h). */
static void dfi_sha256_block(uint32_t h[8], const uint8_t block[64])
{
    uint32_t w[64];
    for (uint32_t t = 0u; t < 16u; ++t) {
        w[t] = dfi_load_u32be(block + 4u * t);
    }
    for (uint32_t t = 16u; t < 64u; ++t) {
        const uint32_t x = w[t - 15u];
        const uint32_t y = w[t - 2u];
        const uint32_t s0 = dfi_rotr32(x, 7u) ^ dfi_rotr32(x, 18u) ^ (x >> 3u);
        const uint32_t s1 = dfi_rotr32(y, 17u) ^ dfi_rotr32(y, 19u) ^ (y >> 10u);
        w[t] = w[t - 16u] + s0 + w[t - 7u] + s1; /* mod 2^32 */
    }

    uint32_t a = h[0];
    uint32_t b = h[1];
    uint32_t c = h[2];
    uint32_t d = h[3];
    uint32_t e = h[4];
    uint32_t f = h[5];
    uint32_t g = h[6];
    uint32_t hh = h[7];
    for (uint32_t t = 0u; t < 64u; ++t) {
        const uint32_t big_s1 = dfi_rotr32(e, 6u) ^ dfi_rotr32(e, 11u) ^ dfi_rotr32(e, 25u);
        const uint32_t ch = (e & f) ^ (~e & g);
        const uint32_t t1 = hh + big_s1 + ch + dfi_sha256_k[t] + w[t]; /* mod 2^32 */
        const uint32_t big_s0 = dfi_rotr32(a, 2u) ^ dfi_rotr32(a, 13u) ^ dfi_rotr32(a, 22u);
        const uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        const uint32_t t2 = big_s0 + maj; /* mod 2^32 */
        hh = g;
        g = f;
        f = e;
        e = d + t1; /* mod 2^32 */
        d = c;
        c = b;
        b = a;
        a = t1 + t2; /* mod 2^32 */
    }
    h[0] += a; /* mod 2^32 */
    h[1] += b;
    h[2] += c;
    h[3] += d;
    h[4] += e;
    h[5] += f;
    h[6] += g;
    h[7] += hh;
}

bool dfi_sha256(const uint8_t *data, size_t size, uint8_t out[DFI_SHA256_SIZE])
{
#if SIZE_MAX > UINT64_C(0x1FFFFFFFFFFFFFFF)
    /* The bit length must fit the 64-bit length field. */
    if ((uint64_t)size >= UINT64_C(0x2000000000000000)) {
        return false;
    }
#endif
    uint32_t h[8];
    for (uint32_t i = 0u; i < 8u; ++i) {
        h[i] = dfi_sha256_h0[i];
    }

    size_t offset = 0u;
    size_t remaining = size;
    while (remaining >= 64u) {
        dfi_sha256_block(h, data + offset);
        offset += 64u;
        remaining -= 64u;
    }

    /* Padding (FIPS 180-4 section 5.1.1): 0x80, zeros, 64-bit bit length. */
    uint8_t tail[128] = {0};
    for (size_t i = 0u; i < remaining; ++i) {
        tail[i] = data[offset + i];
    }
    tail[remaining] = 0x80u;
    const size_t tail_size = (remaining < 56u) ? 64u : 128u;
    dfi_store_u64be(tail + tail_size - 8u, (uint64_t)size * 8u);
    dfi_sha256_block(h, tail);
    if (tail_size == 128u) {
        dfi_sha256_block(h, tail + 64u);
    }

    for (uint32_t i = 0u; i < 8u; ++i) {
        dfi_store_u32be(out + 4u * i, h[i]);
    }
    return true;
}
