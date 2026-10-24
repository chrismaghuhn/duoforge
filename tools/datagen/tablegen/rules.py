"""The pin checks of steps that span moves, items and abilities: the cross-area facts of single steps and
the content batches (C1, C2, C4, C5, K2, A0, A0P1).

Part of the table generator tools/datagen/gen_closure.py (restructure step 5: split by area from
gen_closure.py@8800b625).
"""
import os
import re

from .source import fail, fields, norm, READER_INPUTS, scalar, Source
from .moves import (
    ability_flags, EXPANDING_FORCE_FACTS, G59_INHERIT_ONLY, G61_DRAGONIZE_FACTS, G61_GATE_FACTS, G77_INHERIT_ONLY,
    PSYCHIC_TERRAIN_FACTS)
from .items import (
    G34_ITEM_FACTS, G46_ITEM_FACTS, G47_ITEM_FACTS, G67_ITEM_FACTS, G75_ITEM_FACTS, G77_ITEM_FACTS, G83_ITEM_FACTS,
    SEED_PAIRS, STONE_TAKE_ITEM)
from .abilities import (
    FAILSKILLSWAP_ABILITIES, failskillswap_c_ids, FAILSKILLSWAP_SOURCE, G34_ABILITY_FACTS, G35_ABILITY_FACTS,
    G39_ABILITY_FACTS, G41_ABILITY_FACTS, G45_ABILITY_FACTS, G46_ABILITY_FACTS, G47_ABILITY_FACTS, G51_ABILITY_FACTS,
    G53_ABILITY_FACTS, G59_ABILITY_FACTS, G61_ABILITY_FACTS, G63_ABILITY_FACTS, G65_ABILITY_FACTS, G67_ABILITY_FACTS,
    G69_ABILITY_FACTS, G71_ABILITY_FACTS, G73_ABILITY_FACTS, G75_ABILITY_FACTS, G77_ABILITY_FACTS, G79_ABILITY_FACTS,
    G81_ABILITY_FACTS, G83_ABILITY_FACTS, K2_ABILITY_FACTS, MEGA2_ABILITY_FACTS)

K2_INHERIT_ONLY = ('piercingdrill',)
K2_BATTLE_FACTS = (
    'checkMoveBypassesProtect(move: ActiveMove, attacker: Pokemon, defender: Pokemon, blockStatus = true) {',
    "if ((move.category !== 'Status' || blockStatus) && move.flags['protect'] &&",
    "this.runEvent('HitProtect', attacker, defender, move)) {",
    'return false;',
    'return true;',
)
# The Champions modifyDamage, in this order: the ModifyDamage chain, the bypass (x0.25, -ability, -zbroken), the final 16-bit step.
K2_DAMAGE_ORDER = (
    "baseDamage = this.battle.runEvent('ModifyDamage', pokemon, target, move, baseDamage);",
    "const bypassProtect = target.getMoveHitData(move).bypassProtect;",
    "baseDamage = this.battle.modify(baseDamage, 0.25);",
    "if (bypassProtect !== true && bypassProtect.effectType === 'Ability') {",
    "this.battle.add('-ability', pokemon, bypassProtect.name);",
    "this.battle.add('-zbroken', target);",
    'return tr(baseDamage, 16);',
)
# The protection checks that the engine's bypass rests on: the default call (blockStatus true) of Protect, Spiky Shield, Baneful
# Bunker, Wide Guard and Quick Guard, and King's Shield's call with blockStatus false (its Status moves pass, G66).
K2_MOVE_FACTS = (
    ('protect', 'if (this.checkMoveBypassesProtect(move, source, target)) return;'),
    ('spikyshield', 'if (this.checkMoveBypassesProtect(move, source, target)) return;'),
    ('banefulbunker', 'if (this.checkMoveBypassesProtect(move, source, target)) return;'),
    ('wideguard', 'if (this.checkMoveBypassesProtect(move, source, target)) return;'),
    ('quickguard', 'if (this.checkMoveBypassesProtect(move, source, target)) return;'),
    ('kingsshield', 'if (this.checkMoveBypassesProtect(move, source, target, false)) return;'),
)


def check_k2_facts(battle_ts, champ_scripts, moves_ts):
    """Step K2: the checkMoveBypassesProtect text (K2_BATTLE_FACTS), the Champions damage lines in their order
    (K2_DAMAGE_ORDER), and the protection calls the bypass reaches (K2_MOVE_FACTS), whitespace collapsed."""
    text = norm(chr(10).join(battle_ts.lines))
    pos = -1
    for fact in K2_BATTLE_FACTS:
        if norm(fact) not in text:
            fail('%s: the pin no longer has "%s"' % (battle_ts.rel, fact))
    text = norm(chr(10).join(champ_scripts.lines))
    pos = -1
    for fact in K2_DAMAGE_ORDER:
        at = text.find(norm(fact), pos + 1)
        if at < 0:
            fail('%s: the pin no longer has "%s" after the previous line' % (champ_scripts.rel, fact))
        pos = at
    for mid, fact in K2_MOVE_FACTS:
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        if norm(fact) not in norm(chr(10).join(e[2])):
            fail('move %s: the entry no longer has "%s"' % (mid, fact))


def check_g15_facts(moves_ts, items_ts):
    """Every fact of EXPANDING_FORCE_FACTS and PSYCHIC_TERRAIN_FACTS is in the pinned move entry, and each seed of
    SEED_PAIRS is Grassy Seed with its terrain and its stat (the engine reads one rule for the terrain seeds)."""
    for mid, facts in (('expandingforce', EXPANDING_FORCE_FACTS), ('psychicterrain', PSYCHIC_TERRAIN_FACTS)):
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('move %s: the entry no longer has "%s"' % (mid, fact))
    grassy = items_ts.entry('grassyseed')
    if grassy is None:
        fail('item grassyseed not found')
    g = fields(grassy[2])
    for iid, terrain, stat in SEED_PAIRS:
        e = items_ts.entry(iid)
        if e is None:
            fail('item %s not found' % iid)
        f = fields(e[2])
        for name in ('onSwitchInPriority', 'onStart', 'onTerrainChange'):
            if name not in f or name not in g or norm(f[name][1]) != norm(g[name][1]).replace('grassyterrain', terrain):
                fail('item %s: %s is not that of grassyseed for %s' % (iid, name, terrain))
        if 'boosts' not in f or norm(f['boosts'][1]) != 'boosts: { %s: 1, },' % stat:
            fail('item %s: boosts is not %s +1' % (iid, stat))
        if set(f) != set(g):
            fail('item %s has other fields than grassyseed: %s' % (iid, sorted(set(f) ^ set(g))))


def check_g61_facts(root, abil_ts, champ_abil):
    """Step G61: the Sheer Force and Dragonize texts (G61_ABILITY_FACTS, G61_DRAGONIZE_FACTS) are in the pinned entries, whitespace
    aside. The Champions mod has no entry for Sheer Force, and its Dragonize entry only inherits and lifts isNonstandard. The
    three gate texts of G61_GATE_FACTS are in their files; the Champions afterMoveSecondaryEvent carries no Sheer Force test."""
    e = abil_ts.entry('sheerforce')
    if e is None:
        fail('ability sheerforce not found')
    if champ_abil.entry('sheerforce') is not None:
        fail('ability sheerforce: the champions mod overrides the entry')
    text = norm(chr(10).join(e[2]))
    for fact in G61_ABILITY_FACTS[0][1]:
        if norm(fact) not in text:
            fail('ability sheerforce: the entry no longer has "%s"' % fact)
    d = abil_ts.entry('dragonize')
    if d is None:
        fail('ability dragonize not found')
    dtext = norm(chr(10).join(d[2]))
    for fact in G61_DRAGONIZE_FACTS:
        if norm(fact) not in dtext:
            fail('ability dragonize: the entry no longer has "%s"' % fact)
    cd = champ_abil.entry('dragonize')
    if cd is None:
        fail('ability dragonize: the champions mod has no entry (expected inherit only)')
    ctext = norm(chr(10).join(cd[2]))
    if 'inherit: true' not in ctext or 'onBasePower' in ctext or 'onModifyType' in ctext:
        fail('ability dragonize: the champions entry is not an inherit-only entry: %s' % ctext)
    for rel, fact in G61_GATE_FACTS:
        src = Source(root, rel, READER_INPUTS if rel in READER_INPUTS else None)
        if norm(fact) not in norm(chr(10).join(src.lines)):
            fail('%s: the gate "%s" is gone' % (rel, fact))
    champ_src = norm(chr(10).join(Source(root, 'data/mods/champions/scripts.ts').lines))
    start = champ_src.find('afterMoveSecondaryEvent(targets, pokemon, move) {')
    if start < 0 or 'hasSheerForce' in champ_src[start:start + 260]:
        fail('champions afterMoveSecondaryEvent: not the ungated form (Sheer Force must not gate it)')


def check_failskillswap(pool_abilities, abil_ts, champ_abil, c_text):
    """The pool's abilities with the pin's failskillswap flag are FAILSKILLSWAP_ABILITIES, exactly, and so are the ids that
    the turn code's dfi_fails_skillswap reads (c_text: the text of FAILSKILLSWAP_SOURCE; issue #620)."""
    found = sorted(aid for aid in pool_abilities if 'failskillswap' in ability_flags(abil_ts, champ_abil, aid))
    if found != sorted(FAILSKILLSWAP_ABILITIES):
        fail('the pool abilities with failskillswap are %s, not FAILSKILLSWAP_ABILITIES %s (src/combat/abilities/skill_swap.h dfi_fails_skillswap)'
             % (found, sorted(FAILSKILLSWAP_ABILITIES)))
    c_ids = failskillswap_c_ids(c_text)
    if len(set(c_ids)) != len(c_ids) or sorted(c_ids) != sorted(FAILSKILLSWAP_ABILITIES):
        fail('%s: dfi_fails_skillswap reads %s, not FAILSKILLSWAP_ABILITIES %s'
             % (FAILSKILLSWAP_SOURCE, c_ids, sorted(FAILSKILLSWAP_ABILITIES)))


