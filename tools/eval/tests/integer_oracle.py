#!/usr/bin/env python3
"""Independent arbitrary-precision and exact IEEE binary32 oracle for E3a.
Synthetic byte vectors are generated in private temporary storage, never weights.
The C executable consumes fixed little-endian frames and emits status/value bytes.
"""
import hashlib
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile

LO, HI, UMAX = -(1 << 63), (1 << 63) - 1, (1 << 64) - 1
OK, INVALID, UNSUPPORTED, EXHAUSTED = 0, 2, 11, 9

def nearest(n, d):
    sign = -1 if n < 0 else 1
    q, r = divmod(abs(n), d)
    return sign * (q + (2 * r > d or (2 * r == d and q % 2)))

def requant(n, m, shift):
    if not m or shift > 63:
        return INVALID, 0
    if abs(n) * m > UMAX:
        return EXHAUSTED, 0
    q = nearest(n * m, 1 << shift)
    return (OK, q) if LO <= q <= HI else (EXHAUSTED, 0)

def finite(bits):
    exponent = (bits >> 23) & 255
    if exponent == 255:
        return None
    mantissa = bits & 0x7fffff
    if exponent:
        mantissa |= 1 << 23
    power = exponent - 150 if exponent else -149
    num, den = (mantissa << power, 1) if power >= 0 else (mantissa, 1 << -power)
    return (-num if bits >> 31 else num), den

def clip(n):
    return max(-32768, min(32767, n))

def expect(row):
    op, a, b, c, d, e, f, g = row
    if op in (1, 2):
        q = a + b if op == 1 else a * b
        return (OK, q) if LO <= q <= HI else (EXHAUSTED, 0)
    if op == 3:
        return (OK, nearest(a, b)) if b else (INVALID, 0)
    if op in (4, 7, 10):
        st, q = requant(a, b, c)
        if op == 10 and st == OK and not -(1 << 31) <= q < (1 << 31):
            return EXHAUSTED, 0
        return st, clip(q) if op == 7 and st == OK else q
    if op in (5, 6):
        frac = finite(a)
        if frac is None or not b or (op == 5 and c > 63) or (op == 6 and not c):
            return INVALID, 0
        n, den = frac
        if op == 6 and n < 0:
            return INVALID, 0
        q = nearest(n * b, den * ((1 << c) if op == 5 else 1))
        if op == 5:
            return OK, clip(q)
        # ID recovery refuses huge values before the integer capacity check.
        if abs(q) > UMAX:
            return EXHAUSTED, 0
        return (OK, q) if q < c else (UNSUPPORTED, 0)
    if op in (8, 11):
        # Conservative whole-dot proof; not just the accidentally cancelling sum.
        if not f or g > 63:
            return INVALID, 0
        bound = abs(e) + 2 * max(abs(a), abs(b)) * max(abs(c), abs(d))
        if bound > HI or bound * f > HI:
            return EXHAUSTED, 0
        st, q = requant(e + a * c + b * d, f, g)
        if op == 11:
            return (st, q) if st == OK and -(1 << 31) <= q < (1 << 31) else (EXHAUSTED, 0)
        return st, clip(q) if st == OK else 0
    if op == 9:
        selected = [v for i, v in enumerate((a, b, c)) if d & (1 << i)]
        value = max(selected, default=0) if e else sum(selected)
        st, q = requant(value, f, g)
        return st, clip(q) if st == OK else 0
    if op == 12:
        if not e or f > 63 or b > 32768 or c > 128:
            return INVALID, 0
        bound = d + a * b * c
        return (OK, bound) if bound <= HI and bound * e <= HI else (EXHAUSTED, 0)
    raise AssertionError(op)

