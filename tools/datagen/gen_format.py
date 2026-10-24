#!/usr/bin/env python3
"""The format definition (restructure step 10, docs/architecture/formats.md).

data/formats/reg-mc.json holds the facts of Reg M-C: the format id, the rules, level, team size and pick, the Stat
Point limits, the clauses, the timer and the pool source (data/formats/pools/reg-mc.json, the output of
the pinned TeamValidator). Every fact quotes the line of the pinned Showdown checkout it comes from.

A definition may have a tables section (restructure step 5): what gen_closure.py --pool --format <id> builds for the
format (its rule set, the writer's names, the learnset bytes, the id bounds and the excluded formes); check_tables
checks its shape.

This tool writes src/data/formats/reg-mc/format_tables.h: the facts the C engine uses, as named constants (DFI_FORMAT_*), with
_Static_asserts against the public constants that hold the same values. gen_closure.py reads the format id and the
pool source through load_format().

A second definition, data/formats/champions-ou.json ([Gen 9 Champions] OU, singles; step O1 of
docs/superpowers/specs/2026-10-15-gen9-ou-design.md), is checked the same way (its keys, its facts, its pool source and,
with --pin, every quote). The engine reads none of its values (the singles kind of decision 0083 plays the format on
the Reg M-C pool tables), so it writes no header: --format champions-ou with no other option only checks.

A third, data/formats/gen9ou.json ([Gen 9] OU, singles on the gen9 mod; step O8 of the Gen 9 OU design), is checked
the same way and writes no header either. Its tables section names the gen9 rule set, which gen_closure.py refuses by
name until the Gen 9 design brings standalone table sets.

usage:
  python3 tools/datagen/gen_format.py                  # write src/data/formats/reg-mc/format_tables.h
  python3 tools/datagen/gen_format.py --check          # compare only
  python3 tools/datagen/gen_format.py --pin <checkout> # compare every quote with the pinned checkout
  python3 tools/datagen/gen_format.py --format champions-ou [--pin <checkout>]  # check the second definition
  python3 tools/datagen/gen_format.py --format gen9ou [--pin <checkout>]        # check the third definition
"""
import hashlib
import io
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FORMAT_FILE = os.path.join('data', 'formats', 'reg-mc.json')
ENGINE_FORMAT = 'reg-mc'  # the one format the engine plays; only its definition writes the header
HEADER = os.path.join('src', 'data', 'formats', 'reg-mc', 'format_tables.h')

TOP_KEYS = {'comment', 'id', 'showdown_commit', 'showdown_format_id', 'facts', 'engine', 'pool'}
ENGINE_KEYS = {'comment', 'active_per_side'}
POOL_KEYS = {'source', 'sha256', 'made_by'}
# The tables section (restructure step 5, agreed with the OU lane): what gen_closure.py --pool --format <id> builds for
# the format. Optional: a definition without it builds no tables, and gen_closure.py refuses such a format by name.
TABLES_KEYS = {'comment', 'rule_set', 'symbol_prefix', 'include_guard', 'stem', 'learnset_bytes', 'bounds',
               'excluded_formes'}
BOUND_KEYS = {'formes', 'moves', 'moves_per_forme', 'items', 'abilities'}
EXCLUDED_KEYS = {'id', 'reason'}


def fail(message):
    sys.exit('gen_format: ' + message)


def quoted_list(text):
    """The strings of the one [...] list of a line (single-quoted, with \\' for a quote inside)."""
    m = re.search(r'\[([^\]]*)\]', text)
    if m is None:
        return None
    return [item.replace("\\'", "'") for item in re.findall(r"'((?:[^'\\]|\\.)*)'", m.group(1))]