def check_g34_facts(abil_ts, champ_abil, items_ts, champ_items):
    """Steps G34, G35, Mega batch 2 and G39: every fact of G34_ABILITY_FACTS, G35_ABILITY_FACTS, MEGA2_ABILITY_FACTS, G39_ABILITY_FACTS and G34_ITEM_FACTS is in the pinned entry, whitespace aside, and the
    Champions mod has no entry of its own for it (an override would change what the engine reads). Step G59: the Champions
    entry of a G59_INHERIT_ONLY ability may only inherit (`inherit: true`, `isNonstandard: null`), which is no override."""
    for kind, facts_by_id, src, champ in (('ability', G34_ABILITY_FACTS + G35_ABILITY_FACTS + MEGA2_ABILITY_FACTS + G39_ABILITY_FACTS + G41_ABILITY_FACTS + G45_ABILITY_FACTS + G46_ABILITY_FACTS + G47_ABILITY_FACTS + G51_ABILITY_FACTS + G53_ABILITY_FACTS + G63_ABILITY_FACTS + G59_ABILITY_FACTS + G69_ABILITY_FACTS + G65_ABILITY_FACTS + G73_ABILITY_FACTS + G67_ABILITY_FACTS + G83_ABILITY_FACTS + G81_ABILITY_FACTS + G79_ABILITY_FACTS + G75_ABILITY_FACTS + G71_ABILITY_FACTS + G77_ABILITY_FACTS + K2_ABILITY_FACTS, abil_ts, champ_abil),
                                          ('item', G34_ITEM_FACTS + G46_ITEM_FACTS + G47_ITEM_FACTS + G67_ITEM_FACTS + G83_ITEM_FACTS + G75_ITEM_FACTS + G77_ITEM_FACTS, items_ts, champ_items)):
        for rid, facts in facts_by_id:
            e = src.entry(rid)
            if e is None:
                fail('%s %s not found' % (kind, rid))
            override = champ.entry(rid)
            if override is not None:
                lines = [' '.join(line.split()) for line in override[2]]
                inner = [line for line in lines[1:] if line not in ('', '},', '}')]
                inherit_only = (rid in G59_INHERIT_ONLY + G77_INHERIT_ONLY + K2_INHERIT_ONLY and lines[0].endswith('{') and
                                inner == ['inherit: true,', 'isNonstandard: null,'])
                if not inherit_only:
                    fail('%s %s: the champions mod overrides the entry' % (kind, rid))
            text = norm(chr(10).join(e[2]))
            for fact in facts:
                if norm(fact) not in text:
                    fail('%s %s: the entry no longer has "%s"' % (kind, rid, fact))


# Step C2 (cheap moves, decision 0015 entry 5cp): the pinned fields of the 30 damaging moves with secondaries or self effects,
# read from data/moves.ts at b2cb775 by c2_literal, which reads the entry as the object literal it is (nested secondary,
# secondaries and self objects, arrays, flags as a set of names). Every field of the entry must be listed here with the value
# the pin gives, and nothing else but C2_IGNORED_KEYS. C2_CHAMPIONS_OVERRIDES: the three moves whose Champions mod entry
# only sets a base power (data/mods/champions/moves.ts); their pin entries are the base values listed here.
C2_IGNORED_KEYS = {'num', 'name', 'zMove', 'contestType'}
C2_CHAMPIONS_OVERRIDES = {'appleacid': 90, 'mountaingale': 120, 'nightdaze': 90}
C2_FACTS = (
    ('bittermalice', {'accuracy': 100, 'basePower': 75, 'category': 'Special', 'pp': 10, 'priority': 0, 'target': 'normal',
                      'type': 'Ghost', 'flags': {'protect', 'mirror', 'metronome'},
                      'secondary': {'chance': 100, 'boosts': {'atk': -1}}}),
    ('zenheadbutt', {'accuracy': 90, 'basePower': 80, 'category': 'Physical', 'pp': 15, 'priority': 0, 'target': 'normal',
                     'type': 'Psychic', 'flags': {'contact', 'protect', 'mirror', 'metronome'},
                     'secondary': {'chance': 20, 'volatileStatus': 'flinch'}}),
    ('pyroball', {'accuracy': 90, 'basePower': 120, 'category': 'Physical', 'pp': 5, 'priority': 0, 'target': 'normal',
                  'type': 'Fire', 'flags': {'protect', 'mirror', 'defrost', 'bullet'},
                  'secondary': {'chance': 10, 'status': 'brn'}}),
    ('wildcharge', {'accuracy': 100, 'basePower': 90, 'category': 'Physical', 'pp': 15, 'priority': 0, 'target': 'normal',
                    'type': 'Electric', 'flags': {'contact', 'protect', 'mirror', 'metronome'}, 'recoil': [1, 4]}),
    ('headlongrush', {'accuracy': 100, 'basePower': 120, 'category': 'Physical', 'pp': 5, 'priority': 0, 'target': 'normal',
                      'type': 'Ground', 'flags': {'contact', 'protect', 'mirror', 'punch', 'metronome'},
                      'self': {'boosts': {'def': -1, 'spd': -1}}}),
    ('extrasensory', {'accuracy': 100, 'basePower': 80, 'category': 'Special', 'pp': 20, 'priority': 0, 'target': 'normal',
                      'type': 'Psychic', 'flags': {'protect', 'mirror', 'metronome'},
                      'secondary': {'chance': 10, 'volatileStatus': 'flinch'}}),
    ('chillingwater', {'accuracy': 100, 'basePower': 50, 'category': 'Special', 'pp': 20, 'priority': 0, 'target': 'normal',
                       'type': 'Water', 'flags': {'protect', 'mirror'},
                       'secondary': {'chance': 100, 'boosts': {'atk': -1}}}),
    ('waterpulse', {'accuracy': 100, 'basePower': 60, 'category': 'Special', 'pp': 20, 'priority': 0, 'target': 'any',
                    'type': 'Water', 'flags': {'protect', 'mirror', 'distance', 'metronome', 'pulse'},
                    'secondary': {'chance': 20, 'volatileStatus': 'confusion'}}),
    ('lunge', {'accuracy': 100, 'basePower': 80, 'category': 'Physical', 'pp': 15, 'priority': 0, 'target': 'normal',
               'type': 'Bug', 'flags': {'contact', 'protect', 'mirror', 'metronome'},
               'secondary': {'chance': 100, 'boosts': {'atk': -1}}}),
    ('blazekick', {'accuracy': 90, 'basePower': 85, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal',
                   'type': 'Fire', 'flags': {'contact', 'protect', 'mirror', 'metronome'}, 'critRatio': 2,
                   'secondary': {'chance': 10, 'status': 'brn'}}),
    ('acidspray', {'accuracy': 100, 'basePower': 40, 'category': 'Special', 'pp': 20, 'priority': 0, 'target': 'normal',
                   'type': 'Poison', 'flags': {'protect', 'mirror', 'metronome', 'bullet'},
                   'secondary': {'chance': 100, 'boosts': {'spd': -2}}}),
    ('paraboliccharge', {'accuracy': 100, 'basePower': 65, 'category': 'Special', 'pp': 20, 'priority': 0,
                         'target': 'allAdjacent', 'type': 'Electric', 'flags': {'protect', 'mirror', 'heal', 'metronome'},
                         'drain': [1, 2]}),
    ('torchsong', {'accuracy': 100, 'basePower': 80, 'category': 'Special', 'pp': 10, 'priority': 0, 'target': 'normal',
                   'type': 'Fire', 'flags': {'protect', 'mirror', 'sound', 'bypasssub', 'metronome'},
                   'secondary': {'chance': 100, 'self': {'boosts': {'spa': 1}}}}),
    ('lavaplume', {'accuracy': 100, 'basePower': 80, 'category': 'Special', 'pp': 15, 'priority': 0, 'target': 'allAdjacent',
                   'type': 'Fire', 'flags': {'protect', 'mirror', 'metronome'},
                   'secondary': {'chance': 30, 'status': 'brn'}}),
    ('firefang', {'accuracy': 95, 'basePower': 65, 'category': 'Physical', 'pp': 15, 'priority': 0, 'target': 'normal',
                  'type': 'Fire', 'flags': {'contact', 'protect', 'mirror', 'metronome', 'bite'},
                  'secondaries': [{'chance': 10, 'status': 'brn'}, {'chance': 10, 'volatileStatus': 'flinch'}]}),
    ('lowsweep', {'accuracy': 100, 'basePower': 65, 'category': 'Physical', 'pp': 20, 'priority': 0, 'target': 'normal',
                  'type': 'Fighting', 'flags': {'contact', 'protect', 'mirror', 'metronome'},
                  'secondary': {'chance': 100, 'boosts': {'spe': -1}}}),
    ('skittersmack', {'accuracy': 90, 'basePower': 70, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal',
                      'type': 'Bug', 'flags': {'contact', 'protect', 'mirror', 'metronome'},
                      'secondary': {'chance': 100, 'boosts': {'spa': -1}}}),
    ('hornleech', {'accuracy': 100, 'basePower': 75, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal',
                   'type': 'Grass', 'flags': {'contact', 'protect', 'mirror', 'heal', 'metronome'}, 'drain': [1, 2]}),
    ('zingzap', {'accuracy': 100, 'basePower': 80, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal',
                 'type': 'Electric', 'flags': {'contact', 'protect', 'mirror', 'metronome'},
                 'secondary': {'chance': 30, 'volatileStatus': 'flinch'}}),
    ('irontail', {'accuracy': 75, 'basePower': 100, 'category': 'Physical', 'pp': 15, 'priority': 0, 'target': 'normal',
                  'type': 'Steel', 'flags': {'contact', 'protect', 'mirror', 'metronome'},
                  'secondary': {'chance': 30, 'boosts': {'def': -1}}}),
    ('dynamicpunch', {'accuracy': 50, 'basePower': 100, 'category': 'Physical', 'pp': 5, 'priority': 0, 'target': 'normal',
                      'type': 'Fighting', 'flags': {'contact', 'protect', 'mirror', 'punch', 'metronome'},
                      'secondary': {'chance': 100, 'volatileStatus': 'confusion'}}),
    ('mudshot', {'accuracy': 95, 'basePower': 55, 'category': 'Special', 'pp': 15, 'priority': 0, 'target': 'normal',
                 'type': 'Ground', 'flags': {'protect', 'mirror', 'metronome'},
                 'secondary': {'chance': 100, 'boosts': {'spe': -1}}}),
    ('chargebeam', {'accuracy': 90, 'basePower': 50, 'category': 'Special', 'pp': 10, 'priority': 0, 'target': 'normal',
                    'type': 'Electric', 'flags': {'protect', 'mirror', 'metronome'},
                    'secondary': {'chance': 70, 'self': {'boosts': {'spa': 1}}}}),
    ('thunderfang', {'accuracy': 95, 'basePower': 65, 'category': 'Physical', 'pp': 15, 'priority': 0, 'target': 'normal',
                     'type': 'Electric', 'flags': {'contact', 'protect', 'mirror', 'metronome', 'bite'},
                     'secondaries': [{'chance': 10, 'status': 'par'}, {'chance': 10, 'volatileStatus': 'flinch'}]}),
    ('crosspoison', {'accuracy': 100, 'basePower': 70, 'category': 'Physical', 'pp': 20, 'priority': 0, 'target': 'normal',
                     'type': 'Poison', 'flags': {'contact', 'protect', 'mirror', 'metronome', 'slicing'}, 'critRatio': 2,
                     'secondary': {'chance': 10, 'status': 'psn'}}),
    ('pounce', {'accuracy': 100, 'basePower': 50, 'category': 'Physical', 'pp': 20, 'priority': 0, 'target': 'normal',
                'type': 'Bug', 'flags': {'contact', 'protect', 'mirror'},
                'secondary': {'chance': 100, 'boosts': {'spe': -1}}}),
    ('nightdaze', {'accuracy': 95, 'basePower': 85, 'category': 'Special', 'pp': 10, 'priority': 0, 'target': 'normal',
                   'type': 'Dark', 'flags': {'protect', 'mirror', 'metronome'},
                   'secondary': {'chance': 40, 'boosts': {'accuracy': -1}}}),
    ('mudslap', {'accuracy': 100, 'basePower': 20, 'category': 'Special', 'pp': 10, 'priority': 0, 'target': 'normal',
                 'type': 'Ground', 'flags': {'protect', 'mirror', 'metronome'},
                 'secondary': {'chance': 100, 'boosts': {'accuracy': -1}}}),
    ('appleacid', {'accuracy': 100, 'basePower': 80, 'category': 'Special', 'pp': 10, 'priority': 0, 'target': 'normal',
                   'type': 'Grass', 'flags': {'protect', 'mirror'},
                   'secondary': {'chance': 100, 'boosts': {'spd': -1}}}),
    ('mountaingale', {'accuracy': 85, 'basePower': 100, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal',
                      'type': 'Ice', 'flags': {'protect', 'mirror', 'metronome'},
                      'secondary': {'chance': 30, 'volatileStatus': 'flinch'}}),
)
# Step A0 part 4 (decision 0015 entry 5ds): the C1 row Shelter (a self Defense +2 Status move, data/moves.ts:16315-16329; its flags
# snatch and metronome are ignored flags). Checked by check_c2_facts with `only=C1_PART4_FACTS`, the same field-by-field check: the
# pin entry has exactly these fields and the Champions mod has no entry for it.
C1_PART4_FACTS = (
    ('shelter', {'accuracy': True, 'basePower': 0, 'category': 'Status', 'pp': 10, 'priority': 0, 'target': 'self',
                 'type': 'Steel', 'flags': {'snatch', 'metronome'}, 'boosts': {'def': 2}}),
)
_C2_TOKEN = re.compile(r"\s*(?:('[^']*'|\"[^\"]*\")|(-?\d+)|(true|false)\b|([A-Za-z_]\w*)|([{}\[\]:,]))")


