"""Independent normalization-v1 oracle: Python bigint, math.isqrt, no C helpers.

Inputs/parameters are entirely synthetic. No model dimensions, private artifacts,
learned weights, inference timing or approximation tolerance participates.
"""
from __future__ import annotations
import hashlib
import math
import random
import struct
import subprocess
import sys

OK, INVALID, EXHAUSTED = 0, 2, 9
I32_MIN, I32_MAX = -(1 << 31), (1 << 31) - 1
I64_MIN, I64_MAX = -(1 << 63), (1 << 63) - 1
U64_MAX = (1 << 64) - 1


def rne(x: int, denominator: int) -> int:
    q, remainder = divmod(abs(x), denominator)
    q += remainder * 2 > denominator or (remainder * 2 == denominator and q % 2)
    return -q if x < 0 else q


def sqrt_nearest(n: int) -> int:
    lower = math.isqrt(n)
    dl, dh = n - lower * lower, (lower + 1) ** 2 - n
    return lower + (dl > dh or (dl == dh and lower % 2))


def check64(x: int) -> int:
    if not I64_MIN <= x <= I64_MAX:
        raise OverflowError
    return x


def scale(x: int, multiplier: int, shift: int) -> int:
    return check64(rne(x * multiplier, 1 << shift))


def moments(x: list[int], p: tuple[int, ...]) -> list[int]:
    epsilon, root_shift, numerator_shift, gm, gs, om, os = p
    if not x or not epsilon or root_shift > 31 or numerator_shift > 63 or not gm or not om or gs > 63 or os > 63:
        return [INVALID]
    mean = rne(sum(x), len(x))
    variance = rne(sum((a - mean) ** 2 for a in x), len(x))
    denominator = sqrt_nearest((variance + epsilon) << (2 * root_shift))
    if denominator > U64_MAX:
        return [EXHAUSTED]
    return [OK, mean, variance >> 64, variance & U64_MAX, denominator]


def norm(x: list[int], gamma: list[int], beta: list[int], p: tuple[int, ...]) -> list[int]:
    result = moments(x, p)
    if result[0]:
        return result[:1]
    mean, denominator = result[1], result[4]
    _, _, numerator_shift, gm, gs, om, os = p
    try:
        normalized = [check64(rne((a - mean) << numerator_shift, denominator)) for a in x]
        affine = [check64(scale(a * g, gm, gs) + b) for a, g, b in zip(normalized, gamma, beta)]
        output = [scale(a, om, os) for a in affine]
        if any(a < I32_MIN or a > I32_MAX for a in output):
            return [EXHAUSTED]
        return [OK, *output]
    except OverflowError:
        return [EXHAUSTED]


def residual(a: list[int], b: list[int], p: tuple[int, ...], sat: bool) -> list[int]:
    lm, ls, rm, rs, om, os = p
    if not a or not lm or not rm or not om or max(ls, rs, os) > 63:
        return [INVALID]
    try:
        sums = [check64(scale(x, lm, ls) + scale(y, rm, rs)) for x, y in zip(a, b)]
        output = [scale(x, om, os) for x in sums]
        if sat:
            output = [min(32767, max(-32768, x)) for x in output]
        elif any(x < I32_MIN or x > I32_MAX for x in output):
            return [EXHAUSTED]
        return [OK, *output]
    except OverflowError:
        return [EXHAUSTED]