def quoted_items(text):
    """The single-quoted strings of a line that continues a list (no brackets on the line)."""
    if '[' in text or ']' in text or not text.endswith(','):
        return None
    return re.findall(r"'([^']*)'", text)


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
    'terastallization': lambda q: False if q == 'return null;' else True if q == 'return pokemon.teraType;' else None,
    'timer_starting_s': number(r"'Timer Starting = (\d+)'"),
    'timer_grace_s': number(r"'Timer Grace = (\d+)'"),
    'timer_add_per_turn_s': number(r"'Timer Add Per Turn = (\d+)'"),
    'timer_max_per_turn_s': number(r"'Timer Max Per Turn = (\d+)'"),
    'timer_max_first_turn_s': number(r"'Timer Max First Turn = (\d+)'"),
    'timeout_auto_choose': present("'Timeout Auto Choose'"),
    'dc_timer_bank': present("'DC Timer Bank'"),
    # The facts of champions-ou: a singles format without a game type line, the mod's Standard rules, the server's
    # default ladder timer (no timer rule in the format).
    'game_type_default': lambda q: (re.fullmatch(r"this\.gameType = data\.gameType \|\| '([^']*)';", q).group(1)
                                    if re.fullmatch(r"this\.gameType = data\.gameType \|\| '([^']*)';", q) else None),
    'standard_ag_rules': quoted_items,
    'standard_rules': quoted_items,
    'team_preview': present("'Team Preview'"),
    'lead_only_preview': lambda q: True if q == '// will only ask the user to select their lead(s).' else None,
    'endless_battle_clause': present("'Endless Battle Clause'"),
    'sleep_moves_clause': present("'Sleep Moves Clause'"),
    'ohko_clause': present("'OHKO Clause'"),
    'evasion_clause': present("'Evasion Clause'"),
    'ladder_timer_starting_s': number(r'^const STARTING_TIME = (\d+);$'),
    'ladder_timer_grace_s': number(r'^const STARTING_GRACE_TIME = (\d+);$'),
    'ladder_timer_add_per_turn_s': number(r'^addPerTurn: hasLongTurns \? \d+ : (\d+),$'),
    'ladder_timer_max_per_turn_s': number(r'^const MAX_TURN_TIME = (\d+);$'),
    'ladder_timer_max_first_turn_s': number(r'^const MAX_TURN_TIME = (\d+);$'),
    'ladder_timeout_auto_choose': lambda q: False if q == 'timeoutAutoChoose: false,' else None,
    # The facts of gen9ou: the base Standard (data/rulesets.ts, the gen9 mod has none of its own), the format's own
    # clauses, the singles minimum team size, the level and EV limits of the rule table's defaults and Terastallization.
    'standard_clauses': quoted_items,
    'evasion_items_clause': present("'Evasion Items Clause'"),
    'evasion_moves_clause': present("'Evasion Moves Clause'"),
    'evasion_abilities_clause': present("'Evasion Abilities Clause'"),
    'sleep_clause_mod_removed': present("'!Sleep Clause Mod'"),
    'min_team_size_singles': number(r'^(\d+);$'),
    'max_level': number(r"\|\| (\d+);$"),
    'ev_total_max': number(r'^this\.evLimit = dex\.gen > 2 \? (\d+) : null;$'),
    'ev_max': number(r'^if \(set\.evs\[stat as StatID\] > (\d+)\) \{$'),
}

# The facts each definition must hold, exactly.
FACTS = {
    'reg-mc': {'name', 'mod', 'game_type', 'ruleset', 'flat_rules', 'banlist', 'level', 'team_size', 'max_team_size',
               'picked_team_size', 'moves_per_set', 'stat_points_total_max', 'stat_points_max', 'ivs', 'item_clause',
               'species_clause', 'nickname_clause', 'terastallization', 'timer_starting_s', 'timer_grace_s',
               'timer_add_per_turn_s', 'timer_max_per_turn_s', 'timer_max_first_turn_s', 'timeout_auto_choose',
               'dc_timer_bank'},
    'champions-ou': {'name', 'mod', 'game_type_default', 'ruleset', 'banlist', 'standard_ag_rules', 'standard_rules',
                     'level', 'team_size', 'max_team_size', 'team_preview', 'lead_only_preview', 'moves_per_set',
                     'stat_points_total_max', 'stat_points_max', 'ivs', 'item_clause', 'species_clause',
                     'nickname_clause', 'endless_battle_clause', 'sleep_moves_clause', 'ohko_clause', 'evasion_clause',
                     'terastallization', 'ladder_timer_starting_s', 'ladder_timer_grace_s',
                     'ladder_timer_add_per_turn_s', 'ladder_timer_max_per_turn_s', 'ladder_timer_max_first_turn_s',
                     'ladder_timeout_auto_choose'},
    'gen9ou': {'name', 'mod', 'game_type_default', 'ruleset', 'banlist', 'standard_ag_rules', 'standard_rules',
               'standard_clauses', 'team_preview', 'lead_only_preview', 'endless_battle_clause', 'species_clause',
               'nickname_clause', 'ohko_clause', 'evasion_items_clause', 'evasion_moves_clause',
               'evasion_abilities_clause', 'sleep_moves_clause', 'sleep_clause_mod_removed', 'min_team_size_singles',
               'max_team_size', 'max_level', 'moves_per_set', 'ev_total_max', 'ev_max', 'terastallization',
               'ladder_timer_starting_s', 'ladder_timer_grace_s', 'ladder_timer_add_per_turn_s',
               'ladder_timer_max_per_turn_s', 'ladder_timer_max_first_turn_s', 'ladder_timeout_auto_choose'},
}
assert set(READERS) == set().union(*FACTS.values())