def c2_literal(text):
    """The value of an object literal of the subset the move entries use: numbers, quoted strings, true and false, arrays,
    objects with identifier keys, trailing commas. Anything else fails loudly."""
    tokens, pos = [], 0
    while True:
        m = _C2_TOKEN.match(text, pos)
        if m is None:
            if text[pos:].strip() == '':
                break
            fail('the C2 reader meets %r in a move entry' % text[pos:pos + 24].strip())
        pos = m.end()
        if m.group(1) is not None:
            tokens.append(('v', m.group(1)[1:-1]))
        elif m.group(2) is not None:
            tokens.append(('v', int(m.group(2))))
        elif m.group(3) is not None:
            tokens.append(('v', m.group(3) == 'true'))
        elif m.group(4) is not None:
            tokens.append(('id', m.group(4)))
        else:
            tokens.append(('p', m.group(5)))

    def value(i):
        if i >= len(tokens):
            fail('a move entry ends inside a value')
        kind, val = tokens[i]
        if kind == 'v':
            return val, i + 1
        if val == '{':
            out, i = {}, i + 1
            while tokens[i] != ('p', '}'):
                if tokens[i][0] != 'id' or tokens[i + 1] != ('p', ':'):
                    fail('a move entry has a key that is not an identifier before token %d' % i)
                out[tokens[i][1]], i = value(i + 2)
                if tokens[i] == ('p', ','):
                    i += 1
            return out, i + 1
        if val == '[':
            out, i = [], i + 1
            while tokens[i] != ('p', ']'):
                item, i = value(i)
                out.append(item)
                if tokens[i] == ('p', ','):
                    i += 1
            return out, i + 1
        fail('a move entry has the token %r where a value starts' % (val,))

    if not tokens or tokens[0] != ('p', '{'):
        fail('a move entry does not start with "{"')
    got, end = value(0)
    if end != len(tokens):
        fail('a move entry has tokens after its closing brace')
    return got


def c2_entry_value(source, mid):
    """The parsed entry of a move (its top-level object), with its flags as a set of names (each must be 1)."""
    e = source.entry(mid)
    if e is None:
        return None
    body = '\n'.join(e[2][1:-1])
    got = c2_literal('{' + body + '}')
    if 'flags' in got:
        if any(v != 1 for v in got['flags'].values()):
            fail('move %s: a flag with a value other than 1' % mid)
        got['flags'] = set(got['flags'])
    return got


def check_c2_facts(moves_ts, champ_moves, only=None):
    """Step C2: the pin entry of every listed move has exactly the listed fields with their values (nothing else but
    C2_IGNORED_KEYS), and the Champions mod has no entry for it, except the three base power overrides of C2_CHAMPIONS_OVERRIDES
    (whose entry is exactly that override). `only`: a tuple of (move id, expected) for the tests."""
    for mid, expected in (C2_FACTS if only is None else only):
        got = c2_entry_value(moves_ts, mid)
        if got is None:
            fail('move %s not found' % mid)
        champ = c2_entry_value(champ_moves, mid)
        if mid in C2_CHAMPIONS_OVERRIDES:
            if champ is None or champ != {'inherit': True, 'basePower': C2_CHAMPIONS_OVERRIDES[mid]}:
                fail('move %s: the Champions mod entry is not the base power override %d' % (mid, C2_CHAMPIONS_OVERRIDES[mid]))
        elif champ is not None:
            fail('move %s: the Champions mod overrides it; the C2 facts must be read again' % mid)
        extra = sorted(set(got) - set(expected) - C2_IGNORED_KEYS)
        if extra:
            fail('move %s: the pin has fields the C2 facts do not list: %s' % (mid, ', '.join(extra)))
        for key, want in expected.items():
            if key not in got:
                fail('move %s: the pin has no %s' % (mid, key))
            if got[key] != want:
                fail('move %s: %s is %r in the pin, not %r' % (mid, key, got[key], want))


