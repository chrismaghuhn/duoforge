"""Independent decision-0082 wire vectors, using struct and hashlib only.

This oracle does not import the C serializer or read its output. Layouts are
written from the decision's byte whitelist. Fixture identifiers are neutral
numeric tokens; these wire records do not claim to be complete battle setups.
Regenerate the test header, or verify with --check. No private input.
"""
import argparse
import hashlib
from pathlib import Path
import struct

# Explicit event numbers and field order from decision 0082, not from C.
SCHEMAS = [
    ('TURN', 1, 'i'), ('SWITCH', 2, 'pcbjh'), ('MOVE', 3, 'pocijaf'),
    ('DAMAGE', 4, 'pocjh'), ('HEAL', 5, 'pocjh'), ('FAINT', 6, 'p'),
    ('CANT', 7, 'pocij'), ('MISS', 8, 'po'), ('CRIT', 9, 'p'),
    ('SUPER_EFFECTIVE', 10, 'pa'), ('RESISTED', 11, 'pa'), ('IMMUNE', 12, 'pcj'),
    ('FAIL', 13, 'pocjd'), ('PROTECT', 14, 'p'), ('BLOCKED', 15, 'pd'),
    ('BOOST', 16, 'pocjda'), ('UNBOOST', 17, 'pocjda'), ('STATUS', 18, 'pocjd'),
    ('CURE_STATUS', 19, 'pocjdf'), ('CONFUSION_START', 20, 'p'),
    ('CONFUSION_END', 21, 'p'), ('CONFUSED', 22, 'p'), ('FLASH_FIRE', 23, 'p'),
    ('WEATHER', 24, 'ocjdf'), ('FIELD_START', 25, 'ocjd'), ('FIELD_END', 26, 'd'),
    ('SIDE_START', 27, 'oda'), ('SIDE_END', 28, 'oda'), ('ITEM_END', 29, 'pocijdf'),
    ('FORME', 30, 'pcij'), ('MEGA', 31, 'pj'), ('PREPARE', 32, 'pi'),
    ('ANIMATION', 33, 'poif'), ('ABILITY', 34, 'pocij'), ('ACTIVATE', 35, 'pocij'),
    ('UPKEEP', 36, ''), ('RESULT', 37, 'd'), ('SINGLE_TURN', 38, 'poi'),
    ('VOLATILE_START', 39, 'pocijda'), ('VOLATILE_END', 40, 'pocijda'),
    ('TYPE_CHANGE', 41, 'pcjda'), ('ITEM_START', 42, 'pocij'), ('REVIVE', 43, 'pcbjh'),
    ('DRAG', 45, 'pbh'), ('ILLUSION_END', 46, 'pbh'), ('CLEAR_ALL_BOOSTS', 47, ''),
    ('ITEM_SHOWN', 48, 'pocij'), ('SWAP', 49, 'pocj'), ('COPY_BOOST', 50, 'pocj'),
    ('PROTECT_BROKEN', 51, 'p'),
]

def line(name, kind, fields):
    e = dict(kind=kind, position=0 if 'p' in fields else 255, other=255, cause=0,
             id=0x0102 if 'i' in fields else 0, id2=0, hp=40 if 'h' in fields else 0,
             hp_max=100 if 'h' in fields else 0, hp_kind=2 if 'h' in fields else 0,
             hp_flag=0, status=1 if 'h' in fields else 0, detail=1 if 'd' in fields else 0,
             amount=1 if 'a' in fields else 0, flags=0)
    if name in ('CANT', 'ACTIVATE', 'TYPE_CHANGE', 'ITEM_START', 'REVIVE', 'SWAP', 'COPY_BOOST'):
        e['cause'] = 1
    if 'j' in fields and (e['cause'] or name in ('MEGA', 'ITEM_END', 'ITEM_SHOWN', 'ABILITY')):
        e['id2'] = 0x0304
    if name == 'MOVE':
        e.update(amount=12, flags=4)
    if name == 'WEATHER': e['flags'] = 8
    if name == 'ITEM_END': e['flags'] = 16
    if name == 'CURE_STATUS': e['flags'] = 32
    if name == 'ANIMATION': e['flags'] = 64
    if name == 'BLOCKED': e['detail'] = 0
    if name == 'RESULT': e['detail'] = 3
    if 'b' in fields: e['id'] = 4  # arbitrary particle index; absent from payload
    payload = bytes([kind])
    for field in fields:
        if field == 'b': payload += struct.pack('<HB', 0x0102, 1)
        elif field == 'h': payload += struct.pack('<HHBBB', e['hp'], e['hp_max'], e['hp_kind'], e['hp_flag'], e['status'])
        else:
            key = dict(p='position', o='other', c='cause', i='id', j='id2', d='detail', a='amount', f='flags')[field]
            payload += struct.pack('<H' if field in 'ij' else '<B', e[key])
    return e, payload


