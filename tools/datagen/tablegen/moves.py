"""Moves: the move parser and its key, flag, target and status tables, the special handlers and their pinned
callbacks by step, the move and field-condition facts and their checks.

Part of the table generator tools/datagen/gen_closure.py (restructure step 5: split by area; every
statement is unchanged from gen_closure.py@001a492e).
"""
import re

from .source import CATEGORIES, fail, fields, norm, scalar, TYPES
from .species import G59_POKEMON_FACTS, TAGS_PAST_UNOBTAINABLE

# Move ids 0..35 in the order of decision 0005 (fixture table T1); Struggle is 36.
MOVES = ['woodhammer', 'grassyglide', 'fakeout', 'highhorsepower', 'bravebird', 'closecombat', 'tailwind', 'protect',
         'muddywater', 'coil', 'icebeam', 'hypnosis', 'bitterblade', 'shadowsneak', 'swordsdance', 'zapcannon',
         'focusblast', 'makeitrain', 'shadowball', 'nastyplot', 'weatherball', 'leechlife', 'ironhead', 'drillrun',
         'dragonpulse', 'electroshot', 'snarl', 'psychic', 'grassknot', 'trickroom', 'heatwave', 'hurricane',
         'spiritbreak', 'reflect', 'lightscreen', 'partingshot', 'struggle']
BOOSTS = ['atk', 'def', 'spa', 'spd', 'spe', 'accuracy', 'evasion']
TARGET_CLASS = {'normal': 1, 'any': 2, 'adjacentAlly': 3, 'adjacentAllyOrSelf': 4, 'adjacentFoe': 5, 'self': 6,
                'allAdjacentFoes': 7, 'allySide': 8, 'all': 9, 'randomNormal': 10}
STATUS = {'brn': 1, 'frz': 2, 'par': 3, 'slp': 4}
VOLATILE = {'flinch': 1, 'confusion': 2}
SIDE_CONDITION = {'tailwind': 1, 'reflect': 2, 'lightscreen': 3}
# Step G37 (POOL only): the four entry hazards. The values are the DUOFORGE_SIDE_* values of SIDE_START and SIDE_END (Aurora Veil is 4, a
# handler of its own): Stealth Rock 5, Spikes 6, Toxic Spikes 7, Sticky Web 8. Their moves have the target class foeSide.
SIDE_CONDITION_P = dict(SIDE_CONDITION, stealthrock=5, spikes=6, toxicspikes=7, stickyweb=8)
PSEUDO_WEATHER = {'trickroom': 1, 'gravity': 2}  # K4 (#475): Gravity, decision 0015 5dl
# K4 (#475): the pool moves with the gravity flag (data/moves.ts:1712, 5903, 5942, 8906, 10861). They stay UNMODELLED ('flag
# gravity') until Gravity's choice disable and onStart removal are built; a new gravity-flagged pool move fails the generator.
GRAVITY_FLAG_MOVES = frozenset({'bounce', 'fly', 'flyingpress', 'highjumpkick', 'magnetrise'})
# K4 (#475): facts of Gravity's condition (data/moves.ts:7754-7842, normalized) that the engine implements; each must be in the pin.
GRAVITY_CONDITION_FACTS = ("duration: 5,", "chainModify([6840, 4096])", "onFieldResidualOrder: 27,",
                           "onFieldResidualSubOrder: 2,", "this.add('-fieldend', 'move: Gravity');",
                           "this.add('-fieldstart', 'move: Gravity');", "if (typeof accuracy !== 'number') return;")
# K4 (#475): what the condition must NOT contain: no onFieldRestart (sim/field.ts:196-197: the re-use returns false, the timer is
# not reset) and no `[of]` on its lines (the -fieldstart text is `move: Gravity` alone).
GRAVITY_CONDITION_ABSENT = ("onFieldRestart", "[of]")
STATUS_IMMUNITY = {'brn': 1, 'frz': 2, 'par': 4, 'prankster': 8}

FLAG_BITS = {'contact': 1, 'protect': 2, 'charge': 4}
EXTRA_FLAG_BITS = {'stallingMove': 8, 'selfSwitch': 16, 'noPPBoosts': 32, 'struggleRecoil': 64}
# Move flags without a consumer in the closure (no Soundproof, Bulletproof,
# Mega Launcher, Sharpness, Wind Rider, Magic Bounce, Snatch, Dancer, Heal
# Block, Gravity, Metronome, Mirror Move, Assist, Copycat, Substitute, Encore,
# Me First, Sleep Talk, Mimic, Instruct or Sketch).
IGNORED_FLAGS = {'bullet', 'bypasssub', 'dance', 'distance', 'failcopycat', 'failencore', 'failinstruct',
                 'failmefirst', 'failmimic', 'heal', 'metronome', 'mirror', 'noassist', 'nonsky', 'nosketch',
                 'nosleeptalk', 'pulse', 'reflectable', 'slicing', 'snatch', 'sound', 'wind'}
# Callbacks are code, not data. Each one is accounted for by a named handler.
SPECIAL = {
    'grassknot': ('GRASS_KNOT', {'basePowerCallback', 'onTryHit'}),
    'weatherball': ('WEATHER_BALL', {'onModifyType', 'onModifyMove'}),
    'hurricane': ('HURRICANE', {'onModifyMove'}),
    'grassyglide': ('GRASSY_GLIDE', {'onModifyPriority'}),
    'electroshot': ('ELECTRO_SHOT', {'onTryMove'}),
    'fakeout': ('FAKE_OUT', {'onTry', 'onDisableMove'}),
    'partingshot': ('PARTING_SHOT', {'onHit'}),
    'protect': ('PROTECT', {'onPrepareHit', 'onHit'}),
    'struggle': ('STRUGGLE', {'onModifyMove'}),
}
SPECIAL_IDS = ['NONE', 'GRASS_KNOT', 'WEATHER_BALL', 'HURRICANE', 'GRASSY_GLIDE', 'ELECTRO_SHOT', 'FAKE_OUT',
               'PARTING_SHOT', 'PROTECT', 'STRUGGLE']
DATA_KEYS = {'num', 'accuracy', 'basePower', 'category', 'name', 'pp', 'priority', 'flags', 'target', 'type',
             'critRatio', 'secondary', 'self', 'boosts', 'recoil', 'drain', 'status', 'volatileStatus',
             'sideCondition', 'pseudoWeather', 'selfSwitch', 'stallingMove', 'noPPBoosts', 'struggleRecoil',
             'condition'}
# Keys that describe other generations, contests or mechanics outside the
# closure (Z-Moves, Max Moves, Sheer Force), or mod bookkeeping.
IGNORED_KEYS = {'contestType', 'zMove', 'maxMove', 'isNonstandard', 'hasSheerForceBoost', 'inherit'}
BOOST_ROLE = {'NONE': 0, 'PRIMARY_SELF': 1, 'SECONDARY_TARGET': 2, 'SELF_AFTER_HIT': 3, 'PRIMARY_ALLY': 4,
              'SECONDARY_SELF': 5, 'PRIMARY_TARGET': 6}
# The 13 new moves in team order; ids follow Struggle (36).
MOVES_C = ['direclaw', 'flareblitz', 'darkestlariat', 'hypervoice', 'dracometeor', 'followme', 'helpinghand',
           'kowtowcleave', 'suckerpunch', 'lastrespects', 'wavecrash', 'aquajet', 'flipturn']
# New encodings (decision 0009 section 3.3). Each names the step that consumes it.
STATUS_C = dict(STATUS, psn=5)                    # poison: step 6
STATUS_P = dict(STATUS_C, tox=6)                  # badly poisoned (POOL only: Toxic, Poison Fang; step G36); the tail's toxic_stage counts it
STATUS_IMMUNITY_C = dict(STATUS_IMMUNITY, psn=16)  # Poison and Steel: step 6
# The POOL tables add the immunity to Sandstorm damage (decision 0018 step: Sandstorm and Snowscape): the type chart's
# `sandstorm: 3` of Rock, Ground and Steel. The bit is in the pool's immunity bytes only; the extended and closure
# canonical bytes mask it out. `hail` stays ignored (Snowscape does no damage).
SAND_IMMUNITY = 32
STATUS_IMMUNITY_P = dict(STATUS_IMMUNITY_C, sandstorm=SAND_IMMUNITY)
FLAG_BITS_C = dict(FLAG_BITS, defrost=128)         # Flare Blitz: step 2
SPECIAL_C = dict(SPECIAL, **{
    'darkestlariat': ('DARKEST_LARIAT', set()),                   # step 2
    'lastrespects': ('LAST_RESPECTS', {'basePowerCallback'}),     # step 4
    'suckerpunch': ('SUCKER_PUNCH', {'onTry'}),                   # step 9b
    'helpinghand': ('HELPING_HAND', {'onTryHit'}),                # step 9b
    'followme': ('FOLLOW_ME', {'onTry'}),                         # step 11
})
SPECIAL_IDS_C = SPECIAL_IDS + ['DARKEST_LARIAT', 'LAST_RESPECTS', 'SUCKER_PUNCH', 'HELPING_HAND', 'FOLLOW_ME']
# Data fields that only a named handler consumes.
SPECIAL_FIELDS_C = {'DARKEST_LARIAT': {'ignoreDefensive', 'ignoreEvasion'}}
# Primary volatiles (with their condition blocks) that only a named handler owns.
SPECIAL_VOLATILE_C = {'FOLLOW_ME': 'followme', 'HELPING_HAND': 'helpinghand'}
# Dire Claw's secondary (step 6): its onHit, whitespace-normalised, must be exactly this.
STATUS_PICK_ONHIT = ("onHit(target, source) { const status = this.sample(['psn', 'par', 'slp']); "
                     "target.trySetStatus(status, source); },")
SECONDARY_STATUS_PICK = 4
SECONDARY_SELF_BOOST = 7  # step G28: the secondary's own boosts go to the user (Ancient Power)


def boosts_of(text):
    vec = [0] * len(BOOSTS)
    found = re.findall(r'\b(atk|def|spa|spd|spe|accuracy|evasion): (-?\d+)', text)
    if not found:
        fail('no boosts in %r' % text[:60])
    for name, val in found:
        vec[BOOSTS.index(name)] = int(val)
    return vec


def modelled(table, key, mid, what, unmodeled=None):
    """The code of a name that the tables model. Anything else fails with a message, never as a KeyError; in the
    lenient mode (a list `unmodeled`) it is recorded as a feature that the tables do not model and gives 0."""
    if key not in table:
        if unmodeled is None:
            fail('move %s: %s %s is not modelled' % (mid, what, key))
        unmodeled.append('%s %s' % (what, key))
        return 0
    return table[key]