# Step C4 (cheap moves, decision 0015 entry 5ct), groups b and c: the pinned fields of the twelve data-only moves, read from
# data/moves.ts at b2cb775 (Champions overrides merged the way parse_move merges them). `secondary` is (chance, self boosts).
# Psyshield Bash is the one Champions override here (inherit, basePower 90); any other override fails.
C4_IGNORED_KEYS = {'num', 'name', 'zMove', 'contestType', 'inherit', 'isNonstandard'}
# Storm Throw's Champions entry only lifts isNonstandard (isNonstandard is not read by the tables); Psyshield Bash's raises basePower.
C4_CHAMPION_OVERRIDES = {'psyshieldbash': {'basePower': 90}, 'stormthrow': {'isNonstandard': 'null'}}
C4_FACTS = (
    ('flamecharge', {'accuracy': 100, 'basePower': 50, 'category': 'Physical', 'pp': 20, 'priority': 0, 'target': 'normal',
                     'type': 'Fire', 'flags': {'contact', 'protect', 'mirror', 'metronome'}, 'secondary': (100, {'spe': 1})}),
    ('aquastep', {'accuracy': 100, 'basePower': 80, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal',
                  'type': 'Water', 'flags': {'contact', 'protect', 'mirror', 'dance', 'metronome'}, 'secondary': (100, {'spe': 1})}),
    ('trailblaze', {'accuracy': 100, 'basePower': 50, 'category': 'Physical', 'pp': 20, 'priority': 0, 'target': 'normal',
                    'type': 'Grass', 'flags': {'contact', 'protect', 'mirror'}, 'secondary': (100, {'spe': 1})}),
    ('steelwing', {'accuracy': 90, 'basePower': 70, 'category': 'Physical', 'pp': 25, 'priority': 0, 'target': 'normal',
                   'type': 'Steel', 'flags': {'contact', 'protect', 'mirror', 'metronome'}, 'secondary': (10, {'def': 1})}),
    ('psyshieldbash', {'accuracy': 90, 'basePower': 90, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal',
                       'type': 'Psychic', 'flags': {'contact', 'protect', 'mirror', 'metronome'}, 'secondary': (100, {'def': 1})}),
    ('scaryface', {'accuracy': 100, 'basePower': 0, 'category': 'Status', 'pp': 10, 'priority': 0, 'target': 'normal',
                   'type': 'Normal', 'flags': {'protect', 'reflectable', 'mirror', 'allyanim', 'metronome'}, 'boosts': {'spe': -2}}),
    ('eerieimpulse', {'accuracy': 100, 'basePower': 0, 'category': 'Status', 'pp': 15, 'priority': 0, 'target': 'normal',
                      'type': 'Electric', 'flags': {'protect', 'reflectable', 'mirror', 'metronome'}, 'boosts': {'spa': -2}}),
    ('screech', {'accuracy': 85, 'basePower': 0, 'category': 'Status', 'pp': 40, 'priority': 0, 'target': 'normal',
                 'type': 'Normal', 'flags': {'protect', 'reflectable', 'mirror', 'sound', 'bypasssub', 'allyanim', 'metronome'},
                 'boosts': {'def': -2}}),
    ('nobleroar', {'accuracy': 100, 'basePower': 0, 'category': 'Status', 'pp': 30, 'priority': 0, 'target': 'normal',
                   'type': 'Normal', 'flags': {'protect', 'reflectable', 'mirror', 'sound', 'bypasssub', 'metronome'},
                   'boosts': {'atk': -1, 'spa': -1}}),
    ('spicyextract', {'accuracy': True, 'basePower': 0, 'category': 'Status', 'pp': 15, 'priority': 0, 'target': 'normal',
                      'type': 'Grass', 'flags': {'protect', 'reflectable', 'mirror'}, 'boosts': {'atk': 2, 'def': -2}}),
    ('amnesia', {'accuracy': True, 'basePower': 0, 'category': 'Status', 'pp': 20, 'priority': 0, 'target': 'self',
                 'type': 'Psychic', 'flags': {'snatch', 'metronome'}, 'boosts': {'spd': 2}}),
    ('cosmicpower', {'accuracy': True, 'basePower': 0, 'category': 'Status', 'pp': 20, 'priority': 0, 'target': 'self',
                     'type': 'Psychic', 'flags': {'snatch', 'metronome'}, 'boosts': {'def': 1, 'spd': 1}}),
    # Group a (willCrit, the WILL_CRIT special): the critical hit without a roll.
    ('stormthrow', {'accuracy': 100, 'basePower': 60, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal',
                    'type': 'Fighting', 'flags': {'contact', 'protect', 'mirror', 'metronome'}, 'willCrit': True}),
    ('flowertrick', {'accuracy': True, 'basePower': 70, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal',
                     'type': 'Grass', 'flags': {'protect', 'mirror', 'metronome'}, 'willCrit': True}),
    ('frostbreath', {'accuracy': 90, 'basePower': 60, 'category': 'Special', 'pp': 10, 'priority': 0, 'target': 'normal',
                     'type': 'Ice', 'flags': {'protect', 'mirror', 'metronome'}, 'willCrit': True}),
)


def c4_value(key, text):
    """The value of one pin field, read as c1_value reads it; `secondary` is (chance, the self boosts of its roll)."""
    if key == 'secondary':
        m = re.fullmatch(r'secondary: \{ chance: (\d+), self: \{ boosts: \{ ((?:\w+: -?\d+, ?)+)\}, \}, \},', norm(text))
        if m is None:
            fail('secondary is not a self-boost roll: %s' % norm(text))
        return int(m.group(1)), {name: int(val) for name, val in re.findall(r'(\w+): (-?\d+)', m.group(2))}
    if key == 'flags':
        return set(re.findall(r'(\w+): 1\b', text))
    if key == 'boosts':
        return {name: int(val) for name, val in re.findall(r'(\w+): (-?\d+)', text)}
    return scalar(text)


def check_c4_facts(moves_ts, champ_moves, only=None):
    """Step C4: each listed move has exactly the listed fields (nothing else but C4_IGNORED_KEYS) with its pinned value, its
    Champions override (if any) is the one listed in C4_CHAMPION_OVERRIDES, merged the way parse_move merges it."""
    for mid, expected in (C4_FACTS if only is None else only):
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        got = fields(e[2])
        ce = champ_moves.entry(mid)
        if mid in C4_CHAMPION_OVERRIDES:
            if ce is None:
                fail('move %s: the Champions override is missing' % mid)
            cf = fields(ce[2])
            if 'inherit' not in cf:
                fail('move %s: the Champions override does not inherit' % mid)
            for key, want in C4_CHAMPION_OVERRIDES[mid].items():
                if key not in cf or c4_value(key, cf[key][1]) != want:
                    fail('move %s: the Champions %s is not %r' % (mid, key, want))
            got.update({k: v for k, v in cf.items() if k in C4_CHAMPION_OVERRIDES[mid]})
        elif ce is not None:
            fail('move %s: the Champions mod overrides it; the C4 facts must be read again' % mid)
        extra = sorted(set(got) - set(expected) - C4_IGNORED_KEYS)
        if extra:
            fail('move %s: the pin has fields the C4 facts do not list: %s' % (mid, ', '.join(extra)))
        for key, want in expected.items():
            if key not in got:
                fail('move %s: the pin has no %s' % (mid, key))
            have = c4_value(key, got[key][1])
            if have != want:
                fail('move %s: %s is %r in the pin, not %r' % (mid, key, have, want))


# Step C5 (decision 0015 entry 5cy): the pinned fields of the data-only moves of the step, read from data/moves.ts at b2cb775.
# Every field of the pin entry must be listed (C5_IGNORED_KEYS aside) with its value, and the Champions mod must have no entry.
C5_IGNORED_KEYS = {'num', 'name', 'contestType', 'zMove', 'maxMove', 'damageCallback', 'onTryImmunity'}
C5_FACTS = (
    ('surf', {'accuracy': 100, 'basePower': 90, 'category': 'Special', 'pp': 15, 'priority': 0, 'target': 'allAdjacent',
              'type': 'Water', 'flags': {'protect', 'mirror', 'nonsky', 'metronome'}}),
    # Endeavor (data/moves.ts:4784-4804): the callbacks are checked by the handler (C5_HANDLERS, SPECIAL_P), not here.
    ('endeavor', {'accuracy': 100, 'basePower': 0, 'category': 'Physical', 'pp': 5, 'priority': 0, 'target': 'normal',
                  'type': 'Normal', 'flags': {'contact', 'protect', 'mirror', 'metronome', 'noparentalbond'}}),
)


def c5_value(key, text):
    """The value of one pin field: a flag set or a scalar."""
    if key == 'flags':
        return set(re.findall(r'(\w+): 1\b', text))
    return scalar(text)


def check_c5_facts(moves_ts, champ_moves, only=None):
    """Step C5: each listed move has exactly the listed fields (nothing else but C5_IGNORED_KEYS), each with its pinned value,
    and no Champions override. `only`: a tuple of (move id, expected) for the tests."""
    for mid, expected in (C5_FACTS if only is None else only):
        if champ_moves.entry(mid) is not None:
            fail('move %s: the Champions mod overrides it; the C5 facts must be read again' % mid)
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        got = fields(e[2])
        extra = sorted(set(got) - set(expected) - C5_IGNORED_KEYS)
        if extra:
            fail('move %s: the pin has fields the C5 facts do not list: %s' % (mid, ', '.join(extra)))
        for key, want in expected.items():
            if key not in got:
                fail('move %s: the pin has no %s' % (mid, key))
            have = c5_value(key, got[key][1])
            if have != want:
                fail('move %s: %s is %r in the pin, not %r' % (mid, key, have, want))