# The lines around a quote that make it the format's: the entry, rule or branch the quoted line belongs to.
CONTEXT = {'reg-mc': {
    ('config/formats.ts', 287): '{',
    ('data/mods/champions/rulesets.ts', 28): 'flatrules: {',
    ('data/mods/champions/scripts.ts', 179): 'canTerastallize(pokemon) {',
    ('data/rulesets.ts', 778): 'vgctimer: {',
    ('data/rulesets.ts', 780): "name: 'VGC Timer',",
    ('sim/dex-formats.ts', 336): "if (this.valueRules.get('pickedteamsize') === 'Auto') {",
    ('sim/dex-formats.ts', 348): "if (format.mod.startsWith('champions')) {",
    ('sim/team-validator.ts', 1155): "const useStatPoints = dex.currentMod.startsWith('champions');",
    ('sim/team-validator.ts', 1313): '} else if (useStatPoints) {',
}, 'champions-ou': {
    ('config/formats.ts', 254): '{',
    ('config/formats.ts', 259): '},',
    ('data/mods/champions/rulesets.ts', 2): 'standardag: {',
    ('data/mods/champions/rulesets.ts', 4): 'ruleset: [',
    ('data/mods/champions/rulesets.ts', 7): '],',
    ('data/mods/champions/rulesets.ts', 9): 'standard: {',
    ('data/mods/champions/rulesets.ts', 11): 'ruleset: [',
    ('data/mods/champions/rulesets.ts', 14): '],',
    ('data/mods/champions/scripts.ts', 179): 'canTerastallize(pokemon) {',
    ('sim/battle.ts', 1391): "if (type === 'teampreview') {",
    ('sim/battle.ts', 1392): '// `pickedTeamSize = 6` means the format wants the user to select',
    ('sim/battle.ts', 1395): 'const pickedTeamSize = this.ruleTable.pickedTeamSize;',
    ('sim/dex-formats.ts', 287): "this.pickedTeamSize = Number(this.valueRules.get('pickedteamsize')) || null;",
    ('sim/dex-formats.ts', 348): "if (format.mod.startsWith('champions')) {",
    ('sim/team-validator.ts', 1155): "const useStatPoints = dex.currentMod.startsWith('champions');",
    ('sim/team-validator.ts', 1313): '} else if (useStatPoints) {',
    ('server/room-battle.ts', 183): "const hasLongTurns = format.gameType !== 'singles';",
    ('server/room-battle.ts', 194): 'this.settings = {',
}, 'gen9ou': {
    ('config/formats.ts', 73): '{',
    ('config/formats.ts', 78): '},',
    ('data/rulesets.ts', 11): 'standardag: {',
    ('data/rulesets.ts', 15): 'ruleset: [',
    ('data/rulesets.ts', 17): '],',
    ('data/rulesets.ts', 19): 'standard: {',
    ('data/rulesets.ts', 23): 'ruleset: [',
    ('data/rulesets.ts', 26): '],',
    ('data/rulesets.ts', 166): 'obtainable: {',
    ('data/rulesets.ts', 170): "ruleset: ['Obtainable Moves', 'Obtainable Abilities', 'Obtainable Formes', 'EV Limit = Auto', "
                               "'Obtainable Misc'],",
    ('sim/battle-actions.ts', 1924): 'canTerastallize(pokemon: Pokemon) {',
    ('sim/battle-actions.ts', 1925): 'if (pokemon.getItem().zMove || pokemon.canMegaEvo || this.dex.gen !== 9) {',
    ('sim/battle.ts', 1391): "if (type === 'teampreview') {",
    ('sim/battle.ts', 1392): '// `pickedTeamSize = 6` means the format wants the user to select',
    ('sim/battle.ts', 1395): 'const pickedTeamSize = this.ruleTable.pickedTeamSize;',
    ('sim/dex-formats.ts', 272): "const gameTypeMinTeamSize = ['triples', 'rotation'].includes(format.gameType as 'triples') ? 3 :",
    ('sim/dex-formats.ts', 273): "format.gameType === 'doubles' ? 2 :",
    ('sim/dex-formats.ts', 285): "this.minTeamSize = Number(this.valueRules.get('minteamsize')) || 0;",
    ('sim/dex-formats.ts', 287): "this.pickedTeamSize = Number(this.valueRules.get('pickedteamsize')) || null;",
    ('sim/dex-formats.ts', 343): "if (this.valueRules.get('evlimit') === 'Auto') {",
    ('sim/dex-formats.ts', 391): 'if (!this.minTeamSize) this.minTeamSize = Math.max(gameTypeMinTeamSize, this.pickedTeamSize || 0);',
    ('sim/team-validator.ts', 1319): '} else { // EVs',
    ('server/room-battle.ts', 183): "const hasLongTurns = format.gameType !== 'singles';",
    ('server/room-battle.ts', 194): 'this.settings = {',
}}

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