def parse_move(mid, base, champ, ext=False, pool=False, unmodeled=None):
    """ext: the extended tables' encodings (decision 0009); the closure mode
    keeps exactly the closure's. pool: the pool tables' encodings (decision
    0015), which are the extended ones plus the named handlers of G2_HANDLERS:
    a move whose callbacks or fields the tables do not model is mapped
    deliberately to one of them, and anything else still fails.

    unmodeled (a list, pool mode only): the lenient mode of the whole-pool rows (decision 0015 section 4.2). What
    the tables model is encoded exactly as in the strict mode. A callback, field, secondary, status, volatile, side
    condition, pseudo weather, boost shape, target class or flag that they do not model is appended to the list, as
    one feature string each, instead of failing, and the caller maps the move to the UNMODELED handler. What the
    generator cannot read at all (a type, category, PP or accuracy it does not know, a value that does not fit its
    byte) still fails."""
    ext = ext or pool
    lenient = unmodeled is not None
    if lenient and not pool:
        fail('move %s: the lenient mode is for the pool tables only' % mid)

    def bad(message, feature):
        """An unmodelled feature: a failure in the strict mode, a recorded feature in the lenient one."""
        if not lenient:
            fail(message)
        unmodeled.append(feature)

    e = base.entry(mid)
    if e is None:
        fail('move %s not found' % mid)
    f = fields(e[2])
    ce = champ.entry(mid)
    refs = [base.ref(mid)]
    if ce is not None:
        cf = fields(ce[2])
        if 'inherit' not in cf:
            fail('champions override of %s does not inherit' % mid)
        f.update(cf)
        for _name in list(cf):
            # `secondary: undefined, // no inherit` (the Champions Freeze-Dry): the field is removed, not changed.
            if re.match(r'^\t\t%s: undefined,' % _name, cf[_name][1]):
                del f[_name]
        refs.append(champ.ref(mid))
    handled = (SPECIAL_POOL if pool else SPECIAL_C if ext else SPECIAL).get(mid, ('NONE', set()))
    owned_fields = SPECIAL_FIELDS_C.get(handled[0], set()) if ext else set()
    # What a pool handler owns: data fields and a secondary that only it consumes, each of which must be present and
    # exactly the pinned text, and a condition block (the callbacks inside it are code, not data).
    owned = G2_OWNED_FIELDS.get(handled[0], {}) if pool else {}
    owned_secondary = G2_OWNED_SECONDARY.get(handled[0]) if pool else None
    # Step G8: a secondary whose whole text is one of G8_SECONDARIES is a modelled kind (the lockout of Throat Chop, the
    # Heal Block of Psychic Noise), not a handler's: chance 100 and the kind, in every pool row of that text.
    g8_secondary = None
    if pool and 'secondary' in f and norm(f['secondary'][1]) in G8_SECONDARIES:
        g8_secondary = G8_SECONDARIES[norm(f['secondary'][1])]
    owns_condition = (pool and handled[0] in G2_OWNED_CONDITION) or (g8_secondary is not None and g8_secondary[1])
    for name, text in owned.items():
        if name not in f or norm(f[name][1]) != text:
            fail('move %s: %s is not "%s"' % (mid, name, text))
    if owned_secondary is not None and ('secondary' not in f or norm(f['secondary'][1]) != owned_secondary):
        fail('move %s: the secondary is not "%s"' % (mid, owned_secondary))
    if owns_condition and 'condition' not in f:
        fail('move %s: expected a condition block' % mid)
    for name, (is_fn, _text) in f.items():
        if is_fn:
            if name not in handled[1]:
                bad('move %s: callback %s is not mapped to a handler' % (mid, name), 'callback %s' % name)
        elif (name not in DATA_KEYS and name not in IGNORED_KEYS and name not in owned_fields and name not in owned
              and not (pool and name in POOL_COLUMN_KEYS)
              and not (pool and name == 'forceSwitch' and mid in G46_FORCE_SWITCH_MOVES)
              and not (pool and name == 'tags' and norm(f[name][1]) == TAGS_PAST_UNOBTAINABLE)):
            bad('move %s: unknown field %s' % (mid, name), 'field %s' % name)
    missing = handled[1] - set(n for n, v in f.items() if v[0])
    if missing:
        fail('move %s: expected callbacks %s are absent' % (mid, sorted(missing)))
    if pool and handled[0] == 'GLAIVE_RUSH':
        if 'condition' not in f or norm(f['condition'][1]) != GLAIVE_RUSH_CONDITION:
            fail('move %s: the condition is not the pinned text' % mid)
    if pool and handled[0] == 'PERISH_SONG':
        if 'condition' not in f or norm(f['condition'][1]) != PERISH_SONG_CONDITION:
            fail('move %s: the condition is not the pinned text' % mid)
        if 'onHitField' not in f or norm(f['onHitField'][1]) != PERISH_SONG_HIT_FIELD:
            fail('move %s: onHitField is not the pinned text' % mid)
    if pool and handled[0] in G29_CALLBACKS:
        for name, text in G29_CALLBACKS[handled[0]].items():
            if name not in f or norm(f[name][1]) != text:
                fail('move %s: %s is not the pinned text' % (mid, name))
    if pool and handled[0] == 'KNOCK_OFF':
        for name, text in KNOCK_OFF_CALLBACKS.items():
            if name not in f or norm(f[name][1]) != text:
                fail('move %s: %s is not the pinned text' % (mid, name))
    if pool and handled[0] == 'DISABLE':
        base_condition = fields(base.entry(mid)[2]).get('condition')
        if 'onTryHit' not in f or norm(f['onTryHit'][1]) != DISABLE_ONTRYHIT:
            fail('move %s: onTryHit is not the pinned text' % mid)
        if base_condition is None or norm(base_condition[1]) != DISABLE_CONDITION:
            fail('move %s: the condition is not the pinned text' % mid)
        if 'condition' not in f or norm(f['condition'][1]) not in (DISABLE_CONDITION, DISABLE_CONDITION_CHAMPIONS):
            fail('move %s: the Champions condition is not the pinned text' % mid)
    if pool and handled[0] == 'RAGE_POWDER':
        if 'onTry' not in f or norm(f['onTry'][1]) != RAGE_POWDER_ONTRY:
            fail('move %s: onTry is not the pinned text' % mid)
        if 'condition' not in f or norm(f['condition'][1]) != RAGE_POWDER_CONDITION:
            fail('move %s: the condition is not the pinned text' % mid)
    if pool and handled[0] == 'PSYCHIC_FANGS' and ('onTryHit' not in f or norm(f['onTryHit'][1]) != PSYCHIC_FANGS_ONTRYHIT):
        fail('move %s: onTryHit is not the pinned text' % mid)
    if pool and handled[0] == 'SOLAR_BEAM':
        for name, text in SOLAR_BEAM_CALLBACKS.items():
            if name not in f or norm(f[name][1]) != text:
                fail('move %s: %s is not the pinned text' % (mid, name))
    if pool and handled[0] == 'TAUNT' and ('condition' not in f or norm(f['condition'][1]) != TAUNT_CONDITION):
        fail('move %s: the condition is not the pinned text' % mid)
    if pool and 'gravity: 1' in f['flags'][1] and mid not in GRAVITY_FLAG_MOVES:
        fail('move %s: a pool move with the gravity flag is new: Gravity\'s choice disable (data/moves.ts:7811-7831) and its '
             'onStart removal (:7779-7800) must be built before it is modelled (decision 0015 5dl)' % mid)
    if pool and mid == 'gravity':
        # K4 (#475): the Gravity condition's facts the engine implements; a change of any of them stops the generator.
        cond = norm(f['condition'][1]) if 'condition' in f else ''
        for fact in GRAVITY_CONDITION_FACTS:
            if fact not in cond:
                fail('move gravity: the condition lost the pinned fact %r (data/moves.ts:7754-7842, decision 0015 5dl)' % fact)
        for absent in GRAVITY_CONDITION_ABSENT:
            if absent in cond:
                fail('move gravity: the condition gained %r (data/moves.ts:7754-7842, decision 0015 5dl)' % absent)
    if pool and handled[0] == 'SUBSTITUTE':
        for name, text in (('onTryHit', SUBSTITUTE_ONTRYHIT), ('onHit', SUBSTITUTE_ONHIT), ('condition', SUBSTITUTE_CONDITION)):
            if name not in f or norm(f[name][1]) != text:
                fail('move %s: %s is not the pinned text (decision 0032)' % (mid, name))
    if pool and handled[0] == 'SKILL_SWAP' and ('onHit' not in f or norm(f['onHit'][1]) != norm(SKILL_SWAP_ONHIT)):
        fail('move %s: onHit is not the pinned text' % mid)
    if pool and handled[0] == 'SPEED_SWAP' and ('onHit' not in f or norm(f['onHit'][1]) != norm(SPEED_SWAP_ONHIT)):
        fail('move %s: onHit is not the pinned text (decision 0015 5de)' % mid)
    if pool and handled[0] == 'BATON_PASS' and ('onHit' not in f or norm(f['onHit'][1]) != norm(BATON_PASS_ONHIT)):
        fail('move %s: onHit is not the pinned text (decision 0042)' % mid)
    if pool and handled[0] == 'YAWN':
        if 'onTryHit' not in f or norm(f['onTryHit'][1]) != YAWN_ONTRYHIT:
            fail('move %s: onTryHit is not the pinned text' % mid)
        if 'condition' not in f or norm(f['condition'][1]) != YAWN_CONDITION:
            fail('move %s: the condition is not the pinned text' % mid)
    if pool and handled[0] == 'REVIVAL_BLESSING' and ('condition' not in f or norm(f['condition'][1]) != REVIVAL_BLESSING_CONDITION):
        fail('move %s: the condition is not the pinned text' % mid)
    if pool and handled[0] == 'REVIVAL_BLESSING' and ('onTryHit' not in f or norm(f['onTryHit'][1]) != REVIVAL_BLESSING_ONTRYHIT):
        fail('move %s: onTryHit is not the pinned text' % mid)
    if pool and handled[0] == 'ROOST' and ('condition' not in f or norm(f['condition'][1]) != ROOST_CONDITION):
        fail('move %s: the condition is not the pinned text' % mid)
    if pool and handled[0] == 'STOMPING_TANTRUM':
        if mid not in STOMPING_TANTRUM_CALLBACKS:
            fail('move %s: no pinned text for the STOMPING_TANTRUM handler' % mid)
        for name, text in STOMPING_TANTRUM_CALLBACKS[mid].items():
            if name not in f or norm(f[name][1]) != norm(text):
                fail('move %s: %s is not the pinned text' % (mid, name))
    if pool and handled[0] == 'AURORA_VEIL' and ('onTry' not in f or norm(f['onTry'][1]) != AURORA_VEIL_ONTRY):
        fail('move %s: onTry is not the pinned text' % mid)
    if pool and handled[0] in G20_PROTECT_HANDLERS + G94_HANDLERS:
        punish = PROTECT_VARIANT_PUNISHMENT[handled[0]]
        if 'condition' not in f or norm(f['condition'][1]) != PROTECT_VARIANT_CONDITION % (punish, punish):
            fail('move %s: the condition is not the pinned text' % mid)
        pe = fields(base.entry('protect')[2])
        for name in PROTECT_VARIANT_COPY_FIELDS:
            if name not in f or name not in pe or norm(f[name][1]) != norm(pe[name][1]):
                fail('move %s: %s is not that of protect' % (mid, name))
    if pool and handled[0] in G66_HANDLERS:
        if 'condition' not in f or norm(f['condition'][1]) != norm(KINGS_SHIELD_CONDITION):
            fail('move %s: the condition is not the pinned text' % mid)
        pe = fields(base.entry('protect')[2])
        for name in KINGS_SHIELD_COPY_FIELDS:
            if name not in f or name not in pe or norm(f[name][1]) != norm(pe[name][1]):
                fail('move %s: %s is not that of protect' % (mid, name))
    if pool and mid in PROTECT_COPIES:
        pe = fields(base.entry(PROTECT_COPIES[mid])[2])
        for name in PROTECT_COPY_FIELDS:
            if name not in f or name not in pe or norm(f[name][1]) != norm(pe[name][1]):
                fail('move %s: %s is not that of %s' % (mid, name, PROTECT_COPIES[mid]))

    def get(name, default=None):
        return scalar(f[name][1]) if name in f else default

    flags = 0
    flags2 = 0
    flags3 = 0  # the third flags byte (pool tables only): REFLECTABLE (step G57), MUST_PRESSURE (step G53), FLAGS3_BITS
    static_flags = 0  # decision 0020: the public static flags of every row, from the pin's flags object (pool tables only)
    flag_bits = FLAG_BITS_C if ext else FLAG_BITS
    for fl in re.findall(r'(\w+): 1', f['flags'][1]):
        flags2 |= FLAGS2_BITS.get(fl, 0)
        static_flags |= STATIC_FLAG_BITS.get(fl, 0)
        flags3 |= FLAGS3_BITS.get(fl, 0)
        if fl in flag_bits:
            flags |= flag_bits[fl]
        elif lenient:
            # Every flag of the pool is known (POOL_FLAGS) or the generator cannot read the move; a flag that no
            # encoded bit holds is recorded when a modelled row reads it (flags_that_matter), and otherwise ignored.
            if fl not in POOL_FLAGS:
                fail('move %s: unknown flag %s' % (mid, fl))
            # Step G92 (decision 0062): cantusetwice (Gigaton Hammer, dropped; Blood Moon) has no reader in the turn code: unmodelled.
            if fl in FLAGS_THAT_MATTER or fl == 'cantusetwice':
                unmodeled.append('flag %s' % fl)
            # K4 (#475, decision 0015 5dl): the gravity flag is read by Gravity's choice disable, cant line and onStart removal
            # (data/moves.ts:7811-7831, :7779-7800), none of which is built: the flag is a reason to refuse the move.
            if fl == 'gravity':
                unmodeled.append('flag gravity')
        elif fl not in IGNORED_FLAGS and not (pool and fl in G2_IGNORED_FLAGS):
            fail('move %s: unknown flag %s' % (mid, fl))
    for key, bit in EXTRA_FLAG_BITS.items():
        value = get(key, False)
        if key == 'selfSwitch' and value == 'copyvolatile':
            # Step G74 (decision 0042): Baton Pass is the one row whose selfSwitch carries a copy. It is a pivot of its own
            # (ENGINE_PIVOT_MOVES, dfi_pivot_moves); any other copyvolatile row, and shedtail, stay refused below.
            if mid != 'batonpass':
                bad('move %s: selfSwitch copyvolatile is not Baton Pass' % mid, 'field selfSwitch copyvolatile')
            flags |= bit
            continue
        if value is True:
            flags |= bit
            if key == 'selfSwitch' and lenient and mid not in ENGINE_PIVOT_MOVES:
                # The turn code pivots a damaging move only through a switch flag of its own (dfi_pivot_moves of
                # src/state/closure_member.c: Flip Turn and U-turn, rows of the steps above); Volt Switch or
                # Teleport carry the data flag and nothing else says how they pivot.
                unmodeled.append('field selfSwitch without a switch flag')
        elif value is not False:
            # selfSwitch: "copyvolatile" (Baton Pass) and "shedtail" (Shed Tail) switch the user out and carry
            # something over: no flag of the tables says that.
            bad('move %s: %s is %r, not a flag' % (mid, key, value), 'field %s %s' % (key, value))
    acc = get('accuracy')
    pp_base = get('pp')
    pp_capped = min(pp_base, 20)  # champions init(): data/mods/champions/scripts.ts:3-9
    if flags & EXTRA_FLAG_BITS['noPPBoosts']:
        pp_max = pp_capped
    else:
        if pp_capped % 5 != 0:
            fail('move %s: pp %d is not a multiple of 5' % (mid, pp_capped))
        pp_max = (pp_capped // 5 + 1) * 4  # calculatePP: scripts.ts:41-43
    if get('target') not in (TARGET_CLASS_POOL if lenient else TARGET_CLASS):
        fail('move %s: unknown target class %s' % (mid, get('target')))
    target_class = (TARGET_CLASS_POOL if lenient else TARGET_CLASS)[get('target')]
    if lenient and get('target') not in ENGINE_TARGETS:
        unmodeled.append('target %s' % get('target'))
    for what, table, key in (('type', TYPES, 'type'), ('category', CATEGORIES, 'category')):
        if get(key) not in table:
            fail('move %s: unknown %s %s' % (mid, what, get(key)))
    if 'basePowerCallback' in f and f['basePowerCallback'][0]:
        static_flags |= STATIC_FLAG_POWER_RULE
    hits = [1, 1]  # the pin's multihit: 1/1 for a single hit (decision 0020 item 4)
    if 'multihit' in f:
        mh = re.fullmatch(r'multihit: (?:(\d+)|\[(\d+), (\d+)\]),', norm(f['multihit'][1]))
        if mh is None:
            fail('move %s: multihit is not "multihit: n," or "multihit: [min, max],"' % mid)
        hits = [int(mh.group(1)), int(mh.group(1))] if mh.group(1) else [int(mh.group(2)), int(mh.group(3))]
        if not 1 <= hits[0] <= hits[1] <= 255:
            fail('move %s: multihit %s is not 1 <= min <= max <= 255' % (mid, hits))
    rec = {
        'id': mid, 'name': get('name'), 'refs': refs, 'static_flags': static_flags, 'hits': hits,
        'type': TYPES.index(get('type')), 'category': CATEGORIES[get('category')],
        'base_power': get('basePower'), 'accuracy': 0 if acc is True else acc, 'pp_base': pp_base, 'pp_max': pp_max,
        'priority': get('priority') + 8, 'target_class': target_class,
        'crit_ratio': get('critRatio', 1), 'flags': flags, 'flags2': flags2, 'flags3': flags3, 'heal': [0, 0],
        'recoil': [0, 0], 'drain': [0, 0], 'sec_chance': 0, 'sec_kind': 0, 'sec_param': 0,
        'boost_role': 0, 'boosts': [0] * 7, 'primary_status': 0, 'side_condition': 0, 'pseudo_weather': 0,
        'special': (SPECIAL_IDS_P if pool else SPECIAL_IDS_C if ext else SPECIAL_IDS).index(handled[0]),
    }
    for key in ('recoil', 'drain'):
        if key in f:
            nums = [int(x) for x in re.findall(r'\d+', f[key][1])]
            if len(nums) != 2:
                fail('move %s: %s is not a fraction' % (mid, key))
            rec[key] = nums
    if pool and 'forceSwitch' in f:
        # Step G46: the four moves of G46_FORCE_SWITCH_MOVES, with the pinned text; the turn code forces the switch
        if mid in G46_FORCE_SWITCH_MOVES and norm(f['forceSwitch'][1]) == 'forceSwitch: true,':
            rec['flags2'] |= FLAG2_FORCE_SWITCH
        else:
            bad('move %s: forceSwitch is not "forceSwitch: true," of a G46 move' % mid, 'field forceSwitch')
    if pool and 'thawsTarget' in f:
        if norm(f['thawsTarget'][1]) != 'thawsTarget: true,':
            bad('move %s: thawsTarget is not "thawsTarget: true,"' % mid, 'field thawsTarget')
        else:
            rec['flags2'] |= FLAG2_THAWS_TARGET
    if pool and 'heal' in f:
        heal = re.fullmatch(r'heal: \[(\d+), (\d+)\],', norm(f['heal'][1]))
        if heal is None or not 0 < int(heal.group(1)) <= int(heal.group(2)) <= 255:
            bad('move %s: heal is not a fraction "heal: [a, b],"' % mid, 'field heal')
        else:
            rec['heal'] = [int(heal.group(1)), int(heal.group(2))]
    vectors = 0
    if g8_secondary is not None:
        rec['sec_chance'], rec['sec_kind'] = 100, g8_secondary[0]
    if 'secondary' in f and owned_secondary is None and g8_secondary is None:
        # The whole secondary must be one modelled effect; anything else (a
        # self block, a callback, several effects) fails instead of being misread.
        sec = re.fullmatch(r'secondary: \{ chance: (\d+), (.*) \},', ' '.join(f['secondary'][1].split()))
        if sec is None:
            bad('move %s: unknown secondary' % mid, 'secondary')
            effect = None
        else:
            rec['sec_chance'], effect = int(sec.group(1)), sec.group(2)
        st = re.fullmatch(r"status: '(\w+)',", effect or '')
        vo = re.fullmatch(r"volatileStatus: '(\w+)',", effect or '')
        if effect is None:
            rec['sec_chance'] = 0
        elif st:
            rec['sec_kind'], rec['sec_param'] = 2, modelled(STATUS_P if pool else STATUS, st.group(1), mid, 'secondary status',
                                                            unmodeled)
        elif vo:
            rec['sec_kind'], rec['sec_param'] = 3, modelled(VOLATILE, vo.group(1), mid, 'secondary volatile',
                                                            unmodeled)
        elif re.fullmatch(r'boosts: \{ (?:(?:%s): -?\d+, )+\},' % '|'.join(BOOSTS), effect):
            rec['sec_kind'] = 1
            rec['boost_role'], rec['boosts'] = BOOST_ROLE['SECONDARY_TARGET'], boosts_of(effect)
            vectors += 1
        elif ext and effect == STATUS_PICK_ONHIT:
            rec['sec_kind'] = SECONDARY_STATUS_PICK
        elif pool and re.fullmatch(r'self: \{ boosts: \{ (?:(?:%s): -?\d+, )+\}, \},' % '|'.join(BOOSTS), effect):
            # Step G28: a secondary whose own effect is a stat change of the user (Ancient Power: all five at 10 percent).
            rec['sec_kind'] = SECONDARY_SELF_BOOST
            rec['boost_role'], rec['boosts'] = BOOST_ROLE['SECONDARY_SELF'], boosts_of(effect)
            vectors += 1
        elif re.search(r'\bself: \{', effect):
            bad('move %s: secondary self effects are not supported' % mid, 'secondary self effect')
            rec['sec_chance'] = 0
        else:
            bad('move %s: unknown secondary' % mid, 'secondary')
            rec['sec_chance'] = 0
    if 'self' in f and 'self' not in owned:
        if pool and norm(f['self'][1]) == RECHARGE_SELF:
            # Step G17: the recharge moves (flags.recharge and this self effect, which the turn code reads as the
            # second flags byte's RECHARGE bit: the user must recharge after a hit).
            rec['flags2'] |= FLAG2_RECHARGE
        elif lenient and not re.search(r'\bboosts: ', f['self'][1]):
            unmodeled.append('self effect')
        else:
            rec['boost_role'], rec['boosts'] = BOOST_ROLE['SELF_AFTER_HIT'], boosts_of(f['self'][1])
            vectors += 1
    if pool and ('recharge: 1' in norm(f['flags'][1])) != ((rec['flags2'] & FLAG2_RECHARGE) != 0):
        bad('move %s: the recharge flag and the mustrecharge self effect do not come together' % mid, 'recharge flag')
    if 'boosts' in f:
        if pool and rec['target_class'] == TARGET_CLASS['adjacentAlly'] and rec['category'] == CATEGORIES['Status']:
            # Step G19: Coaching, a status move whose primary boosts go to the ally (BOOST_ROLE PRIMARY_ALLY).
            rec['boost_role'], rec['boosts'] = BOOST_ROLE['PRIMARY_ALLY'], boosts_of(f['boosts'][1])
            vectors += 1
        elif pool and rec['target_class'] == TARGET_CLASS['normal'] and rec['category'] == CATEGORIES['Status']:
            # Step G39: Charm and Fake Tears, a status move of one adjacent target whose primary boosts go to that target
            # (BOOST_ROLE PRIMARY_TARGET); a spread class (Growl) or a Pokemon of any distance stays UNMODELED.
            rec['boost_role'], rec['boosts'] = BOOST_ROLE['PRIMARY_TARGET'], boosts_of(f['boosts'][1])
            vectors += 1
        elif pool and rec['target_class'] == TARGET_CLASS_POOL['allies'] and rec['category'] == CATEGORIES['Status']:
            # Step G80: Howl, a status move whose primary boosts go to each standing member of the user's side (the user and
            # its ally: alliesAndSelf in slot order, sim/pokemon.ts:818-819). The turn code runs BOOST_ROLE PRIMARY_TARGET over
            # every target of the allies class (the Life Dew list), so the role is the same one Charm uses.
            rec['boost_role'], rec['boosts'] = BOOST_ROLE['PRIMARY_TARGET'], boosts_of(f['boosts'][1])
            vectors += 1
        elif rec['target_class'] != TARGET_CLASS['self']:
            bad('move %s: primary boosts on a non-self target' % mid, 'primary boosts on a non-self target')
        else:
            rec['boost_role'], rec['boosts'] = BOOST_ROLE['PRIMARY_SELF'], boosts_of(f['boosts'][1])
            vectors += 1
    if vectors > 1:
        bad('move %s: more than one boost vector' % mid, 'more than one boost vector')
        rec['boost_role'], rec['boosts'] = 0, [0] * 7
    if 'status' in f:
        rec['primary_status'] = modelled(STATUS_P if pool else STATUS_C if ext else STATUS, get('status'), mid, 'primary status', unmodeled)
    owned_volatile = SPECIAL_VOLATILE_C.get(handled[0]) if ext else None
    if 'volatileStatus' in f and 'volatileStatus' not in owned and get('volatileStatus') not in ('protect', owned_volatile):
        bad('move %s: unknown primary volatile' % mid, 'primary volatile %s' % get('volatileStatus'))
    if 'sideCondition' in f and 'sideCondition' not in owned:
        rec['side_condition'] = modelled(SIDE_CONDITION_P if pool else SIDE_CONDITION, get('sideCondition'), mid, 'side condition', unmodeled)
    if 'pseudoWeather' in f:
        rec['pseudo_weather'] = modelled(PSEUDO_WEATHER, get('pseudoWeather'), mid, 'pseudo weather', unmodeled)
    if 'condition' in f and not (rec['side_condition'] or rec['pseudo_weather'] or mid == 'protect' or
                                 owned_volatile is not None or owns_condition):
        bad('move %s: condition block without a known owner' % mid, 'condition block')
    for k in ('base_power', 'accuracy', 'pp_base', 'pp_max', 'priority', 'crit_ratio'):
        if not 0 <= rec[k] <= 255:
            fail('move %s: %s out of range' % (mid, k))
    return rec


G2_MOVES = ['uturn', 'rockslide', 'throatchop', 'encore', 'doubleedge', 'thunderbolt', 'scald', 'wideguard',
            'flashcannon', 'extremespeed', 'headsmash', 'firstimpression', 'bulkup', 'liquidation', 'icepunch',
            'shadowclaw', 'recover', 'soak', 'psychicnoise', 'drumbeating', 'lowkick', 'dazzlinggleam']
# Nine of the 22 moves have a callback or a field that the tables do not model. As decision 0009 section 3.3 did for
# Sucker Punch or Follow Me, each is mapped deliberately to a named handler id (the value of the move's special
# column) that owns what the columns cannot hold, and the engine refuses it: the move stays unmarked in the support
# manifest, and the turn code returns an error for a special it does not have. The handler may own only the
# callbacks, fields, condition block and secondary named below, each of which must be present and, for a field or a
# secondary, exactly this text of the pinned data; everything else about the move is read by parse_move as for any
# other move, and anything it does not know still fails. Each step that implements one of them (G7 to G11) consumes
# the handler id and, if it needs a column, changes the tables and the POOL fingerprint and says so.
# (SOAK is implemented by the turn code since step G11 and marked; it keeps its handler id, so no table byte changed. The same
# holds for ENCORE since step G9.)
G2_HANDLERS = ['ENCORE', 'SCALD', 'WIDE_GUARD', 'FIRST_IMPRESSION', 'RECOVER', 'SOAK', 'LOW_KICK']
# The two weather moves of the Sandstorm and Snowscape step: rows of the whole pool (not of G2) with a named handler,
# because the field `weather` that sets the weather has no column; the turn code implements both.
WEATHER_HANDLERS = ['SANDSTORM', 'SNOWSCAPE']
# Step G16: Knock Off keeps its two callbacks as a handler of its own that the turn code implements (a row of the whole
# pool, like the weather moves: not one of G2's). The generator checks the callbacks' whole text, whitespace aside
# (data/moves.ts:9959-9984; the Champions mod does not change the move): the item is read with the same
# singleEvent('TakeItem') that the turn code knows (a Mega Stone refuses its own species), the boost is 1.5, and the item is
# taken after the hit with the -enditem line that the converter reads.
G16_HANDLERS = ['KNOCK_OFF']
# Step G19: Glaive Rush keeps its self effect and its condition as a handler of its own that the turn code implements: the
# user is hit by moves that never miss and deal double damage until its next move starts (data/moves.ts:6647-6678). The
# generator checks the self effect and the whole condition text, whitespace aside.
G19_HANDLERS = ['GLAIVE_RUSH']
GLAIVE_RUSH_CONDITION = ("condition: { noCopy: true, onStart(pokemon) { this.add('-singlemove', pokemon, 'Glaive Rush', '[silent]'); }, "
                         "onAccuracy() { return true; }, onSourceModifyDamage() { return this.chainModify(2); }, "
                         "onBeforeMovePriority: 100, onBeforeMove(pokemon) { this.debug('removing Glaive Rush drawback before attack'); "
                         "pokemon.removeVolatile('glaiverush'); }, },")
# Step G20: Aurora Veil is a handler of its own that the turn code implements (a row of the whole pool, like Knock Off:
# not one of G2's). Its onTry is the snow test (data/moves.ts:830-877; the Champions mod does not change the move); the
# condition is read from the pinned text (G20_CONDITION_FACTS) and the side condition itself (a tail field, not a column)
# is owned by the handler.
G20_HANDLERS = ['AURORA_VEIL']
# Step G20, the Protect variants: Spiky Shield (data/moves.ts:17532-17584) is Protect with a contact punishment, so it has a
# handler of its own that the turn code implements (the Protect path plus the punishment). Baneful Bunker (:985-1037) is the
# same with poison, but its only learner, Toxapex, has no supported ability, so it stays UNMODELED until one is marked.
# The generator checks that the fields and both callbacks are Protect's (not its volatile, whose name is the move's, and
# not its type) and the whole condition text of the variant, whitespace aside: onTryHit's contact punishment is the one
# thing that differs. King's Shield stays unmarked (its only learner, Aegislash, has no supported ability either).
G20_PROTECT_HANDLERS = ['SPIKY_SHIELD']
PROTECT_VARIANT_COPY_FIELDS = ('onPrepareHit', 'onHit', 'stallingMove', 'flags', 'priority', 'accuracy', 'target')
PROTECT_VARIANT_CONDITION = (
    "condition: { duration: 1, onStart(target) { this.add('-singleturn', target, 'move: Protect'); }, onTryHitPriority: 3, "
    "onTryHit(target, source, move) { if (this.checkMoveBypassesProtect(move, source, target)) return; "
    "if (move.smartTarget) { move.smartTarget = false; } else { this.add('-activate', target, 'move: Protect'); } "
    "const lockedmove = source.getVolatile('lockedmove'); if (lockedmove) { // Outrage counter is reset "
    "if (source.volatiles['lockedmove'].duration === 2) { delete source.volatiles['lockedmove']; } } "
    "if (this.checkMoveMakesContact(move, source, target)) { %s } return this.NOT_FAIL; }, "
    "onHit(target, source, move) { if (move.isZOrMaxPowered && this.checkMoveMakesContact(move, source, target)) { %s } }, },")
PROTECT_VARIANT_PUNISHMENT = {'SPIKY_SHIELD': 'this.damage(source.baseMaxhp / 8, source, target);',
                              'BANEFUL_BUNKER': "source.trySetStatus('psn', target);"}
# Step G94 (decision 0015 5cv, decision 0061): Baneful Bunker (data/moves.ts:985-1037) is the same Protect variant with poison
# on a contact attacker; its only learner in the pool is Toxapex, whose Limber and Regenerator are marked (G39, G20-era
# Regenerator). Its handler is a row of its own, appended after G78 (before UNMODELED). The template check above covers
# the whole condition text with the punishment filled in; the move's copied fields are Protect's, as for Spiky Shield.
G94_HANDLERS = ['BANEFUL_BUNKER']
# Step G66, King's Shield: the pinned condition (data/moves.ts:9905-9955), whitespace aside. Unlike Spiky Shield's, its
# onTryHit passes a Status move (checkMoveBypassesProtect with blockStatus false) and its contact drop is -1 Attack on the
# attacker (both in onTryHit and in onHit for a Z-move). The move's own flags differ from Protect's (failinstruct), so only
# these fields are copied from Protect: onPrepareHit, onHit, stallingMove, priority, accuracy and target.
KINGS_SHIELD_COPY_FIELDS = ('onPrepareHit', 'onHit', 'stallingMove', 'priority', 'accuracy', 'target')
KINGS_SHIELD_CONDITION = """condition: {
duration: 1,
onStart(target) {
this.add('-singleturn', target, 'Protect');
},
onTryHitPriority: 3,
onTryHit(target, source, move) {
if (this.checkMoveBypassesProtect(move, source, target, false)) return;
if (move.smartTarget) {
move.smartTarget = false;
} else {
this.add('-activate', target, 'move: Protect');
}
const lockedmove = source.getVolatile('lockedmove');
if (lockedmove) {
// Outrage counter is reset
if (source.volatiles['lockedmove'].duration === 2) {
delete source.volatiles['lockedmove'];
}
}
if (this.checkMoveMakesContact(move, source, target)) {
this.boost({ atk: -1 }, source, target, this.dex.getActiveMove("King's Shield"));
}
return this.NOT_FAIL;
},
onHit(target, source, move) {
if (move.isZOrMaxPowered && this.checkMoveMakesContact(move, source, target)) {
this.boost({ atk: -1 }, source, target, this.dex.getActiveMove("King's Shield"));
}
},
},"""
# Step G27: Disable (data/moves.ts:3648-3716 with the Champions override data/mods/champions/moves.ts:228-238) is a handler of its
# own that the turn code implements (its onTryHit, and a condition whose state is the tail's disable_slot and disable_turns).
# The generator checks the onTryHit and both condition texts, whitespace aside: the pinned condition (duration 5, the onStart
# that takes one turn off when the target has not moved or when Cursed Body acts, the lines, order 17, onBeforeMove priority
# 7, onDisableMove) and the Champions condition that only changes onBeforeMove (a move with the cantusetwice flag is not
# stopped). Cursed Body (data/abilities.ts:784-797) is an engine row (ENGINE_ROWS).
G27_HANDLERS = ['DISABLE']
DISABLE_ONTRYHIT = ("onTryHit(target) { if (!target.lastMove || target.lastMove.isZOrMaxPowered || target.lastMove.isMax || "
                    "target.lastMove.id === 'struggle') { return false; } },")
DISABLE_CONDITION = (
    "condition: { duration: 5, noCopy: true, // doesn't get copied by Baton Pass onStart(pokemon, source, effect) { "
    "// The target hasn't taken its turn, or Cursed Body activated and the move was not used through Dancer or Instruct "
    "if ( this.queue.willMove(pokemon) || (pokemon === this.activePokemon && this.activeMove && !this.activeMove.isExternal) ) "
    "{ this.effectState.duration!--; } if (!pokemon.lastMove) { this.debug(`Pokemon hasn't moved yet`); return false; } "
    "for (const moveSlot of pokemon.moveSlots) { if (moveSlot.id === pokemon.lastMove.id) { if (!moveSlot.pp) { "
    "this.debug('Move out of PP'); return false; } } } if (effect.effectType === 'Ability') { this.add('-start', pokemon, "
    "'Disable', pokemon.lastMove.name, '[from] ability: ' + effect.name, `[of] ${source}`); } else { this.add('-start', pokemon, "
    "'Disable', pokemon.lastMove.name); } this.effectState.move = pokemon.lastMove.id; }, onResidualOrder: 17, onEnd(pokemon) { "
    "this.add('-end', pokemon, 'Disable'); }, onBeforeMovePriority: 7, onBeforeMove(attacker, defender, move) { "
    "if (!(move.isZ && move.isZOrMaxPowered) && move.id === this.effectState.move) { this.add('cant', attacker, 'Disable', move); "
    "return false; } }, onDisableMove(pokemon) { for (const moveSlot of pokemon.moveSlots) { if (moveSlot.id === "
    "this.effectState.move) { pokemon.disableMove(moveSlot.id); } } }, },")
DISABLE_CONDITION_CHAMPIONS = (
    "condition: { inherit: true, onBeforeMove(attacker, defender, move) { if (!(move.isZ && move.isZOrMaxPowered) && move.id === "
    "this.effectState.move && !move.flags['cantusetwice']) { this.add('cant', attacker, 'Disable', move); return false; } }, },")
# Step G28 (a batch of move rules): Shell Smash keeps its boost order (the pin lists def and spd before atk, spa and spe and the
# engine applies a vector in stat order), Acrobatics and Blizzard their one callback, Feint its `breaksProtect`: handlers
# of their own that the turn code implements. The generator checks their texts (G28_FACTS; Expert Belt, an item rule
# of the turn code, G28_ITEM_FACTS), because the engine hard-codes them. Ancient Power needs no handler: its secondary
# self boost is a new secondary kind (SECONDARY_SELF_BOOST) of the generic columns.
G28_HANDLERS = ['SHELL_SMASH', 'ACROBATICS', 'BLIZZARD', 'FEINT']
G28_FACTS = (
    ('shellsmash', ['accuracy: true,', 'category: "Status",', 'target: "self",', 'priority: 0,',
                    'boosts: { def: -1, spd: -1, atk: 2, spa: 2, spe: 2, },']),
    ('acrobatics', ['accuracy: 100,', 'basePower: 55,', 'category: "Physical",', 'target: "any",', 'type: "Flying",',
                    'flags: { contact: 1, protect: 1, mirror: 1, distance: 1, metronome: 1 },',
                    "basePowerCallback(pokemon, target, move) { if (!pokemon.item) { this.debug(\"BP doubled for no item\"); "
                    "return move.basePower * 2; } return move.basePower; },"]),
    ('blizzard', ['accuracy: 70,', 'basePower: 110,', 'category: "Special",', 'target: "allAdjacentFoes",', 'type: "Ice",',
                  "onModifyMove(move) { if (this.field.isWeather(['hail', 'snowscape'])) move.accuracy = true; },",
                  "secondary: { chance: 10, status: 'frz', },"]),
    ('feint', ['accuracy: 100,', 'basePower: 30,', 'category: "Physical",', 'priority: 2,', 'target: "normal",', 'type: "Normal",',
               'flags: { mirror: 1, noassist: 1, failcopycat: 1 },', 'breaksProtect: true,']),
    ('grassyterrain', ['onBasePowerPriority: 6,',
                       "onBasePower(basePower, attacker, defender, move) { const weakenedMoves = ['earthquake', 'bulldoze', 'magnitude']; "
                       "if (weakenedMoves.includes(move.id) && defender.isGrounded() && !defender.isSemiInvulnerable()) { "
                       "this.debug('move weakened by grassy terrain'); return this.chainModify(0.5); } "
                       "if (move.type === 'Grass' && attacker.isGrounded()) { this.debug('grassy terrain boost'); "
                       "return this.chainModify([5325, 4096]); } },"]),
    ('earthquake', ['accuracy: 100,', 'basePower: 100,', 'category: "Physical",', 'priority: 0,', 'target: "allAdjacent",',
                    'type: "Ground",', 'flags: { protect: 1, mirror: 1, nonsky: 1, metronome: 1 },']),
    ('ancientpower', ['accuracy: 100,', 'basePower: 60,', 'category: "Special",', 'target: "normal",', 'type: "Rock",',
                      "secondary: { chance: 10, self: { boosts: { atk: 1, def: 1, spa: 1, spd: 1, spe: 1, }, }, },"]),
)
# Step G38: Imprison (data/moves.ts:9489-9523; the Champions mod has no entry) keeps its volatile as a handler of its own that
# the turn code implements: the start line `-start|user|move: Imprison`, the foes' hidden disable of every move the user knows
# (onFoeDisableMove, run for every active Pokemon in endTurn) and the BeforeMove check at priority 4 that shows
# `cant|foe|move: Imprison|Move` (onFoeBeforeMove). The generator checks the whole text, whitespace aside, because the engine
# hard-codes it.
G38_HANDLERS = ['IMPRISON']
G38_FACTS = (
    ('imprison', ['accuracy: true,', 'basePower: 0,', 'category: "Status",', 'pp: 10,', 'priority: 0,',
                  'flags: { snatch: 1, bypasssub: 1, metronome: 1, mustpressure: 1 },', "volatileStatus: 'imprison',",
                  'noCopy: true,', "onStart(target) { this.add('-start', target, 'move: Imprison'); },",
                  "onFoeDisableMove(pokemon) { for (const moveSlot of this.effectState.source.moveSlots) { "
                  "if (moveSlot.id === 'struggle') continue; pokemon.disableMove(moveSlot.id, true); } "
                  "pokemon.maybeDisabled = true; },",
                  'onFoeBeforeMovePriority: 4,',
                  "onFoeBeforeMove(attacker, defender, move) { if (move.id !== 'struggle' && "
                  "this.effectState.source.hasMove(move.id) && !move.isZOrMaxPowered) { "
                  "this.add('cant', attacker, 'move: Imprison', move); return false; } },",
                  'target: "self",', 'type: "Psychic",']),
)
# Step G34 (a batch of small rules): Steel Roller (fails without a terrain and ends it), Clangorous Soul (a third of the HP for
# five boosts) and Brick Break (the screens go before the hit) keep their callbacks as handlers of their own that the turn code
# implements; the abilities Compound Eyes, Iron Fist, Sharpness, Solid Rock, Technician, Multiscale and Gale Wings and the item
# Wide Lens are engine rows (ENGINE_ROWS). The generator checks the pinned texts the engine hard-codes (G34_FACTS for the moves,
# G34_ABILITY_FACTS and G34_ITEM_FACTS), the Champions mod overriding none of the entries but Clangorous Soul's accuracy: true,
# which parse_move merges (data/mods/champions/moves.ts:121-124).
G34_HANDLERS = ['STEEL_ROLLER', 'CLANGOROUS_SOUL', 'BRICK_BREAK']
G34_FACTS = (
    ('steelroller', ['accuracy: 100,', 'basePower: 130,', 'category: "Physical",', 'target: "normal",', 'type: "Steel",',
                     'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },',
                     "onTry() { return !this.field.isTerrain(''); },", 'onHit() { this.field.clearTerrain(); },',
                     'onAfterSubDamage() { this.field.clearTerrain(); },']),
    ('clangoroussoul', ['basePower: 0,', 'category: "Status",', 'target: "self",', 'type: "Dragon",', 'priority: 0,',
                        'flags: { snatch: 1, sound: 1, dance: 1 },',
                        "onTry(source) { if (source.hp <= (source.maxhp * 33 / 100) || source.maxhp === 1) return false; },",
                        "onTryHit(pokemon, target, move) { if (!this.boost(move.boosts!)) return null; delete move.boosts; },",
                        "onHit(pokemon) { this.directDamage(pokemon.maxhp * 33 / 100); },",
                        'boosts: { atk: 1, def: 1, spa: 1, spd: 1, spe: 1, },']),
    ('brickbreak', ['accuracy: 100,', 'basePower: 75,', 'category: "Physical",', 'target: "normal",', 'type: "Fighting",',
                    'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },',
                    "onTryHit(pokemon) { // will shatter screens through sub, before you hit pokemon.side.removeSideCondition('reflect'); "
                    "pokemon.side.removeSideCondition('lightscreen'); pokemon.side.removeSideCondition('auroraveil'); },"]),
)
# Step G37 (the entry hazards): the four moves with the target class foeSide are rows of the tables without a handler of
# their own (the side condition is a column: SIDE_CONDITION_P) and the turn code runs their conditions: the layers, the
# damage of the switch-in and the status and the stat drop. The generator checks the whole pinned text the engine hard-codes:
# the Champions mod overrides none of the four (data/mods/champions/moves.ts). Toxic Debris (Glimmora's ability) is an engine
# row (ENGINE_ROWS) with its own text (G37_ABILITY_FACTS).
G37_FACTS = (
    ('stealthrock', ['accuracy: true,', 'category: "Status",', 'target: "foeSide",', 'type: "Rock",', 'priority: 0,',
                     'flags: { reflectable: 1, metronome: 1, mustpressure: 1 },', "sideCondition: 'stealthrock',",
                     "onSideStart(side) { this.add('-sidestart', side, 'move: Stealth Rock'); },",
                     "onSwitchIn(pokemon) { if (pokemon.hasItem('heavydutyboots')) return; "
                     "const typeMod = this.clampIntRange(pokemon.runEffectiveness(this.dex.getActiveMove('stealthrock')), -6, 6); "
                     "this.damage(pokemon.maxhp * (2 ** typeMod) / 8); },"]),
    ('spikes', ['accuracy: true,', 'category: "Status",', 'target: "foeSide",', 'type: "Ground",', 'priority: 0,',
                'flags: { reflectable: 1, nonsky: 1, metronome: 1, mustpressure: 1 },', "sideCondition: 'spikes',",
                "onSideStart(side) { this.add('-sidestart', side, 'Spikes'); this.effectState.layers = 1; },",
                "onSideRestart(side) { if (this.effectState.layers >= 3) return false; this.add('-sidestart', side, 'Spikes'); "
                "this.effectState.layers++; },",
                "onSwitchIn(pokemon) { if (!pokemon.isGrounded() || pokemon.hasItem('heavydutyboots')) return; "
                "const damageAmounts = [0, 3, 4, 6]; // 1/8, 1/6, 1/4 this.damage(damageAmounts[this.effectState.layers] * pokemon.maxhp / 24); },"]),
    ('toxicspikes', ['accuracy: true,', 'category: "Status",', 'target: "foeSide",', 'type: "Poison",', 'priority: 0,',
                     'flags: { reflectable: 1, nonsky: 1, metronome: 1, mustpressure: 1 },', "sideCondition: 'toxicspikes',",
                     "onSideStart(side) { this.add('-sidestart', side, 'move: Toxic Spikes'); this.effectState.layers = 1; },",
                     "onSideRestart(side) { if (this.effectState.layers >= 2) return false; "
                     "this.add('-sidestart', side, 'move: Toxic Spikes'); this.effectState.layers++; },",
                     "onSwitchIn(pokemon) { if (!pokemon.isGrounded()) return; if (pokemon.hasType('Poison')) { "
                     "this.add('-sideend', pokemon.side, 'move: Toxic Spikes', `[of] ${pokemon}`); "
                     "pokemon.side.removeSideCondition('toxicspikes'); } else if (pokemon.hasType('Steel') || "
                     "pokemon.hasItem('heavydutyboots')) { // do nothing } else if (this.effectState.layers >= 2) { "
                     "pokemon.trySetStatus('tox', pokemon.side.foe.active[0]); } else { "
                     "pokemon.trySetStatus('psn', pokemon.side.foe.active[0]); } },"]),
    ('stickyweb', ['accuracy: true,', 'category: "Status",', 'target: "foeSide",', 'type: "Bug",', 'priority: 0,',
                   'flags: { reflectable: 1, metronome: 1 },', "sideCondition: 'stickyweb',",
                   "onSideStart(side) { this.add('-sidestart', side, 'move: Sticky Web'); },",
                   "onSwitchIn(pokemon) { if (!pokemon.isGrounded() || pokemon.hasItem('heavydutyboots')) return; "
                   "this.add('-activate', pokemon, 'move: Sticky Web'); "
                   "this.boost({ spe: -1 }, pokemon, pokemon.side.foe.active[0], this.dex.getActiveMove('stickyweb')); },"]),
)
# the moves: Sacred Sword is Darkest Lariat's handler (ignoreEvasion and ignoreDefensive, no callback), Super Fang has the one
# damageCallback of the handler SUPER_FANG, Charm and Fake Tears are data (a status move whose primary boosts go to its target)
G39_HANDLERS = ['SUPER_FANG']
G39_FACTS = (
    ('sacredsword', ['accuracy: 100,', 'basePower: 90,', 'category: "Physical",', 'priority: 0,', 'target: "normal",', 'type: "Fighting",',
                     'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1, slicing: 1 },', 'ignoreEvasion: true,',
                     'ignoreDefensive: true,']),
    ('charm', ['accuracy: 100,', 'basePower: 0,', 'category: "Status",', 'priority: 0,', 'target: "normal",', 'type: "Fairy",',
               'flags: { protect: 1, reflectable: 1, mirror: 1, allyanim: 1, metronome: 1 },', 'boosts: { atk: -2, },']),
    ('faketears', ['accuracy: 100,', 'basePower: 0,', 'category: "Status",', 'priority: 0,', 'target: "normal",', 'type: "Dark",',
                   'flags: { protect: 1, reflectable: 1, mirror: 1, allyanim: 1, metronome: 1 },', 'boosts: { spd: -2, },']),
    ('superfang', ['accuracy: 90,', 'basePower: 0,', 'damageCallback(pokemon, target) { return this.clampIntRange(target.getUndynamaxedHP() / 2, 1); },',
                   'category: "Physical",', 'priority: 0,', 'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },',
                   'target: "normal",', 'type: "Normal",']),
)
G59_INHERIT_ONLY = ('firemane', 'spicyspray', 'megasol')
# The pinned lines the suppression rests on (sim/field.ts, sim/battle.ts, sim/battle-actions.ts) and the weather's own residual
# (data/conditions.ts): which weather handlers run while the weather is suppressed, and where the holder's end is shown.
G79_FIELD_FACTS = (
    ('field', ('suppressingWeather() {',
               'if (pokemon && !pokemon.fainted && !pokemon.ignoringAbility() &&',
               'pokemon.getAbility().suppressWeather && !pokemon.abilityState.ending) {',
               "if (this.suppressingWeather()) return '';",
               'const ourWeather = this.effectiveWeather();')),
    ('battle', ("effect.effectType === 'Weather' && eventid !== 'FieldStart' && eventid !== 'FieldResidual' &&",
                "eventid !== 'FieldEnd' && this.field.suppressingWeather()",
                "(effect.effectType === 'Weather' || eventid === 'Weather') &&",
                "eventid !== 'Residual' && eventid !== 'End' && this.field.suppressingWeather()",
                "if (eventid === 'Weather' && this.gen >= 7) {",
                "if (eventid === 'Residual' && handler.end && handler.state?.duration) {",
                'handler.state.duration--;',
                "this.singleEvent('End', pokemon.getAbility(), pokemon.abilityState, pokemon);",
                'pokemon.fainted = true;')),
    ('battle-actions', ("this.battle.singleEvent('End', oldActive.getAbility(), oldActive.abilityState, oldActive);",)),
    ('conditions', ("this.add('-weather', 'RainDance', '[upkeep]');",
                    "this.add('-weather', 'SunnyDay', '[upkeep]');",
                    "if (this.field.isWeather('sandstorm')) this.eachEvent('Weather');",
                    "if (this.field.isWeather('snowscape')) this.eachEvent('Weather');")),
)
# Step G32 (small rules): eight handlers of the turn code, one per rule that the generic columns cannot hold: HP_POWER
# (Eruption and Water Spout: power 150 x HP / maximum HP, one callback), BODY_PRESS, FOUL_PLAY and PSYSHOCK (the three
# `override...` fields of the damage formula), RAIN_DANCE and SUNNY_DAY (the weather moves, like Sandstorm and Snowscape),
# FREEZE_DRY (the Water type takes it super effective: onEffectiveness; the Champions mod drops its freeze) and
# CLANGING_SCALES (selfBoost: the user's own Defense drop after a hit). The generator checks their texts (G32_FACTS), and the
# entries of the ability and item rows of the step (G32_ENTRY_FACTS: Soundproof, Unnerve, Speed Boost and the Champions
# Eject Button), because the engine hard-codes them. Life Dew needs no handler (its target class `allies` is now an engine
# class: ENGINE_TARGETS), Volt Switch none (ENGINE_PIVOT_MOVES: a switch flag of its own).
G32_HANDLERS = ['HP_POWER', 'BODY_PRESS', 'FOUL_PLAY', 'PSYSHOCK', 'RAIN_DANCE', 'SUNNY_DAY', 'FREEZE_DRY', 'CLANGING_SCALES']
# Step G33 (the multi-hit batch): two handlers, one per rule that the generic columns cannot hold. MULTI_HIT_2 (Dual Wingbeat
# and Twin Beam: `multihit: 2,`) and TRIPLE_AXEL (`multihit: 3,`, `multiaccuracy: true,` and the power 20 x the hit). Population
# Bomb (ten hits, `multiaccuracy`) has no handler: its only learners, Maushold and Maushold-Four, have no marked ability, so no
# legal team can play it and no battle can be recorded; it gets one with the first of Friend Guard, Cheek Pouch and Technician.
# The hit count lives in the handler, not in a column: the static
# columns of decision 0020 have no engine reader (item 5), and the other multihit rows (random counts, smartTarget, secondaries)
# stay unmodelled. The generator checks the four rows' whole texts (G33_FACTS) and Mirror Armor's entry (G33_ENTRY_FACTS).
G33_HANDLERS = ['MULTI_HIT_2', 'TRIPLE_AXEL']
G33_FACTS = (
    ('dualwingbeat', ['accuracy: 90,', 'basePower: 40,', 'category: "Physical",', 'priority: 0,',
                      'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },', 'multihit: 2,', 'target: "normal",',
                      'type: "Flying",']),
    ('tripleaxel', ['accuracy: 90,', 'basePower: 20,', 'basePowerCallback(pokemon, target, move) { return 20 * move.hit; },',
                    'category: "Physical",', 'priority: 0,', 'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },',
                    'multihit: 3,', 'multiaccuracy: true,', 'target: "normal",', 'type: "Ice",']),
    ('twinbeam', ['accuracy: 100,', 'basePower: 40,', 'category: "Special",', 'priority: 0,',
                  'flags: { protect: 1, mirror: 1 },', 'multihit: 2,', 'target: "normal",', 'type: "Psychic",']),
    ('doublehit', ['accuracy: 90,', 'basePower: 35,', 'category: "Physical",', 'priority: 0,',
                   'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },', 'multihit: 2,', 'target: "normal",',
                   'type: "Normal",']),
)
G33_ENTRY_FACTS = (
    ('ability', 'mirrorarmor', False,
     ["if (!source || target === source || !boost || effect.name === 'Mirror Armor') return;",
      "let b: BoostID; for (b in boost) { if (boost[b]! < 0) { if (target.boosts[b] === -6) continue; "
      "const negativeBoost: SparseBoostsTable = {}; negativeBoost[b] = boost[b]; delete boost[b]; if (source.hp) { "
      "this.add('-ability', target, 'Mirror Armor'); this.boost(negativeBoost, source, target, null, true); } } }",
      'flags: { breakable: 1 },']),
)
# Step G48 (moves that use the rev 4 fields that exist): Rage Fist (the power of the user's hits_taken, tail rev 4), Stone Axe and
# Ceaseless Edge (a hazard on the foe's side after a hit, the G37 hazard add) and Population Bomb (ten hits, multiaccuracy; its
# accuracy is 90, which the later-hit proof of G33 covers). The Champions mod overrides none of the four (data/mods/champions/
# moves.ts has only an inherit for Rage Fist, whose hit counter is reset in Pokemon#clearVolatile). Quick Guard is not here: its
# block line needs a new BLOCKED detail. The generator checks the four whole texts (G48_FACTS) and the handler ids.
G48_HANDLERS = ['RAGE_FIST', 'STONE_AXE', 'CEASELESS_EDGE', 'MULTI_HIT_10']
G48_FACTS = (
    ('ragefist', ['accuracy: 100,', 'basePower: 50,',
                  'basePowerCallback(pokemon) { return Math.min(350, 50 + 50 * pokemon.timesAttacked); },',
                  'category: "Physical",', 'priority: 0,', 'flags: { contact: 1, protect: 1, mirror: 1, punch: 1 },',
                  'target: "normal",', 'type: "Ghost",']),
    ('stoneaxe', ['accuracy: 90,', 'basePower: 65,', 'category: "Physical",', 'priority: 0,',
                  'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1, slicing: 1 },',
                  "onAfterHit(target, source, move) { if (!move.hasSheerForce) { for (const side of source.side.foeSidesWithConditions()) { "
                  "side.addSideCondition('stealthrock'); } } },",
                  'secondary: {},', 'target: "normal",', 'type: "Rock",']),
    ('ceaselessedge', ['accuracy: 90,', 'basePower: 65,', 'category: "Physical",', 'priority: 0,',
                       'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1, slicing: 1 },',
                       "onAfterHit(target, source, move) { if (!move.hasSheerForce) { for (const side of source.side.foeSidesWithConditions()) { "
                       "side.addSideCondition('spikes'); } } },",
                       'secondary: {},', 'target: "normal",', 'type: "Dark",']),
    ('populationbomb', ['accuracy: 90,', 'basePower: 20,', 'category: "Physical",', 'priority: 0,',
                        'flags: { contact: 1, protect: 1, mirror: 1, slicing: 1 },', 'multihit: 10,', 'multiaccuracy: true,',
                        'target: "normal",', 'type: "Normal",']),
)
_HP_POWER_CALLBACK = ("basePowerCallback(pokemon, target, move) { const bp = move.basePower * pokemon.hp / pokemon.maxhp; "
                      "this.debug(`BP: ${bp}`); return bp; },")
G32_FACTS = (
    ('eruption', ['accuracy: 100,', 'basePower: 150,', _HP_POWER_CALLBACK, 'category: "Special",', 'priority: 0,',
                  'flags: { protect: 1, mirror: 1, metronome: 1 },', 'target: "allAdjacentFoes",', 'type: "Fire",']),
    ('waterspout', ['accuracy: 100,', 'basePower: 150,', _HP_POWER_CALLBACK, 'category: "Special",', 'priority: 0,',
                    'flags: { protect: 1, mirror: 1, metronome: 1 },', 'target: "allAdjacentFoes",', 'type: "Water",']),
    ('bodypress', ['accuracy: 100,', 'basePower: 80,', 'category: "Physical",', 'priority: 0,',
                   'flags: { contact: 1, protect: 1, mirror: 1 },', "overrideOffensiveStat: 'def',", 'target: "normal",',
                   'type: "Fighting",']),
    ('foulplay', ['accuracy: 100,', 'basePower: 95,', 'category: "Physical",', 'priority: 0,',
                  'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },', "overrideOffensivePokemon: 'target',",
                  'target: "normal",', 'type: "Dark",']),
    ('psyshock', ['accuracy: 100,', 'basePower: 80,', 'category: "Special",', "overrideDefensiveStat: 'def',", 'priority: 0,',
                  'flags: { protect: 1, mirror: 1, metronome: 1 },', 'target: "normal",', 'type: "Psychic",']),
    ('raindance', ['accuracy: true,', 'category: "Status",', 'priority: 0,', 'flags: { metronome: 1 },', "weather: 'RainDance',",
                   'target: "all",', 'type: "Water",']),
    ('sunnyday', ['accuracy: true,', 'category: "Status",', 'priority: 0,', 'flags: { metronome: 1 },', "weather: 'sunnyday',",
                  'target: "all",', 'type: "Fire",']),
    ('freezedry', ['accuracy: 100,', 'basePower: 70,', 'category: "Special",', 'priority: 0,',
                   'flags: { protect: 1, mirror: 1, metronome: 1 },',
                   "onEffectiveness(typeMod, target, type) { if (type === 'Water') return 1; },", 'target: "normal",',
                   'type: "Ice",']),
    ('clangingscales', ['accuracy: 100,', 'basePower: 110,', 'category: "Special",', 'priority: 0,',
                        'flags: { protect: 1, mirror: 1, sound: 1, bypasssub: 1, metronome: 1 },',
                        'selfBoost: { boosts: { def: -1, }, },', 'target: "allAdjacentFoes",', 'type: "Dragon",']),
    ('voltswitch', ['accuracy: 100,', 'basePower: 70,', 'category: "Special",', 'priority: 0,',
                    'flags: { protect: 1, mirror: 1, metronome: 1 },', 'selfSwitch: true,', 'target: "normal",',
                    'type: "Electric",']),
    ('lifedew', ['accuracy: true,', 'category: "Status",', 'priority: 0,', 'flags: { snatch: 1, heal: 1, bypasssub: 1 },',
                 'heal: [1, 4],', 'target: "allies",', 'type: "Water",']),
)
# Ability and item rows that the turn code runs by id: the entry of the pin (or of the Champions mod, which is read first
# for the item) must have exactly these texts. (kind, id, in the Champions file, texts)
G32_ENTRY_FACTS = (
    ('ability', 'regenerator', True,
     ["onSwitchOut(pokemon) { if (pokemon.heal(pokemon.baseMaxhp / 3)) { this.add('-heal', pokemon, pokemon.getHealth, "
      "'[from] ability: Regenerator', '[silent]'); } },"]),
    ('ability', 'soundproof', False,
     ["onTryHit(target, source, move) { if (target !== source && move.flags['sound']) { "
      "this.add('-immune', target, '[from] ability: Soundproof'); return null; } },",
      'flags: { breakable: 1 },']),
    ('ability', 'unnerve', False,
     ['onSwitchInPriority: 1,',
      "onStart(pokemon) { if (this.effectState.unnerved) return; this.add('-ability', pokemon, 'Unnerve'); "
      "this.effectState.unnerved = true; },",
      'onEnd() { this.effectState.unnerved = false; },',
      'onFoeTryEatItem() { return !this.effectState.unnerved; },', 'flags: {},']),
    ('ability', 'speedboost', False,
     ['onResidualOrder: 28,', 'onResidualSubOrder: 2,', 'onResidual(pokemon) { if (pokemon.activeTurns) { this.boost({ spe: 1 }); } },',
      'flags: {},']),
    ('item', 'ejectbutton', True,
     ["onAfterMoveSecondary(target, source, move) { if (source && source !== target && target.hp && move && "
      "move.category !== 'Status' && !move.flags['futuremove']) { if (!this.canSwitch(target.side) || target.forceSwitchFlag || "
      "target.beingCalledBack || target.isSkyDropped()) return; if (target.volatiles['commanding'] || "
      "target.volatiles['commanded']) return; for (const pokemon of this.getAllActive()) { "
      "if (pokemon.switchFlag === true) return; } target.switchFlag = true; if (!target.useItem()) { "
      "target.switchFlag = false; } } },"]),
)
# Rain Dance and Sunny Day (data/conditions.ts, as Sandstorm and Snowscape): the duration (5; 8 with the rock item, which is
# UNMODELED and so never held), the start line without a source, the upkeep and the end line.
G32_WEATHER_FACTS = (
    ('raindance', ['duration: 5,', "if (source?.hasItem('damprock')) { return 8; } return 5;",
                   "onFieldStart(field, source, effect) { if (effect?.effectType === 'Ability') { if (this.gen <= 5) "
                   "this.effectState.duration = 0; this.add('-weather', 'RainDance', '[from] ability: ' + effect.name, `[of] ${source}`); } "
                   "else { this.add('-weather', 'RainDance'); } },", 'onFieldResidualOrder: 1,',
                   "this.add('-weather', 'RainDance', '[upkeep]'); this.eachEvent('Weather');",
                   "this.add('-weather', 'none');"]),
    ('sunnyday', ['duration: 5,', "if (source?.hasItem('heatrock')) { return 8; } return 5;",
                  "onFieldStart(battle, source, effect) { if (effect?.effectType === 'Ability') { if (this.gen <= 5) "
                  "this.effectState.duration = 0; this.add('-weather', 'SunnyDay', '[from] ability: ' + effect.name, `[of] ${source}`); } "
                  "else { this.add('-weather', 'SunnyDay'); } },", 'onFieldResidualOrder: 1,',
                  "this.add('-weather', 'SunnyDay', '[upkeep]'); this.eachEvent('Weather');",
                  "this.add('-weather', 'none');",
                  "onImmunity(type, pokemon) { if (pokemon.effectiveWeather() !== 'sunnyday') return; if (type === 'frz') return false; },"]),
)
# Step G55 (the duration rows): the terrain durations of Grassy Terrain and Psychic Terrain (data/moves.ts:7673-7691 and
# :14095-14113; Electric and Misty are G25_FACTS), which read Terrain Extender through their durationCallback. The engine
# hard-codes the callback's 8 and 5 (dfi_field_start_turns); the five rock items are read by id (ENGINE_ROWS) and have no
# callback of their own, and the weather rows (Damp, Heat, Smooth and Icy Rock) are WEATHER_FACTS and G32_WEATHER_FACTS.
G55_TERRAIN_DURATION = "durationCallback(source, effect) { if (source?.hasItem('terrainextender')) { return 8; } return 5; },"
G55_FACTS = (
    ('grassyterrain', [G55_TERRAIN_DURATION, 'duration: 5,']),
    ('psychicterrain', [G55_TERRAIN_DURATION, 'duration: 5,']),
)
# Step G31: Taunt (data/moves.ts:18974-19016) and Yawn (:21131-21162) are handlers of their own that the turn code implements
# (a condition whose state is the tail's taunt_turns / yawn_turns). The Champions mod changes neither. The generator checks
# the whole condition text of both and Yawn's onTryHit, whitespace aside: Taunt's duration 3 (4 when the target has been out
# for a turn and has no move queued), order 15, onBeforeMove priority 5 and the Status-category bar; Yawn's duration 2,
# order 23 and the silent end that calls trySetStatus('slp').
G31_HANDLERS = ['TAUNT', 'YAWN']
# Step G60 (decision 0032): Substitute (data/moves.ts:18305-18374). The turn code implements the move: the gate of each hit
# that a Substitute takes (the pin's onTryPrimaryHit), the HP cost, the break and the events of the decision. The generator
# checks the three texts, whitespace aside. Its bypasssub flag is bit 4 of the third flags byte (FLAGS3_BITS).
G60_HANDLERS = ['SUBSTITUTE']
# Step G70 (Skill Swap, decision 0041; data/moves.ts:16590-16606): the handler swaps the two holders' abilities.
G70_HANDLERS = ['SKILL_SWAP']
SKILL_SWAP_ONHIT = "onHit(target, source, move) { return this.skillSwap(source, target); },"
# Step G74: Baton Pass (decision 0042). Its onHit (data/moves.ts:1097-1103) fails with [still] when the target side cannot
# switch or the target is commanded; its self block (1108-1111) skips the BeforeSwitchOut of the switch that follows.
# selfSwitch 'copyvolatile' (1113) is the pivot of the row (ENGINE_PIVOT_MOVES, dfi_pivot_moves).
G74_HANDLERS = ['BATON_PASS']
BATON_PASS_ONHIT = ("onHit(target) { if (!this.canSwitch(target.side) || target.volatiles['commanded']) { "
                    "this.attrLastMove('[still]'); this.add('-fail', target); return this.NOT_FAIL; } },")
BATON_PASS_SELF = "self: { onHit(source) { source.skipBeforeSwitchOutEventFlag = true; }, },"
SUBSTITUTE_ONTRYHIT = (
    "onTryHit(source) { if (source.volatiles['substitute']) { this.add('-fail', source, 'move: Substitute'); "
    "return this.NOT_FAIL; } if (source.hp <= source.maxhp / 4 || source.maxhp === 1) { // Shedinja clause "
    "this.add('-fail', source, 'move: Substitute', '[weak]'); return this.NOT_FAIL; } },")
SUBSTITUTE_ONHIT = "onHit(target) { this.directDamage(target.maxhp / 4); },"
SUBSTITUTE_CONDITION = (
    "condition: { onStart(target, source, effect) { if (effect?.id === 'shedtail') { "
    "this.add('-start', target, 'Substitute', '[from] move: Shed Tail'); } else { this.add('-start', target, 'Substitute'); } "
    "this.effectState.hp = Math.floor(target.maxhp / 4); if (target.volatiles['partiallytrapped']) { "
    "this.add('-end', target, target.volatiles['partiallytrapped'].sourceEffect, '[partiallytrapped]', '[silent]'); "
    "delete target.volatiles['partiallytrapped']; } }, onTryPrimaryHitPriority: -1, onTryPrimaryHit(target, source, move) { "
    "if (target === source || move.flags['bypasssub'] || move.infiltrates) { return; } let damage = "
    "this.actions.getDamage(source, target, move); if (!damage && damage !== 0) { this.add('-fail', source); "
    "this.attrLastMove('[still]'); return null; } if (damage > target.volatiles['substitute'].hp) { "
    "damage = target.volatiles['substitute'].hp as number; } target.volatiles['substitute'].hp -= damage; "
    "source.lastDamage = damage; if (target.volatiles['substitute'].hp <= 0) { if (move.ohko) this.add('-ohko'); "
    "target.removeVolatile('substitute'); } else { this.add('-activate', target, 'move: Substitute', '[damage]'); } "
    "if (damage) { this.actions.applyRecoilDamage(damage, move, source); } if (move.drain) { "
    "this.heal(Math.ceil(damage * move.drain[0] / move.drain[1]), source, target, 'drain'); } "
    "this.singleEvent('AfterSubDamage', move, null, target, source, move, damage); "
    "this.runEvent('AfterSubDamage', target, source, move, damage); return this.HIT_SUBSTITUTE; }, "
    "onEnd(target) { this.add('-end', target, 'Substitute'); }, },")
# Step G52 (decision 0025 item 6): Revival Blessing (data/moves.ts:15110-15136). onTryHit fails when the user's side has no fainted
# Pokemon; selfSwitch and the slot condition make the user's slot a revive at its PIVOT (sim/side.ts 925-985, sim/battle.ts
# 2781-2797). The turn code implements the move (DFI_SWITCH_REVIVE_BLESSING and the revive action); the generator checks onTryHit.
G52_HANDLERS = ['REVIVAL_BLESSING']
REVIVAL_BLESSING_ONTRYHIT = "onTryHit(source) { if (!source.side.pokemon.filter(ally => ally.fainted).length) { return false; } },"
REVIVAL_BLESSING_CONDITION = "condition: { duration: 1, // reviving implemented in side.ts, kind of },"
# Step G50 (decision 0025 items 1 and 2): Double Shock. Its onTryMove fails without the Electric type (data/moves.ts:3954-3959);
# its self onHit sets the type ??? in place of Electric and shows -start|X|typechange|???/Fighting (data/moves.ts:3960-3964). The
# Champions mod adds the punch flag (its flags column) and nothing else. The self text is owned by the handler (G2_OWNED_FIELDS),
# whole, so a change at the pin fails the generator.
G50_HANDLERS = ['DOUBLE_SHOCK']
TAUNT_CONDITION = (
    "condition: { duration: 3, onStart(target) { if (target.activeTurns && !this.queue.willMove(target)) { "
    "this.effectState.duration!++; } this.add('-start', target, 'move: Taunt'); }, onResidualOrder: 15, onEnd(target) { "
    "this.add('-end', target, 'move: Taunt'); }, onDisableMove(pokemon) { for (const moveSlot of pokemon.moveSlots) { "
    "const move = this.dex.moves.get(moveSlot.id); if (move.category === 'Status' && move.id !== 'mefirst') { "
    "pokemon.disableMove(moveSlot.id); } } }, onBeforeMovePriority: 5, onBeforeMove(attacker, defender, move) { "
    "if (!(move.isZ && move.isZOrMaxPowered) && move.category === 'Status' && move.id !== 'mefirst') { "
    "this.add('cant', attacker, 'move: Taunt', move); return false; } }, },")
YAWN_ONTRYHIT = "onTryHit(target) { if (target.status || !target.runStatusImmunity('slp')) { return false; } },"
YAWN_CONDITION = (
    "condition: { noCopy: true, // doesn't get copied by Baton Pass duration: 2, onStart(target, source) { "
    "this.add('-start', target, 'move: Yawn', `[of] ${source}`); }, onResidualOrder: 23, onEnd(target) { "
    "this.add('-end', target, 'move: Yawn', '[silent]'); target.trySetStatus('slp', this.effectState.source); }, },")
# Step G42: Roost (data/moves.ts:15428-15463) heals the user (the heal column, the heal flag) and then, through its self
# volatile, takes the Flying type off until the residual of order 25; its condition is the handler ROOST (the tail's
# single_turn bit). Stomping Tantrum's basePowerCallback doubles its power when the user's last move result is `false`.
# The generator checks both texts, whitespace aside.
G42_HANDLERS = ['ROOST', 'STOMPING_TANTRUM']
ROOST_SELF = "self: { volatileStatus: 'roost', },"
ROOST_CONDITION = (
    "condition: { duration: 1, onResidualOrder: 25, onStart(target) { if (target.terastallized) { "
    "if (target.hasType('Flying')) { this.add('-hint', \"If a Terastallized Pokemon uses Roost, it remains Flying-type.\"); } "
    "return false; } this.add('-singleturn', target, 'move: Roost'); }, onTypePriority: -1, "
    "onType(types, pokemon) { this.effectState.typeWas = types; return types.filter(type => type !== 'Flying'); }, },")
# Step K1 (#476, entry 5dc): Temper Flare (data/moves.ts:19185-19203) has the same callback as Stomping Tantrum, with its own debug text, so the
# handler serves both moves and the pinned text is checked per move (the debug line is the one difference).
STOMPING_TANTRUM_CALLBACKS = {
    'stompingtantrum': {
        'basePowerCallback': "basePowerCallback(pokemon, target, move) { if (pokemon.moveLastTurnResult === false) { "
                             "this.debug('doubling Stomping Tantrum BP due to previous move failure'); "
                             "return move.basePower * 2; } return move.basePower; },",
    },
    'temperflare': {
        'basePowerCallback': "basePowerCallback(pokemon, target, move) { if (pokemon.moveLastTurnResult === false) { "
                             "this.debug('doubling Temper Flare BP due to previous move failure'); "
                             "return move.basePower * 2; } return move.basePower; },",
    },
}

# Step G25 (Electric Terrain, Misty Terrain): the two terrain moves keep their `terrain` field and their condition as handlers of
# their own that the turn code implements (setTerrain, then the terrain's rules in the damage chain and in SetStatus and
# TryAddVolatile), and Rising Voltage and Terrain Pulse keep the callback that reads the terrain (base power; type and
# base power). Their texts are G25_FACTS, read from the pin, because the engine hard-codes them.
G25_HANDLERS = ['ELECTRIC_TERRAIN', 'MISTY_TERRAIN', 'RISING_VOLTAGE', 'TERRAIN_PULSE']

# Step G29: the item-transfer moves. Trick and Switcheroo (status, onTryImmunity and onHit), Thief and Covet (damaging, onAfterHit)
# keep their callbacks as handlers of their own that the turn code implements (rows of the whole pool). The generator checks the
# whole text of each callback, whitespace aside (data/moves.ts:19865-19911, :18644-18690, :19302-19330, :3099-3123; the Champions
# mod changes none): the Sticky Hold test of Trick's target, the TakeItem checks (a Mega Stone refuses the species it belongs to), the
# order of the takes and sets, and the lines that the converter reads (-activate move: Trick, -item and the silent -enditem, with
# [from] move: and, for Thief and Covet, [of]).
G29_HANDLERS = ['TRICK', 'SWITCHEROO', 'THIEF', 'COVET']
G29_CALLBACKS = {
    'TRICK': {
        'onTryImmunity': "onTryImmunity(target) { return !target.hasAbility('stickyhold'); },",
        'onHit': "onHit(target, source, move) { const yourItem = target.takeItem(source); const myItem = source.takeItem(); if (yourItem === false || myItem === false || (!yourItem && !myItem)) { if (yourItem) target.item = yourItem.id; if (myItem) source.item = myItem.id; return false; } if ( (myItem && !this.singleEvent('TakeItem', myItem, source.itemState, target, source, move, myItem)) || (yourItem && !this.singleEvent('TakeItem', yourItem, target.itemState, source, target, move, yourItem)) ) { if (yourItem) target.item = yourItem.id; if (myItem) source.item = myItem.id; return false; } this.add('-activate', source, 'move: Trick', `[of] ${target}`); if (myItem) { target.setItem(myItem); this.add('-item', target, myItem, '[from] move: Trick'); } else { this.add('-enditem', target, yourItem, '[silent]', '[from] move: Trick'); } if (yourItem) { source.setItem(yourItem); this.add('-item', source, yourItem, '[from] move: Trick'); } else { this.add('-enditem', source, myItem, '[silent]', '[from] move: Trick'); } },",
    },
    'SWITCHEROO': {
        'onTryImmunity': "onTryImmunity(target) { return !target.hasAbility('stickyhold'); },",
        'onHit': "onHit(target, source, move) { const yourItem = target.takeItem(source); const myItem = source.takeItem(); if (yourItem === false || myItem === false || (!yourItem && !myItem)) { if (yourItem) target.item = yourItem.id; if (myItem) source.item = myItem.id; return false; } if ( (myItem && !this.singleEvent('TakeItem', myItem, source.itemState, target, source, move, myItem)) || (yourItem && !this.singleEvent('TakeItem', yourItem, target.itemState, source, target, move, yourItem)) ) { if (yourItem) target.item = yourItem.id; if (myItem) source.item = myItem.id; return false; } this.add('-activate', source, 'move: Trick', `[of] ${target}`); if (myItem) { target.setItem(myItem); this.add('-item', target, myItem, '[from] move: Switcheroo'); } else { this.add('-enditem', target, yourItem, '[silent]', '[from] move: Switcheroo'); } if (yourItem) { source.setItem(yourItem); this.add('-item', source, yourItem, '[from] move: Switcheroo'); } else { this.add('-enditem', source, myItem, '[silent]', '[from] move: Switcheroo'); } },",
    },
    'THIEF': {
        'onAfterHit': "onAfterHit(target, source, move) { if (source.item || source.volatiles['gem']) { return; } const yourItem = target.takeItem(source); if (!yourItem) { return; } if (!this.singleEvent('TakeItem', yourItem, target.itemState, source, target, move, yourItem) || !source.setItem(yourItem)) { target.item = yourItem.id; // bypass setItem so we don't break choicelock or anything return; } this.add('-enditem', target, yourItem, '[silent]', '[from] move: Thief', `[of] ${source}`); this.add('-item', source, yourItem, '[from] move: Thief', `[of] ${target}`); },",
    },
    'COVET': {
        'onAfterHit': "onAfterHit(target, source, move) { if (source.item || source.volatiles['gem']) { return; } const yourItem = target.takeItem(source); if (!yourItem) { return; } if ( !this.singleEvent('TakeItem', yourItem, target.itemState, source, target, move, yourItem) || !source.setItem(yourItem) ) { target.item = yourItem.id; // bypass setItem so we don't break choicelock or anything return; } this.add('-item', source, yourItem, '[from] move: Covet', `[of] ${target}`); },",
    },
}
AURORA_VEIL_ONTRY = "onTry() { return this.field.isWeather(['hail', 'snowscape']); },"
# Step G26: Perish Song keeps its onHitField and its condition as a handler of its own that the turn code implements: every
# active Pokemon without the volatile gets it with a duration of 4, the residual (order 24) shows the count and the end
# shows perish0 and faints the holder (data/moves.ts:13233-13277). The generator checks both texts, whitespace aside.
G26_HANDLERS = ['PERISH_SONG']
PERISH_SONG_HIT_FIELD = ("onHitField(target, source, move) { let result = false; let message = false; "
                         "for (const pokemon of this.getAllActive()) { "
                         "if (this.runEvent('Invulnerability', pokemon, source, move) === false) { "
                         "this.add('-miss', source, pokemon); result = true; } "
                         "else if (this.runEvent('TryHit', pokemon, source, move) === null) { result = true; } "
                         "else if (!pokemon.volatiles['perishsong']) { pokemon.addVolatile('perishsong'); "
                         "this.add('-start', pokemon, 'perish3', '[silent]'); result = true; message = true; } } "
                         "if (!result) return false; if (message) this.add('-fieldactivate', 'move: Perish Song'); },")
PERISH_SONG_CONDITION = ("condition: { duration: 4, onEnd(target) { this.add('-start', target, 'perish0'); target.faint(); }, "
                         "onResidualOrder: 24, onResidual(pokemon) { const duration = pokemon.volatiles['perishsong'].duration; "
                         "this.add('-start', pokemon, `perish${duration}`); }, },")
KNOCK_OFF_CALLBACKS = {
    'onBasePower': "onBasePower(basePower, source, target, move) { const item = target.getItem(); "
                   "if (!this.singleEvent('TakeItem', item, target.itemState, target, target, move, item)) return; "
                   "if (item.id) { return this.chainModify(1.5); } },",
    'onAfterHit': "onAfterHit(target, source) { const item = target.takeItem(); if (item) { "
                  "this.add('-enditem', target, item.name, '[from] move: Knock Off', `[of] ${source}`); } },",
}
# Step G15 (Psychic Terrain): Expanding Force has a handler of its own, because its two callbacks change the move's
# base power and its target class and no column holds either; the turn code implements it, and the row is marked.
G15_HANDLERS = ['EXPANDING_FORCE']
# Step G30: Rage Powder, Psychic Fangs and Solar Beam keep what the columns cannot hold as handlers of their own that the turn
# code implements (rows of the whole pool, like Knock Off). Rage Powder is Follow Me's redirection with the powder immunity of
# its user's foes (data/moves.ts:14598-14630); Psychic Fangs breaks the screens before the hit (14060-14078); Solar Beam is a
# two-turn move that sun skips and rain, sand and snow halve (17224-17258). The generator checks the whole text of each callback
# and of the condition, whitespace aside; the Champions mod changes none of them.
G30_HANDLERS = ['RAGE_POWDER', 'PSYCHIC_FANGS', 'SOLAR_BEAM']
RAGE_POWDER_ONTRY = "onTry(source) { return this.activePerHalf > 1; },"
RAGE_POWDER_CONDITION = ("condition: { duration: 1, onStart(pokemon) { this.add('-singleturn', pokemon, 'move: Rage Powder'); }, "
                         "onFoeRedirectTargetPriority: 1, onFoeRedirectTarget(target, source, source2, move) { "
                         "const ragePowderUser = this.effectState.target; if (ragePowderUser.isSkyDropped()) return; "
                         "if (source.runStatusImmunity('powder') && this.validTarget(ragePowderUser, source, move.target)) { "
                         "if (move.smartTarget) move.smartTarget = false; this.debug(\"Rage Powder redirected target of move\"); "
                         "return ragePowderUser; } }, },")
PSYCHIC_FANGS_ONTRYHIT = ("onTryHit(pokemon) { // will shatter screens through sub, before you hit pokemon.side.removeSideCondition('reflect'); "
                          "pokemon.side.removeSideCondition('lightscreen'); pokemon.side.removeSideCondition('auroraveil'); },")
SOLAR_BEAM_CALLBACKS = {
    'onTryMove': "onTryMove(attacker, defender, move) { if (attacker.removeVolatile(move.id)) { return; } "
                 "this.add('-prepare', attacker, move.name); "
                 "if (['sunnyday', 'desolateland'].includes(attacker.effectiveWeather(undefined, true))) { "
                 "this.attrLastMove('[still]'); this.addMove('-anim', attacker, move.name, defender); return; } "
                 "if (!this.runEvent('ChargeMove', attacker, defender, move)) { return; } "
                 "attacker.addVolatile('twoturnmove', defender); return null; },",
    'onBasePower': "onBasePower(basePower, pokemon, target) { "
                   "const weakWeathers = ['raindance', 'primordialsea', 'sandstorm', 'hail', 'snowscape']; "
                   "if (weakWeathers.includes(pokemon.effectiveWeather())) { this.debug('weakened by weather'); "
                   "return this.chainModify(0.5); } },",
}
SPECIAL_P = dict(SPECIAL_C, **{
    'perishsong': ('PERISH_SONG', {'onHitField'}),                        # G26: a volatile on every active Pokemon, faints at 0
    'glaiverush': ('GLAIVE_RUSH', set()),                                 # G19: the volatile that makes its user hit as vulnerable
    'destinybond': ('DESTINY_BOND', {'onPrepareHit'}),                    # G76: the user's volatile; a foe's KO is answered with its own faint
    'finalgambit': ('FINAL_GAMBIT', {'damageCallback'}),                  # G76: damage equal to the user's HP, and the user faints
    'outrage': ('LOCKED_MOVE', set()),                                    # G56: a two-to-three turn lock, then confusion
    'thrash': ('LOCKED_MOVE', set()),                                     # G56: the same lock as Outrage
    'petaldance': ('LOCKED_MOVE', set()),                                 # G56: the same lock as Outrage
    'ragingfury': ('LOCKED_MOVE', set()),                                 # A0 part 3: the same lock as Outrage (flags protect, mirror)
    'knockoff': ('KNOCK_OFF', {'onAfterHit', 'onBasePower'}),             # G16: takes the target's item, x1.5 while it has one
    'encore': ('ENCORE', set()),                                          # G9 (implemented): last move, a volatile, a queue change
    'disable': ('DISABLE', {'onTryHit'}),                                 # G27: bars the target's last move
    'spikyshield': ('SPIKY_SHIELD', {'onPrepareHit', 'onHit'}),           # G20: Protect that damages a contact attacker
    'banefulbunker': ('BANEFUL_BUNKER', {'onPrepareHit', 'onHit'}),       # G94: Protect that poisons a contact attacker
    'kingsshield': ('KINGS_SHIELD', {'onPrepareHit', 'onHit'}),           # G66: Protect that passes Status moves and lowers a contact attacker's Attack
    'taunt': ('TAUNT', set()),                                            # G31: bars the Status moves for three or four turns
    'substitute': ('SUBSTITUTE', {'onTryHit', 'onHit'}),                  # G60: a 1/4 HP decoy that takes the hits (decision 0032)
    'skillswap': ('SKILL_SWAP', {'onHit'}),                               # G70: swaps the two abilities (decision 0041)
    'batonpass': ('BATON_PASS', {'onHit'}),                               # G74: switches the user out and copies its volatiles (decision 0042)
    'yawn': ('YAWN', {'onTryHit'}),                                       # G31: sleep at the end of the next turn
    'revivalblessing': ('REVIVAL_BLESSING', {'onTryHit'}),                # G52: the revive at the PIVOT of the user's slot
    'leechseed': ('LEECH_SEED', {'onTryImmunity'}),                       # G84 (decision 0047): the seed; its drain is a residual
    'curse': ('CURSE', {'onModifyMove', 'onTryHit', 'onHit'}),            # G84: non-Ghost boosts; a Ghost Curse is refused explicitly
    'healingwish': ('HEALING_WISH', {'onTryHit'}),                        # G82 (decision 0045): the user's slot condition; the user faints
    'roost': ('ROOST', set()),                                            # G42: heals, then the Flying type is off for the turn
    'stompingtantrum': ('STOMPING_TANTRUM', {'basePowerCallback'}),        # G42: base power x2 after a failed last move
    'temperflare': ('STOMPING_TANTRUM', {'basePowerCallback'}),            # K1 (#476): the same callback, its own debug text
    'auroraveil': ('AURORA_VEIL', {'onTry'}),                             # G20: a screen against both categories, in snow only
    'trick': ('TRICK', {'onTryImmunity', 'onHit'}),                         # G29: swaps the two items
    'switcheroo': ('SWITCHEROO', {'onTryImmunity', 'onHit'}),               # G29: Trick's text with its own name in the lines
    'thief': ('THIEF', {'onAfterHit'}),                                    # G29: takes the target's item after the hit
    'covet': ('COVET', {'onAfterHit'}),                                    # G29: the same without the silent -enditem line
    'wideguard': ('WIDE_GUARD', {'onTry', 'onHitSide'}),                 # G7: a side condition against spread moves
    'firstimpression': ('FIRST_IMPRESSION', {'onTry', 'onDisableMove'}),  # G10a: first turn out only (Fake Out's rule)
    'soak': ('SOAK', {'onHit'}),                                          # G11: sets the target's type to Water
    'lowkick': ('LOW_KICK', {'basePowerCallback', 'onTryHit'}),           # G10d: base power by the target's weight
    'sandstorm': ('SANDSTORM', set()),                                    # weather: sets the weather (for 5 turns)
    'snowscape': ('SNOWSCAPE', set()),
    'expandingforce': ('EXPANDING_FORCE', {'onBasePower', 'onModifyMove'}),  # G15: x1.5 and a spread in Psychic Terrain
    'shellsmash': ('SHELL_SMASH', set()),                                 # G28: its boosts apply in the pin's order
    'acrobatics': ('ACROBATICS', {'basePowerCallback'}),                  # G28: doubled without an item
    'blizzard': ('BLIZZARD', {'onModifyMove'}),                           # G28: never misses in snow
    'feint': ('FEINT', set()),                                            # G28: breaks Protect and Wide Guard
    'ragepowder': ('RAGE_POWDER', {'onTry'}),                              # G30: Follow Me for the foes that are not powder immune
    'psychicfangs': ('PSYCHIC_FANGS', {'onTryHit'}),                       # G30: the screens go before the hit
    'solarbeam': ('SOLAR_BEAM', {'onBasePower', 'onTryMove'}),             # G30: a two-turn move that sun skips, x0.5 in rain, sand, snow
    'solarblade': ('SOLAR_BEAM', {'onBasePower', 'onTryMove'}),           # A0 part 3: the same two callbacks (SOLAR_BEAM_CALLBACKS), physical, 125
    'steelroller': ('STEEL_ROLLER', {'onTry', 'onHit', 'onAfterSubDamage'}),  # G34: fails without a terrain and ends it
    'clangoroussoul': ('CLANGOROUS_SOUL', {'onTry', 'onTryHit', 'onHit'}),    # G34: a third of the HP for five boosts
    'brickbreak': ('BRICK_BREAK', {'onTryHit'}),
    'imprison': ('IMPRISON', set()),                                      # G38: the foes may not use the moves it knows                          # G34: the screens go before the hit
    'eruption': ('HP_POWER', {'basePowerCallback'}),                      # G32: power by the user's HP
    'waterspout': ('HP_POWER', {'basePowerCallback'}),
    'bodypress': ('BODY_PRESS', set()),                                   # G32: the Defense stat attacks
    'foulplay': ('FOUL_PLAY', set()),                                     # G32: the target's Attack and stages
    'psyshock': ('PSYSHOCK', set()),                                      # G32: a special hit at the Defense stat
    'raindance': ('RAIN_DANCE', set()),                                   # G32: weather moves
    'sunnyday': ('SUNNY_DAY', set()),
    'freezedry': ('FREEZE_DRY', {'onEffectiveness'}),                     # G32: Water takes it super effective
    'clangingscales': ('CLANGING_SCALES', set()),                         # G32: the user's Defense falls after a hit
    'electricterrain': ('ELECTRIC_TERRAIN', set()),                       # G25: sets the terrain (5 turns)
    'mistyterrain': ('MISTY_TERRAIN', set()),
    'risingvoltage': ('RISING_VOLTAGE', {'basePowerCallback'}),           # G25: doubled at a grounded target in Electric Terrain
    'terrainpulse': ('TERRAIN_PULSE', {'onModifyType', 'onModifyMove'}),  # G25: the terrain's type, doubled for a grounded user
    'dualwingbeat': ('MULTI_HIT_2', set()),                               # G33: two hits
    'doublehit': ('MULTI_HIT_2', set()),                                  # A0 part 3: two hits (the fixed count 2)
    'twinbeam': ('MULTI_HIT_2', set()),
    'tripleaxel': ('TRIPLE_AXEL', {'basePowerCallback'}),                 # G33: three hits, a check for each, 20 x the hit
    'sacredsword': ('DARKEST_LARIAT', set()),                             # G39: Darkest Lariat's ignoreDefensive and ignoreEvasion
    'superfang': ('SUPER_FANG', {'damageCallback'}),                      # G39: half the target's current HP
    'powertrip': ('POWER_TRIP', {'basePowerCallback'}),                   # G44: 20 plus 20 per positive stage of the user
    'thunder': ('THUNDER', {'onModifyMove'}),                             # G44: never misses in rain, 50 under sun (as Hurricane)
    'icefang': ('ICE_FANG', set()),                                       # G44: a 10 percent freeze, then a 10 percent flinch (G2_OWNED_FIELDS)
    'triattack': ('TRI_ATTACK', set()),
    'iciclespear': ('MULTI_HIT_2_5', set()),                              # G54: 2 to 5 hits, a weighted draw (SITE_MULTIHIT_COUNT)
    'tailslap': ('MULTI_HIT_2_5', set()),                                 # A0 part 3: 2 to 5 hits, the same draw
    'bonerush': ('MULTI_HIT_2_5', set()),                                 # A0 part 3: the same draw; Champions basePower 30 (merged)
    # Step A0 (decision 0015, batch A0 part 1): the moves whose one unmodelled feature a handler already runs. Each is checked by
    # check_a0p1_facts (the pinned fields, the callbacks and their texts, the legal pool guards) before it is marked.
    'storedpower': ('POWER_TRIP', {'basePowerCallback'}),                 # A0: 20 plus 20 per positive stage (Power Trip's text)
    'bulletseed': ('MULTI_HIT_2_5', set()),                               # A0: 2 to 5 hits, the Champions sample (as Icicle Spear)
    'rockblast': ('MULTI_HIT_2_5', set()),
    'pinmissile': ('MULTI_HIT_2_5', set()),
    'watershuriken': ('MULTI_HIT_2_5', {'basePowerCallback'}),            # A0: the Battle Bond callback, unreachable in the pool (checked)
    'heatcrash': ('HEAVY_SLAM', {'basePowerCallback', 'onTryHit'}),       # A0: Heavy Slam's callbacks, text-equal (checked)
    'scaleshot': ('SCALE_SHOT', set()),                                   # G54: 2 to 5 hits, then the user's Defense -1 and Speed +1
    'quickguard': ('QUICK_GUARD', {'onTry', 'onHitSide'}),                # G54: a side condition against the priority moves of the foes
    'upperhand': ('UPPER_HAND', {'onTry'}),                               # G54: a priority move against a target that moves first with one
    'healpulse': ('HEAL_PULSE', {'onHit'}),                               # G54: heals the target by half of its maximum HP
    'strengthsap': ('STRENGTH_SAP', {'onHit'}),                           # G54: heals the user by the target's Attack, then lowers it
    'beatup': ('BEAT_UP', {'basePowerCallback', 'onModifyMove'}),         # G64: one hit per eligible party member, its base Attack
    'bugbite': ('BUG_BITE', {'onHit'}),                                   # G64: takes the target's berry and eats it
    'poltergeist': ('POLTERGEIST', {'onTry', 'onTryHit'}),                # G64: fails without a target item; reveals it
    'sheercold': ('SHEER_COLD', set()),                                   # G64: an OHKO move (ohko 'Ice'), see G2_OWNED_FIELDS
    'stormthrow': ('WILL_CRIT', set()),                                   # C4: willCrit, the critical hit without a draw (sim/battle-actions.ts:1638)
    'flowertrick': ('WILL_CRIT', set()),                                  # C4: willCrit
    'frostbreath': ('WILL_CRIT', set()),                                  # C4: willCrit
    'endeavor': ('ENDEAVOR', {'damageCallback', 'onTryImmunity'}),       # C5 (5cy): damage = target HP - user HP; immune if user HP >= target HP
    'haze': ('HAZE', {'onHitField'}),                                     # G62: clears every boost of the standing actives (decision 0031)
    'afteryou': ('AFTER_YOU', {'onHit'}),                                 # G62: the target's queued move goes next (decision 0015 entry 5az)
    'quash': ('QUASH', {'onHit'}),                                        # G62: the target's queued move goes last
    'phantomforce': ('PHANTOM_FORCE', {'onTryMove'}),                     # G58: a two-turn move, semi-invulnerable on the charge turn; breaks Protect on a hit
                                   # G44: a 20 percent pick of burn, paralysis or freeze (G2_OWNED_SECONDARY)
    'ragefist': ('RAGE_FIST', {'basePowerCallback'}),                     # G48: 50 + 50 per hit the user took, at most 350
    'stoneaxe': ('STONE_AXE', {'onAfterHit', 'onAfterSubDamage'}),        # G48: Stealth Rock on the foe's side after a hit
    'ceaselessedge': ('CEASELESS_EDGE', {'onAfterHit', 'onAfterSubDamage'}),  # G48: a Spikes layer on the foe's side after a hit
    'populationbomb': ('MULTI_HIT_10', set()),
    'alluringvoice': ('ALLURING_VOICE', set()),                       # G72b: confusion when the target's stats were raised this turn
    'dragoncheer': ('DRAGON_CHEER', set()),    # G72b: the crit stage of its target (the ally), by its Dragon type at start
    'lashout': ('LASH_OUT', {'onBasePower'}),   # G88: 2x power when the user's stat fell this turn (position flag LOWERED, decision 0046)
    'assurance': ('ASSURANCE', {'basePowerCallback'}),  # G88: 2x power when the target was hurt this turn (position flag HURT)
    'psychup': ('PSYCH_UP', {'onHit'}),        # G80: the user takes the target's boosts, Focus Energy and Dragon Cheer (its copies are [silent])
    'allyswitch': ('ALLY_SWITCH', {'onHit', 'onPrepareHit'}),  # G80: swaps the user with its ally; the allyswitch volatile's counter
    'doubleshock': ('DOUBLE_SHOCK', {'onTryMove'}),                       # G50: fails without Electric; its self effect is owned                            # G48: ten hits, a check for each (multiaccuracy)
    'steelbeam': ('STEEL_BEAM', {'onMoveFail'}),                          # G68: mindBlownRecoil (half the maximum HP on a hit and in MoveFail)
    'thunderwave': ('THUNDER_WAVE', set()),                               # G68: ignoreImmunity false (Ground is immune to the Electric move)
    'dragondarts': ('DRAGON_DARTS', set()),                               # G78: two hits, the second on the partner (decision 0043)
    'heavyslam': ('HEAVY_SLAM', {'basePowerCallback', 'onTryHit'}),       # G86: base power by the user's and the target's weight
    'hardpress': ('HARD_PRESS', {'basePowerCallback'}),                   # G86: base power by the target's current HP
    'icespinner': ('ICE_SPINNER', {'onAfterHit', 'onAfterSubDamage'}),    # G86: clears the terrain after a hit (no onTry)
    'bellydrum': ('BELLY_DRUM', {'onHit'}),                               # G86: half the maximum HP for +6 Attack
    # Step G92 (decision 0062): the primary confusion of four moves (Swagger and Flatter boost first), the OHKO moves of
    # Sheer Cold's kind with ohko true, Memento's selfdestruct, Night Shade's damage 'level'.
    'confuseray': ('CONFUSE', set()),                                     # G92: volatileStatus confusion (G2_OWNED_FIELDS)
    'swagger': ('CONFUSE', set()),                                        # G92: boosts atk +2 to the target, then the confusion
    'flatter': ('CONFUSE', set()),                                        # G92: boosts spa +1 to the target, then the confusion
    'teeterdance': ('CONFUSE', set()),                                    # G92: allAdjacent, the confusion of each adjacent foe
    'fissure': ('OHKO', set()),                                           # G92: ohko true (no type immunity, level 50 vs 50)
    'guillotine': ('OHKO', set()),
    'horndrill': ('OHKO', set()),
    'memento': ('MEMENTO', set()),                                        # G92: target atk and spa -2, then the user faints
    'nightshade': ('LEVEL_DAMAGE', set()),                                # G92: damage 'level' (the user's level, no crit draw)
    # Step A0 (batch A0 part 2): the same handlers, owning the same pinned lines (damage 'level', volatileStatus 'confusion').
    'seismictoss': ('LEVEL_DAMAGE', set()),                               # A0: damage 'level' (the user's level, no crit draw)
    'sweetkiss': ('CONFUSE', set()),                                      # A0: the primary confusion of Confuse Ray's kind (reflectable)
    # G90 (decision 0060): the six moves that apply the volatile partiallytrapped (G2_OWNED_FIELDS owns the volatileStatus line)
    'bind': ('PARTIAL_TRAP', set()), 'wrap': ('PARTIAL_TRAP', set()), 'firespin': ('PARTIAL_TRAP', set()),
    'sandtomb': ('PARTIAL_TRAP', set()), 'infestation': ('PARTIAL_TRAP', set()),
    'snaptrap': ('PARTIAL_TRAP', set()),  # A0 part 3: the sixth move of decision 0060's table (the Champions type Steel is merged)
    'psychicterrain': ('PSYCHIC_TERRAIN', set()),                         # G96: sets the Psychic Terrain (5 turns, 8 with Terrain Extender)
    'speedswap': ('SPEED_SWAP', {'onHit'}),                               # K3 (decision 0015 5de): swaps the two Speed stats (stored, not staged)
})
# Step G13: Detect is Protect (data/moves.ts:3526-3547 against 13961-14005): the same handler (not one of the G2 handlers,
# so it is added to the pool's map only), and the generator checks that its stalling fields and both callbacks are,
# whitespace aside, the text of Protect's; its volatile 'protect' is Protect's condition, which lives on the Protect
# entry. The engine reads the special column, so the stall counter is shared (the pin's StallMove event is per Pokemon,
# not per move).
SPECIAL_POOL = dict(SPECIAL_P, detect=('PROTECT', {'onPrepareHit', 'onHit'}))
PROTECT_COPIES = {'detect': 'protect'}
PROTECT_COPY_FIELDS = ('onPrepareHit', 'onHit', 'stallingMove', 'volatileStatus', 'priority', 'accuracy', 'target')
# Step G44 (simple moves): four handlers, each a rule that the generic columns cannot hold. POWER_TRIP (basePowerCallback: 20 plus
# 20 per positive stage of the user, the pin's positiveBoosts), THUNDER (onModifyMove: never misses in rain, 50 under sun, as
# HURRICANE), ICE_FANG (two secondaries, a freeze roll then a flinch roll, each random(100) < 10) and TRI_ATTACK (a secondary
# of chance 20 whose onHit draws sample(['brn', 'par', 'frz']), the status pick of SITE_STATUS_PICK). G44_FACTS checks their texts.
G44_HANDLERS = ['POWER_TRIP', 'THUNDER', 'ICE_FANG', 'TRI_ATTACK']
# Step G56: Outrage, Thrash and Petal Dance: a self volatile lockedmove (data/conditions.ts:253-285). Its duration is 2
# and its count a random(2, 4) drawn in onStart; the countdown runs in onResidual; onAfterMove removes it at duration 1;
# onEnd adds confusion unless the count is above 1. The turn code runs these; the facts below are read from the pin.
G56_HANDLERS = ['LOCKED_MOVE']
G56_LOCKED_MOVES = ('outrage', 'thrash', 'petaldance', 'ragingfury')
LOCKED_MOVE_CONDITION_FACTS = (
    'duration: 2,',
    'this.effectState.trueDuration = this.random(2, 4);',
    'this.effectState.move = effect.id;',
    'this.effectState.trueDuration--;',
    "if (this.effectState.duration === 1) { pokemon.removeVolatile('lockedmove'); }",
    'if (this.effectState.trueDuration > 1) return;',
    "target.addVolatile('confusion');",
    "delete target.volatiles['lockedmove'];",
    'if (this.effectState.trueDuration >= 2) { this.effectState.duration = 2; }',
    'if (this.effectState.duration === 1) {',
)
LOCKED_MOVE_MOVE_FACTS = {
    'outrage': ('basePower: 120,', 'accuracy: 100,', 'category: "Physical",', 'target: "randomNormal",', 'type: "Dragon",'),
    'thrash': ('basePower: 120,', 'accuracy: 100,', 'category: "Physical",', 'target: "randomNormal",', 'type: "Normal",'),
    'petaldance': ('basePower: 120,', 'accuracy: 100,', 'category: "Special",', 'target: "randomNormal",', 'type: "Grass",'),
    'ragingfury': ('basePower: 120,', 'accuracy: 100,', 'category: "Physical",', 'target: "randomNormal",', 'type: "Fire",'),
}
G44_FACTS = (
    ('powertrip', ['accuracy: 100,', 'basePower: 20,',
                   'basePowerCallback(pokemon, target, move) { const bp = move.basePower + 20 * pokemon.positiveBoosts();',
                   'category: "Physical",', 'priority: 0,', 'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },',
                   'target: "normal",', 'type: "Dark",']),
    ('thunder', ['accuracy: 70,', 'basePower: 110,', 'category: "Special",', 'priority: 0,',
                 'flags: { protect: 1, mirror: 1, metronome: 1 },', 'switch (target?.effectiveWeather()) {',
                 "case 'raindance':", "case 'primordialsea':", 'move.accuracy = true;', "case 'sunnyday':",
                 "case 'desolateland':", 'move.accuracy = 50;', 'chance: 30,', "status: 'par',", 'target: "normal",',
                 'type: "Electric",']),
    ('icefang', ['accuracy: 95,', 'basePower: 65,', 'category: "Physical",', 'priority: 0,',
                 'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1, bite: 1 },', 'target: "normal",', 'type: "Ice",']),
    ('triattack', ['accuracy: 100,', 'basePower: 80,', 'category: "Special",', 'priority: 0,',
                   'flags: { protect: 1, mirror: 1, metronome: 1 },', 'target: "normal",', 'type: "Normal",']),
)
# Step G54 (multi-hit 2 to 5, Quick Guard, Upper Hand, Heal Pulse, Strength Sap, Steel Beam, Final Gambit). MULTI_HIT_2_5 (Icicle
# Spear: `multihit: [2, 5]`, the Champions sample of the hit count, SITE_MULTIHIT_COUNT) and SCALE_SHOT (the same, then the
# user's `selfBoost`); QUICK_GUARD (Wide Guard's side condition, priority 4 against positive priority); UPPER_HAND (Sucker
# Punch's queue read with the priority test); HEAL_PULSE and STRENGTH_SAP (the heals of the target and the user); STEEL_BEAM
# (mindBlownRecoil: the recoil of half the maximum HP, after a hit and in MoveFail); FINAL_GAMBIT (damage = the user's HP).
G54_HANDLERS = ['MULTI_HIT_2_5', 'SCALE_SHOT', 'QUICK_GUARD', 'UPPER_HAND', 'HEAL_PULSE', 'STRENGTH_SAP']
# Step G58, Phantom Force (data/moves.ts:13307-13335; the Champions mod has no entry). The charge is the two-turn move of
# Electro Shot and Solar Beam (twoturnmove, -prepare on the charge turn), and the user is semi-invulnerable through its
# volatile phantomforce (duration 2, onInvulnerability false: every move that targets it misses). The move has no protect
# flag, so Protect does not stop it; its breaksProtect removes the target's protections after the accuracy check.
G58_HANDLERS = ['PHANTOM_FORCE']
# Step G66, King's Shield (data/moves.ts:9905-9955; Champions: pp 5 only, data/mods/champions/moves.ts:564-568): the Protect
# variant with -1 Attack on a contact attacker and no block of a Status move (checkMoveBypassesProtect with blockStatus false).
G66_HANDLERS = ['KINGS_SHIELD']
# Step G72b (decision 0015 5ce, lead's approval): Alluring Voice's secondary (confusion when the target's stats were raised this
# turn: the position flag of tail rev 5) and Dragon Cheer's volatile (the crit stage in the position flags).
G72B_HANDLERS = ['ALLURING_VOICE', 'DRAGON_CHEER']
# Step G88 (decision 0046): Lash Out's onBasePower (data/moves.ts:10048-10066) and Assurance's basePowerCallback
# (data/moves.ts:643-660). Both read a turn-history position flag (LOWERED, HURT); the flags are set and cleared by the engine.
G88_HANDLERS = ['LASH_OUT', 'ASSURANCE']
G88_FACTS = {
    'assurance': (
        'accuracy: 100,', 'basePower: 60,', 'category: "Physical",', 'priority: 0,',
        'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },', 'if (target.hurtThisTurn) {',
        'return move.basePower * 2;', 'target: "normal",', 'type: "Dark",',
    ),
    'lashout': (
        'accuracy: 100,', 'basePower: 75,', 'category: "Physical",', 'priority: 0,',
        'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },', 'onBasePower(basePower, source) {',
        'if (source.statsLoweredThisTurn) {', 'return this.chainModify(2);', 'target: "normal",', 'type: "Dark",',
    ),
}
G72B_FACTS = (
    'accuracy: 100,', 'basePower: 80,', 'category: "Special",', 'priority: 0,',
    'flags: { protect: 1, mirror: 1, sound: 1, bypasssub: 1, metronome: 1 },', 'chance: 100,',
    'if (target?.statsRaisedThisTurn) {', "target.addVolatile('confusion', source, move);", 'target: "normal",', 'type: "Fairy",',
)
G72B_DRAGON_CHEER_FACTS = (
    'accuracy: true,', 'basePower: 0,', 'category: "Status",', 'priority: 0,',
    'flags: { bypasssub: 1, allyanim: 1, metronome: 1 },', "volatileStatus: 'dragoncheer',",
    "if (target.volatiles['focusenergy']) return false;", "this.add('-start', target, 'move: Dragon Cheer');",
    'this.effectState.hasDragonType = target.hasType("Dragon");',
    'return critRatio + (this.effectState.hasDragonType ? 2 : 1);', 'target: "adjacentAlly",', 'type: "Dragon",',
)
# Step G84 (decision 0047, lead's phase 2 approval): Leech Seed (data/moves.ts:10202-10231) and Curse (the Champions override,
# data/mods/champions/moves.ts:165-196). The seed's residual drain is a turn-code residual of order 8; a Ghost Curse is refused.
G84_HANDLERS = ['LEECH_SEED', 'CURSE']
G84_LEECH_FACTS = (
    'accuracy: 90,', 'category: "Status",', 'flags: { protect: 1, reflectable: 1, mirror: 1, metronome: 1 },',
    "volatileStatus: 'leechseed',", "onTryImmunity(target) {", "return !target.hasType('Grass');", 'onResidualOrder: 8,',
    'const damage = this.damage(pokemon.baseMaxhp / 8, pokemon, target);', 'this.heal(damage, target, pokemon);',
)
# The base entry (data/moves.ts:3266-3308) is checked here; the Champions override's boost text is pinned in turn.c's comment
# (champions/moves.ts:165-196), since the check reads the base file.
G84_CURSE_FACTS = (
    'flags: { bypasssub: 1, metronome: 1 },', "volatileStatus: 'curse',", "onModifyMove(move, source, target) {",
    'this.directDamage(source.maxhp / 2, source, source);', 'onResidualOrder: 12,', 'this.damage(pokemon.baseMaxhp / 4);',
)
# Step G82 (decision 0045, lead approval 2026-10-10): Healing Wish (data/moves.ts:8348-8382). The user's position gets the slot
# condition 'healingwish' (side.slotConditions[position], sim/side.ts:464-495) and the user faints (selfdestruct ifHit, after the
# condition is added, sim/battle-actions.ts:1244-1246, :1287). The next entrant of that slot is healed to full HP and cured when it
# is hurt or statused (the condition's onSwap, :8370-8377); otherwise the condition waits. onTryHit fails with [still] when the side
# has no bench (:8357-8363). The turn code implements the move and the heal (src/combat/turn.c, decision 0045).
G82_HANDLERS = ['HEALING_WISH']
G82_HEALING_WISH_FACTS = (
    'accuracy: true,', 'basePower: 0,', 'category: "Status",', 'priority: 0,',
    'flags: { snatch: 1, heal: 1, metronome: 1 },', 'selfdestruct: "ifHit",', "slotCondition: 'healingwish',",
    'target: "self",', 'type: "Psychic",', 'if (!this.canSwitch(source.side)) {', "this.attrLastMove('[still]');",
    "this.add('-fail', source);", 'return this.NOT_FAIL;', 'onSwitchIn(target) {',
    "this.singleEvent('Swap', this.effect, this.effectState, target);", 'onSwap(target) {',
    "if (!target.fainted && (target.hp < target.maxhp || target.status)) {", 'target.heal(target.maxhp);',
    'target.clearStatus();', "this.add('-heal', target, target.getHealth, '[from] move: Healing Wish');",
    "target.side.removeSlotCondition(target, 'healingwish');",
)
# Step G80, Psych Up (data/moves.ts:14211-14240; no Champions override): the user takes the target's seven stages, then its
# crit-stage volatiles are removed and the target's copies are added (Focus Energy and Dragon Cheer; the Dragon Cheer stage is
# copied as the stored Dragon flag, not recomputed). Laser Focus and Gmax Chi Strike are not in the pool (checked by the generator).
G80_HANDLERS = ['PSYCH_UP', 'ALLY_SWITCH']
G80_ALLYSWITCH_FACTS = (
    'accuracy: true,', 'basePower: 0,', 'category: "Status",', 'priority: 2,', 'flags: { metronome: 1 },',
    'onPrepareHit(pokemon) {', "return pokemon.addVolatile('allyswitch');",
    'const newPosition = (pokemon.position === 0 ? pokemon.side.active.length - 1 : 0);',
    'if (!pokemon.side.active[newPosition]) success = false;', 'if (pokemon.side.active[newPosition].fainted) success = false;',
    "this.add('-fail', pokemon, 'move: Ally Switch');", 'this.attrLastMove(\'[still]\');', 'return this.NOT_FAIL;',
    "this.swapPosition(pokemon, newPosition, '[from] move: Ally Switch');",
    'duration: 2,', 'counterMax: 729,', 'this.effectState.counter = 3;',
    'const success = this.randomChance(1, counter);', 'delete pokemon.volatiles[\'allyswitch\'];', 'return false;',
    'this.effectState.counter *= 3;', 'this.effectState.duration = 2;', 'target: "self",', 'type: "Psychic",',
)
G80_FACTS = (
    'accuracy: true,', 'basePower: 0,', 'category: "Status",', 'priority: 0,',
    'flags: { bypasssub: 1, allyanim: 1, metronome: 1 },', 'target: "normal",', 'type: "Normal",',
    'for (i in target.boosts) {', 'source.boosts[i] = target.boosts[i];',
    "const volatilesToCopy = ['dragoncheer', 'focusenergy', 'gmaxchistrike', 'laserfocus'];",
    'for (const volatile of volatilesToCopy) source.removeVolatile(volatile);',
    'if (target.volatiles[volatile]) {', 'source.addVolatile(volatile);',
    "if (volatile === 'dragoncheer') source.volatiles[volatile].hasDragonType = target.volatiles[volatile].hasDragonType;",
    "this.add('-copyboost', source, target, '[from] move: Psych Up');",
)
# Step G76 (decision 0015 5cg, lead's approval 2026-10-10): Destiny Bond. The volatile is the move's volatileStatus on the
# user; onPrepareHit fails the move while the volatile is up (removeVolatile returns true: a consecutive use fails and
# removes it); the condition prints the -singlemove start; onBeforeMove (not for Destiny Bond itself) and onMoveAborted
# remove it; onFaint KOs the foe that faints from a Move (not an ally, not a Future Sight move) with -activate and faint.
G76_HANDLERS = ['DESTINY_BOND', 'FINAL_GAMBIT']
G76_DESTINY_BOND_FACTS = (
    'accuracy: true,', 'basePower: 0,', 'category: "Status",', 'priority: 0,',
    'flags: { bypasssub: 1, noassist: 1, failcopycat: 1 },', "volatileStatus: 'destinybond',",
    "onPrepareHit(pokemon) { return !pokemon.removeVolatile('destinybond'); },", 'condition: {', 'noCopy: true,',
    "this.add('-singlemove', pokemon, 'Destiny Bond');", 'if (!source || !effect || target.isAlly(source)) return;',
    "if (effect.effectType === 'Move' && !effect.flags['futuremove']) {",
    "this.add('-activate', target, 'move: Destiny Bond');", 'source.faint();', 'onBeforeMovePriority: -1,',
    "if (move.id === 'destinybond') return;", "pokemon.removeVolatile('destinybond');",
    "onMoveAborted(pokemon, target, move) { pokemon.removeVolatile('destinybond'); },", 'target: "self",', 'type: "Ghost",',
)
# Final Gambit (data/moves.ts:5301-5322): damage equal to the user's current HP, the user faints in the damageCallback (before
# the damage is dealt), and selfdestruct ifHit faints it again (a no-op). An immune or a Protected target gives no damage call.
G76_FINAL_GAMBIT_FACTS = (
    'accuracy: 100,', 'basePower: 0,', 'damageCallback(pokemon) {', 'const damage = pokemon.hp;', 'pokemon.faint();',
    'return damage;', 'selfdestruct: "ifHit",', 'category: "Special",', 'priority: 0,',
    'flags: { protect: 1, metronome: 1, noparentalbond: 1 },', 'target: "normal",', 'type: "Fighting",',
)
# Step G78, Dragon Darts (decision 0043, lead's approval of 2026-10-10): the split of its two hits (smartTarget) over the
# chosen foe and its partner; the hit count is the number 2 (no draw), the hit loop is the Champions one.
G78_HANDLERS = ['DRAGON_DARTS']
# Step G90, the partial trap (decision 0060, lead's approval 2026-10-11): the volatile partiallytrapped of six moves. The pin's
# volatile (data/conditions.ts:222-258: the duration draw random(5, 7) or 8 with a Grip Claw, the Binding Band divisor, the
# residual at order 13, the end line, the trapped flag of the source) is what the turn code reads; the moves are plain hits.
G90_HANDLERS = ['PARTIAL_TRAP']
G90_MOVES = ('bind', 'wrap', 'firespin', 'sandtomb', 'infestation', 'snaptrap')
G90_MOVE_FACTS = ("volatileStatus: 'partiallytrapped',", 'target: "normal",')
G90_CONDITION_FACTS = (
    'durationCallback(target, source) {', "if (source?.hasItem('gripclaw')) return 8;", 'return this.random(5, 7);',
    "this.effectState.boundDivisor = source.hasItem('bindingband') ? 6 : 8;", 'onResidualOrder: 13,',
    'if (source && (!source.isActive || source.hp <= 0 || !source.activeTurns) && !gmaxEffect) {',
    "this.add('-end', pokemon, this.effectState.sourceEffect, '[partiallytrapped]', '[silent]');",
    'this.damage(pokemon.baseMaxhp / this.effectState.boundDivisor);',
    "this.add('-end', pokemon, this.effectState.sourceEffect, '[partiallytrapped]');",
    'if (this.effectState.source?.isActive || gmaxEffect) pokemon.tryTrap();',
)
# Step C5 (decision 0015 entry 5cy): Endeavor, the damageCallback path of Final Gambit (G76) with an onTryImmunity (the user's HP
# must be below the target's, else -immune). Read by parse_move from SPECIAL_P (the callbacks named there).
C5_HANDLERS = ['ENDEAVOR']
# Step G96 (decision 0015 5cz, decision 0063): Psychic Terrain's move, a field terrain setter like Electric and Misty. Its
# condition (the priority block of grounded foes, the Psychic boost, the duration) is the engine's terrain rule (turn.c).
G96_HANDLERS = ['PSYCHIC_TERRAIN']
# Step K3 (decision 0015 5de): Speed Swap's onHit (data/moves.ts:17439-17444, Champions has no
# override): the two storedStats.spe values are exchanged, then the line -activate|source|move: Speed Swap|[of] target.
K3_HANDLERS = ['SPEED_SWAP']
SPEED_SWAP_ONHIT = ("onHit(target, source) { const targetSpe = target.storedStats.spe; target.storedStats.spe = source.storedStats.spe; "
                    "source.storedStats.spe = targetSpe; this.add('-activate', source, 'move: Speed Swap', `[of] ${target}`); },")
G96_TERRAIN_COMMON = ('terrain: \'psychicterrain\',', 'category: "Status",', 'accuracy: true,', 'target: "all",', 'duration: 5,',
                      "durationCallback(source, effect) { if (source?.hasItem('terrainextender')) { return 8; } return 5; },",
                      'onBasePowerPriority: 6,',
                      "onFieldStart(field, source, effect) { if (effect?.effectType === 'Ability') { "
                      "this.add('-fieldstart', 'move: Psychic Terrain', '[from] ability: ' + effect.name, `[of] ${source}`); } else { "
                      "this.add('-fieldstart', 'move: Psychic Terrain'); } },",
                      'onFieldResidualOrder: 27,', 'onFieldResidualSubOrder: 7,')
G96_FACTS = (
    ('psychicterrain', list(G96_TERRAIN_COMMON) + [
        'onTryHitPriority: 4,',
        "onTryHit(target, source, effect) { if (effect && (effect.priority <= 0.1 || effect.target === 'self')) { return; } "
        "if (target.isSemiInvulnerable() || target.isAlly(source)) return;",
        "if (!target.isGrounded()) {",
        "this.add('-activate', target, 'move: Psychic Terrain'); return null; },",
        "onFieldEnd() { this.add('-fieldend', 'move: Psychic Terrain'); },",
    ]),
)
G78_FACTS = (
    'accuracy: 100,', 'basePower: 50,', 'category: "Physical",', 'priority: 0,',
    'flags: { protect: 1, mirror: 1, metronome: 1, noparentalbond: 1 },', 'multihit: 2,', 'smartTarget: true,',
    'target: "normal",', 'type: "Dragon",',
)
# Step G86 (decision 0015 5cn, batch 6, the power moves): Heavy Slam (base power by the user's and the target's weight in
# hectograms, getWeight() being an integer here; onTryHit is the Dynamax refusal, owned as Low Kick's), Hard Press (base power
# from the target's current HP, the pin's integer formula), Ice Spinner (clears the terrain after a hit: onAfterHit runs only
# while the user is alive, onAfterSubDamage for a Substitute absorb; no onTry, so no terrain is no failure) and Belly Drum
# (onHit: refused at half HP or at +6 Attack, half the maximum HP as directDamage, +12 Attack capped to +6, shown as -setboost).
G86_HANDLERS = ['HEAVY_SLAM', 'HARD_PRESS', 'ICE_SPINNER', 'BELLY_DRUM']
G86_FACTS = (
    ('heavyslam', ['accuracy: 100,', 'basePower: 0,', 'category: "Physical",', 'priority: 0,',
                   'flags: { contact: 1, protect: 1, mirror: 1, nonsky: 1, metronome: 1, minimize: 1 },',
                   'const targetWeight = target.getWeight();', 'const pokemonWeight = pokemon.getWeight();',
                   'if (pokemonWeight >= targetWeight * 5) {', 'bp = 120;', 'if (pokemonWeight >= targetWeight * 4) {', 'bp = 100;',
                   'if (pokemonWeight >= targetWeight * 3) {', 'bp = 80;', 'if (pokemonWeight >= targetWeight * 2) {', 'bp = 60;',
                   'bp = 40;', 'this.debug(`BP: ${bp}`);', 'return bp;', 'pp: 10,', "if (target.volatiles['dynamax']) {",
                   "this.add('-fail', pokemon, 'Dynamax');", 'target: "normal",', 'type: "Steel",']),
    ('hardpress', ['accuracy: 100,', 'basePower: 0,', 'const hp = target.hp;', 'const maxHP = target.maxhp;',
                   'const bp = Math.floor(Math.floor((100 * (100 * Math.floor(hp * 4096 / maxHP)) + 2048 - 1) / 4096) / 100) || 1;',
                   'return bp;', 'category: "Physical",', 'priority: 0,',
                   'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },', 'target: "normal",', 'type: "Steel",']),
    ('icespinner', ['accuracy: 100,', 'basePower: 80,', 'category: "Physical",', 'priority: 0,',
                    'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },', 'onAfterHit(target, source) {',
                    'this.field.clearTerrain();', 'onAfterSubDamage(damage, target, source) {', 'if (source.hp) {',
                    'target: "normal",', 'type: "Ice",']),
    ('bellydrum', ['accuracy: true,', 'basePower: 0,', 'category: "Status",', 'priority: 0,',
                   'flags: { snatch: 1, metronome: 1 },',
                   'if (target.hp <= target.maxhp / 2 || target.boosts.atk >= 6 || target.maxhp === 1) {',
                   'return false;', 'this.directDamage(target.maxhp / 2);', 'this.boost({ atk: 12 }, target);',
                   'target: "self",', 'type: "Normal",']),
)
# Step G92 (decision 0062, lead's approval 2026-10-11). CONFUSE: the primary volatile confusion of Confuse Ray, Swagger, Flatter and
# Teeter Dance (moveHit: the boosts first, then addVolatile; Misty Terrain's onTryAddVolatile prints -activate for a move without
# secondaries). OHKO: ohko true (Fissure, Guillotine, Horn Drill; hitStepAccuracy's ohko branch with accuracy 30 and no type
# immunity). MEMENTO: the target's boosts, then selfdestruct ifHit. LEVEL_DAMAGE: damage 'level' (Night Shade; no critical hit
# roll, no modifiers). Gigaton Hammer (cantusetwice) is dropped (decision 0062): its only learner has no marked ability.
G92_HANDLERS = ['CONFUSE', 'OHKO', 'MEMENTO', 'LEVEL_DAMAGE']
G92_FACTS = (
    ('confuseray', ['accuracy: 100,', 'basePower: 0,', 'category: "Status",', 'priority: 0,',
                    'flags: { protect: 1, reflectable: 1, mirror: 1, metronome: 1 },', "volatileStatus: 'confusion',",
                    'target: "normal",', 'type: "Ghost",']),
    ('swagger', ['accuracy: 85,', 'basePower: 0,', 'category: "Status",', 'priority: 0,',
                 'flags: { protect: 1, reflectable: 1, mirror: 1, allyanim: 1, metronome: 1 },', "volatileStatus: 'confusion',",
                 'boosts: { atk: 2, },', 'target: "normal",', 'type: "Normal",']),
    ('flatter', ['accuracy: 100,', 'basePower: 0,', 'category: "Status",', 'priority: 0,',
                 'flags: { protect: 1, reflectable: 1, mirror: 1, allyanim: 1, metronome: 1 },', "volatileStatus: 'confusion',",
                 'boosts: { spa: 1, },', 'target: "normal",', 'type: "Dark",']),
    ('teeterdance', ['accuracy: 100,', 'basePower: 0,', 'category: "Status",', 'priority: 0,',
                     'flags: { protect: 1, mirror: 1, dance: 1, metronome: 1 },', "volatileStatus: 'confusion',",
                     'target: "allAdjacent",', 'type: "Normal",']),
    ('fissure', ['accuracy: 30,', 'basePower: 0,', 'category: "Physical",', 'priority: 0,',
                 'flags: { protect: 1, mirror: 1, nonsky: 1, metronome: 1 },', 'ohko: true,', 'target: "normal",', 'type: "Ground",']),
    ('guillotine', ['accuracy: 30,', 'basePower: 0,', 'category: "Physical",', 'priority: 0,',
                    'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },', 'ohko: true,', 'target: "normal",', 'type: "Normal",']),
    ('horndrill', ['accuracy: 30,', 'basePower: 0,', 'category: "Physical",', 'priority: 0,',
                   'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },', 'ohko: true,', 'target: "normal",', 'type: "Normal",']),
    ('memento', ['accuracy: 100,', 'basePower: 0,', 'category: "Status",', 'priority: 0,',
                 'flags: { protect: 1, mirror: 1, metronome: 1 },', 'boosts: { atk: -2, spa: -2, },',
                 'selfdestruct: "ifHit",', 'target: "normal",', 'type: "Dark",']),
    ('nightshade', ['accuracy: 100,', 'basePower: 0,', "damage: 'level',", 'category: "Special",', 'priority: 0,',
                    'flags: { protect: 1, mirror: 1, metronome: 1 },', 'target: "normal",', 'type: "Ghost",']),
)
G58_FACTS = (
    'accuracy: 100,', 'basePower: 90,', 'category: "Physical",', 'priority: 0,', 'target: "normal",', 'type: "Ghost",',
    'flags: { contact: 1, charge: 1, mirror: 1, metronome: 1, nosleeptalk: 1, noassist: 1, failinstruct: 1 },',
    'breaksProtect: true,', 'if (attacker.removeVolatile(move.id)) {', "this.add('-prepare', attacker, move.name);",
    "if (!this.runEvent('ChargeMove', attacker, defender, move)) {", "attacker.addVolatile('twoturnmove', defender);",
    'return null;', 'duration: 2,', 'onInvulnerability: false,',
)
G54_FACTS = (
    ('iciclespear', ['accuracy: 100,', 'basePower: 25,', 'category: "Physical",', 'priority: 0,',
                     'flags: { protect: 1, mirror: 1, metronome: 1 },', 'multihit: [2, 5],', 'target: "normal",', 'type: "Ice",']),
    ('tailslap', ['accuracy: 85,', 'basePower: 25,', 'category: "Physical",', 'priority: 0,',
                  'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },', 'multihit: [2, 5],', 'target: "normal",',
                  'type: "Normal",']),
    ('bonerush', ['accuracy: 90,', 'basePower: 25,', 'category: "Physical",', 'priority: 0,',
                  'flags: { protect: 1, mirror: 1, metronome: 1 },', 'multihit: [2, 5],', 'target: "normal",',
                  'type: "Ground",']),
    ('scaleshot', ['accuracy: 90,', 'basePower: 25,', 'category: "Physical",', 'priority: 0,',
                   'flags: { protect: 1, mirror: 1, metronome: 1 },', 'multihit: [2, 5],',
                   'selfBoost: { boosts: { def: -1, spe: 1, }, },', 'target: "normal",', 'type: "Dragon",']),
    ('quickguard', ['accuracy: true,', 'basePower: 0,', 'category: "Status",', 'priority: 3,', 'flags: { snatch: 1 },',
                    "sideCondition: 'quickguard',", 'onTry() { return !!this.queue.willAct(); },',
                    'onHitSide(side, source) { source.addVolatile(\'stall\'); },', 'onTryHitPriority: 4,',
                    'if (move.priority <= 0.1) return;', "this.add('-activate', target, 'move: Quick Guard');",
                    'target: "allySide",', 'type: "Fighting",']),
    ('upperhand', ['accuracy: 100,', 'basePower: 65,', 'category: "Physical",', 'priority: 3,',
                   'if (!move || move.priority <= 0.1 || move.category === \'Status\') {', 'chance: 100,',
                   "volatileStatus: 'flinch',", 'target: "normal",', 'type: "Fighting",']),
    ('healpulse', ['accuracy: true,', 'basePower: 0,', 'category: "Status",', 'priority: 0,',
                   'this.heal(Math.ceil(target.baseMaxhp * 0.5));', "this.add('-fail', target, 'heal');",
                   'target: "any",', 'type: "Psychic",']),
    ('strengthsap', ['accuracy: 100,', 'basePower: 0,', 'category: "Status",', 'priority: 0,',
                     'if (target.boosts.atk === -6) return false;', "const atk = target.getStat('atk', false, true);",
                     "const success = this.boost({ atk: -1 }, target, source, null, false, true);",
                     'return !!(this.heal(atk, source, target) || success);', 'target: "normal",', 'type: "Grass",']),
)
# Step G64 (moves batch 2, decision 0015 item 5ca). BEAT_UP (Beat Up: onModifyMove counts the side's eligible members, one hit each,
# and basePowerCallback gives each hit 5 plus the base Attack of its set species, 10th part), BUG_BITE (onHit takes the target's
# berry when it is a berry and eats it, for the user), POLTERGEIST (onTry fails without a target item; onTryHit reveals it with
# -activate) and SHEER_COLD (an OHKO move: ohko 'Ice', the accuracy and immunity of hitStepAccuracy; G2_OWNED_FIELDS owns the field).
G64_HANDLERS = ['BEAT_UP', 'BUG_BITE', 'POLTERGEIST', 'SHEER_COLD']
# Step C4 (decision 0015 entry 5ct): willCrit, a move that is always a critical hit and draws no critical roll (Storm Throw,
# Flower Trick, Frost Breath). The engine reads it in the damage call (dfi_get_damage); the Shell Armor check is unchanged.
C4_HANDLERS = ['WILL_CRIT']
G64_FACTS = (
    ('beatup', ['move.allies = pokemon.side.pokemon.filter(ally => ally === pokemon || !ally.fainted && !ally.status);',
                'move.multihit = move.allies.length;',
                'const setSpecies = this.dex.species.get(move.allies!.shift()!.set.species);',
                'const bp = 5 + Math.floor(setSpecies.baseStats.atk / 10);', 'return bp;',
                'accuracy: 100,', 'basePower: 0,', 'category: "Physical",', 'priority: 0,',
                'flags: { protect: 1, mirror: 1, allyanim: 1, metronome: 1 },', 'target: "normal",', 'type: "Dark",']),
    ('bugbite', ['const item = target.getItem();', 'if (source.hp && item.isBerry && target.takeItem(source)) {',
                 "this.add('-enditem', target, item.name, '[from] stealeat', '[move] Bug Bite', `[of] ${source}`);",
                 "if (this.singleEvent('Eat', item, target.itemState, source, source, move)) {",
                 "this.runEvent('EatItem', source, source, move, item);", "if (item.id === 'leppaberry') target.staleness = 'external';",
                 'if (item.onEat) source.ateBerry = true;', 'accuracy: 100,', 'basePower: 60,', 'category: "Physical",',
                 'priority: 0,', 'flags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },', 'target: "normal",', 'type: "Bug",']),
    ('poltergeist', ['onTry(source, target) {', 'return !!target.item;',
                     'onTryHit(target, source, move) {',
                     "this.add('-activate', target, 'move: Poltergeist', this.dex.items.get(target.item).name);",
                     'accuracy: 90,', 'basePower: 110,', 'category: "Physical",', 'priority: 0,',
                     'flags: { protect: 1, mirror: 1, metronome: 1 },', 'target: "normal",', 'type: "Ghost",']),
    ('sheercold', ["ohko: 'Ice',", 'accuracy: 30,', 'basePower: 0,', 'category: "Special",', 'priority: 0,',
                   'flags: { protect: 1, mirror: 1, metronome: 1 },', 'target: "normal",', 'type: "Ice",']),
)
# Step G62 (Haze, decision 0031; the turn-order moves After You and Quash follow in their own rows). HAZE: `onHitField` prints
# `-clearallboost` and clears the boosts of every active Pokemon (getAllActive(), the standing ones only); no protect flag, a
# target of the field (`all`), accuracy true. The engine's stages are the boosts; clearBoosts zeroes the seven of them only.
G62_HANDLERS = ['HAZE', 'AFTER_YOU', 'QUASH']
G62_FACTS = (
    ('haze', ['accuracy: true,', 'basePower: 0,', 'category: "Status",', 'priority: 0,',
              'flags: { bypasssub: 1, metronome: 1 },', "this.add('-clearallboost');",
              'for (const pokemon of this.getAllActive()) {', 'pokemon.clearBoosts();', 'target: "all",', 'type: "Ice",']),
    # After You (data/moves.ts:195-218): the target's pending move goes first (prioritizeAction, order 3) and the line
    # `-activate|target|move: After You`; no move action of the target (fainted, moved, switching) fails the move.
    ('afteryou', ['accuracy: true,', 'basePower: 0,', 'category: "Status",', 'priority: 0,', 'flags: { bypasssub: 1, allyanim: 1 },',
                  'if (this.activePerHalf === 1) return false;', 'const action = this.queue.willMove(target);',
                  'this.queue.prioritizeAction(action);', "this.add('-activate', target, 'move: After You');",
                  'return false;', 'target: "normal",', 'type: "Normal",']),
    # Quash (data/moves.ts:14454-14475): the target's pending move goes last (action.order = 201) and the line
    # `-activate|target|move: Quash`; a protect move, accuracy 100.
    ('quash', ['accuracy: 100,', 'basePower: 0,', 'category: "Status",', 'priority: 0,', 'flags: { protect: 1, mirror: 1 },',
               'if (this.activePerHalf === 1) return false;', 'const action = this.queue.willMove(target);',
               'if (!action) return false;', 'action.order = 201;', "this.add('-activate', target, 'move: Quash');",
               'target: "normal",', 'type: "Dark",']),
)
# Step G68 (moves batch 4, decision 0015 item 5cc). STEEL_BEAM: mindBlownRecoil (round(maxhp / 2) to the user after a hit, the
# move's own condition as the effect, so the line is `[from] steelbeam`) and onMoveFail (the same damage when the hit steps
# leave no target: a miss, a Protect, an invulnerability). THUNDER_WAVE: ignoreImmunity false, so the Electric type immunity of
# the target applies (a Ground target is -immune before the accuracy check). G68_FACTS holds the pinned texts.
G68_HANDLERS = ['STEEL_BEAM', 'THUNDER_WAVE']
G68_FACTS = (
    ('steelbeam', ['accuracy: 95,', 'basePower: 140,', 'category: "Special",', 'priority: 0,',
                   'flags: { protect: 1, mirror: 1 },', 'mindBlownRecoil: true,', 'onMoveFail(target, source, move) {',
                   'if (move.multihit) return;',
                   "this.damage(Math.round(source.maxhp / 2), source, source, this.dex.conditions.get('Steel Beam'));",
                   'target: "normal",', 'type: "Steel",']),
    ('thunderwave', ['accuracy: 90,', 'basePower: 0,', 'category: "Status",', 'priority: 0,',
                     'flags: { protect: 1, reflectable: 1, mirror: 1, metronome: 1 },', "status: 'par',",
                     'ignoreImmunity: false,', 'target: "normal",', 'type: "Electric",']),
)
SPECIAL_IDS_P = SPECIAL_IDS_C + G2_HANDLERS + WEATHER_HANDLERS + G16_HANDLERS + G15_HANDLERS + G19_HANDLERS + G20_HANDLERS + G20_PROTECT_HANDLERS + G28_HANDLERS + G30_HANDLERS + G32_HANDLERS + G34_HANDLERS + G27_HANDLERS + G25_HANDLERS + G26_HANDLERS + G33_HANDLERS + G38_HANDLERS + G29_HANDLERS + G39_HANDLERS + G31_HANDLERS + G48_HANDLERS + G44_HANDLERS + G50_HANDLERS + G42_HANDLERS + G56_HANDLERS + G52_HANDLERS + G54_HANDLERS + G64_HANDLERS + G62_HANDLERS + G60_HANDLERS + G58_HANDLERS + G68_HANDLERS + G70_HANDLERS + G66_HANDLERS + G72B_HANDLERS + G74_HANDLERS + G76_HANDLERS + G78_HANDLERS + G88_HANDLERS + G94_HANDLERS + G86_HANDLERS + C4_HANDLERS + G84_HANDLERS + G92_HANDLERS + G82_HANDLERS + G90_HANDLERS + C5_HANDLERS + G80_HANDLERS + G96_HANDLERS + K3_HANDLERS + ['UNMODELED']# Step G10 made two of these handlers data: Scald (thawsTarget) and Recover (heal) are read into the second flags# byte (bit 4, thaws the target) and the heal column, and have the special NONE; their ids stay defined (the ids after
# them keep their values). First Impression and Low Kick keep theirs: the turn code implements them.
POOL_COLUMN_KEYS = {'thawsTarget', 'heal'}
G2_OWNED_FIELDS = {
    'ROOST': {'self': ROOST_SELF},
    'ENCORE': {'volatileStatus': "volatileStatus: 'encore',"},
    'WIDE_GUARD': {'sideCondition': "sideCondition: 'wideguard',"},
    'AURORA_VEIL': {'sideCondition': "sideCondition: 'auroraveil',"},
    'DISABLE': {'volatileStatus': "volatileStatus: 'disable',"},
    'SPIKY_SHIELD': {'volatileStatus': "volatileStatus: 'spikyshield',"},
    'BANEFUL_BUNKER': {'volatileStatus': "volatileStatus: 'banefulbunker',"},
    'TAUNT': {'volatileStatus': "volatileStatus: 'taunt',"},
    'DRAGON_CHEER': {'volatileStatus': "volatileStatus: 'dragoncheer',"},
    'SUBSTITUTE': {'volatileStatus': "volatileStatus: 'substitute',"},
    'YAWN': {'volatileStatus': "volatileStatus: 'yawn',"},
    'REVIVAL_BLESSING': {'slotCondition': "slotCondition: 'revivalblessing', // No this not a real switchout move // This is needed "
                                         "to trigger a switch protocol to choose a fainted party member // Feel free to refactor"},
    'LEECH_SEED': {'volatileStatus': "volatileStatus: 'leechseed',"},
    'HEALING_WISH': {'slotCondition': "slotCondition: 'healingwish',", 'selfdestruct': 'selfdestruct: "ifHit",'},
    'SANDSTORM': {'weather': "weather: 'Sandstorm',"},
    'SNOWSCAPE': {'weather': "weather: 'snowscape',"},
    'ELECTRIC_TERRAIN': {'terrain': "terrain: 'electricterrain',"},
    'MISTY_TERRAIN': {'terrain': "terrain: 'mistyterrain',"},
    'PSYCHIC_TERRAIN': {'terrain': "terrain: 'psychicterrain',"},  # G96 (decision 0015 5cz): the terrain field of the setter
    'SHELL_SMASH': {'boosts': "boosts: { def: -1, spd: -1, atk: 2, spa: 2, spe: 2, },"},
    'FEINT': {'breaksProtect': "breaksProtect: true, // Breaking protection implemented in scripts.js"},
    'GLAIVE_RUSH': {'self': "self: { volatileStatus: 'glaiverush', },"},
    'DESTINY_BOND': {'volatileStatus': "volatileStatus: 'destinybond',"},
    'FINAL_GAMBIT': {'selfdestruct': 'selfdestruct: "ifHit",'},
    'LOCKED_MOVE': {'self': "self: { volatileStatus: 'lockedmove', },"},
    'PHANTOM_FORCE': {'breaksProtect': 'breaksProtect: true,'},
    'KINGS_SHIELD': {'volatileStatus': "volatileStatus: 'kingsshield',"},
    'RAGE_POWDER': {'volatileStatus': "volatileStatus: 'ragepowder',"},
    'MULTI_HIT_2': {'multihit': 'multihit: 2,'},
    'DOUBLE_SHOCK': {'self': "self: { onHit(pokemon) { pokemon.setType(pokemon.getTypes(true).map(type => type === \"Electric\" ? \"???\" : type)); this.add('-start', pokemon, 'typechange', pokemon.getTypes().join('/'), '[from] move: Double Shock'); }, },"},
    'TRIPLE_AXEL': {'multihit': 'multihit: 3,', 'multiaccuracy': 'multiaccuracy: true,'},
    'MULTI_HIT_10': {'multihit': 'multihit: 10,', 'multiaccuracy': 'multiaccuracy: true,'},
    'BODY_PRESS': {'overrideOffensiveStat': "overrideOffensiveStat: 'def',"},
    'FOUL_PLAY': {'overrideOffensivePokemon': "overrideOffensivePokemon: 'target',"},
    'PSYSHOCK': {'overrideDefensiveStat': "overrideDefensiveStat: 'def',"},
    'RAIN_DANCE': {'weather': "weather: 'RainDance',"},
    'SUNNY_DAY': {'weather': "weather: 'sunnyday',"},
    'CLANGING_SCALES': {'selfBoost': "selfBoost: { boosts: { def: -1, }, },"},
    'IMPRISON': {'volatileStatus': "volatileStatus: 'imprison',"},
    'ICE_FANG': {'secondaries': "secondaries: [ { chance: 10, status: 'frz', }, { chance: 10, volatileStatus: 'flinch', }, ],"},
    'MULTI_HIT_2_5': {'multihit': 'multihit: [2, 5],'},
    'SCALE_SHOT': {'multihit': 'multihit: [2, 5],', 'selfBoost': "selfBoost: { boosts: { def: -1, spe: 1, }, },"},
    'QUICK_GUARD': {'sideCondition': "sideCondition: 'quickguard',"},
    'SHEER_COLD': {'ohko': "ohko: 'Ice',"},
    'WILL_CRIT': {'willCrit': 'willCrit: true,'},
    'STEEL_BEAM': {'mindBlownRecoil': 'mindBlownRecoil: true,'},
    'THUNDER_WAVE': {'ignoreImmunity': 'ignoreImmunity: false,'},
    'BATON_PASS': {'self': BATON_PASS_SELF},
    'DRAGON_DARTS': {'multihit': 'multihit: 2,', 'smartTarget': 'smartTarget: true,'},
    # Step G92 (decision 0062): the primary volatile of the confusion moves, ohko true, Memento's selfdestruct, Night Shade's damage.
    'CONFUSE': {'volatileStatus': "volatileStatus: 'confusion',"},
    'OHKO': {'ohko': 'ohko: true,'},
    'MEMENTO': {'selfdestruct': 'selfdestruct: "ifHit",'},
    'LEVEL_DAMAGE': {'damage': "damage: 'level',"},
    'PARTIAL_TRAP': {'volatileStatus': "volatileStatus: 'partiallytrapped',"},
}
# Step G48: the empty secondary of Stone Axe and Ceaseless Edge (the Sheer Force placeholder). Without Sheer Force the pin runs
# it for every hit target (moveHit of an empty secondary with chance undefined, sim/battle-actions.ts:1336-1349): the engine
# draws the roll and does nothing else; the engine's special case is in dfi_run_move.
G2_OWNED_SECONDARY = {'STONE_AXE': 'secondary: {}, // Sheer Force-boosted', 'CEASELESS_EDGE': 'secondary: {}, // Sheer Force-boosted', 'ALLURING_VOICE': "secondary: { chance: 100, onHit(target, source, move) { if (target?.statsRaisedThisTurn) { "
                  "target.addVolatile('confusion', source, move); } }, },", 'TRI_ATTACK': "secondary: { chance: 20, onHit(target, source) { const status = this.sample(['brn', 'par', 'frz']); "
                  "target.trySetStatus(status, source); }, },"}
G2_OWNED_CONDITION = {'ROOST', 'ENCORE', 'WIDE_GUARD', 'QUICK_GUARD', 'GLAIVE_RUSH', 'AURORA_VEIL', 'SPIKY_SHIELD', 'RAGE_POWDER', 'DISABLE',
                      'ELECTRIC_TERRAIN', 'MISTY_TERRAIN', 'PERISH_SONG', 'IMPRISON', 'TAUNT', 'YAWN', 'REVIVAL_BLESSING',
                      'SUBSTITUTE', 'PHANTOM_FORCE', 'KINGS_SHIELD', 'DRAGON_CHEER', 'HEALING_WISH', 'ALLY_SWITCH', 'DESTINY_BOND', 'BANEFUL_BUNKER', 'LEECH_SEED', 'CURSE', 'PSYCHIC_TERRAIN'}
# Step G8 (Throat Chop and Psychic Noise): the two secondaries become modelled kinds, and the column that their
# consumers read is the move's second flags byte (the first is full): the `sound` flag (Throat Chop bars the sound
# moves) and the `heal` flag (Heal Block bars the moves that heal). Both are derived for every pool move, the prefix
# included; the CLOSURE and extended bytes do not have them. Decision 0015 section 2.
SECONDARY_LOCKOUT = 5     # Throat Chop: chance 100, addVolatile('throatchop'): the target may not use sound moves
SECONDARY_HEAL_BLOCK = 6  # Psychic Noise: chance 100, volatileStatus 'healblock' (2 turns from Psychic Noise)
G8_SECONDARIES = {
    "secondary: { chance: 100, onHit(target) { target.addVolatile('throatchop'); }, },": (SECONDARY_LOCKOUT, True),
    "secondary: { chance: 100, volatileStatus: 'healblock', },": (SECONDARY_HEAL_BLOCK, False),
}
FLAGS2_BITS = {'sound': 1, 'heal': 2, 'powder': 16, 'punch': 32, 'slicing': 64}  # steps G30 (powder) and G34 (punch, slicing)
# The third flags byte (DFI_MOVE_FLAG3_*, pool tables only): one bit per Showdown flag name, assigned centrally (HauptSession).
FLAGS3_BITS = {'reflectable': 1, 'mustpressure': 2, 'bypasssub': 4, 'pulse': 8, 'bullet': 16}  # steps G57 (Magic Bounce), G53 (Pressure), G60 (Substitute), G59 (Mega Launcher), G83 (Bulletproof)
# Decision 0020: the public static flags of a move (DUOFORGE_MOVE_STATIC_FLAG_*, include/duoforge/duoforge.h), one bit per
# Showdown flag name, additive only; the generated column dfi_pool_move_static_flags holds them for every pool row and has
# no engine reader. POWER_RULE is not a flag of the pin: the move has a basePowerCallback (its basePower is not the damage).
STATIC_FLAG_BITS = {'contact': 1, 'sound': 2, 'punch': 4, 'bite': 8, 'bullet': 16, 'pulse': 32, 'slicing': 64,
                    'wind': 128, 'dance': 256, 'powder': 512, 'mustpressure': 2048}  # mustpressure: step G53 (Pressure's targets)
STATIC_FLAG_POWER_RULE = 1024
FLAG2_RECHARGE = 8  # step G17: flags.recharge with self: {volatileStatus: 'mustrecharge'} (data/moves.ts, Hyper Beam 9113-9128)
RECHARGE_SELF = "self: { volatileStatus: 'mustrecharge', },"
FLAG2_THAWS_TARGET = 4  # step G10: thawsTarget (data/moves.ts:15770), the move cures a frozen target after the secondaries
# Step G46: forceSwitch (data/moves.ts: Roar 15157-15171, Whirlwind 20760-20774, Dragon Tail 4208-4221, Circle Throw
# 2451-2464). The four moves whose forced switch the turn code runs (battle-actions.ts runMoveEffects and forceSwitch,
# through scripts.ts:374 and :392); any other move with the key stays UNMODELED.
FLAG2_FORCE_SWITCH = 128
G46_FORCE_SWITCH_MOVES = ('roar', 'whirlwind', 'dragontail', 'circlethrow')  # each marked with its battle (g46_roar_drag, g46_whirlwind_drag, g46_dragontail_drag, g46_circlethrow_drag)
# What the engine hard-codes about the two conditions, read from the pin (build_pool checks it): the duration and the
# residual order of Throat Chop's condition, and Heal Block's (the move healblock) order and Psychic Noise duration.
G8_CONDITION_FACTS = (
    ('throatchop', ['duration: 2,', 'onResidualOrder: 22,', "if (this.dex.moves.get(moveSlot.id).flags['sound']) {",
                    "if (!move.isZOrMaxPowered && move.flags['sound']) {", 'onBeforeMovePriority: 6,']),
    ('healblock', ['onResidualOrder: 20,', 'onBeforeMovePriority: 6,', 'if (effect?.name === "Psychic Noise") {',
                   'return 2;', "if (this.dex.moves.get(moveSlot.id).flags['heal']) {",
                   "if (move.flags['heal'] && !move.isZ && !move.isMax) {",
                   'onTryHeal(damage, target, source, effect) {']),
)
# Step G20: what the engine hard-codes about Aurora Veil, whole callbacks and values of the pinned entry (the
# durations, the damage modifier and its two exceptions, the order among the side conditions, both lines).
G20_CONDITION_FACTS = (
    ('auroraveil', ['duration: 5,',
                    "durationCallback(target, source, effect) { if (source?.hasItem('lightclay')) { return 8; } return 5; },",
                    "onAnyModifyDamage(damage, source, target, move) { if (target !== source && "
                    "this.effectState.target.hasAlly(target)) { "
                    "if ((target.side.getSideCondition('reflect') && this.getCategory(move) === 'Physical') || "
                    "(target.side.getSideCondition('lightscreen') && this.getCategory(move) === 'Special')) { return; } "
                    "if (!target.getMoveHitData(move).crit && !move.infiltrates) { this.debug('Aurora Veil weaken'); "
                    "if (this.activePerHalf > 1) return this.chainModify([2732, 4096]); return this.chainModify(0.5); } } },",
                    "onSideStart(side) { this.add('-sidestart', side, 'move: Aurora Veil'); },",
                    'onSideResidualOrder: 26,', 'onSideResidualSubOrder: 10,',
                    "onSideEnd(side) { this.add('-sideend', side, 'move: Aurora Veil'); },"]),
)
# Step G25: what the engine hard-codes about Electric Terrain and Misty Terrain (data/moves.ts:4497-4551 and 12151-12205), Rising
# Voltage (:15137-15162) and Terrain Pulse (:19265-19311), whole callbacks and values of the pinned entries: the durations
# (and Terrain Extender's 8, which no marked item gives), the residual order, the sleep and status refusals and which of
# them print the -activate line, the confusion refusal of Misty Terrain, the base power modifiers, the lines of the field.
# The converter reads the one quirk of the pin: Misty Terrain's -fieldend line has no "move: " in it.
G25_TERRAIN_COMMON = ('terrain: \'%(id)s\',', 'category: "Status",', 'accuracy: true,', 'target: "all",', 'duration: 5,',
                      "durationCallback(source, effect) { if (source?.hasItem('terrainextender')) { return 8; } return 5; },",
                      'onBasePowerPriority: 6,',
                      "onFieldStart(field, source, effect) { if (effect?.effectType === 'Ability') { "
                      "this.add('-fieldstart', 'move: %(name)s', '[from] ability: ' + effect.name, `[of] ${source}`); } else { "
                      "this.add('-fieldstart', 'move: %(name)s'); } },",
                      'onFieldResidualOrder: 27,', 'onFieldResidualSubOrder: 7,')
G25_FACTS = (
    ('electricterrain', [f % {'id': 'electricterrain', 'name': 'Electric Terrain'} for f in G25_TERRAIN_COMMON] + [
        "onSetStatus(status, target, source, effect) { if (status.id === 'slp' && target.isGrounded() && "
        "!target.isSemiInvulnerable()) { if (effect.id === 'yawn' || (effect.effectType === 'Move' && !effect.secondaries)) { "
        "this.add('-activate', target, 'move: Electric Terrain'); } return false; } },",
        "onTryAddVolatile(status, target) { if (!target.isGrounded() || target.isSemiInvulnerable()) return; "
        "if (status.id === 'yawn') { this.add('-activate', target, 'move: Electric Terrain'); return null; } },",
        "onBasePower(basePower, attacker, defender, move) { if (move.type === 'Electric' && attacker.isGrounded() && "
        "!attacker.isSemiInvulnerable()) { this.debug('electric terrain boost'); return this.chainModify([5325, 4096]); } },",
        "onFieldEnd() { this.add('-fieldend', 'move: Electric Terrain'); },"]),
    ('mistyterrain', [f % {'id': 'mistyterrain', 'name': 'Misty Terrain'} for f in G25_TERRAIN_COMMON] + [
        "onSetStatus(status, target, source, effect) { if (!target.isGrounded() || target.isSemiInvulnerable()) return; "
        "if (effect && ((effect as Move).status || effect.id === 'yawn')) { this.add('-activate', target, 'move: Misty Terrain'); } "
        "return false; },",
        "onTryAddVolatile(status, target, source, effect) { if (!target.isGrounded() || target.isSemiInvulnerable()) return; "
        "if (status.id === 'confusion') { if (effect.effectType === 'Move' && !effect.secondaries) "
        "this.add('-activate', target, 'move: Misty Terrain'); return null; } },",
        "onBasePower(basePower, attacker, defender, move) { if (move.type === 'Dragon' && defender.isGrounded() && "
        "!defender.isSemiInvulnerable()) { this.debug('misty terrain weaken'); return this.chainModify(0.5); } },",
        "onFieldEnd() { this.add('-fieldend', 'Misty Terrain'); },"]),
    ('risingvoltage', ['basePower: 70,', 'accuracy: 100,', 'category: "Special",', 'target: "normal",', 'type: "Electric",',
                       "basePowerCallback(source, target, move) { if (this.field.isTerrain('electricterrain') && "
                       "target.isGrounded()) { if (!source.isAlly(target)) this.hint(`${move.name}'s BP doubled on "
                       "grounded target.`); return move.basePower * 2; } return move.basePower; },"]),
    ('terrainpulse', ['basePower: 50,', 'accuracy: 100,', 'category: "Special",', 'target: "normal",', 'type: "Normal",',
                      'flags: { protect: 1, mirror: 1, metronome: 1, pulse: 1 },',
                      "onModifyType(move, pokemon) { if (!pokemon.isGrounded()) return; switch (this.field.terrain) { "
                      "case 'electricterrain': move.type = 'Electric'; break; case 'grassyterrain': move.type = 'Grass'; break; "
                      "case 'mistyterrain': move.type = 'Fairy'; break; case 'psychicterrain': move.type = 'Psychic'; break; } },",
                      "onModifyMove(move, pokemon) { if (this.field.terrain && pokemon.isGrounded()) { move.basePower *= 2; "
                      "this.debug('BP doubled in Terrain'); } },"]),
)
# Move flags that the new moves carry and no row reads. `punch` is read by Iron Fist and `slicing` (already ignored)
# by Sharpness, `allyanim` by nothing in the tables: build_pool fails if one of those readers is a pool ability,
# because ignoring the flag would then hide a mechanic.
G2_IGNORED_FLAGS = {'punch', 'allyanim'}
FLAG_READERS = {'punch': 'ironfist', 'slicing': 'sharpness'}

# ---- The whole legal pool (decision 0015 section 4.2): a row for every move, item, ability and forme of the format,
# appended after the rows of the steps above. A row that the tables model fully is encoded exactly as before; one that
# has anything unmodelled gets the UNMODELED handler (the move's special column; the handler column of an item or an
# ability) and a recorded list of the features that are not modelled. Such rows are never marked in the manifest. ----
# Target classes of the pool that the closure encodings lack, as codes of the generated header only (the public
# DUOFORGE_TARGET_CLASS_* values stay 1 to 9; Struggle's randomNormal is 10). They are encoded; the turn code does not
# implement them, so a move with one is UNMODELED.
TARGET_CLASS_POOL = dict(TARGET_CLASS, allAdjacent=11, scripted=12, allyTeam=13, allies=14, foeSide=15)
TARGET_CLASS_POOL_NAMES = {11: 'ALL_ADJACENT', 12: 'SCRIPTED', 13: 'ALLY_TEAM', 14: 'ALLIES', 15: 'FOE_SIDE'}
# The target classes that the turn code resolves (src/combat/turn.c, dfi_resolve_targets and request.c).
ENGINE_TARGETS = {'normal', 'any', 'adjacentAlly', 'adjacentFoe', 'self', 'allAdjacentFoes', 'allySide', 'all',
                  'randomNormal', 'allAdjacent', 'allies', 'foeSide'}  # allAdjacent: step G28 (Earthquake hits the ally too); allies: G32 (Life Dew); foeSide: G37 (the four hazards)
# Every move flag of the 510 pool moves: a flag outside this set is something the generator cannot read.
POOL_FLAGS = (set(FLAG_BITS_C) | IGNORED_FLAGS | G2_IGNORED_FLAGS |
              {'bite', 'recharge', 'minimize', 'gravity', 'powder', 'noparentalbond', 'futuremove', 'cantusetwice',
               'mustpressure', 'nosketch'})
# The move flags that no bit holds and that a modelled row reads. It is filled by build_pool from the rows that are
# modelled by definition (the prefix); a move with such a flag is UNMODELED. The set is empty while no modelled row
# reads an unencoded flag; the day one does, the move rows that carry the flag change by rule, never silently.
FLAGS_THAT_MATTER = set()
# Flags that a row of the prefix reads and that still do not matter, each with the reason and the row whose
# modelling would make it matter (build_pool fails if that row is modelled):
#   bypasssub -- Chople Berry reads it next to the substitute volatile, which no modelled row has (Substitute is
#                UNMODELED); pledgecombo -- Lightning Rod reads it; only the pledge moves have it, none is in the pool.
INERT_FLAG_READS = {'pledgecombo': None}
# The moves of the whole pool that the turn code pivots with a switch flag of their own (dfi_pivot_moves,
# src/state/closure_member.c) beyond Flip Turn and U-turn, which are rows of the steps. Empty: Volt Switch comes with the
# step that gives it a flag value, and adds its id here.
ENGINE_PIVOT_MOVES = ('voltswitch', 'revivalblessing', 'batonpass')  # step G32: switch flag 6; step G74: Baton Pass, switch flag 8


def prefix_flag_reads(srcs, dx):
    """The move flags that the rows of the extended prefix (the closure and Team C, whose handlers are code in the turn
    core) read in their pinned handlers: `flags['x']` or `.flags.x`. A flag that a modelled row reads and that no bit
    holds would matter to the move rows that carry it."""
    items_ts, champ_items, abil_ts, champ_abil, moves_ts, champ_moves = srcs
    reads = set()
    for src, champ, rows in ((abil_ts, champ_abil, dx['abilities']), (items_ts, champ_items, dx['items']),
                             (moves_ts, champ_moves, dx['moves'])):
        for r in rows:
            for s in (src, champ):
                e = s.entry(r['id'])
                if e is not None:
                    text = '\n'.join(e[2])
                    reads.update(re.findall(r"flags\['(\w+)'\]", text))
                    reads.update(re.findall(r'\.flags\.(\w+)', text))
    return reads


def parse_pool_move(mid, moves_ts, champ_moves):
    """A move of the whole pool that no step has handled: parsed in the lenient mode. Everything that the tables
    model is encoded as parse_move encodes it; a move with any unmodelled feature gets the UNMODELED handler, its effect
    columns neutral (a refused row claims nothing beyond its plain data: type, category, power, accuracy, PP,
    priority, target class, crit ratio, flags, recoil and drain), and the list of its features."""
    features = []
    rec = parse_move(mid, moves_ts, champ_moves, pool=True, unmodeled=features)
    rec['unmodeled'] = sorted(set(features))
    if rec['unmodeled']:
        rec.update(sec_chance=0, sec_kind=0, sec_param=0, boost_role=0, boosts=[0] * 7, primary_status=0,
                   side_condition=0, pseudo_weather=0, special=SPECIAL_IDS_P.index('UNMODELED'), heal=[0, 0],
                   flags2=rec['flags2'] & ~(FLAG2_THAWS_TARGET | FLAG2_RECHARGE | FLAG2_FORCE_SWITCH))
    return rec


# Sandstorm and Snowscape (data/conditions.ts, read through READER_INPUTS) and Weather Ball (data/moves.ts): what the
# engine hard-codes about them, as normalised texts that must be in the pinned entries: the duration (5; 8 with the rock
# item, which is UNMODELED and so never held in a battle), the stat modifiers and their handler priority, the residual
# order, the damage, the upkeep line and the type and power of Weather Ball.
WEATHER_FACTS = (
    ('sandstorm', ['duration: 5,', "if (source?.hasItem('smoothrock')) { return 8; } return 5;",
                   'onModifySpDPriority: 10,',
                   "if (pokemon.hasType('Rock') && pokemon.effectiveWeather() === 'sandstorm') { return this.modify(spd, 1.5); }",
                   'onFieldResidualOrder: 1,',
                   "this.add('-weather', 'Sandstorm', '[upkeep]'); if (this.field.isWeather('sandstorm')) this.eachEvent('Weather');",
                   'onWeather(target) { this.damage(target.baseMaxhp / 16); },',
                   "this.add('-weather', 'Sandstorm', '[from] ability: ' + effect.name, `[of] ${source}`);",
                   "this.add('-weather', 'none');"]),
    ('snowscape', ['duration: 5,', "if (source?.hasItem('icyrock')) { return 8; } return 5;",
                   'onModifyDefPriority: 10,',
                   "if (pokemon.hasType('Ice') && pokemon.effectiveWeather() === 'snowscape') { return this.modify(def, 1.5); }",
                   'onFieldResidualOrder: 1,',
                   "this.add('-weather', 'Snowscape', '[upkeep]'); if (this.field.isWeather('snowscape')) this.eachEvent('Weather');",
                   "this.add('-weather', 'Snowscape', '[from] ability: ' + effect.name, `[of] ${source}`);",
                   "this.add('-weather', 'none');"]),
)
# Snowscape has no onWeather: it does no damage (the hail condition does, and the format does not have Hail).
WEATHER_ABSENT = (('snowscape', 'onWeather'),)
WEATHER_BALL_FACTS = ("case 'sandstorm': move.type = 'Rock'; break; case 'hail': case 'snowscape': move.type = 'Ice'; break;",
                      "case 'sandstorm': move.basePower *= 2; break; case 'hail': case 'snowscape': move.basePower *= 2; break;")


def check_g56_facts(conditions_ts, moves_ts):
    """Step G56: the lockedmove condition and the three moves are the pinned text the turn code reads."""
    e = conditions_ts.entry('lockedmove')
    if e is None:
        fail('condition lockedmove not found')
    text = norm('\n'.join(e[2]))
    for fact in LOCKED_MOVE_CONDITION_FACTS:
        if norm(fact) not in text:
            fail('condition lockedmove: the entry no longer has "%s"' % fact)
    for mid in G56_LOCKED_MOVES:
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        text = norm('\n'.join(e[2]))
        for fact in LOCKED_MOVE_MOVE_FACTS[mid]:
            if norm(fact) not in text:
                fail('move %s: the entry no longer has "%s"' % (mid, fact))


def check_g58_facts(moves_ts):
    """Step G58: the Phantom Force entry is the pinned text the turn code reads (its charge, its volatile, its flags)."""
    e = moves_ts.entry('phantomforce')
    if e is None:
        fail('move phantomforce not found')
    text = norm('\n'.join(e[2]))
    for fact in G58_FACTS:
        if norm(fact) not in text:
            fail('move phantomforce: the entry no longer has "%s"' % fact)


def check_g90_facts(conditions_ts, moves_ts):
    """Step G90: the partiallytrapped condition and the six moves are the pinned text the turn code reads."""
    e = conditions_ts.entry('partiallytrapped')
    if e is None:
        fail('condition partiallytrapped not found')
    text = norm('\n'.join(e[2]))
    for fact in G90_CONDITION_FACTS:
        if norm(fact) not in text:
            fail('condition partiallytrapped: the entry no longer has "%s"' % fact)
    for mid in G90_MOVES:
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        text = norm('\n'.join(e[2]))
        for fact in G90_MOVE_FACTS:
            if norm(fact) not in text:
                fail('move %s: the entry no longer has "%s"' % (mid, fact))


def check_g96_facts(moves_ts):
    """Step G96: the Psychic Terrain entry is the pinned text the turn code reads (the terrain, the duration, the block)."""
    for mid, facts in G96_FACTS:
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('move %s: the entry no longer has "%s"' % (mid, fact))


def check_g78_facts(moves_ts):
    """Step G78: the Dragon Darts entry is the pinned text the turn code reads (its hits, its smartTarget, its target)."""
    e = moves_ts.entry('dragondarts')
    if e is None:
        fail('move dragondarts not found')
    text = norm('\n'.join(e[2]))
    for fact in G78_FACTS:
        if norm(fact) not in text:
            fail('move dragondarts: the entry no longer has "%s"' % fact)


def check_g88_facts(moves_ts):
    """Step G88: the Lash Out and Assurance entries are the pinned texts the turn code reads."""
    for mid, facts in sorted(G88_FACTS.items()):
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        text = norm('\n'.join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('move %s: the entry no longer has "%s"' % (mid, fact))


def check_g92_facts(moves_ts):
    """Step G92: the entries of the confusion, OHKO, Memento and Night Shade moves have the pinned texts that
    the turn code reads (data/moves.ts; the Champions mod has no override of any of them)."""
    for mid, facts in G92_FACTS:
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        text = norm('\n'.join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('move %s: the entry no longer has "%s"' % (mid, fact))


def check_g72b_facts(moves_ts):
    """Step G72b: the Alluring Voice and Dragon Cheer entries are the pinned texts the turn code reads."""
    for mid, facts in (('alluringvoice', G72B_FACTS), ('dragoncheer', G72B_DRAGON_CHEER_FACTS)):
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        text = norm('\n'.join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('move %s: the entry no longer has "%s"' % (mid, fact))


def check_g86_facts(moves_ts):
    """Step G86: the four handler entries are the pinned texts the turn code reads (the callbacks and the flags)."""
    for mid, facts in G86_FACTS:
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        text = norm('\n'.join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('move %s: the entry no longer has "%s"' % (mid, fact))


def check_g80_facts(moves_ts):
    """Step G80: the Psych Up and Ally Switch entries are the pinned texts the turn code reads (boosts, copied volatiles, the
    log lines; the swap, the priority, the counter and its draw)."""
    for mid, facts in (('psychup', G80_FACTS), ('allyswitch', G80_ALLYSWITCH_FACTS)):
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        text = norm('\n'.join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('move %s: the entry no longer has "%s"' % (mid, fact))


def check_g84_facts(moves_ts):
    """Step G84 (decision 0047): the Leech Seed and Curse base entries have the pinned texts the turn code reads."""
    for mid, facts in (('leechseed', G84_LEECH_FACTS), ('curse', G84_CURSE_FACTS)):
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        text = norm('\n'.join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('move %s: the entry no longer has "%s"' % (mid, fact))


def check_g82_facts(moves_ts):
    """Step G82: the Healing Wish entry has the pinned texts the turn code reads (data/moves.ts:8348-8382, decision 0045)."""
    e = moves_ts.entry('healingwish')
    if e is None:
        fail('move healingwish not found')
    text = norm('\n'.join(e[2]))
    for fact in G82_HEALING_WISH_FACTS:
        if norm(fact) not in text:
            fail('move healingwish: the entry no longer has "%s"' % fact)


def check_g76_facts(moves_ts):
    """Step G76: the Destiny Bond and Final Gambit entries have the pinned texts the turn code reads (data/moves.ts)."""
    for mid, facts in (('destinybond', G76_DESTINY_BOND_FACTS), ('finalgambit', G76_FINAL_GAMBIT_FACTS)):
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        text = norm('\n'.join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('move %s: the entry no longer has "%s"' % (mid, fact))


def check_weather_facts(conditions_ts, moves_ts):
    """Every fact of WEATHER_FACTS is in the pinned condition entry, the absent ones are not, and Weather Ball has the
    types and the doubling that the engine reads for every weather."""
    for cid, facts in WEATHER_FACTS + G32_WEATHER_FACTS:
        e = conditions_ts.entry(cid)
        if e is None:
            fail('condition %s not found' % cid)
        text = norm('\n'.join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('condition %s: the entry no longer has "%s"' % (cid, fact))
    for cid, name in WEATHER_ABSENT:
        if name in '\n'.join(conditions_ts.entry(cid)[2]):
            fail('condition %s now has %s' % (cid, name))
    e = moves_ts.entry('weatherball')
    if e is None:
        fail('move weatherball not found')
    text = norm('\n'.join(e[2]))
    for fact in WEATHER_BALL_FACTS:
        if norm(fact) not in text:
            fail('move weatherball: the entry no longer has "%s"' % fact)


# Step G15 (Psychic Terrain), what the engine hard-codes, as normalised texts that must be in the pinned entries:
#  - Expanding Force (data/moves.ts:4943-4965): 80 base power, a x1.5 chain modifier from the move's own onBasePower
#    (handler priority 0, so after the terrain's 5325/4096 at 6 and Helping Hand's 1.5 at 10) and the target class
#    allAdjacentFoes from onModifyMove, both for a user that isGrounded in Psychic Terrain; its base target is "normal";
#  - Psychic Terrain (data/moves.ts:14095-14150): the base power modifier and the priority block that Team C reads;
#  - Psychic Seed (data/items.ts:4903-4922) is Grassy Seed (data/items.ts:2595-2614) for the other terrain and the Special
#    Defense instead of the Defense: the same switch-in priority, onStart and onTerrainChange, one boost of +1.
EXPANDING_FORCE_FACTS = (
    'basePower: 80,', 'category: "Special",', 'accuracy: 100,', 'priority: 0,', 'target: "normal",', 'type: "Psychic",',
    "onBasePower(basePower, source) { if (this.field.isTerrain('psychicterrain') && source.isGrounded()) { "
    "this.debug('terrain buff'); return this.chainModify(1.5); } },",
    "onModifyMove(move, source, target) { if (this.field.isTerrain('psychicterrain') && source.isGrounded()) { "
    "move.target = 'allAdjacentFoes'; } },")
PSYCHIC_TERRAIN_FACTS = (
    'onBasePowerPriority: 6,',
    "onBasePower(basePower, attacker, defender, move) { if (move.type === 'Psychic' && attacker.isGrounded() && "
    "!attacker.isSemiInvulnerable()) { this.debug('psychic terrain boost'); return this.chainModify([5325, 4096]); } },",
    'duration: 5,')
# Step G61, Dragonize (the Mega ability of Feraligatr, an "-ate" member of the ATE family, param Dragon): the pinned texts
# of its handlers, which are the -ate pattern of ATE_MODIFY_TYPE and ATE_BASE_POWER. The Champions entry only inherits it
# and lifts isNonstandard (champions/abilities.ts:14-17); no handler of its own.
G61_DRAGONIZE_FACTS = (
    "const noModifyType = [ 'judgment', 'multiattack', 'naturalgift', 'revelationdance', 'technoblast', 'terrainpulse', 'weatherball', ];",
    'onModifyTypePriority: -1,',
    'onBasePowerPriority: 23,',
    "move.type = 'Dragon';",
    'move.typeChangerBoosted = this.effect;',
    'if (move.typeChangerBoosted === this.effect) return this.chainModify([4915, 4096]);',
    'flags: {},',
)
# Step G61: the turn code's gates on Sheer Force (turn.c dfi_run_move_body and useMoveInner) are the pinned gates: the base
# gate on the user's AfterMoveSecondarySelf (Life Orb) and its Emergency Exit, the base and Champions gates on the
# target's Emergency Exit, and the Champions afterMoveSecondaryEvent that has no Sheer Force test at all (Red Card,
# Eject Button and the thaw of Scald run under Sheer Force).
G61_GATE_FACTS = (
    ('sim/battle-actions.ts', "if (!(move.hasSheerForce && pokemon.hasAbility('sheerforce')) && !move.flags['futuremove']) {"),
    ('sim/battle-actions.ts', "if (!(move.hasSheerForce && pokemon.hasAbility('sheerforce'))) {"),
    ('data/mods/champions/scripts.ts', "if (!(move.hasSheerForce && pokemon.hasAbility('sheerforce'))) {"),
)
G77_INHERIT_ONLY = ('leek',)
G59_SUNNY_FACTS = (
    "if (defender.effectiveWeather() !== 'sunnyday') return;",
    "if (move.type === 'Fire') { this.debug('Sunny Day fire boost'); return this.chainModify(1.5); }",
    "if (move.type === 'Water') { this.debug('Sunny Day water suppress'); return this.chainModify(0.5); }",
)


def check_g59_facts(abil_ts, champ_abil, pokemon_ts, conditions_ts):
    """Step G59: the texts of the six Mega abilities (G59_ABILITY_FACTS, through check_g34_facts), and the two sides of Mega Sol
    that the engine's refusal and modifier rest on (G59_POKEMON_FACTS, G59_SUNNY_FACTS) are in the pinned files, whitespace
    collapsed."""
    for src, facts in ((pokemon_ts, G59_POKEMON_FACTS), (conditions_ts, G59_SUNNY_FACTS)):
        text = norm(chr(10).join(src.lines))
        for fact in facts:
            if norm(fact) not in text:
                fail('%s: the pin no longer has "%s"' % (src.rel, fact))


def check_g79_facts(field_ts, battle_ts, actions_ts, conditions_ts):
    """Step G79: the Cloud Nine entry (G79_ABILITY_FACTS, through check_g34_facts) and the pinned lines of the suppression
    (G79_FIELD_FACTS: Field.suppressingWeather, the handler skips of singleEvent and runEvent, the Update of a Weather event,
    the holder's End at a switch-out and at a faint, and the weather's upkeep lines), whitespace collapsed."""
    srcs = {'field': field_ts, 'battle': battle_ts, 'battle-actions': actions_ts, 'conditions': conditions_ts}
    for name, facts in G79_FIELD_FACTS:
        text = norm(chr(10).join(srcs[name].lines))
        for fact in facts:
            if norm(fact) not in text:
                fail('%s: the pin no longer has "%s"' % (srcs[name].rel, fact))


def check_g32_entries(items_ts, champ_items, abil_ts, champ_abil, only=None):
    """Step G32: the ability and item entries that the turn code runs by id (G32_ENTRY_FACTS) have the pinned texts, whole;
    the Champions Eject Button is read from the mod's file. `only`: a tuple of such entries (the generator's tests)."""
    for kind, eid, champ, facts in (G32_ENTRY_FACTS + G33_ENTRY_FACTS if only is None else only):
        src = (champ_items if champ else items_ts) if kind == 'item' else (champ_abil if champ else abil_ts)
        e = src.entry(eid)
        if e is None:
            fail('%s %s not found' % (kind, eid))
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('%s %s: the entry no longer has "%s"' % (kind, eid, fact))


def check_g8_conditions(moves_ts, only=None):
    """The engine hard-codes the durations, orders and tests of the Throat Chop and Heal Block conditions (step G8), those of
    Aurora Veil (step G20) and the texts of G25_FACTS (the two terrains, Rising Voltage, Terrain Pulse): every one of them
    must be in the pinned entry, as one normalised text. `only`: a tuple of (move id, facts) to check instead of all of
    them (the generator's tests)."""
    for mid, facts in (G8_CONDITION_FACTS + G20_CONDITION_FACTS + G28_FACTS + G32_FACTS + G34_FACTS + G25_FACTS +
                       G33_FACTS + G38_FACTS + G39_FACTS + G37_FACTS + G44_FACTS + G48_FACTS + G55_FACTS + G54_FACTS + G64_FACTS + G62_FACTS + G68_FACTS if only is None else only):
        e = moves_ts.entry(mid)
        if e is None:
            fail('move %s not found' % mid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('move %s: the condition no longer has "%s"' % (mid, fact))