# Step C1 (cheap moves, decision 0015 entry 5co): the pinned fields of the 21 moves of the first cheap batch, read from
# data/moves.ts at b2cb775. Every field of the pin entry must be listed here, with the value the pin gives (numbers, true,
# the target and type names, the flag names, boosts, status and the heal fraction), and the Champions mod must not
# override any of them. Jet Punch is listed for its pin values only: it is not marked (no POOL team can use it).
C1_IGNORED_KEYS = {'num', 'name', 'zMove', 'contestType'}
C1_FACTS = (
    ('slackoff', {'accuracy': True, 'basePower': 0, 'category': 'Status', 'pp': 5, 'priority': 0, 'target': 'self', 'type': 'Normal',
                  'flags': {'snatch', 'heal', 'metronome'}, 'heal': (1, 2)}),
    ('cottonguard', {'accuracy': True, 'basePower': 0, 'category': 'Status', 'pp': 10, 'priority': 0, 'target': 'self',
                     'type': 'Grass', 'flags': {'snatch', 'metronome'}, 'boosts': {'def': 3}}),
    ('shelter', {'accuracy': True, 'basePower': 0, 'category': 'Status', 'pp': 10, 'priority': 0, 'target': 'self', 'type': 'Steel',
                 'flags': {'snatch', 'metronome'}, 'boosts': {'def': 2}}),
    ('glare', {'accuracy': 100, 'basePower': 0, 'category': 'Status', 'pp': 30, 'priority': 0, 'target': 'normal', 'type': 'Normal',
               'flags': {'protect', 'reflectable', 'mirror', 'metronome'}, 'status': 'par'}),
    ('acidarmor', {'accuracy': True, 'basePower': 0, 'category': 'Status', 'pp': 20, 'priority': 0, 'target': 'self', 'type': 'Poison',
                   'flags': {'snatch', 'metronome'}, 'boosts': {'def': 2}}),
    ('featherdance', {'accuracy': 100, 'basePower': 0, 'category': 'Status', 'pp': 15, 'priority': 0, 'target': 'normal',
                      'type': 'Flying', 'flags': {'protect', 'reflectable', 'mirror', 'dance', 'allyanim', 'metronome'},
                      'boosts': {'atk': -2}}),
    ('babydolleyes', {'accuracy': 100, 'basePower': 0, 'category': 'Status', 'pp': 30, 'priority': 1, 'target': 'normal',
                      'type': 'Fairy', 'flags': {'protect', 'reflectable', 'mirror', 'allyanim', 'metronome'}, 'boosts': {'atk': -1}}),
    ('metalsound', {'accuracy': 85, 'basePower': 0, 'category': 'Status', 'pp': 40, 'priority': 0, 'target': 'normal', 'type': 'Steel',
                    'flags': {'protect', 'reflectable', 'mirror', 'sound', 'bypasssub', 'allyanim', 'metronome'},
                    'boosts': {'spd': -2}}),
    ('shiftgear', {'accuracy': True, 'basePower': 0, 'category': 'Status', 'pp': 10, 'priority': 0, 'target': 'self', 'type': 'Steel',
                   'flags': {'snatch', 'metronome'}, 'boosts': {'spe': 2, 'atk': 1}}),
    ('rockpolish', {'accuracy': True, 'basePower': 0, 'category': 'Status', 'pp': 20, 'priority': 0, 'target': 'self', 'type': 'Rock',
                    'flags': {'snatch', 'metronome'}, 'boosts': {'spe': 2}}),
    ('jetpunch', {'accuracy': 100, 'basePower': 60, 'category': 'Physical', 'pp': 15, 'priority': 1, 'target': 'normal', 'type': 'Water',
                  'flags': {'contact', 'protect', 'mirror', 'punch'}}),
    ('aerialace', {'accuracy': True, 'basePower': 60, 'category': 'Physical', 'pp': 20, 'priority': 0, 'target': 'any', 'type': 'Flying',
                   'flags': {'contact', 'protect', 'mirror', 'distance', 'metronome', 'slicing'}}),
    ('seedbomb', {'accuracy': 100, 'basePower': 80, 'category': 'Physical', 'pp': 15, 'priority': 0, 'target': 'normal', 'type': 'Grass',
                  'flags': {'protect', 'mirror', 'metronome', 'bullet'}}),
    ('megahorn', {'accuracy': 85, 'basePower': 120, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal', 'type': 'Bug',
                  'flags': {'contact', 'protect', 'mirror', 'metronome'}}),
    ('megakick', {'accuracy': 75, 'basePower': 120, 'category': 'Physical', 'pp': 5, 'priority': 0, 'target': 'normal', 'type': 'Normal',
                  'flags': {'contact', 'protect', 'mirror', 'metronome'}}),
    ('drillpeck', {'accuracy': 100, 'basePower': 80, 'category': 'Physical', 'pp': 20, 'priority': 0, 'target': 'any', 'type': 'Flying',
                   'flags': {'contact', 'protect', 'mirror', 'distance', 'metronome'}}),
    ('smartstrike', {'accuracy': True, 'basePower': 70, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal',
                     'type': 'Steel', 'flags': {'contact', 'protect', 'mirror', 'metronome'}}),
    ('aquatail', {'accuracy': 90, 'basePower': 90, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal', 'type': 'Water',
                  'flags': {'contact', 'protect', 'mirror', 'metronome'}}),
    ('shadowpunch', {'accuracy': True, 'basePower': 60, 'category': 'Physical', 'pp': 20, 'priority': 0, 'target': 'normal',
                     'type': 'Ghost', 'flags': {'contact', 'protect', 'mirror', 'punch', 'metronome'}}),
    ('brutalswing', {'accuracy': 100, 'basePower': 60, 'category': 'Physical', 'pp': 20, 'priority': 0, 'target': 'allAdjacent',
                     'type': 'Dark', 'flags': {'contact', 'protect', 'mirror', 'metronome'}}),
    ('petalblizzard', {'accuracy': 100, 'basePower': 90, 'category': 'Physical', 'pp': 15, 'priority': 0, 'target': 'allAdjacent',
                       'type': 'Grass', 'flags': {'protect', 'mirror', 'metronome', 'wind'}}),
)


def c1_value(key, text):
    """The value of one pin field, read as the pin writes it: a flag set, a heal fraction, a boosts dict, or a scalar."""
    if key == 'flags':
        return set(re.findall(r'(\w+): 1\b', text))
    if key == 'heal':
        return tuple(int(x) for x in re.findall(r'\d+', text.split(':', 1)[1]))
    if key == 'boosts':
        return {name: int(val) for name, val in re.findall(r'(\w+): (-?\d+)', text)}
    return scalar(text)


def check_c1_facts(moves_ts, champ_moves, only=None):
    """Step C1: the pin entry of every listed move has exactly the listed fields (nothing else but C1_IGNORED_KEYS), each
    with its value, and the Champions mod has no entry for it. `only`: a tuple of (move id, expected) for the tests."""
    for mid, expected in (C1_FACTS if only is None else only):
        if champ_moves.entry(mid) is not None:
            fail('move %s: the Champions mod overrides it; the C1 facts must be read again' % mid)
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        got = fields(e[2])
        extra = sorted(set(got) - set(expected) - C1_IGNORED_KEYS)
        if extra:
            fail('move %s: the pin has fields the C1 facts do not list: %s' % (mid, ', '.join(extra)))
        for key, want in expected.items():
            if key not in got:
                fail('move %s: the pin has no %s' % (mid, key))
            have = c1_value(key, got[key][1])
            if have != want:
                fail('move %s: %s is %r in the pin, not %r' % (mid, key, have, want))


# Step A0 (decision 0015, lane A batch A0, part 2): the pinned fields of the data-only moves of the batch, read from data/moves.ts
# at b2cb775 with the Champions override merged the way parse_move merges it (inherit true: the listed fields replace the base's).
# Every field of the merged entry must be listed (A0_IGNORED_KEYS aside) with its value, and the Champions mod overrides exactly
# the fields of A0_CHAMPIONS_OVERRIDES and nothing else. Toxic Thread is not in the batch: its primary status and its primary
# target boost are not both applied by the move body (turn.c, the PRIMARY_TARGET branch continues before the primary status).
A0_IGNORED_KEYS = {'num', 'name', 'contestType', 'zMove', 'maxMove', 'isNonstandard'}
A0_CHAMPIONS_OVERRIDES = {
    'crabhammer': {'accuracy': 95},
    'crushclaw': {'flags': {'contact', 'protect', 'mirror', 'metronome', 'slicing'}},
    'firelash': {'basePower': 90},
}
A0_FACTS = (
    ('dragonrush', {'accuracy': 75, 'basePower': 100, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal',
                    'type': 'Dragon', 'flags': {'contact', 'protect', 'mirror', 'metronome', 'minimize'},
                    'secondary': {'chance': 20, 'volatileStatus': 'flinch'}}),
    ('crabhammer', {'accuracy': 95, 'basePower': 100, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal',
                    'type': 'Water', 'flags': {'contact', 'protect', 'mirror', 'metronome'}, 'critRatio': 2}),
    ('bite', {'accuracy': 100, 'basePower': 60, 'category': 'Physical', 'pp': 25, 'priority': 0, 'target': 'normal',
              'type': 'Dark', 'flags': {'contact', 'protect', 'mirror', 'metronome', 'bite'},
              'secondary': {'chance': 30, 'volatileStatus': 'flinch'}}),
    ('crosschop', {'accuracy': 80, 'basePower': 100, 'category': 'Physical', 'pp': 5, 'priority': 0, 'target': 'normal',
                   'type': 'Fighting', 'flags': {'contact', 'protect', 'mirror', 'metronome'}, 'critRatio': 2}),
    ('crushclaw', {'accuracy': 95, 'basePower': 75, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal',
                   'type': 'Normal', 'flags': {'contact', 'protect', 'mirror', 'metronome', 'slicing'},
                   'secondary': {'chance': 50, 'boosts': {'def': -1}}}),
    ('doubleteam', {'accuracy': True, 'basePower': 0, 'category': 'Status', 'pp': 15, 'priority': 0, 'target': 'self',
                    'type': 'Normal', 'flags': {'snatch', 'metronome'}, 'boosts': {'evasion': 1}}),
    ('firelash', {'accuracy': 100, 'basePower': 90, 'category': 'Physical', 'pp': 15, 'priority': 0, 'target': 'normal',
                  'type': 'Fire', 'flags': {'contact', 'protect', 'mirror', 'metronome'},
                  'secondary': {'chance': 100, 'boosts': {'def': -1}}}),
    ('inferno', {'accuracy': 50, 'basePower': 100, 'category': 'Special', 'pp': 5, 'priority': 0, 'target': 'normal',
                 'type': 'Fire', 'flags': {'protect', 'mirror', 'metronome'}, 'secondary': {'chance': 100, 'status': 'brn'}}),
    ('seismictoss', {'accuracy': 100, 'basePower': 0, 'damage': 'level', 'category': 'Physical', 'pp': 20, 'priority': 0,
                     'target': 'normal', 'type': 'Fighting', 'flags': {'contact', 'protect', 'mirror', 'nonsky', 'metronome'}}),
    ('sweetkiss', {'accuracy': 75, 'basePower': 0, 'category': 'Status', 'pp': 10, 'priority': 0, 'target': 'normal',
                   'type': 'Fairy', 'flags': {'protect', 'reflectable', 'mirror', 'metronome'}, 'volatileStatus': 'confusion'}),
    ('tearfullook', {'accuracy': True, 'basePower': 0, 'category': 'Status', 'pp': 20, 'priority': 0, 'target': 'normal',
                     'type': 'Normal', 'flags': {'reflectable', 'mirror', 'metronome'}, 'boosts': {'atk': -1, 'spa': -1}}),
    ('aromaticmist', {'accuracy': True, 'basePower': 0, 'category': 'Status', 'pp': 20, 'priority': 0, 'target': 'adjacentAlly',
                      'type': 'Fairy', 'flags': {'bypasssub', 'metronome'}, 'boosts': {'spd': 1}}),
)


