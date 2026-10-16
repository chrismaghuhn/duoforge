"""Compare two builds of one binary function by function (restructure proofs).

Usage: python3 tools/restructure/fn_diff.py <before binary> <after binary> [--json]

Disassembles both with objdump and compares each function's instruction text after normalising what moves with the
layout: RIP displacements, absolute call and jump targets (kept as symbol names), objdump's `#` annotations and the
numbers of CSWTCH tables. Apply it to the binary that is measured (for the callgrind gate: the bench executable, which
links the engine statically and, with IPO, runs its own LTO link), not only to the shared library: the two links can
inline differently.

Clones are grouped by their source function: `dfi_lum_cure` and `dfi_lum_cure.lto_priv.0.cold` are both group
`dfi_lum_cure` (C names have no dot, so the group is the name up to the first `.`). A group differs when its set of
clone names or any clone's instructions differ; it is marked `rename_only` when its code is equal once the numbered
clone parts (`.lto_priv.N`, `.constprop.N`, `.isra.N`, `.part.N`, `.clone.N`) are dropped from its own names and its
call targets.
"""
import json
import re
import subprocess
import sys

SYMBOL = re.compile(r'^[0-9a-f]+ <(.+)>:$')
INSN = re.compile(r'^\s+[0-9a-f]+:\s+(.*)$')
CLONE = re.compile(r"\.(?:lto_priv|constprop|isra|part|clone)\.\d+|'\d+")  # the numbered clone parts; `.cold` stays


def base(name):
    """The source function of a clone name (`foo.isra.0'2` -> `foo`); PLT stubs keep their suffix."""
    if name.endswith('@plt'):
        return name
    return re.split(r"[.']", name, maxsplit=1)[0]


def normalise(ins):
    """One instruction of objdump's text without what moves with the layout."""
    ins = re.sub(r'\b[0-9a-f]+ <([^>+]+)(\+0x[0-9a-f]+)?>', r'<\1\2>', ins)
    ins = re.sub(r'0x[0-9a-f]+\(%rip\)', 'RIP', ins)
    ins = re.sub(r'CSWTCH\.\d+', 'CSWTCH', ins)
    return re.sub(r'\s*#.*$', '', ins)


def functions(path):
    out = subprocess.check_output(['objdump', '-d', '--no-show-raw-insn', path], text=True)
    fs, cur = {}, None
    for line in out.splitlines():
        m = SYMBOL.match(line)
        if m:
            cur = m.group(1)
            fs[cur] = []
            continue
        m = INSN.match(line)
        if m and cur is not None:
            fs[cur].append(normalise(m.group(1)))
    return {re.sub(r'^CSWTCH\.\d+$', 'CSWTCH', k): v for k, v in fs.items()}


def compare(before, after):
    a, b = functions(before), functions(after)
    groups = {}
    for side, fs in (('before', a), ('after', b)):
        for name, body in fs.items():
            groups.setdefault(base(name), {'before': {}, 'after': {}})[side][name] = body
    differing = sorted(g for g, v in groups.items() if v['before'] != v['after'])
    # A group whose code is equal once every clone name (its own and its call targets') is read as its source
    # function only differs by a renamed clone, not by an instruction.
    unclone = lambda fs: {CLONE.sub('', n): [CLONE.sub('', i) for i in body] for n, body in fs.items()}
    rename_only = sorted(g for g in differing if unclone(groups[g]['before']) == unclone(groups[g]['after']))
    return {
        'functions': [len(a), len(b)],
        'groups': len(groups),
        'differing_groups': differing,
        'rename_only': rename_only,
        'clones': {g: {'before': sorted(groups[g]['before']), 'after': sorted(groups[g]['after'])} for g in differing},
        'instructions': {g: [sum(map(len, groups[g]['before'].values())), sum(map(len, groups[g]['after'].values()))]
                         for g in differing},
    }


def main(argv):
    if len(argv) not in (3, 4) or (len(argv) == 4 and argv[3] != '--json'):
        sys.exit(__doc__)
    r = compare(argv[1], argv[2])
    if len(argv) == 4:
        print(json.dumps(r, indent=1, sort_keys=True))
        return
    print('functions', *r['functions'], 'groups', r['groups'])
    for g in r['differing_groups']:
        c = r['clones'][g]
        print(f"differs: {g}  instructions {r['instructions'][g][0]} -> {r['instructions'][g][1]}"
              + ('' if c['before'] == c['after'] else f"  clones {c['before']} -> {c['after']}")
              + ('  (clone names only)' if g in r['rename_only'] else ''))


if __name__ == '__main__':
    main(sys.argv)
