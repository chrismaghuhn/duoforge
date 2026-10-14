#!/usr/bin/env python3
"""The format definition (restructure step 10, docs/architecture/formats.md).

data/formats/reg-mc.json holds the facts of Reg M-C: the format id, the rules, level, team size and pick, the Stat
Point limits, the clauses, the timer and the pool source (docs/research/expansion/data/legal_pool.json, the output of
the pinned TeamValidator). Every fact quotes the line of the pinned Showdown checkout it comes from.

This tool writes src/data/format_tables.h: the facts the C engine uses, as named constants (DFI_FORMAT_*), with
_Static_asserts against the public constants that hold the same values. gen_closure.py reads the format id and the
pool source through load_format().

usage:
  python3 tools/datagen/gen_format.py                  # write src/data/format_tables.h
  python3 tools/datagen/gen_format.py --check          # compare only
  python3 tools/datagen/gen_format.py --pin <checkout> # compare every quote with the pinned checkout
"""
import hashlib
import io
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FORMAT_FILE = os.path.join('data', 'formats', 'reg-mc.json')
HEADER = os.path.join('src', 'data', 'format_tables.h')

TOP_KEYS = {'comment', 'id', 'showdown_commit', 'showdown_format_id', 'facts', 'engine', 'pool'}
ENGINE_KEYS = {'comment', 'active_per_side'}
POOL_KEYS = {'source', 'sha256', 'made_by'}


def fail(message):
    sys.exit('gen_format: ' + message)


def quoted_list(text):
    """The strings of the one [...] list of a line."""
    m = re.search(r'\[([^\]]*)\]', text)
    if m is None:
        return None
    return re.findall(r"'([^']*)'", m.group(1))


def number(pattern):
    return lambda q: int(re.search(pattern, q).group(1)) if re.search(pattern, q) else None


def present(text):
    return lambda q: True if text in q else None


# How each fact is read back from its quote: an unknown fact or a quote that does not give the value fails.
READERS = {
    'name': lambda q: re.fullmatch(r'name: "([^"]*)",', q).group(1) if re.fullmatch(r'name: "([^"]*)",', q) else None,
    'mod': lambda q: re.fullmatch(r"mod: '([^']*)',", q).group(1) if re.fullmatch(r"mod: '([^']*)',", q) else None,
    'game_type': lambda q: re.fullmatch(r"gameType: '([^']*)',", q).group(1) if re.fullmatch(r"gameType: '([^']*)',", q)
    else None,
    'ruleset': quoted_list,
    'flat_rules': quoted_list,
    'banlist': quoted_list,
    'level': number(r"^'Adjust Level = (\d+)'$"),
    'team_size': number(r"^'Min Team Size = (\d+)'$"),
    'max_team_size': number(r"\|\| (\d+);$"),
    'picked_team_size': number(r"^\['doubles', 'rotation'\]\.includes\(format\.gameType\) \? (\d+) :$"),
    'moves_per_set': number(r"\|\| (\d+);$"),
    'stat_points_total_max': number(r'^this\.evLimit = (\d+);$'),
    'stat_points_max': number(r'^if \(set\.evs\[stat as StatID\] > (\d+)\) \{$'),
    'ivs': number(r'\.every\(stat => stat === (\d+)\);$'),
    'item_clause': number(r"^'Item Clause = (\d+)'$"),
    'species_clause': present("'Species Clause'"),
    'nickname_clause': present("'Nickname Clause'"),
    'terastallization': lambda q: False if q == 'return null;' else None,
    'timer_starting_s': number(r"'Timer Starting = (\d+)'"),
    'timer_grace_s': number(r"'Timer Grace = (\d+)'"),
    'timer_add_per_turn_s': number(r"'Timer Add Per Turn = (\d+)'"),
    'timer_max_per_turn_s': number(r"'Timer Max Per Turn = (\d+)'"),
    'timer_max_first_turn_s': number(r"'Timer Max First Turn = (\d+)'"),
    'timeout_auto_choose': present("'Timeout Auto Choose'"),
    'dc_timer_bank': present("'DC Timer Bank'"),
}