def check_a0_facts(moves_ts, champ_moves, only=None):
    """Step A0: each listed move has exactly the listed fields of its merged entry (nothing else but A0_IGNORED_KEYS), each with
    its pinned value; the Champions mod overrides it only as A0_CHAMPIONS_OVERRIDES says. `only`: a tuple of (move id, expected)
    for the tests."""
    for mid, expected in (A0_FACTS if only is None else only):
        got = c2_entry_value(moves_ts, mid)
        if got is None:
            fail('move %s not found' % mid)
        champ = c2_entry_value(champ_moves, mid)
        if mid in A0_CHAMPIONS_OVERRIDES:
            if champ != dict({'inherit': True}, **A0_CHAMPIONS_OVERRIDES[mid]):
                fail('move %s: the Champions mod entry is not the override %r' % (mid, A0_CHAMPIONS_OVERRIDES[mid]))
            got.update(A0_CHAMPIONS_OVERRIDES[mid])
        elif champ is not None:
            fail('move %s: the Champions mod overrides it; the A0 facts must be read again' % mid)
        extra = sorted(set(got) - set(expected) - A0_IGNORED_KEYS)
        if extra:
            fail('move %s: the pin has fields the A0 facts do not list: %s' % (mid, ', '.join(extra)))
        for key, want in expected.items():
            if key not in got:
                fail('move %s: the pin has no %s' % (mid, key))
            if got[key] != want:
                fail('move %s: %s is %r in the pin, not %r' % (mid, key, got[key], want))


# Step A0 (decision 0015, batch A0 part 1; the C1 model for data-only moves). The pinned fields of the ten moves below, read from
# data/moves.ts at b2cb775 (Champions overrides merged as parse_move merges them). Every field of the pin entry must be listed
# (A0P1_IGNORED_KEYS aside) with its value; a callback must be listed in A0P1_CALLBACKS and is checked by its text (A0P1_SAME_TEXT:
# the donor move of the handler, whose callback the row runs). Meteor Assault's Champions basePower 170 is in A0P1_CHAMPION_OVERRIDES.
A0P1_IGNORED_KEYS = {'num', 'name', 'zMove', 'maxMove', 'contestType', 'isNonstandard'}
A0P1_CHAMPION_OVERRIDES = {'meteorassault': {'basePower': 170}}
A0P1_FACTS = (
    ('meteorassault', {'accuracy': 100, 'basePower': 170, 'category': 'Physical', 'pp': 5, 'priority': 0, 'target': 'normal',
                       'type': 'Fighting', 'flags': {'recharge', 'protect', 'mirror', 'failinstruct'},
                       'self': "self: { volatileStatus: 'mustrecharge', },"}),
    ('watershuriken', {'accuracy': 100, 'basePower': 15, 'category': 'Special', 'pp': 20, 'priority': 1, 'target': 'normal',
                       'type': 'Water', 'flags': {'protect', 'mirror', 'metronome'}, 'multihit': (2, 5)}),
    ('rockblast', {'accuracy': 90, 'basePower': 25, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal',
                   'type': 'Rock', 'flags': {'protect', 'mirror', 'metronome', 'bullet'}, 'multihit': (2, 5)}),
    ('bulletseed', {'accuracy': 100, 'basePower': 25, 'category': 'Physical', 'pp': 30, 'priority': 0, 'target': 'normal',
                    'type': 'Grass', 'flags': {'protect', 'mirror', 'metronome', 'bullet'}, 'multihit': (2, 5)}),
    ('pinmissile', {'accuracy': 95, 'basePower': 25, 'category': 'Physical', 'pp': 20, 'priority': 0, 'target': 'normal',
                    'type': 'Bug', 'flags': {'protect', 'mirror', 'metronome'}, 'multihit': (2, 5)}),
    ('storedpower', {'accuracy': 100, 'basePower': 20, 'category': 'Special', 'pp': 10, 'priority': 0, 'target': 'normal',
                     'type': 'Psychic', 'flags': {'protect', 'mirror', 'metronome'}}),
    ('aircutter', {'accuracy': 95, 'basePower': 60, 'category': 'Special', 'pp': 25, 'priority': 0, 'target': 'allAdjacentFoes',
                   'type': 'Flying', 'flags': {'protect', 'mirror', 'metronome', 'slicing', 'wind'}, 'critRatio': 2}),
    ('hornleech', {'accuracy': 100, 'basePower': 75, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal',
                   'type': 'Grass', 'flags': {'contact', 'protect', 'mirror', 'heal', 'metronome'}, 'drain': (1, 2)}),
    ('heatcrash', {'accuracy': 100, 'basePower': 0, 'category': 'Physical', 'pp': 10, 'priority': 0, 'target': 'normal',
                   'type': 'Fire', 'flags': {'contact', 'protect', 'mirror', 'nonsky', 'metronome', 'minimize'}}),
    ('decorate', {'accuracy': True, 'basePower': 0, 'category': 'Status', 'pp': 15, 'priority': 0, 'target': 'normal',
                  'type': 'Fairy', 'flags': {'allyanim'}, 'boosts': {'atk': 2, 'spa': 2}}),
)
A0P1_CALLBACKS = {'storedpower': {'basePowerCallback'}, 'watershuriken': {'basePowerCallback'},
                'heatcrash': {'basePowerCallback', 'onTryHit'}}
# The callback of a moved handler must be the text of its donor move (the pinned callbacks of Power Trip and Heavy Slam).
A0P1_SAME_TEXT = {('storedpower', 'basePowerCallback'): ('powertrip', 'basePowerCallback'),
                ('heatcrash', 'basePowerCallback'): ('heavyslam', 'basePowerCallback'),
                ('heatcrash', 'onTryHit'): ('heavyslam', 'onTryHit')}
# Water Shuriken's callback adds 5 for Greninja-Ash with Battle Bond; the pool has neither, so it never runs (check_a0p1_pool).
A0P1_WATERSHURIKEN_CALLBACK = "pokemon.species.name === 'Greninja-Ash' && pokemon.hasAbility('battlebond')"
# The Mega Stones of the batch: the item, its base species and its Mega forme (data/items.ts and the legal pool).
A0P1_STONES = {'chesnaughtite': ('Chesnaught', 'Chesnaught-Mega', ('chesnaught', 'chesnaughtmega')),
             'altarianite': ('Altaria', 'Altaria-Mega', ('altaria', 'altariamega'))}


def a0p1_value(key, text):
    """The value of one pin field: a flag set, a boosts dict, a tuple of a multihit or drain array, the normalised text of a
    block (self), or a scalar."""
    if key == 'flags':
        return set(re.findall(r'(\w+): 1\b', text))
    if key == 'boosts':
        return {name: int(val) for name, val in re.findall(r'(\w+): (-?\d+)', text)}
    if key in ('multihit', 'drain'):
        return tuple(int(x) for x in re.findall(r'\d+', text.split(':', 1)[1]))
    if key == 'self':
        return norm(text)
    return scalar(text)


def check_a0p1_pool(legal):
    """The three facts of the legal pool that the A0 marks rest on: no Battle Bond and no Greninja-Ash (the Water Shuriken callback
    is unreachable), no Loaded Dice (the multi-hit count of MULTI_HIT_2_5 is the Champions one), and each stone's Mega link."""
    if 'battlebond' in legal['abilities'] or 'greninjaash' in legal['species']:
        fail('A0: Battle Bond or Greninja-Ash is legal in the pool: the Water Shuriken callback would run')
    if 'loadeddice' in legal['items']:
        fail('A0: Loaded Dice is legal in the pool: the multi-hit count of MULTI_HIT_2_5 would differ')
    for iid, (base, mega, link) in A0P1_STONES.items():
        if legal['stones'].get(iid) != [link]:
            fail('A0: %s is not the Mega Stone of %s in the legal pool' % (iid, link[1]))