def vectors() -> tuple[list[str], list[list[int]], list[str]]:
    rng = random.Random(20261014)
    cases, expected, kinds = [], [], []

    def add(kind: str, args: list[int], want: list[int]) -> None:
        cases.append(kind + " " + " ".join(map(str, args)))
        expected.append(want)
        kinds.append(kind)

    # Each square and both sides of the adjacent-square midpoint; sqrt ties
    # cannot occur for an integer radicand because 2*r+1 is odd.
    roots = list(range(129)) + [2**16 - 1, 2**32 - 1, 2**32, 2**63 - 1, U64_MAX - 1, U64_MAX]
    radicands = {0, (1 << 128) - 1}
    for root in roots:
        radicands.update(n for n in (root * root, root * root + root, root * root + root + 1,
                                    root * root - 1, (root + 1) ** 2 - 1) if 0 <= n < 1 << 128)
    radicands.update(rng.getrandbits(128) for _ in range(4000))
    for n in sorted(radicands):
        root = sqrt_nearest(n)
        add("S", [n >> 64, n & U64_MAX], [OK, root] if root <= U64_MAX else [EXHAUSTED, 0])

    p0 = (1, 0, 0, 1, 0, 1, 0)
    shapes = [1, 2, 3, 4, 7, 16, 31, 64]
    datasets = [[-1, 0], [-2, -1], [-2, -1, 1, 2], [0], [I32_MIN] * 64,
                [I32_MIN, I32_MAX] * 32, [I32_MIN, I32_MAX, I32_MAX], [I32_MIN] + [I32_MAX] * 63]
    parameters = [p0, (1, 31, 31, 1, 0, 1, 0), (U64_MAX, 31, 63, 1, 31, 1, 0),
                  (0, 0, 0, 1, 0, 1, 0), (1, 32, 0, 1, 0, 1, 0), (1, 0, 64, 1, 0, 1, 0),
                  (1, 0, 0, 0, 0, 1, 0), (1, 0, 0, 1, 64, 1, 0), (1, 0, 0, 1, 0, 0, 0)]
    norm_cases = [(x, [1] * len(x), [0] * len(x), p) for x in datasets for p in parameters]
    for _ in range(4000):
        n = rng.choice(shapes)
        limit = rng.choice([4, 32768, 1 << 31])
        x = [rng.randint(-limit, limit - 1) for _ in range(n)]
        if rng.randrange(5) == 0:
            x = [x[0]] * n
        gamma = [rng.choice([-2147483648, -1024, -3, 0, 1, 3, 1024, I32_MAX]) for _ in x]
        beta = [rng.choice([I32_MIN, -3, 0, 3, I32_MAX]) for _ in x]
        p = (rng.choice([1, 2, 3, 17, 1 << 32, U64_MAX]), rng.choice([0, 1, 7, 16, 31]),
             rng.choice([0, 1, 15, 31, 63]), rng.choice([1, 3, 65535, (1 << 32) - 1]),
             rng.choice([0, 1, 17, 31, 63]), rng.choice([1, 3, 65535, (1 << 32) - 1]),
             rng.choice([0, 1, 17, 31, 63]))
        norm_cases.append((x, gamma, beta, p))
    for x, gamma, beta, p in norm_cases:
        args = [len(x), *p, *x, *gamma, *beta]
        add("M", args, moments(x, p))
        add("N", args, norm(x, gamma, beta, p))

    for _ in range(4000):
        n = rng.choice(shapes)
        a = [rng.choice([I32_MIN, I32_MAX, -32768, 32767, -3, -1, 0, 1, 3]) for _ in range(n)]
        b = [rng.choice([I32_MIN, I32_MAX, -32768, 32767, -3, -1, 0, 1, 3]) for _ in range(n)]
        p = tuple(v for _ in range(3) for v in (rng.choice([0, 1, 3, (1 << 32) - 1]), rng.choice([0, 1, 31, 63, 64])))
        add("R", [n, *p, *a, *b], residual(a, b, p, False))
        add("T", [n, *p, *a, *b], residual(a, b, p, True))
    return cases, expected, kinds


def canonical(kind: str, values: list[int]) -> bytes:
    status, *rest = values
    prefix = kind.encode("ascii") + struct.pack("<I", status)
    if status:
        return prefix
    if kind == "M":
        return prefix + struct.pack("<qQQQ", *rest)
    if kind == "S":
        return prefix + struct.pack("<Q", *rest)
    return prefix + struct.pack("<" + "i" * len(rest), *rest)


def main() -> None:
    cases, expected, kinds = vectors()
    run = subprocess.run([sys.argv[1], "--vectors"], input="\n".join(cases) + "\n",
                         text=True, check=True, capture_output=True)
    lines = run.stdout.splitlines()
    assert len(lines) == len(cases), (len(lines), len(cases), run.stderr)
    digest = hashlib.sha256()
    for case, want, kind, line in zip(cases, expected, kinds, lines):
        actual = list(map(int, line.split()))
        assert actual == want, (case, want, actual)
        digest.update(canonical(kind, actual))
    counts = {kind: kinds.count(kind) for kind in sorted(set(kinds))}
    print(f"normalization-v1: {len(cases)} bit-exact bigint/isqrt vectors {counts}; SHA256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