# The lines around a quote that make it the format's: the entry, rule or branch the quoted line belongs to.
CONTEXT = {
    ('config/formats.ts', 287): '{',
    ('data/mods/champions/rulesets.ts', 28): 'flatrules: {',
    ('data/mods/champions/scripts.ts', 179): 'canTerastallize(pokemon) {',
    ('data/rulesets.ts', 778): 'vgctimer: {',
    ('data/rulesets.ts', 780): "name: 'VGC Timer',",
    ('sim/dex-formats.ts', 336): "if (this.valueRules.get('pickedteamsize') === 'Auto') {",
    ('sim/dex-formats.ts', 348): "if (format.mod.startsWith('champions')) {",
    ('sim/team-validator.ts', 1155): "const useStatPoints = dex.currentMod.startsWith('champions');",
    ('sim/team-validator.ts', 1313): '} else if (useStatPoints) {',
}

# The facts the engine uses: (constant, fact or engine key, the public constant of the same value or None).
CONSTANTS = [
    ('DFI_FORMAT_ACTIVE_PER_SIDE', 'active_per_side', 'DUOFORGE_ACTIVE_PER_SIDE'),
    ('DFI_FORMAT_TEAM_SIZE', 'team_size', 'DUOFORGE_MAX_ROSTER'),
    ('DFI_FORMAT_BROUGHT_COUNT', 'picked_team_size', None),
    ('DFI_FORMAT_LEVEL', 'level', None),
    ('DFI_FORMAT_MOVES_PER_SET', 'moves_per_set', 'DUOFORGE_MAX_MOVE_SLOTS'),
    ('DFI_FORMAT_STAT_POINTS_MAX', 'stat_points_max', 'DUOFORGE_STAT_POINTS_MAX'),
    ('DFI_FORMAT_STAT_POINTS_TOTAL_MAX', 'stat_points_total_max', 'DUOFORGE_STAT_POINTS_TOTAL_MAX'),
]


def file_sha256(path):
    with io.open(path, 'rb') as fh:
        return hashlib.sha256(fh.read().replace(b'\r\n', b'\n')).hexdigest()


def load_format(repo=REPO):
    """The format definition, checked: its keys, the facts' shapes and the pool source (its sha256 and the Showdown
    commit and format id of its meta)."""
    with io.open(os.path.join(repo, FORMAT_FILE), encoding='utf-8') as fh:
        fmt = json.load(fh)
    if set(fmt) != TOP_KEYS or set(fmt['engine']) != ENGINE_KEYS or set(fmt['pool']) != POOL_KEYS:
        fail('%s: unexpected keys' % FORMAT_FILE)
    if set(fmt['facts']) != set(READERS):
        fail('%s: the facts are not %s' % (FORMAT_FILE, sorted(READERS)))
    for name, fact in fmt['facts'].items():
        if set(fact) != {'value', 'pin'} or len(fact['pin']) != 3:
            fail('%s: fact %s is not {value, pin: [file, line, quote]}' % (FORMAT_FILE, name))
    pool = os.path.join(repo, fmt['pool']['source'])
    if file_sha256(pool) != fmt['pool']['sha256']:
        fail('%s differs from the sha256 that %s names' % (fmt['pool']['source'], FORMAT_FILE))
    with io.open(pool, encoding='utf-8') as fh:
        meta = json.load(fh)['meta']
    if meta['showdown_commit'] != fmt['showdown_commit'] or meta['format_id'] != fmt['showdown_format_id']:
        fail('%s was not made at the commit for the format that %s names' % (fmt['pool']['source'], FORMAT_FILE))
    return fmt


def value_of(fmt, key):
    return fmt['engine'][key] if key in fmt['engine'] else fmt['facts'][key]['value']