def check_a0p1_facts(moves_ts, champ_moves, items_ts, champ_items, legal, only=None):
    """Step A0: each listed move has exactly the listed fields (nothing else but A0P1_IGNORED_KEYS) with its pinned value, its
    callbacks are exactly A0P1_CALLBACKS with the donor texts of A0P1_SAME_TEXT, and its Champions entry is exactly A0P1_CHAMPION_OVERRIDES.
    Each Mega Stone of A0P1_STONES has the pinned megaStone, itemUser and the standard onTakeItem, and a Champions entry of
    `inherit` and `isNonstandard: null` only. The legal pool facts of check_a0p1_pool hold. `only`: a tuple of (move id, expected)."""
    check_a0p1_pool(legal)
    for mid, expected in (A0P1_FACTS if only is None else only):
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        got = fields(e[2])
        ce = champ_moves.entry(mid)
        if mid in A0P1_CHAMPION_OVERRIDES:
            if ce is None:
                fail('move %s: the Champions override is missing' % mid)
            cf = fields(ce[2])
            if 'inherit' not in cf:
                fail('move %s: the Champions override does not inherit' % mid)
            for key, want in A0P1_CHAMPION_OVERRIDES[mid].items():
                if key not in cf or a0p1_value(key, cf[key][1]) != want:
                    fail('move %s: the Champions %s is not %r' % (mid, key, want))
            got.update({k: v for k, v in cf.items() if k in A0P1_CHAMPION_OVERRIDES[mid]})
        elif ce is not None:
            fail('move %s: the Champions mod overrides it; the A0 facts must be read again' % mid)
        callbacks = {k for k, (is_fn, _) in got.items() if is_fn}
        if callbacks != A0P1_CALLBACKS.get(mid, set()):
            fail('move %s: callbacks %s, not %s' % (mid, sorted(callbacks), sorted(A0P1_CALLBACKS.get(mid, set()))))
        extra = sorted(k for k, (is_fn, _) in got.items() if not is_fn and k not in expected and k not in A0P1_IGNORED_KEYS)
        if extra:
            fail('move %s: the pin has fields the A0 facts do not list: %s' % (mid, ', '.join(extra)))
        for key, want in expected.items():
            if key not in got:
                fail('move %s: the pin has no %s' % (mid, key))
            have = a0p1_value(key, got[key][1])
            if have != want:
                fail('move %s: %s is %r in the pin, not %r' % (mid, key, have, want))
        for name in callbacks:
            donor = A0P1_SAME_TEXT.get((mid, name))
            if donor is not None:
                dentry = moves_ts.entry(donor[0])
                if dentry is None:
                    fail('move %s: the donor %s is not found' % (mid, donor[0]))
                dtext = fields(dentry[2]).get(donor[1])
                if dtext is None or norm(got[name][1]) != norm(dtext[1]):
                    fail('move %s: %s is not the text of %s' % (mid, name, donor[0]))
            if mid == 'watershuriken' and A0P1_WATERSHURIKEN_CALLBACK not in norm(got[name][1]):
                fail('move %s: the callback is not the Battle Bond one' % mid)
    for iid, (base, mega, _link) in (A0P1_STONES.items() if only is None else ()):
        e = items_ts.entry(iid)
        if e is None:
            fail('item %s not found' % iid)
        got = fields(e[2])
        if norm(got.get('megaStone', (0, ''))[1]) != norm('megaStone: { "%s": "%s" },' % (base, mega)):
            fail('item %s: megaStone is not %s -> %s' % (iid, base, mega))
        if norm(got.get('itemUser', (0, ''))[1]) != norm('itemUser: ["%s"],' % base):
            fail('item %s: itemUser is not %s' % (iid, base))
        if 'onTakeItem' not in got or not got['onTakeItem'][0] or \
                norm(re.sub(r'//[^\n]*', '', got['onTakeItem'][1])) not in STONE_TAKE_ITEM:
            fail('item %s: onTakeItem is not the standard Mega Stone text' % iid)
        # gen is the generation of the item and isNonstandard the pin's tag (Future or Past); the Champions entry nulls the tag.
        extra = sorted(set(got) - {'name', 'spritenum', 'megaStone', 'itemUser', 'onTakeItem', 'num', 'gen', 'isNonstandard'})
        if extra:
            fail('item %s: the pin has fields the A0 facts do not list: %s' % (iid, ', '.join(extra)))
        ci = champ_items.entry(iid)
        if ci is None:
            fail('item %s: the Champions entry is missing' % iid)
        cf = fields(ci[2])
        if set(cf) - {'inherit', 'isNonstandard'} or norm(cf.get('isNonstandard', (0, ''))[1]) != 'isNonstandard: null,':
            fail('item %s: the Champions entry is not inherit and isNonstandard null' % iid)


# Batch A1b (decision 0015 entry 5dz): nine abilities and one item, each one member of an existing damage chain (Heatproof also
# a clause of the burn residual), engine rows (ENGINE_ROWS) that the damage phases of src/combat/mechanics/damage/ and the
# residual read by id. Each entry's callbacks are exactly A1B_CALLBACKS and their pinned texts are demanded whole, whitespace
# aside; no Champions entry overrides one. The pin lines that the clauses rely on (A1B_PIN_FACTS) are demanded too:
# queue.willMove and getAllActive (Analytic), the allies of a side and the onAlly handlers (Plus, Minus, Steely Spirit),
# activeTurns and newlySwitched (Stakeout), the stat events of getDamage, the terrain read (Grass Pelt, with no onTryTerrain
# handler in the data), and the burn residual through spreadDamage's Damage event (Heatproof).
A1B_ABILITY_FACTS = (
    ('furcoat', ('onModifyDefPriority: 6,',
                 'onModifyDef(def) { return this.chainModify(2); },',
                 'flags: { breakable: 1 },')),
    ('grasspelt', ('onModifyDefPriority: 6,',
                   "onModifyDef(pokemon) { if (this.field.isTerrain('grassyterrain')) return this.chainModify(1.5); },",
                   'flags: { breakable: 1 },')),
    ('steelyspirit', ('onAllyBasePowerPriority: 22,',
                      "onAllyBasePower(basePower, attacker, defender, move) { if (move.type === 'Steel') { "
                      "this.debug('Steely Spirit boost'); return this.chainModify(1.5); } },",
                      'flags: {},')),
    ('plus', ('onModifySpAPriority: 5,',
              "onModifySpA(spa, pokemon) { for (const allyActive of pokemon.allies()) { "
              "if (allyActive.hasAbility(['minus', 'plus'])) { return this.chainModify(1.5); } } },",
              'flags: {},')),
    ('minus', ('onModifySpAPriority: 5,',
               "onModifySpA(spa, pokemon) { for (const allyActive of pokemon.allies()) { "
               "if (allyActive.hasAbility(['minus', 'plus'])) { return this.chainModify(1.5); } } },",
               'flags: {},')),
    ('stakeout', ('onModifyAtkPriority: 5,',
                  "onModifyAtk(atk, attacker, defender) { if (!defender.activeTurns) { this.debug('Stakeout boost'); "
                  "return this.chainModify(2); } },",
                  'onModifySpAPriority: 5,',
                  "onModifySpA(atk, attacker, defender) { if (!defender.activeTurns) { this.debug('Stakeout boost'); "
                  "return this.chainModify(2); } },",
                  'flags: {},')),
    ('analytic', ('onBasePowerPriority: 21,',
                  'onBasePower(basePower, pokemon) { let boosted = true; for (const target of this.getAllActive()) { '
                  'if (target === pokemon) continue; if (this.queue.willMove(target)) { boosted = false; break; } } '
                  "if (boosted) { this.debug('Analytic boost'); return this.chainModify([5325, 4096]); } },",
                  'flags: {},')),
    ('fluffy', ("onSourceModifyDamage(damage, source, target, move) { let mod = 1; if (move.type === 'Fire') mod *= 2; "
                "if (move.flags['contact']) mod /= 2; return this.chainModify(mod); },",
                'flags: { breakable: 1 },')),
    ('heatproof', ('onSourceModifyAtkPriority: 6,',
                   "onSourceModifyAtk(atk, attacker, defender, move) { if (move.type === 'Fire') { "
                   "this.debug('Heatproof Atk weaken'); return this.chainModify(0.5); } },",
                   'onSourceModifySpAPriority: 5,',
                   "onSourceModifySpA(atk, attacker, defender, move) { if (move.type === 'Fire') { "
                   "this.debug('Heatproof SpA weaken'); return this.chainModify(0.5); } },",
                   "onDamage(damage, target, source, effect) { if (effect && effect.id === 'brn') { return damage / 2; } },",
                   'flags: { breakable: 1 },')),
)
A1B_ITEM_FACTS = (
    ('lightball', ('onModifyAtkPriority: 1,',
                   "onModifyAtk(atk, pokemon) { if (pokemon.baseSpecies.baseSpecies === 'Pikachu') { return this.chainModify(2); } },",
                   'onModifySpAPriority: 1,',
                   "onModifySpA(spa, pokemon) { if (pokemon.baseSpecies.baseSpecies === 'Pikachu') { return this.chainModify(2); } },")),
)
A1B_CALLBACKS = {
    'furcoat': {'onModifyDef'}, 'grasspelt': {'onModifyDef'}, 'steelyspirit': {'onAllyBasePower'},
    'plus': {'onModifySpA'}, 'minus': {'onModifySpA'}, 'stakeout': {'onModifyAtk', 'onModifySpA'}, 'analytic': {'onBasePower'},
    'fluffy': {'onSourceModifyDamage'}, 'heatproof': {'onSourceModifyAtk', 'onSourceModifySpA', 'onDamage'},
    'lightball': {'onModifyAtk', 'onModifySpA'},
}
# Each pin fact is anchored to its place: (file, anchor, facts in order). An anchor `entry:<id>` is that top-level entry of a data
# file; any other anchor is the start of a class method (one tab of indent, `anchor` at the start of its line, exactly one such line),
# whose window ends at its closing `\t}`. The facts must stand in the window in this order, whitespace aside, so a fact that the file
# has twice (spreadDamage's two clamps) is demanded where the clause needs it.
A1B_PIN_FACTS = (
    ('sim/battle-queue.ts', 'willMove(pokemon: Pokemon) {',
     ('if (pokemon.fainted) return null;', 'for (const action of this.list) {',
      "if (action.choice === 'move' && action.pokemon === pokemon) {", 'return action;')),
    ('sim/battle.ts', 'getAllActive(includeFainted?: boolean) {',
     ('if (pokemon && (includeFainted || !pokemon.fainted)) {',)),
    ('sim/battle.ts', 'endTurn() {',
     ('pokemon.newlySwitched = false;', 'if (pokemon.fainted) continue;', 'pokemon.activeTurns++;')),
    ('sim/battle.ts', 'findEventHandlers(',
     ('for (const allyActive of target.alliesAndSelf()) {',
      'handlers.push(...this.findPokemonEventHandlers(allyActive, `onAlly${eventName}`));')),
    ('sim/battle.ts', 'spreadDamage(',
     ('if (targetDamage !== 0) targetDamage = this.clampIntRange(targetDamage, 1);',
      "targetDamage = this.runEvent('Damage', target, source, effect, targetDamage, true);",
      'if (targetDamage !== 0) targetDamage = this.clampIntRange(targetDamage, 1);')),
    ('sim/battle-actions.ts', 'switchIn(', ('pokemon.activeTurns = 0;',)),
    ('sim/battle-actions.ts', 'getDamage(',
     ("attack = this.battle.runEvent('Modify' + statTable[attackStat], source, target, move, attack);",
      "defense = this.battle.runEvent('Modify' + statTable[defenseStat], target, source, move, defense);")),
    ('sim/side.ts', 'allies(all?: boolean) {',
     ('let allies = this.activeTeam().filter(ally => ally);', 'if (!all) allies = allies.filter(ally => !!ally.hp);')),
    ('sim/pokemon.ts', 'alliesAndSelf(): Pokemon[] {', ('return this.side.allies();',)),
    ('sim/pokemon.ts', 'allies(): Pokemon[] {', ('return this.side.allies().filter(ally => ally !== this);',)),
    ('sim/field.ts', 'effectiveTerrain(target?: Pokemon | Side | Battle) {',
     ('if (this.battle.event && !target) target = this.battle.event.target;',
      "return this.battle.runEvent('TryTerrain', target) ? this.terrain : '';")),
    ('sim/field.ts', 'isTerrain(', ('const ourTerrain = this.effectiveTerrain(target);',)),
    ('data/conditions.ts', 'entry:brn',
     ('onResidualOrder: 10,', 'onResidual(pokemon) { this.damage(pokemon.baseMaxhp / 16); },')),
)
A1B_NO_TRY_TERRAIN = ('data/abilities.ts', 'data/items.ts', 'data/moves.ts', 'data/conditions.ts')
# The Champions mod must not change what the clauses read: no TryTerrain handler, no brn condition of its own, and no method of its
# scripts that replaces one of the anchored methods (data/mods/champions/scripts.ts overrides modifyDamage, which is not one).
A1B_CHAMPIONS_SOURCES = ('data/mods/champions/abilities.ts', 'data/mods/champions/items.ts', 'data/mods/champions/moves.ts',
                         'data/mods/champions/conditions.ts', 'data/mods/champions/scripts.ts')