def format_file(format_id):
    if format_id not in FACTS:
        fail('no format definition %r (known: %s)' % (format_id, ', '.join(sorted(FACTS))))
    return os.path.join('data', 'formats', format_id + '.json')


def check_keys(rel, what, got, want):
    """Exactly the keys `want`: a missing or an unknown key fails by name, nothing gets a default."""
    if type(got) is not dict:
        fail('%s: %s is not an object' % (rel, what))
    missing, unknown = sorted(want - set(got)), sorted(set(got) - want)
    if missing or unknown:
        fail('%s: %s: missing %s, unknown %s' % (rel, what, missing or 'none', unknown or 'none'))


def check_tables(tables, rel):
    """The tables section of a definition, checked by shape (gen_closure.py checks the rule set and the pool)."""
    check_keys(rel, 'tables', tables, TABLES_KEYS)
    for key in ('comment', 'rule_set', 'symbol_prefix', 'include_guard', 'stem'):
        if type(tables[key]) is not str or not tables[key]:
            fail('%s: tables.%s must be a non-empty string' % (rel, key))
    if not re.fullmatch(r'[a-z][a-z0-9]*', tables['symbol_prefix']):
        fail('%s: tables.symbol_prefix %r is not a lower-case C name part' % (rel, tables['symbol_prefix']))
    if not re.fullmatch(r'DUOFORGE_[A-Z0-9_]+_H', tables['include_guard']):
        fail('%s: tables.include_guard %r is not DUOFORGE_..._H' % (rel, tables['include_guard']))
    if not re.fullmatch(r'[a-z][a-z0-9_]*', tables['stem']):
        fail('%s: tables.stem %r is not a file name stem' % (rel, tables['stem']))
    if type(tables['learnset_bytes']) is not int or tables['learnset_bytes'] < 1:
        fail('%s: tables.learnset_bytes must be a positive int' % rel)
    check_keys(rel, 'tables.bounds', tables['bounds'], BOUND_KEYS)
    for key, value in tables['bounds'].items():
        if type(value) is not int or value < 1:
            fail('%s: tables.bounds.%s must be a positive int' % (rel, key))
    if type(tables['excluded_formes']) is not list:
        fail('%s: tables.excluded_formes is not a list' % rel)
    seen = set()
    for i, e in enumerate(tables['excluded_formes']):
        check_keys(rel, 'tables.excluded_formes[%d]' % i, e, EXCLUDED_KEYS)
        if type(e['id']) is not str or not re.fullmatch(r'[a-z0-9]+', e['id']):
            fail('%s: tables.excluded_formes[%d].id %r is not a Showdown id' % (rel, i, e['id']))
        if type(e['reason']) is not str or not e['reason'].strip():
            fail('%s: tables.excluded_formes[%d] (%s) has no reason' % (rel, i, e['id']))
        if e['id'] in seen:
            fail('%s: tables.excluded_formes names %s twice' % (rel, e['id']))
        seen.add(e['id'])