def render(fmt):
    lines = ['/* Generated by tools/datagen/gen_format.py from %s; do not edit.' % FORMAT_FILE.replace(os.sep, '/'),
             ' * The facts of the format %s that the engine uses (restructure step 10,' % fmt['id'],
             ' * docs/architecture/formats.md). Public constants that hold the same values are checked here. */',
             '#ifndef DUOFORGE_DATA_FORMAT_TABLES_H',
             '#define DUOFORGE_DATA_FORMAT_TABLES_H',
             '',
             '#include <duoforge/duoforge.h>',
             '']
    for name, key, _public in CONSTANTS:
        value = value_of(fmt, key)
        if type(value) is not int or not 0 < value < 256:
            fail('%s: %s is not a count' % (FORMAT_FILE, key))
        lines.append('#define %s %du' % (name, value))
    lines.append('')
    for name, key, public in CONSTANTS:
        if public is not None:
            lines.append('_Static_assert(%s == %s, "%s: %s");' % (name, public, FORMAT_FILE.replace(os.sep, '/'), key))
    lines.append('_Static_assert(DFI_FORMAT_BROUGHT_COUNT <= DFI_FORMAT_TEAM_SIZE, "a format brings at most its team");')
    lines += ['', '#endif', '']
    return '\n'.join(lines)


def check_pin(fmt, checkout):
    """Every quote is (part of) its line in the checkout, its context lines are there, and it gives the value."""
    texts = {}

    def line(path, number):
        if path not in texts:
            with io.open(os.path.join(checkout, path), encoding='utf-8') as fh:
                texts[path] = fh.read().replace('\r\n', '\n').split('\n')
        return texts[path][number - 1].strip()

    for name, fact in sorted(fmt['facts'].items()):
        path, number_, quote = fact['pin']
        have = line(path, number_)
        if quote != have and not (quote.startswith("'") and quote in have):
            fail('fact %s: %s:%d is %r, not %r' % (name, path, number_, have, quote))
        got = READERS[name](quote)
        if got != fact['value'] or type(got) is not type(fact['value']):
            fail('fact %s: the quote gives %r, the definition says %r' % (name, got, fact['value']))
    for (path, number_), text in sorted(CONTEXT.items()):
        if line(path, number_) != text:
            fail('%s:%d is %r, not %r' % (path, number_, line(path, number_), text))
    rules = fmt['facts']
    for rule in ('Species Clause', 'Nickname Clause', 'Item Clause = 1', 'Picked Team Size = Auto'):
        if rule not in rules['flat_rules']['value']:
            fail('Flat Rules lack %s' % rule)
    if rules['game_type']['value'] != 'doubles' or fmt['engine']['active_per_side'] != 2:
        fail('a doubles format has two positions per side')
    if 'Flat Rules' not in rules['ruleset']['value'] or 'VGC Timer' not in rules['ruleset']['value']:
        fail('the format lacks Flat Rules or VGC Timer')


def main():
    args = sys.argv[1:]
    fmt = load_format()
    if args[:1] == ['--pin'] and len(args) == 2:
        check_pin(fmt, args[1])
        print('%s: %d facts match the pinned checkout (%s)' % (FORMAT_FILE, len(fmt['facts']), fmt['showdown_commit']))
        return
    if args not in ([], ['--check']):
        sys.exit(__doc__)
    text = render(fmt)
    path = os.path.join(REPO, HEADER)
    if args == ['--check']:
        with io.open(path, 'rb') as fh:
            if fh.read().replace(b'\r\n', b'\n') != text.encode('ascii'):
                fail('%s differs from the generator output' % HEADER)
    else:
        with io.open(path, 'w', encoding='ascii', newline='\n') as fh:
            fh.write(text)
    print('%s: %d constants, sha256 %s%s' % (HEADER.replace(os.sep, '/'), len(CONSTANTS),
                                            hashlib.sha256(text.encode('ascii')).hexdigest(),
                                            ' (check ok)' if args else ''))


if __name__ == '__main__':
    main()