A1B_PINNED_METHODS = ('willMove', 'getAllActive', 'endTurn', 'findEventHandlers', 'spreadDamage', 'switchIn', 'getDamage',
                      'allies', 'alliesAndSelf', 'effectiveTerrain', 'isTerrain')


def a1b_window(src, anchor):
    """The lines of `anchor` in `src` (see A1B_PIN_FACTS); fails unless it is there exactly once and closed."""
    if anchor.startswith('entry:'):
        e = src.entry(anchor[len('entry:'):])
        if e is None:
            fail('%s: the entry %s is not found' % (src.rel, anchor[len('entry:'):]))
        return e[2]
    starts = [i for i, line in enumerate(src.lines) if line.startswith('\t' + anchor) and not line.startswith('\t\t')]
    if len(starts) != 1:
        fail('%s: the method "%s" is found %d times, not once' % (src.rel, anchor, len(starts)))
    for j in range(starts[0] + 1, len(src.lines)):
        if src.lines[j] == '\t}':
            return src.lines[starts[0]:j + 1]
    fail('%s: the method "%s" is not closed' % (src.rel, anchor))


def check_a1b_facts(abil_ts, champ_abil, items_ts, champ_items, pins):
    """Batch A1b: each entry of A1B_ABILITY_FACTS and A1B_ITEM_FACTS has exactly the callbacks of A1B_CALLBACKS and every fact,
    whitespace aside, and the Champions mod has no entry for it. `pins` maps every other file that A1B_PIN_FACTS,
    A1B_NO_TRY_TERRAIN and A1B_CHAMPIONS_SOURCES name to its Source: each pin fact stands in its anchored window in order, none of
    A1B_NO_TRY_TERRAIN has an onTryTerrain handler (so Grass Pelt's field.isTerrain is the field's terrain), and the Champions
    sources have no TryTerrain handler, no brn condition and no method named in A1B_PINNED_METHODS."""
    for kind, facts_by_id, src, champ in (('ability', A1B_ABILITY_FACTS, abil_ts, champ_abil),
                                          ('item', A1B_ITEM_FACTS, items_ts, champ_items)):
        for rid, facts in facts_by_id:
            e = src.entry(rid)
            if e is None:
                fail('%s %s not found' % (kind, rid))
            if champ.entry(rid) is not None:
                fail('%s %s: the champions mod overrides the entry' % (kind, rid))
            callbacks = {k for k, (is_fn, _) in fields(e[2]).items() if is_fn}
            if callbacks != A1B_CALLBACKS[rid]:
                fail('%s %s: callbacks %s, not %s' % (kind, rid, sorted(callbacks), sorted(A1B_CALLBACKS[rid])))
            text = norm(chr(10).join(e[2]))
            for fact in facts:
                if norm(fact) not in text:
                    fail('%s %s: the entry no longer has "%s"' % (kind, rid, fact))
    sources = dict(pins, **{'data/abilities.ts': abil_ts, 'data/items.ts': items_ts,
                            'data/mods/champions/abilities.ts': champ_abil, 'data/mods/champions/items.ts': champ_items})
    for rel, anchor, facts in A1B_PIN_FACTS:
        text = norm(chr(10).join(a1b_window(sources[rel], anchor)))
        at = 0
        for fact in facts:
            k = text.find(norm(fact), at)
            if k < 0:
                fail('%s: the pin no longer has "%s" (in order, within %s)' % (rel, fact, anchor))
            at = k + len(norm(fact))
    for rel in A1B_NO_TRY_TERRAIN:
        if any('onTryTerrain' in line for line in sources[rel].lines):
            fail('%s: an onTryTerrain handler, which Grass Pelt\'s terrain read does not model' % rel)
    method = re.compile(r'^\s+(%s)\s*\([^;]*\{\s*$' % '|'.join(A1B_PINNED_METHODS))
    for rel in A1B_CHAMPIONS_SOURCES:
        src = sources[rel]
        if any('TryTerrain' in line for line in src.lines):
            fail('%s: a TryTerrain handler, which Grass Pelt\'s terrain read does not model' % rel)
        if rel.endswith('conditions.ts') and src.entry('brn') is not None:
            fail('%s: a brn condition of the Champions mod, which the burn residual and Heatproof\'s halving do not model' % rel)
        for line in src.lines:
            m = method.match(line)
            if m is not None:
                fail('%s: the Champions mod defines %s, a method whose pinned lines batch A1b reads' % (rel, m.group(1)))


# Batch A1b review (L3): Fluffy, Tough Claws and Aura Guard read the move's static contact flag (DFI_MOVE_FLAG_CONTACT of the
# pool row, src/combat/mechanics/damage/), as do the other contact readers of the turn code. At the pin Fluffy reads
# move.flags['contact'] after onModifyMove, where Long Reach (onModifyMove deletes the flag) and Punching Glove (for punch moves)
# change it, and Protective Pads takes the contact effects away (checkMoveMakesContact). None of the three is played: Long Reach is
# an UNMODELED pool row, and Punching Glove and Protective Pads are not in the pool. The build fails, naming the readers, as soon as
# one of them would reach a battle while these readers use the static flag.
CONTACT_FLAG_CHANGERS = {'abilities': ('longreach',), 'items': ('punchingglove', 'protectivepads')}
CONTACT_FLAG_DAMAGE_READERS = ('Fluffy', 'Tough Claws', 'Aura Guard')


def contact_flag_readers(repo):
    """The lines of src/combat that read the static contact flag (DFI_MOVE_FLAG_CONTACT), as 'path:line', sorted."""
    out = []
    base = os.path.join(repo, 'src', 'combat')
    for dirpath, _dirs, files in os.walk(base):
        for name in files:
            if not name.endswith(('.c', '.h')) or 'generated' in dirpath:
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, repo).replace(os.sep, '/')
            with open(path, encoding='utf-8') as fh:
                for i, line in enumerate(fh):
                    if 'DFI_MOVE_FLAG_CONTACT' in line and '#define' not in line:
                        out.append('%s:%d' % (rel, i + 1))
    return sorted(out)


def check_contact_flag(items, abilities, repo):
    """No row that changes the contact flag or its effects is played while the readers use the static flag: Long Reach stays
    an UNMODELED row (a marked row must be modelled, duoforge.data.pool_tables), and Punching Glove and Protective Pads are no pool
    rows. `items` and `abilities` are the pool rows (with their `unmodeled` feature lists)."""
    readers = contact_flag_readers(repo)
    named = '%s (the damage chains) and every reader of the static contact flag: %s' % (
        ', '.join(CONTACT_FLAG_DAMAGE_READERS), ', '.join(readers) or 'none found')
    for it in items:
        if it['id'] in CONTACT_FLAG_CHANGERS['items']:
            fail('item %s is a pool row: it changes the contact flag or its effects, which %s read unchanged' % (it['id'], named))
    for ab in abilities:
        if ab['id'] in CONTACT_FLAG_CHANGERS['abilities'] and not ab['unmodeled']:
            fail('ability %s is a modelled row: its onModifyMove deletes the contact flag, which %s read unchanged' % (
                ab['id'], named))