def own_request():
    # Two own roster rows, one own active position and a bench switch option.
    header = struct.pack('<7BI', 1, 2, 3, 1, 2, 1, 1, 2)
    header += bytes([2, 0, 0, 255, 0, 1, 255, 255, 255, 255])
    member = struct.pack('<7H', 0x0123, 150, 200, 7, 8, 0, 0)
    member += struct.pack('<5H', 101, 102, 103, 104, 105)
    member += bytes([3, 4, 0, 0, 10, 20, 0, 0, 1, 2, 3, 4, 5, 6])
    member += bytes([2, 1, 0, 1, 2, 1, 0, 1, 3, 4, 5, 0, 0])
    member += struct.pack('<HB', 0x0102, 0)
    bench = bytearray(member)
    bench[:6] = struct.pack('<3H', 0x0124, 80, 100)
    bench[42] = 1  # location: bench, not active
    # stages, visible position scalars (including the named POSITION_FLAG byte),
    # then whitelisted extension fields and the own volatiles2 word.
    position = bytes([6] * 7 + [1, 0, 255, 255, 1, 0, 0, 0, 0])
    position += struct.pack('<IH7BI', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    empty = bytes([6] * 7 + [0, 0, 255, 255, 0, 0, 0, 0, 0]) + bytes(17)
    side = bytes([3, 4, 2, 0, 1, 0, 0, 0, 0, 0])
    domain = bytes([2, 0, 0, 2, 1])
    commands = bytes([1, 0, 2, 0, 0, 2, 0, 0, 0, 1, 0, 0, 0, 0, 0])
    pairs = struct.pack('<2I', 1, 1)
    payload = header + member + bench + position + empty + side + domain + commands + pairs
    assert len(header) == 21 and len(member) == 54 and len(position) == 33
    return payload


def render():
    lines = []
    payloads = []
    for name, kind, fields in SCHEMAS:
        e, payload = line(name, kind, fields)
        payloads.append(payload)
        init = ', '.join(f'.{key} = {val}u' for key, val in e.items())
        lines.append(f'    {{"{name}", {{{init}, .reserved = {{222u, 173u}}}}, "{payload.hex()}"}},')
    request = own_request()
    # Independently framed stream: the first three wire lines, one viewer,
    # count and the complete request. The expected hash never calls C SHA.
    stream = b'duoforge.observation-digest.v1\0' + b'\0'
    for payload in payloads[:3]: stream += struct.pack('<I', len(payload)) + payload
    stream += struct.pack('<II', 3, len(request)) + request
    return ('/* Generated by tools/reference/observation_digest_vectors.py; --check. */\n'
            '#ifndef DUOFORGE_TEST_OBSERVATION_VECTORS_H\n#define DUOFORGE_TEST_OBSERVATION_VECTORS_H\n'
            '#include <duoforge/duoforge.h>\n'
            'static const struct { const char *name; duoforge_event event; const char *hex; } df_observation_lines[] = {\n'
            + '\n'.join(lines) + '\n};\n'
            + f'#define DF_OBSERVATION_REQUEST_HEX "{request.hex()}"\n'
            + f'#define DF_OBSERVATION_STREAM_HEX "{stream.hex()}"\n'
            + f'#define DF_OBSERVATION_STREAM_SHA256 "{hashlib.sha256(stream).hexdigest()}"\n'
            + '#endif\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    target = Path(__file__).resolve().parents[2] / 'tests/support/observation_digest_vectors.h'
    output = render()
    if args.check:
        if not target.exists() or target.read_text(encoding='utf-8') != output:
            raise SystemExit('observation digest vectors are stale; regenerate with their generator')
        print(f'observation digest vectors: {len(SCHEMAS)} line kinds, own request and framed SHA: OK')
    else:
        target.write_text(output, encoding='utf-8')


if __name__ == '__main__':
    main()