def vectors():
    rng = random.Random(20261014)
    extremes = [LO, LO + 1, -32769, -32768, -7, -5, -3, -1, 0, 1, 3, 5, 7, 32767, 32768, HI - 1, HI]
    rows = []
    def add(*r): rows.append(tuple(r) + (0,) * (8 - len(r)))
    for a in extremes:
        for b in extremes:
            add(1, a, b); add(2, a, b)
        for b in (0, 1, 2, 3, 7, 1 << 63, UMAX): add(3, a, b)
        for m in (0, 1, 2, 3, (1 << 32) - 1):
            for s in (0, 1, 2, 31, 32, 63, 64):
                add(4, a, m, s); add(7, a, m, s); add(10, a, m, s)
    for bits in (0, 0x80000000, 1, 0x80000001, 0x7fffff, 0x800000, 0x3f000000,
                 0x3fc00000, 0x40200000, 0xbf000000, 0xbfc00000, 0xc0200000,
                 0x7f7fffff, 0xff7fffff, 0x7f800000, 0xff800000, 0x7fc00000):
        for m in (0, 1, 3, 65535, (1 << 32) - 1):
            for s in (0, 1, 63, 64): add(5, bits, m, s)
        for factor, capacity in ((65535, 65536), (255, 256), (24, 25), (1, 2), (4, 5), (1, 0)):
            add(6, bits, factor, capacity)
    # Every valid species/move ID, including zero, follows check_ids' validated
    # binary32 -> binary64 multiply -> ties-even mapping before quantization.
    for factor, cap in ((65535, 65536), (255, 256), (24, 25)):
        for ident in range(cap):
            bits = struct.unpack("<I", struct.pack("<f", ident / factor))[0]
            add(6, bits, factor, cap)
            assert expect(rows[-1]) == (OK, ident)
    for bias in ((1 << 31)-1-65534, (1 << 31)-65534, -(1 << 31)-65534, -(1 << 31)-65535, 0, 3145728-65534):
        add(11, 32767, 32767, 1, 1, bias, 1, 0)
    for _ in range(4000):
        add(4, rng.randint(LO, HI), rng.randrange(1, 1 << 32), rng.randrange(64))
        add(5, rng.getrandbits(32), rng.randrange(1, 1 << 32), rng.randrange(64))
        add(6, rng.getrandbits(32), rng.choice((65535, 255, 24)), rng.choice((25, 256, 65536)))
        add(8, rng.randint(-32768, 32767), rng.randint(-32768, 32767), rng.randint(-128, 127),
            rng.randint(-128, 127), rng.randint(-1000000, 1000000), rng.randrange(1, 65536), rng.randrange(32))
        add(11, *rows[-1][1:])
        add(9, rng.randint(-32768, 32767), rng.randint(-32768, 32767), rng.randint(-32768, 32767),
            rng.randrange(8), rng.randrange(2), rng.randrange(1, 65536), rng.randrange(32))
    # Append dot-bound controls, keeping every previous vector in order.
    for bias in (0, 1, (1 << 31)-1, 1 << 31, (1 << 31)+1, 1 << 32,
                 (1 << 62)-1, 1 << 62, HI, 1 << 63, UMAX):
        for m in (0, 1, 2, 3, (1 << 32)-1):
            for shift in (0, 63, 64):
                add(12, 0, 0, 0, bias, m, shift)
    for m in (1, 2, 3, 65535, (1 << 32)-1):
        for delta in (-1, 0, 1):
            add(12, 0, 0, 0, HI // m + delta, m, 0)
    bound_rng = random.Random(20261015)
    for _ in range(4000):
        add(12, bound_rng.getrandbits(32),
            bound_rng.choice((0, 1, 32768, 32769, bound_rng.randrange(32769))),
            bound_rng.choice((0, 1, 128, 129, bound_rng.randrange(129))),
            bound_rng.getrandbits(64), bound_rng.choice((0, 1, 2, (1 << 32)-1)),
            bound_rng.choice((0, 63, 64)))
        count, a, w = bound_rng.randrange(33), bound_rng.randrange(32769), bound_rng.randrange(129)
        m = bound_rng.randrange(1, 1 << 32)
        bias = HI // m - count * a * w + bound_rng.choice((-1, 0, 1))
        add(12, count, a, w, bias, m, bound_rng.randrange(64))
    return rows

def main():
    rows = vectors()
    source = b"".join(struct.pack("<8Q", *(n & UMAX for n in row)) for row in rows)
    expected = b"".join(struct.pack("<Iq", *expect(row)) for row in rows)
    with tempfile.TemporaryDirectory(prefix="duoforge-e3a-") as temp:
        path = Path(temp) / "synthetic.bin"
        path.write_bytes(source)
        got = subprocess.run([sys.argv[1], str(path)], check=True, stdout=subprocess.PIPE).stdout
    if got != expected:
        if len(got) != len(expected):
            raise AssertionError(f"oracle output length {len(got)} != {len(expected)}")
        for i, row in enumerate(rows):
            if got[12*i:12*(i+1)] != expected[12*i:12*(i+1)]:
                raise AssertionError(f"vector {i}: {row}; actual {struct.unpack('<Iq', got[12*i:12*(i+1)])}; expected {expect(row)}")
    print(f"integer oracle: {len(rows)} byte-exact vectors; SHA256 {hashlib.sha256(got).hexdigest()}")

if __name__ == "__main__":
    main()