def load_format(repo=REPO, format_id=ENGINE_FORMAT):
    """The format definition, checked: its id, its keys, the facts' shapes and the pool source (its sha256 and the
    Showdown commit and format id of its meta)."""
    rel = format_file(format_id)
    with io.open(os.path.join(repo, rel), encoding='utf-8') as fh:
        fmt = json.load(fh)
    if set(fmt) - {'tables'} != TOP_KEYS or set(fmt['engine']) != ENGINE_KEYS or set(fmt['pool']) != POOL_KEYS:
        fail('%s: unexpected keys' % rel)
    if 'tables' in fmt:
        check_tables(fmt['tables'], rel)
    if fmt['id'] != format_id:
        fail('%s: id %r is not %r' % (rel, fmt['id'], format_id))
    if set(fmt['facts']) != FACTS[format_id]:
        fail('%s: the facts are not %s' % (rel, sorted(FACTS[format_id])))
    for name, fact in fmt['facts'].items():
        if set(fact) != {'value', 'pin'} or len(fact['pin']) != 3:
            fail('%s: fact %s is not {value, pin: [file, line, quote]}' % (rel, name))
    pool = os.path.join(repo, fmt['pool']['source'])
    if file_sha256(pool) != fmt['pool']['sha256']:
        fail('%s differs from the sha256 that %s names' % (fmt['pool']['source'], rel))
    with io.open(pool, encoding='utf-8') as fh:
        meta = json.load(fh)['meta']
    if meta['showdown_commit'] != fmt['showdown_commit'] or meta['format_id'] != fmt['showdown_format_id']:
        fail('%s was not made at the commit for the format that %s names' % (fmt['pool']['source'], rel))
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
    for (path, number_), text in sorted(CONTEXT[fmt['id']].items()):
        if line(path, number_) != text:
            fail('%s:%d is %r, not %r' % (path, number_, line(path, number_), text))
    rules = fmt['facts']
    if fmt['id'] == 'champions-ou':
        check_champions_ou(fmt, line)
        return
    if fmt['id'] == 'gen9ou':
        check_gen9ou(fmt, line)
        return
    for rule in ('Species Clause', 'Nickname Clause', 'Item Clause = 1', 'Picked Team Size = Auto'):
        if rule not in rules['flat_rules']['value']:
            fail('Flat Rules lack %s' % rule)
    if rules['game_type']['value'] != 'doubles' or fmt['engine']['active_per_side'] != 2:
        fail('a doubles format has two positions per side')
    if 'Flat Rules' not in rules['ruleset']['value'] or 'VGC Timer' not in rules['ruleset']['value']:
        fail('the format lacks Flat Rules or VGC Timer')


def check_champions_ou(fmt, line):
    """The checks of a singles Champions format beyond its quotes: the game type comes from the default (the format
    entry has no gameType line), its rules are the mod's Standard, and the definition says one position per side."""
    rules = fmt['facts']
    entry = [line('config/formats.ts', n) for n in range(254, 260)]
    if entry[1] != 'name: "%s",' % rules['name']['value'] or any(text.startswith('gameType:') for text in entry):
        fail('config/formats.ts:254-259 is not the entry of %s without a game type' % rules['name']['value'])
    if rules['game_type_default']['value'] != 'singles' or fmt['engine']['active_per_side'] != 1:
        fail('a singles format has one position per side')
    if rules['ruleset']['value'] != ['Standard'] or 'Standard AG' not in rules['standard_rules']['value']:
        fail('the format is not the mod\'s Standard')
    for rule in ('Species Clause', 'Item Clause = 1', 'Adjust Level = 50', 'Min Team Size = 6'):
        if rule not in rules['standard_ag_rules']['value']:
            fail('Standard AG lacks %s' % rule)
    # The other rules are quoted one by one: the line of each must belong to the list it names.
    for name, rule_line in (('team_preview', 5), ('endless_battle_clause', 5), ('nickname_clause', 13),
                            ('sleep_moves_clause', 13), ('ohko_clause', 13), ('evasion_clause', 13),
                            ('standard_ag_rules', 6), ('species_clause', 6), ('item_clause', 6), ('level', 6),
                            ('team_size', 6), ('standard_rules', 12)):
        pin = rules[name]['pin']
        if pin[0] != 'data/mods/champions/rulesets.ts' or pin[1] != rule_line or rules[name]['value'] in (None, False):
            fail('fact %s is not the rule of data/mods/champions/rulesets.ts:%d' % (name, rule_line))


