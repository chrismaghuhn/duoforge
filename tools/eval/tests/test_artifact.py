"""Independent DFEVAL-v1 byte oracle. Synthetic files exist only in temp storage."""
from __future__ import annotations
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

RUNNER = sys.argv[1]
CONTEXT_HEX, SPECIES, MOVES = subprocess.check_output([RUNNER, "--context"], text=True).split()
CONTEXT = bytes.fromhex(CONTEXT_HEX)
META = ("export_commit=" + "a" * 40 + "\nexport_dirty=0\nseed=42\nsplit_sha256="
        + "b" * 64 + "\ntraining_commit=" + "c" * 40 + "\ntraining_dirty=0\n").encode("ascii")


def put(buf, offset, fmt, value):
    struct.pack_into("<" + fmt, buf, offset, value)


def artifact(dtype=1):
    buf = bytearray(512)  # header and exactly two directory records
    buf[:8] = b"DFEVAL\0\0"
    for off, value in [(8, 1), (12, 256), (24, 1), (28, 1), (32, 6),
                       (36, 1094), (88, int(SPECIES)), (92, int(MOVES)), (48, 3), (52, 3), (56, 2), (60, len(META))]:
        put(buf, off, "I", value)
    for off, value in [(40, 0), (64, 256), (72, 512)]:
        put(buf, off, "Q", value)
    buf[96:128] = CONTEXT
    buf[128:160] = bytes([3]) * 32
    buf[160:192] = bytes([4]) * 32
    buf[192] = 1
    buf[224] = 2
    buf.extend(META)
    buf.extend(bytes(-len(buf) % 8))
    put(buf, 80, "Q", len(buf))
    for index, (name, dtype, dims, data, scales) in enumerate([
        (b"dense.weight", dtype, (2, 3), {
            1: bytes([1, 255, 128, 127, 0, 2]),
            2: struct.pack("<6h", 1, -1, -32768, 32767, 0, 2),
            3: struct.pack("<6i", 1, -1, -(1 << 31), (1 << 31) - 1, 0, 2),
        }[dtype], [(1, 0), (3, 7)]),
        (b"dense.bias", 4, (2,), struct.pack("<qq", -17, 17), []),
    ]):
        entry = 256 + index * 128
        buf[entry:entry + len(name)] = name
        put(buf, entry + 32, "I", dtype)
        put(buf, entry + 36, "I", len(dims))
        for i, dim in enumerate(dims):
            put(buf, entry + 40 + i * 4, "I", dim)
        put(buf, entry + 56, "Q", len(buf))
        put(buf, entry + 64, "Q", len(data))
        buf.extend(data)
        buf.extend(bytes(-len(buf) % 8))
        if scales:
            put(buf, entry + 72, "Q", len(buf))
            put(buf, entry + 80, "I", len(scales))
            for multiplier, shift in scales:
                buf.extend(struct.pack("<II", multiplier, shift))
    put(buf, 16, "Q", len(buf))
    return buf