def check_gen9ou(fmt, line):
    """The checks of [Gen 9] OU beyond its quotes: a singles format of the gen9 mod without a game type line, its rules
    the base Standard (data/rulesets.ts, not a mod's), no Item Clause anywhere in its rules, Terastallization, and one
    position per side."""
    rules = fmt['facts']
    entry = [line('config/formats.ts', n) for n in range(73, 79)]
    if entry[1] != 'name: "%s",' % rules['name']['value'] or any(text.startswith('gameType:') for text in entry):
        fail('config/formats.ts:73-78 is not the entry of %s without a game type' % rules['name']['value'])
    if rules['mod']['value'] != 'gen9' or rules['game_type_default']['value'] != 'singles' or \
            fmt['engine']['active_per_side'] != 1:
        fail('gen9ou is a singles format of the gen9 mod with one position per side')
    if rules['ruleset']['value'][0] != 'Standard' or rules['standard_rules']['value'] != ['Standard AG']:
        fail('the format is not the base Standard')
    lists = [rules[k]['value'] for k in ('ruleset', 'standard_ag_rules', 'standard_rules', 'standard_clauses')]
    if any(r.startswith('Item Clause') for value in lists for r in value):
        fail('gen9ou has no Item Clause; a rule list now names one')
    if rules['terastallization']['value'] is not True:
        fail('gen9ou plays with Terastallization')
    # The other rules are quoted one by one: the line of each must belong to the list it names.
    for name, (path, rule_line) in (
            (('team_preview', ('data/rulesets.ts', 16)), ('endless_battle_clause', ('data/rulesets.ts', 16)),
             ('standard_ag_rules', ('data/rulesets.ts', 16)), ('standard_rules', ('data/rulesets.ts', 24)),
             ('standard_clauses', ('data/rulesets.ts', 25)), ('species_clause', ('data/rulesets.ts', 25)),
             ('nickname_clause', ('data/rulesets.ts', 25)), ('ohko_clause', ('data/rulesets.ts', 25)),
             ('evasion_items_clause', ('data/rulesets.ts', 25)), ('evasion_moves_clause', ('data/rulesets.ts', 25)),
             ('evasion_abilities_clause', ('config/formats.ts', 76)), ('sleep_moves_clause', ('config/formats.ts', 76)),
             ('sleep_clause_mod_removed', ('config/formats.ts', 76)),
             # Quotes that a reader would also accept on another line ("1;", "|| 100;"): their lines are fixed here.
             ('min_team_size_singles', ('sim/dex-formats.ts', 274)), ('max_level', ('sim/dex-formats.ts', 292)),
             ('ev_total_max', ('sim/dex-formats.ts', 344)), ('ev_max', ('sim/team-validator.ts', 1321)),
             ('terastallization', ('sim/battle-actions.ts', 1928)))):
        pin = rules[name]['pin']
        if pin[0] != path or pin[1] != rule_line or rules[name]['value'] in (None, False):
            fail('fact %s is not the rule of %s:%d' % (name, path, rule_line))
    if 'Sleep Clause Mod' not in rules['standard_clauses']['value']:
        fail('the Standard clauses no longer name the Sleep Clause Mod that gen9ou removes')


def main():
    args = sys.argv[1:]
    format_id = ENGINE_FORMAT
    if args[:1] == ['--format'] and len(args) >= 2:
        format_id, args = args[1], args[2:]
    fmt = load_format(format_id=format_id)
    rel = format_file(format_id).replace(os.sep, '/')
    if args[:1] == ['--pin'] and len(args) == 2:
        check_pin(fmt, args[1])
        print('%s: %d facts match the pinned checkout (%s)' % (rel, len(fmt['facts']), fmt['showdown_commit']))
        return
    if format_id != ENGINE_FORMAT:
        if args:
            sys.exit(__doc__)
        print('%s: %d facts, pool %s (check ok; no header is generated from this format)' % (
            rel, len(fmt['facts']), fmt['pool']['source']))
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