def main():
    cases = 0
    checks = 0
    with tempfile.TemporaryDirectory(prefix="duoforge-dfeval-") as folder:
        path = Path(folder) / "synthetic.dfeval"

        def run(buf, reason, mode="--load", expected=None):
            nonlocal cases, checks
            path.write_bytes(buf)
            digest = hashlib.sha256(buf).hexdigest() if expected is None else expected
            result = subprocess.run([RUNNER, mode, str(path.resolve()), digest, reason],
                                    capture_output=True, text=True, check=True)
            checks += int(result.stdout.split(" checks, ")[0].split()[-1])
            cases += 1

        base = artifact()
        run(base, "OK")
        run(artifact(2), "OK", "--i16")
        run(artifact(3), "OK", "--i32")
        run(base, "eval_graph_unregistered", "--public")
        run(base, "eval_file_sha256", "--race")
        run(base, "eval_tensor_invalid:dense.weight", "--bound")
        run(base, "eval_tensor_invalid:dense.weight", "--product")
        run(base, "SCRATCH", "--scratch")
        buf = base.copy()
        put(buf, 256 + 36, "I", 4)
        for offset in range(256 + 40, 256 + 56, 4):
            put(buf, offset, "I", 0xffffffff)
        run(buf, "eval_tensor_invalid:dense.weight", "--shape")
        run(base, "OOM", "--oom")
        run(base, "eval_file_sha256", expected="0" * 64)
        run(base, "eval_file_sha256", "--public", expected="0" * 64)
        for offset, fmt, value, reason in [
            (0, "B", 0, "eval_header"), (8, "I", 2, "eval_format_version"),
            (12, "I", 128, "eval_format_version"), (16, "Q", len(base) - 1, "eval_file_length"),
            (88, "I", 0, "eval_context"), (48, "I", 99, "eval_semantics"),
            (52, "I", 99, "eval_semantics"), (96, "B", CONTEXT[0] ^ 1, "eval_context"),
            (32, "I", 5, "eval_encoder_mask"), (40, "Q", 1, "eval_encoder_mask"),
            (24, "I", 99, "eval_graph_unregistered"), (28, "I", 2, "eval_graph_schema"),
            (36, "I", 1093, "eval_graph_schema"), (192, "B", 3, "eval_graph_schema"),
            (224, "B", 3, "eval_graph_schema"), (56, "I", 1, "eval_tensor_inventory"),
            (56, "I", 129, "eval_tensor_inventory"), (60, "I", 65537, "eval_metadata_capacity"),
            (64, "Q", 257, "eval_metadata"), (72, "Q", 513, "eval_metadata"),
            (80, "Q", 999999, "eval_data_offset"),
            (256 + 32, "I", 4, "eval_tensor_invalid:dense.weight"),
            (256 + 36, "I", 5, "eval_tensor_invalid:dense.weight"),
            (256 + 40, "I", 0, "eval_tensor_invalid:dense.weight"),
            (256 + 40, "I", 0xffffffff, "eval_tensor_invalid:dense.weight"),
            (256 + 48, "I", 1, "eval_tensor_invalid:dense.weight"),
            (256 + 56, "Q", 0xffffffffffffffff, "eval_tensor_invalid:dense.weight"),
            (256 + 64, "Q", 7, "eval_tensor_invalid:dense.weight"),
            (256 + 72, "Q", 0, "eval_tensor_invalid:dense.weight"),
            (256 + 80, "I", 3, "eval_tensor_invalid:dense.weight"),
            (256 + 84, "B", 1, "eval_tensor_invalid:dense.weight"),
            (384 + 56, "Q", struct.unpack_from("<Q", base, 312)[0], "eval_tensor_invalid:dense.bias"),
        ]:
            buf = base.copy()
            put(buf, offset, fmt, value)
            run(buf, reason)
        for location in [128, 160]:
            buf = base.copy()
            buf[location:location + 32] = bytes(32)
            run(buf, "eval_metadata")
        for offset, value in [(512, 0xff), (512 + META.index(b"seed=42") + 5, ord("0")),
                              (512 + META.index(b"export_dirty=0") + 13, ord("2"))]:
            buf = base.copy()
            buf[offset] = value
            run(buf, "eval_metadata")
        buf = base.copy()
        buf[384:416] = buf[256:288]  # duplicate/also missing exact bias inventory
        run(buf, "eval_tensor_invalid:dense.bias")
        buf = base.copy()
        buf[256] = ord("x")
        run(buf, "eval_tensor_invalid:dense.weight")
        scale = struct.unpack_from("<Q", base, 328)[0]
        for offset, value in [(scale, 0), (scale + 4, 64), (scale + 8, 0)]:
            buf = base.copy()
            put(buf, offset, "I", value)
            run(buf, "eval_tensor_invalid:dense.weight")
        bias = struct.unpack_from("<Q", base, 440)[0]
        for value in [18, -(1 << 63)]:
            buf = base.copy()
            put(buf, bias, "q", value)
            run(buf, "eval_tensor_invalid:dense.bias")
        for size in [0, 255, len(base) - 1]:
            run(base[:size], "eval_header" if size < 256 else "eval_file_length")
        padding = struct.unpack_from("<Q", base, 312)[0] + 6
        buf = base.copy()
        buf[padding] = 1
        run(buf, "eval_tensor_invalid:dense.weight")
        buf = base.copy()
        buf[512 + len(META)] = 1
        run(buf, "eval_data_offset")
        run(bytes(4097), "eval_file_capacity")
        buf = base + b"\0"
        put(buf, 16, "Q", len(buf))
        run(buf, "eval_trailing_data")
    print(f"DFEVAL independent oracle: {cases} cases, {checks} C checks, 0 failures")


if __name__ == "__main__":
    main()
