#!/usr/bin/env python3
"""Refusal checks for gen_closure.py's move parser: a secondary effect the
tables do not model must fail instead of being encoded as something else.
The same for the family patterns of the pool tables (decision 0015): an item or
ability that deviates from the one pattern of its family must fail, and so must
one that follows a pattern without being listed as a member. And for the moves
and abilities of the formes: a learnset that is not one block of "9M" entries,
a learnset that the validator contradicts, an ability the pin does not release.
The texts copy the pinned data/moves.ts, data/items.ts, data/abilities.ts and
data/mods/champions/learnsets.ts layout, so no checkout is needed.

usage: python3 tools/datagen/test_gen_closure.py
"""
import io
import os
import unittest

import gen_closure

# Flame Charge at the pin (data/moves.ts) with its secondary as a slot.
MOVE = '''\tflamecharge: {
\t\tnum: 488,
\t\taccuracy: 100,
\t\tbasePower: 50,
\t\tcategory: "Physical",
\t\tname: "Flame Charge",
\t\tpp: 20,
\t\tpriority: 0,
\t\tflags: { contact: 1, protect: 1, mirror: 1, metronome: 1 },
%s
\t\ttarget: "normal",
\t\ttype: "Fire",
\t\tcontestType: "Cool",
\t},'''
# The pinned secondary: a Speed boost for the user, not the target.
SELF_BOOST = '''\t\tsecondary: {
\t\t\tchance: 100,
\t\t\tself: {
\t\t\t\tboosts: {
\t\t\t\t\tspe: 1,
\t\t\t\t},
\t\t\t},
\t\t},'''
TARGET_BOOST = '''\t\tsecondary: {
\t\t\tchance: 100,
\t\t\tboosts: {
\t\t\t\tspe: -1,
\t\t\t},
\t\t},'''
TWO_EFFECTS = '''\t\tsecondary: {
\t\t\tchance: 10,
\t\t\tstatus: 'brn',
\t\t\tvolatileStatus: 'flinch',
\t\t},'''
EMPTY = '\t\tsecondary: {}, // Sheer Force-boosted'


class TextSource(gen_closure.Source):
    """A Source over the test's own text, without the pin check."""

    def __init__(self, rel, text):
        self.rel, self.lines = rel, text.split('\n')


def parse(secondary, ext):
    base = TextSource('data/moves.ts', MOVE % secondary)
    champ = TextSource('data/mods/champions/moves.ts', '')
    return gen_closure.parse_move('flamecharge', base, champ, ext)


class Secondary(unittest.TestCase):
    def assert_refused(self, secondary, message):
        for ext in (False, True):
            with self.subTest(ext=ext):
                with self.assertRaises(SystemExit) as cm:
                    parse(secondary, ext)
                self.assertEqual(cm.exception.code, 'gen_closure: move flamecharge: ' + message)

    def test_self_boost_is_refused(self):
        self.assert_refused(SELF_BOOST, 'secondary self effects are not supported')

    def test_two_effects_are_refused(self):
        self.assert_refused(TWO_EFFECTS, 'unknown secondary')

    def test_empty_secondary_is_refused(self):
        self.assert_refused(EMPTY, 'unknown secondary')

    def test_target_boost_is_encoded(self):
        # Control: the same move text with a modelled secondary parses.
        want = [0] * len(gen_closure.BOOSTS)
        want[gen_closure.BOOSTS.index('spe')] = -1
        for ext in (False, True):
            with self.subTest(ext=ext):
                rec = parse(TARGET_BOOST, ext)
                self.assertEqual((rec['sec_chance'], rec['sec_kind'], rec['boost_role'], rec['boosts']),
                                 (100, 1, gen_closure.BOOST_ROLE['SECONDARY_TARGET'], want))


# ---- the family patterns of the pool tables (entries as in data/items.ts and data/abilities.ts at the pin) ----
def entry(rid, *lines):
    return '\t%s: {\n%s\n\t},' % (rid, '\n'.join('\t\t' + line for line in lines))


BOOSTER = entry('blackbelt', 'name: "Black Belt",', 'spritenum: 32,', 'fling: {', '\tbasePower: 30,', '},',
                'onBasePowerPriority: 15,', 'onBasePower(basePower, user, target, move) {',
                "\tif (move && move.type === 'Fighting') {", '\t\treturn this.chainModify([4915, 4096]);', '\t}', '},',
                'num: 241,', 'gen: 2,')
# Magnet's handler has no `move &&` guard; nothing else differs.
BOOSTER_UNGUARDED = BOOSTER.replace('move && ', '')
SUPER_EFFECTIVE = "move.type === '%s' && target.getMoveHitData(move).typeMod > 0"


def berry(rid, name, type_, condition=SUPER_EFFECTIVE):
    return entry(rid, 'name: "%s",' % name, 'spritenum: 311,', 'isBerry: true,', 'naturalGift: {', '\tbasePower: 80,',
                 '\ttype: "%s",' % type_, '},', 'onSourceModifyDamage(damage, source, target, move) {',
                 '\tif (' + (condition % type_) + ') {',
                 "\t\tconst hitSub = target.volatiles['substitute'] && !move.flags['bypasssub'] && "
                 "!(move.infiltrates && this.gen >= 6);", '\t\tif (hitSub) return;', '',
                 '\t\tif (target.eatItem()) {', "\t\t\tthis.debug('-50% reduction');",
                 "\t\t\tthis.add('-enditem', target, this.effect, '[weaken]');", '\t\t\treturn this.chainModify(0.5);',
                 '\t\t}', '\t}', '},', 'onEat() { },', 'num: 184,', 'gen: 4,')


OCCA = berry('occaberry', 'Occa Berry', 'Fire')
# Chilan Berry: any Normal hit, with the substitute test written the other way round.
CHILAN = entry('chilanberry', 'name: "Chilan Berry",', 'spritenum: 66,', 'isBerry: true,', 'naturalGift: {',
               '\tbasePower: 80,', '\ttype: "Normal",', '},', 'onSourceModifyDamage(damage, source, target, move) {',
               '\tif (', "\t\tmove.type === 'Normal' &&",
               "\t\t(!target.volatiles['substitute'] || move.flags['bypasssub'] || (move.infiltrates && this.gen >= 6))",
               '\t) {', '\t\tif (target.eatItem()) {', "\t\t\tthis.debug('-50% reduction');",
               "\t\t\tthis.add('-enditem', target, this.effect, '[weaken]');", '\t\t\treturn this.chainModify(0.5);',
               '\t\t}', '\t}', '},', 'onEat() { },', 'num: 200,', 'gen: 4,')


def ate(rid, name, type_):
    return entry(rid, 'onModifyTypePriority: -1,', 'onModifyType(move, pokemon) {', '\tconst noModifyType = [',
                 "\t\t'judgment', 'multiattack', 'naturalgift', 'revelationdance', 'technoblast', 'terrainpulse', 'weatherball',",
                 '\t];', "\tif (move.type === 'Normal' && (!noModifyType.includes(move.id) || this.activeMove?.isMax) &&",
                 "\t\t!(move.isZ && move.category !== 'Status') && !(move.name === 'Tera Blast' && pokemon.terastallized)) {",
                 "\t\tmove.type = '%s';" % type_, '\t\tmove.typeChangerBoosted = this.effect;', '\t}', '},',
                 'onBasePowerPriority: 23,', 'onBasePower(basePower, pokemon, target, move) {',
                 '\tif (move.typeChangerBoosted === this.effect) return this.chainModify([4915, 4096]);', '},',
                 'flags: {},', 'name: "%s",' % name, 'rating: 4,', 'num: 182,')


def pinch(rid, name, type_, divisor='3', spa_type=None):
    def handler(callback, kind):
        return ['%s(atk, attacker, defender, move) {' % callback,
                "\tif (move.type === '%s' && attacker.hp <= attacker.maxhp / %s) {" % (kind, divisor),
                "\t\tthis.debug('%s boost');" % name, '\t\treturn this.chainModify(1.5);', '\t}', '},']
    return entry(rid, 'onModifyAtkPriority: 5,', *handler('onModifyAtk', type_), 'onModifySpAPriority: 5,',
                 *handler('onModifySpA', spa_type or type_), 'flags: {},', 'name: "%s",' % name, 'rating: 2,', 'num: 66,')


def setter(rid, name, call, guard=''):
    return entry(rid, 'onStart(source) {', *(['\t' + guard] if guard else []), '\t' + call, '},', 'flags: {},',
                 'name: "%s",' % name, 'rating: 4,', 'num: 2,')


GUARD = "if (source.species.id === 'kyogre' && source.item === 'blueorb') return;"
DRIZZLE = setter('drizzle', 'Drizzle', "this.field.setWeather('raindance');", GUARD)
GRASSY_SURGE = setter('grassysurge', 'Grassy Surge', "this.field.setTerrain('grassyterrain');")
INTIMIDATE = entry('intimidate', 'onStart(pokemon) {', "\tthis.add('-ability', pokemon, 'Intimidate', 'boost');", '},',
                   'flags: {},', 'name: "Intimidate",', 'rating: 3.5,', 'num: 22,')


class PoolFamilies(unittest.TestCase):
    def derive(self, text, expected, champ='', what='item'):
        rid = text.split(':')[0].strip()
        if what == 'item':
            src, ch = TextSource('data/items.ts', text), TextSource('data/mods/champions/items.ts', champ)
            matchers = gen_closure.ITEM_MATCHERS
        else:
            src, ch = TextSource('data/abilities.ts', text), TextSource('data/mods/champions/abilities.ts', champ)
            matchers = gen_closure.ABILITY_MATCHERS
        return gen_closure.derive_family(src, ch, rid, expected, matchers, what)

    def refused(self, text, expected, message, champ='', what='item'):
        with self.assertRaises(SystemExit) as cm:
            self.derive(text, expected, champ, what)
        self.assertIn(message, str(cm.exception.code))

    # Type boosters.
    def test_a_type_booster_gives_its_type(self):
        for text in (BOOSTER, BOOSTER_UNGUARDED):
            self.assertEqual(self.derive(text, 'TYPE_BOOSTER'), ('TYPE_BOOSTER', 'Fighting'))

    def test_a_type_booster_that_deviates_is_refused(self):
        for what, text in (('modifier', BOOSTER.replace('4915', '4916')),
                           ('priority', BOOSTER.replace('onBasePowerPriority: 15', 'onBasePowerPriority: 14')),
                           ('comparison', BOOSTER.replace('===', '!==')),
                           ('extra callback', BOOSTER.replace('\t\tnum: 241,', '\t\tonTakeItem() { },\n\t\tnum: 241,')),
                           ('extra data', BOOSTER.replace('\t\tnum: 241,', '\t\tisNonstandard: "Past",\n\t\tnum: 241,'))):
            with self.subTest(what):
                self.refused(text, 'TYPE_BOOSTER', 'blackbelt is listed as TYPE_BOOSTER but deviates')

    # Resist berries.
    def test_a_resist_berry_gives_its_type(self):
        self.assertEqual(self.derive(OCCA, 'RESIST_BERRY'), ('RESIST_BERRY', 'Fire'))

    def test_the_normal_berry_is_the_only_variant(self):
        self.assertEqual(self.derive(CHILAN, 'RESIST_BERRY'), ('RESIST_BERRY', 'Normal'))
        # The variant text on another berry, and the super effective text on Chilan Berry, are refused.
        self.refused(CHILAN.replace('chilanberry', 'occaberry').replace('Normal', 'Fire'), 'RESIST_BERRY',
                     'occaberry is listed as RESIST_BERRY but deviates')
        self.refused(berry('chilanberry', 'Chilan Berry', 'Normal'), 'RESIST_BERRY',
                     'chilanberry is listed as RESIST_BERRY but deviates')

    def test_a_resist_berry_that_deviates_is_refused(self):
        for what, text in (('halving', OCCA.replace('chainModify(0.5)', 'chainModify(0.75)')),
                           ('no super effective condition', berry('occaberry', 'Occa Berry', 'Fire', "move.type === '%s'")),
                           ('natural gift type', OCCA.replace('type: "Fire"', 'type: "Water"')),
                           ('eaten twice', OCCA.replace('target.eatItem()', 'target.eatItem() && target.eatItem()')),
                           ('not a berry', OCCA.replace('isBerry: true', 'isBerry: false'))):
            with self.subTest(what):
                self.refused(text, 'RESIST_BERRY', 'occaberry is listed as RESIST_BERRY but deviates')

    # An id that follows a pattern must be listed; one that is not a member has no family.
    def test_an_unlisted_member_is_refused(self):
        self.refused(BOOSTER, 'NONE', 'blackbelt follows the TYPE_BOOSTER pattern but decision 0015 does not list it')
        self.refused(OCCA, 'NONE', 'occaberry follows the RESIST_BERRY pattern but decision 0015 does not list it')
        self.refused(ate('pixilate', 'Pixilate', 'Fairy'), 'NONE', 'pixilate follows the ATE pattern', what='ability')
        self.refused(GRASSY_SURGE, 'NONE', 'grassysurge follows the TERRAIN_SETTER pattern', what='ability')

    def test_an_id_that_is_no_member_has_no_family(self):
        self.assertEqual(self.derive(INTIMIDATE, 'NONE', what='ability'), ('NONE', None))
        self.assertEqual(self.derive(BOOSTER.replace('onBasePowerPriority: 15', 'onBasePowerPriority: 14'), 'NONE'),
                         ('NONE', None))

    def test_a_listed_id_that_is_no_member_is_refused(self):
        self.refused(INTIMIDATE, 'WEATHER_SETTER', 'intimidate is listed as WEATHER_SETTER but deviates', what='ability')

    def test_the_champions_mod_may_only_change_isnonstandard(self):
        champ = entry('blackbelt', 'inherit: true,', 'isNonstandard: null,')
        self.assertEqual(self.derive(BOOSTER, 'TYPE_BOOSTER', champ), ('TYPE_BOOSTER', 'Fighting'))
        changed = entry('blackbelt', 'inherit: true,', 'onBasePower() { },')
        self.refused(BOOSTER, 'TYPE_BOOSTER', "blackbelt: the champions mod changes ['onBasePower']", changed)

    # "-ate" abilities.
    def test_an_ate_ability_gives_its_type(self):
        self.assertEqual(self.derive(ate('pixilate', 'Pixilate', 'Fairy'), 'ATE', what='ability'), ('ATE', 'Fairy'))

    def test_an_ate_ability_that_deviates_is_refused(self):
        text = ate('pixilate', 'Pixilate', 'Fairy')
        for what, changed in (('modifier', text.replace('4915', '5325')),
                              ('priority', text.replace('onBasePowerPriority: 23', 'onBasePowerPriority: 21')),
                              ('type priority', text.replace('onModifyTypePriority: -1', 'onModifyTypePriority: 1')),
                              ('exceptions', text.replace("'weatherball',", '')),
                              ('source type', text.replace("move.type === 'Normal'", "move.type === 'Fire'"))):
            with self.subTest(what):
                self.refused(changed, 'ATE', 'pixilate is listed as ATE but deviates', what='ability')

    # Pinch abilities.
    def test_a_pinch_ability_gives_its_type(self):
        self.assertEqual(self.derive(pinch('blaze', 'Blaze', 'Fire'), 'PINCH', what='ability'), ('PINCH', 'Fire'))

    def test_a_pinch_ability_that_deviates_is_refused(self):
        text = pinch('blaze', 'Blaze', 'Fire')
        for what, changed in (('threshold', pinch('blaze', 'Blaze', 'Fire', '2')),
                              ('multiplier', text.replace('chainModify(1.5)', 'chainModify(2)')),
                              ('label', text.replace('Blaze boost', 'Torrent boost')),
                              ('two types', pinch('blaze', 'Blaze', 'Fire', spa_type='Water'))):
            with self.subTest(what):
                self.refused(changed, 'PINCH', 'blaze is listed as PINCH but deviates', what='ability')

    # Weather and terrain setters.
    def test_a_weather_setter_gives_its_weather(self):
        self.assertEqual(self.derive(DRIZZLE, 'WEATHER_SETTER', what='ability'), ('WEATHER_SETTER', 'raindance'))

    def test_a_weather_setter_needs_the_primal_guard_of_its_weather(self):
        # Without the guard, with the guard of the other weather, and with a weather that has no state code.
        self.refused(setter('drizzle', 'Drizzle', "this.field.setWeather('raindance');"), 'WEATHER_SETTER',
                     'drizzle is listed as WEATHER_SETTER but deviates', what='ability')
        self.refused(DRIZZLE.replace(GUARD, "if (source.species.id === 'groudon' && source.item === 'redorb') return;"),
                     'WEATHER_SETTER', 'drizzle is listed as WEATHER_SETTER but deviates', what='ability')
        self.refused(setter('deltastream', 'Delta Stream', "this.field.setWeather('deltastream');"), 'WEATHER_SETTER',
                     'deltastream is listed as WEATHER_SETTER but deviates', what='ability')

    def test_the_sand_and_snow_setters_give_their_weather(self):
        # Sand Stream and Snow Warning have no Primal guard: one that is there, or one of the other weather, is a
        # deviation (the guard of a weather that has none is not (None, None)).
        sand = setter('sandstream', 'Sand Stream', "this.field.setWeather('sandstorm');")
        snow = setter('snowwarning', 'Snow Warning', "this.field.setWeather('snowscape');")
        self.assertEqual(self.derive(sand, 'WEATHER_SETTER', what='ability'), ('WEATHER_SETTER', 'sandstorm'))
        self.assertEqual(self.derive(snow, 'WEATHER_SETTER', what='ability'), ('WEATHER_SETTER', 'snowscape'))
        self.assertEqual((gen_closure.WEATHER_CODES['sandstorm'], gen_closure.WEATHER_CODES['snowscape']),
                         (('SAND', 3), ('SNOW', 4)))
        self.refused(setter('sandstream', 'Sand Stream', "this.field.setWeather('sandstorm');", GUARD),
                     'WEATHER_SETTER', 'sandstream is listed as WEATHER_SETTER but deviates', what='ability')

    def test_a_terrain_setter_gives_its_terrain(self):
        self.assertEqual(self.derive(GRASSY_SURGE, 'TERRAIN_SETTER', what='ability'), ('TERRAIN_SETTER', 'grassyterrain'))
        # Step G25: Electric Surge is a member (the codes of the column are the engine's DFI_TERRAIN_* values).
        self.assertEqual(self.derive(setter('electricsurge', 'Electric Surge', "this.field.setTerrain('electricterrain');"),
                                     'TERRAIN_SETTER', what='ability'), ('TERRAIN_SETTER', 'electricterrain'))
        self.refused(setter('electricsurge', 'Electric Surge', "this.field.setTerrain('foggyterrain');"),
                     'TERRAIN_SETTER', 'electricsurge is listed as TERRAIN_SETTER but deviates', what='ability')

    def test_the_members_of_the_decision_are_what_the_tables_list(self):
        # 18 type boosters and 18 resist berries, three "-ate", four pinch, four weather and three terrain setters.
        self.assertEqual((len(gen_closure.ITEM_MEMBERS['TYPE_BOOSTER']), len(gen_closure.ITEM_MEMBERS['RESIST_BERRY'])),
                         (18, 18))
        self.assertEqual({k: len(v) for k, v in gen_closure.ABILITY_MEMBERS.items()},
                         {'ATE': 3, 'PINCH': 4, 'WEATHER_SETTER': 4, 'TERRAIN_SETTER': 3})
        every = gen_closure.POOL_ITEMS + gen_closure.POOL_ABILITIES
        self.assertEqual(len(every), len(set(every)))
        self.assertEqual((len(gen_closure.POOL_ITEMS), len(gen_closure.POOL_ABILITIES)), (33, 5))


# ---- the learnable moves and the legal abilities of the formes ----
def learnset(fid, *moves, after=()):
    return entry(fid, 'learnset: {', *['\t%s: ["9M"],' % m for m in moves], '},', *after)


class FormeLegal(unittest.TestCase):
    POOL_MOVES = ['woodhammer', 'fakeout', 'protect']
    POOL_ABILITIES = ['grassysurge', 'overgrow', 'megaability']
    ABILITIES = (entry('grassysurge', 'name: "Grassy Surge",') + '\n' + entry('overgrow', 'name: "Overgrow",') + '\n' +
                 entry('megaability', 'name: "Mega Ability",'))

    def base(self, **extra):
        # Set: Wood Hammer and Fake Out with Grassy Surge (pool ability 0); the pokedex declares Overgrow and Grassy Surge.
        fo = {'id': 'rillaboom', 'is_mega': 0, 'ability': 0, 'abilities': ['overgrow', 'grassysurge'], 'set_moves': [0, 1]}
        fo.update(extra)
        return fo

    def species(self, **extra):
        rec = {'abilities_legal': ['overgrow', 'grassysurge'], 'moves': ['woodhammer', 'fakeout', 'protect', 'tackle']}
        rec.update(extra)
        return {'rillaboom': rec}

    def run_one(self, formes, species, learn_text=None, abilities=None, champ='', pool_abilities=None):
        learn = TextSource('data/mods/champions/learnsets.ts',
                           learn_text if learn_text is not None else
                           learnset('rillaboom', 'woodhammer', 'fakeout', 'protect', 'tackle'))
        abil = TextSource('data/abilities.ts', abilities if abilities is not None else self.ABILITIES)
        return gen_closure.forme_legal(formes, self.POOL_MOVES, pool_abilities or self.POOL_ABILITIES, learn, species, abil,
                                       TextSource('data/mods/champions/abilities.ts', champ))

    def refused(self, message, *args, **kwargs):
        with self.assertRaises(SystemExit) as cm:
            self.run_one(*args, **kwargs)
        self.assertIn(message, str(cm.exception.code))

    # The learnset.
    def test_a_learnset_gives_its_moves(self):
        learn = TextSource('data/mods/champions/learnsets.ts', learnset('rillaboom', 'woodhammer', 'tackle'))
        self.assertEqual(gen_closure.learnset_moves(learn, 'rillaboom'), {'woodhammer', 'tackle'})

    def test_a_learnset_may_start_with_inherit(self):
        # Floette-Eternal's Champions entry: the mod keeps the other fields of the base entry.
        learn = TextSource('data/mods/champions/learnsets.ts',
                           entry('floetteeternal', 'inherit: true,', 'learnset: {', '\tprotect: ["9M"],', '},'))
        self.assertEqual(gen_closure.learnset_moves(learn, 'floetteeternal'), {'protect'})
        for what, text in (('inherit false', entry('floetteeternal', 'inherit: false,', 'learnset: {', '\tprotect: ["9M"],', '},')),
                           ('inherit twice', entry('floetteeternal', 'inherit: true,', 'inherit: true,', 'learnset: {',
                                                   '\tprotect: ["9M"],', '},')),
                           ('inherit after', entry('floetteeternal', 'learnset: {', '\tprotect: ["9M"],', '},', 'inherit: true,')),
                           ('another field', entry('floetteeternal', 'inherit: true,', 'eventOnly: true,', 'learnset: {',
                                                   '\tprotect: ["9M"],', '},'))):
            with self.subTest(what):
                with self.assertRaises(SystemExit):
                    gen_closure.learnset_moves(TextSource('data/mods/champions/learnsets.ts', text), 'floetteeternal')

    def test_a_learnset_that_is_not_one_block_of_9m_is_refused(self):
        for what, text in (('level-up', learnset('rillaboom', 'woodhammer').replace('["9M"]', '["9L1"]')),
                           ('two sources', learnset('rillaboom', 'woodhammer').replace('["9M"]', '["9M", "9S0"]')),
                           ('a move twice', learnset('rillaboom', 'woodhammer', 'woodhammer')),
                           ('another block', learnset('rillaboom', 'woodhammer', after=('eventData: [],',))),
                           ('no block', entry('rillaboom', 'eventData: [],'))):
            with self.subTest(what):
                learn = TextSource('data/mods/champions/learnsets.ts', text)
                with self.assertRaises(SystemExit):
                    gen_closure.learnset_moves(learn, 'rillaboom')

    def test_a_forme_without_a_learnset_is_refused(self):
        learn = TextSource('data/mods/champions/learnsets.ts', learnset('other', 'woodhammer'))
        with self.assertRaises(SystemExit) as cm:
            gen_closure.learnset_moves(learn, 'rillaboom')
        self.assertIn('rillaboom has no champions learnset', str(cm.exception.code))

    # The moves and abilities of a base forme.
    def test_the_moves_and_abilities_of_a_base_forme(self):
        (fl,) = self.run_one([self.base()], self.species())
        self.assertEqual(fl['learnable'], [0b111])  # one bit per pool move, in pool order
        self.assertEqual(fl['moves'], ['woodhammer', 'fakeout', 'protect'])
        self.assertEqual(fl['abilities'], [1, 0])  # Overgrow, Grassy Surge: the pokedex's slot order

    def test_the_validator_filters_the_declared_abilities(self):
        # A declared ability that the validator does not allow (Greninja's Battle Bond) is dropped; one outside the
        # pool is dropped from the list.
        fo = self.base(abilities=['overgrow', 'grassysurge', 'battlebond', 'reckless'])
        (fl,) = self.run_one([fo], self.species(abilities_legal=['overgrow', 'grassysurge', 'reckless']),
                             abilities=self.ABILITIES + '\n' + entry('reckless', 'name: "Reckless",'))
        self.assertEqual(fl['abilities'], [1, 0])

    def test_a_learnset_that_the_validator_contradicts_is_refused(self):
        self.refused('rillaboom: the learnset and the validator disagree on [\'protect\']', [self.base()],
                     self.species(moves=['woodhammer', 'fakeout', 'tackle']))
        # The other way: the validator allows a move that the learnset does not list.
        self.refused('the learnset and the validator disagree', [self.base()], self.species(),
                     learn_text=learnset('rillaboom', 'woodhammer', 'fakeout', 'tackle'))

    def test_a_set_that_is_not_legal_is_refused(self):
        self.refused('a move of its set is not learnable', [self.base()],
                     self.species(moves=['woodhammer', 'protect']),
                     learn_text=learnset('rillaboom', 'woodhammer', 'protect'))
        self.refused('its set ability is not one of its legal abilities', [self.base()],
                     self.species(abilities_legal=['overgrow']))

    def test_more_than_three_abilities_are_refused(self):
        fo = self.base(abilities=['grassysurge', 'overgrow', 'megaability', 'x'])
        species = self.species(abilities_legal=['grassysurge', 'overgrow', 'megaability', 'x'])
        abilities = self.ABILITIES + '\n' + entry('x', 'name: "X",')
        self.refused('more than 3 legal abilities', [fo], species, abilities=abilities,
                     pool_abilities=self.POOL_ABILITIES + ['x'])
        # The list is cut to the pool: a fourth ability outside it is no reason to refuse.
        (fl,) = self.run_one([fo], species, abilities=abilities)
        self.assertEqual(fl['abilities'], [0, 1, 2])

    def test_a_forme_that_the_research_does_not_know_is_refused(self):
        self.refused('rillaboom is not a species of', [self.base()], {})

    # Mega formes.
    def mega(self, **extra):
        fo = {'id': 'rillaboommega', 'is_mega': 1, 'ability': 2, 'abilities': ['megaability'], 'set_moves': []}
        fo.update(extra)
        return fo

    def mega_species(self, **extra):
        rec = {'abilities_legal': ['megaability'], 'moves': []}
        rec.update(extra)
        return {'rillaboommega': rec}

    def test_a_mega_forme_has_no_moves_and_its_one_ability(self):
        (fl,) = self.run_one([self.mega()], self.mega_species())
        self.assertEqual((fl['learnable'], fl['abilities'], fl['moves']), ([0], [2], []))

    def test_a_mega_forme_with_two_abilities_or_none_in_the_pool_is_refused(self):
        self.refused('a Mega forme must have exactly its one legal ability', [self.mega(abilities=['megaability', 'overgrow'])],
                     self.mega_species(abilities_legal=['megaability', 'overgrow']))
        self.refused('a Mega forme must have exactly its one legal ability', [self.mega()],
                     self.mega_species(abilities_legal=[]))

    def test_an_ability_that_the_pin_does_not_release_is_refused(self):
        # Lucario-Mega-Z's Aura Guard: legal for the validator, tagged Future in the data. The Champions mod may release it.
        future = self.ABILITIES.replace('name: "Mega Ability",', 'isNonstandard: "Future",\n\t\tname: "Mega Ability",')
        self.refused('ability megaability is tagged Future', [self.mega()], self.mega_species(), abilities=future)
        champ = entry('megaability', 'inherit: true,', 'isNonstandard: null,')
        (fl,) = self.run_one([self.mega()], self.mega_species(), abilities=future, champ=champ)
        self.assertEqual(fl['abilities'], [2])


# ---- the rows of step G2: moves with a handler of their own, and the flags that the tables ignore ----
def move_entry(mid, name, *lines, flags='protect: 1', category='Status', target='normal', type_='Water', pp=10,
               base_power=0):
    return '\t%s: {\n%s\n\t},' % (mid, '\n'.join('\t\t' + line for line in [
        'num: 1,', 'accuracy: 100,', 'basePower: %d,' % base_power, 'category: "%s",' % category, 'name: "%s",' % name,
        'pp: %d,' % pp, 'priority: 0,', 'flags: { %s },' % flags] + list(lines) + [
        'target: "%s",' % target, 'type: "%s",' % type_]))


SOAK = move_entry('soak', 'Soak', 'onHit(target) {', "\tif (target.getTypes().join() === 'Water') {", '\t\treturn null;', '\t}',
                  '},', pp=20, flags='protect: 1, allyanim: 1')
SCALD = move_entry('scald', 'Scald', 'thawsTarget: true,', 'secondary: {', '\tchance: 30,', "\tstatus: 'brn',", '},',
                   category='Special', base_power=80, pp=15, flags='protect: 1, defrost: 1')
RECOVER = move_entry('recover', 'Recover', 'heal: [1, 2],', pp=5, flags='snatch: 1, heal: 1', target='self',
                     type_='Normal')
PSYCHIC_NOISE = move_entry('psychicnoise', 'Psychic Noise', 'secondary: {', '\tchance: 100,',
                           "\tvolatileStatus: 'healblock',", '},', category='Special', base_power=75, type_='Psychic',
                           flags='protect: 1, sound: 1')
THROAT_CHOP = move_entry('throatchop', 'Throat Chop', 'condition: {', '\tduration: 2,', '},', 'secondary: {',
                         '\tchance: 100,', '\tonHit(target) {', "\t\ttarget.addVolatile('throatchop');", '\t},', '},',
                         category='Physical', base_power=80, pp=15, type_='Dark', flags='contact: 1, protect: 1')
EXPANDING_FORCE = move_entry('expandingforce', 'Expanding Force', 'onBasePower(basePower, source) {',
                             "\tif (this.field.isTerrain('psychicterrain') && source.isGrounded()) {",
                             "\t\tthis.debug('terrain buff');", '\t\treturn this.chainModify(1.5);', '\t}', '},',
                             'onModifyMove(move, source, target) {',
                             "\tif (this.field.isTerrain('psychicterrain') && source.isGrounded()) {",
                             "\t\tmove.target = 'allAdjacentFoes';", '\t}', '},', category='Special', base_power=80,
                             type_='Psychic', flags='protect: 1, mirror: 1, metronome: 1')
ICE_PUNCH = move_entry('icepunch', 'Ice Punch', 'secondary: {', '\tchance: 10,', "\tstatus: 'frz',", '},',
                       category='Physical', base_power=75, pp=15, type_='Ice', flags='contact: 1, protect: 1, punch: 1')


KNOCK_OFF = move_entry(
    'knockoff', 'Knock Off',
    'onBasePower(basePower, source, target, move) {', '\tconst item = target.getItem();',
    "\tif (!this.singleEvent('TakeItem', item, target.itemState, target, target, move, item)) return;",
    '\tif (item.id) {', '\t\treturn this.chainModify(1.5);', '\t}', '},',
    'onAfterHit(target, source) {', '\tconst item = target.takeItem();', '\tif (item) {',
    "\t\tthis.add('-enditem', target, item.name, '[from] move: Knock Off', `[of] ${source}`);", '\t}', '},',
    category='Physical', base_power=65, pp=20, type_='Dark', flags='contact: 1, protect: 1, mirror: 1, metronome: 1')

AURORA_VEIL = move_entry(
    'auroraveil', 'Aurora Veil', "sideCondition: 'auroraveil',", 'onTry() {', "\treturn this.field.isWeather(['hail', 'snowscape']);",
    '},', 'condition: {', '\tduration: 5,', '},', pp=20, flags='snatch: 1, metronome: 1', target='allySide', type_='Ice')
GLAIVE_RUSH = move_entry(
    'glaiverush', 'Glaive Rush', 'self: {', "\tvolatileStatus: 'glaiverush',", '},', 'condition: {', '\tnoCopy: true,',
    '\tonStart(pokemon) {', "\t\tthis.add('-singlemove', pokemon, 'Glaive Rush', '[silent]');", '\t},',
    '\tonAccuracy() {', '\t\treturn true;', '\t},', '\tonSourceModifyDamage() {', '\t\treturn this.chainModify(2);', '\t},',
    '\tonBeforeMovePriority: 100,', '\tonBeforeMove(pokemon) {',
    "\t\tthis.debug('removing Glaive Rush drawback before attack');", "\t\tpokemon.removeVolatile('glaiverush');", '\t},', '},',
    category='Physical', base_power=120, pp=5, type_='Dragon', flags='contact: 1, protect: 1, mirror: 1, metronome: 1')
PERISH_SONG = move_entry(
    'perishsong', 'Perish Song', 'onHitField(target, source, move) {', '\tlet result = false;', '\tlet message = false;',
    '\tfor (const pokemon of this.getAllActive()) {',
    "\t\tif (this.runEvent('Invulnerability', pokemon, source, move) === false) {",
    "\t\t\tthis.add('-miss', source, pokemon);", '\t\t\tresult = true;',
    "\t\t} else if (this.runEvent('TryHit', pokemon, source, move) === null) {", '\t\t\tresult = true;',
    "\t\t} else if (!pokemon.volatiles['perishsong']) {", "\t\t\tpokemon.addVolatile('perishsong');",
    "\t\t\tthis.add('-start', pokemon, 'perish3', '[silent]');", '\t\t\tresult = true;', '\t\t\tmessage = true;',
    '\t\t}', '\t}', '\tif (!result) return false;', "\tif (message) this.add('-fieldactivate', 'move: Perish Song');", '},',
    'condition: {', '\tduration: 4,', '\tonEnd(target) {', "\t\tthis.add('-start', target, 'perish0');", '\t\ttarget.faint();', '\t},',
    '\tonResidualOrder: 24,', '\tonResidual(pokemon) {', "\t\tconst duration = pokemon.volatiles['perishsong'].duration;",
    "\t\tthis.add('-start', pokemon, `perish${duration}`);", '\t},', '},', pp=5, flags='sound: 1, distance: 1, bypasssub: 1, metronome: 1',
    target='all', type_='Normal')
COACHING = move_entry('coaching', 'Coaching', 'boosts: {', '\tatk: 1,', '\tdef: 1,', '},', target='adjacentAlly', type_='Fighting',
                      flags='bypasssub: 1, allyanim: 1, metronome: 1')

DISABLE = move_entry(
    'disable', 'Disable', "volatileStatus: 'disable',",
    'onTryHit(target) {',
    "\tif (!target.lastMove || target.lastMove.isZOrMaxPowered || target.lastMove.isMax || target.lastMove.id === 'struggle') {",
    '\t\treturn false;',
    '\t}',
    '},',
    'condition: {',
    '\tduration: 5,',
    "\tnoCopy: true, // doesn't get copied by Baton Pass",
    '\tonStart(pokemon, source, effect) {',
    "\t\t// The target hasn't taken its turn, or Cursed Body activated and the move was not used through Dancer or Instruct",
    '\t\tif (',
    '\t\t\tthis.queue.willMove(pokemon) ||',
    '\t\t\t(pokemon === this.activePokemon && this.activeMove && !this.activeMove.isExternal)',
    '\t\t) {',
    '\t\t\tthis.effectState.duration!--;',
    '\t\t}',
    '\t\tif (!pokemon.lastMove) {',
    "\t\t\tthis.debug(`Pokemon hasn't moved yet`);",
    '\t\t\treturn false;',
    '\t\t}',
    '\t\tfor (const moveSlot of pokemon.moveSlots) {',
    '\t\t\tif (moveSlot.id === pokemon.lastMove.id) {',
    '\t\t\t\tif (!moveSlot.pp) {',
    "\t\t\t\t\tthis.debug('Move out of PP');",
    '\t\t\t\t\treturn false;',
    '\t\t\t\t}',
    '\t\t\t}',
    '\t\t}',
    "\t\tif (effect.effectType === 'Ability') {",
    "\t\t\tthis.add('-start', pokemon, 'Disable', pokemon.lastMove.name, '[from] ability: ' + effect.name, `[of] ${source}`);",
    '\t\t} else {',
    "\t\t\tthis.add('-start', pokemon, 'Disable', pokemon.lastMove.name);",
    '\t\t}',
    '\t\tthis.effectState.move = pokemon.lastMove.id;',
    '\t},',
    '\tonResidualOrder: 17,',
    '\tonEnd(pokemon) {',
    "\t\tthis.add('-end', pokemon, 'Disable');",
    '\t},',
    '\tonBeforeMovePriority: 7,',
    '\tonBeforeMove(attacker, defender, move) {',
    '\t\tif (!(move.isZ && move.isZOrMaxPowered) && move.id === this.effectState.move) {',
    "\t\t\tthis.add('cant', attacker, 'Disable', move);",
    '\t\t\treturn false;',
    '\t\t}',
    '\t},',
    '\tonDisableMove(pokemon) {',
    '\t\tfor (const moveSlot of pokemon.moveSlots) {',
    '\t\t\tif (moveSlot.id === this.effectState.move) {',
    '\t\t\t\tpokemon.disableMove(moveSlot.id);',
    '\t\t\t}',
    '\t\t}',
    '\t},',
    '},',
    flags='protect: 1, reflectable: 1, mirror: 1, bypasssub: 1, metronome: 1', pp=20)
PROTECT_ONPREPARE = ['onPrepareHit(pokemon) {', "\treturn !!this.queue.willAct() && this.runEvent('StallMove', pokemon);", '},',
                     'onHit(pokemon) {', "\tpokemon.addVolatile('stall');", '},']


def protect_variant(mid, name, volatile, punish):
    return move_entry(
        mid, name, 'stallingMove: true,', "volatileStatus: '%s'," % volatile, *PROTECT_ONPREPARE, 'condition: {', '\tduration: 1,',
        '\tonStart(target) {', "\t\tthis.add('-singleturn', target, 'move: Protect');", '\t},', '\tonTryHitPriority: 3,',
        '\tonTryHit(target, source, move) {', '\t\tif (this.checkMoveBypassesProtect(move, source, target)) return;',
        '\t\tif (move.smartTarget) {', '\t\t\tmove.smartTarget = false;', '\t\t} else {',
        "\t\t\tthis.add('-activate', target, 'move: Protect');", '\t\t}',
        "\t\tconst lockedmove = source.getVolatile('lockedmove');", '\t\tif (lockedmove) {',
        '\t\t\t// Outrage counter is reset', "\t\t\tif (source.volatiles['lockedmove'].duration === 2) {",
        "\t\t\t\tdelete source.volatiles['lockedmove'];", '\t\t\t}', '\t\t}',
        '\t\tif (this.checkMoveMakesContact(move, source, target)) {', '\t\t\t' + punish, '\t\t}', '\t\treturn this.NOT_FAIL;',
        '\t},', '\tonHit(target, source, move) {',
        '\t\tif (move.isZOrMaxPowered && this.checkMoveMakesContact(move, source, target)) {', '\t\t\t' + punish, '\t\t}', '\t},',
        '},', flags='noassist: 1, failcopycat: 1', target='self', type_='Grass')


PROTECT_BASE = move_entry('protect', 'Protect', 'stallingMove: true,', "volatileStatus: 'protect',", *PROTECT_ONPREPARE,
                          flags='noassist: 1, failcopycat: 1', target='self', type_='Normal')
SPIKY_SHIELD = protect_variant('spikyshield', 'Spiky Shield', 'spikyshield', 'this.damage(source.baseMaxhp / 8, source, target);')

TAUNT = move_entry('taunt', 'Taunt', "volatileStatus: 'taunt',", gen_closure.TAUNT_CONDITION, type_='Dark', pp=20,
                   flags='protect: 1, reflectable: 1, mirror: 1, bypasssub: 1, metronome: 1')
YAWN = move_entry('yawn', 'Yawn', "volatileStatus: 'yawn',", gen_closure.YAWN_ONTRYHIT, gen_closure.YAWN_CONDITION, type_='Normal',
                  flags='protect: 1, reflectable: 1, mirror: 1, metronome: 1')

PLAIN = move_entry('plain', 'Plain', category='Physical', base_power=50, flags='contact: 1')

# ---- step G30: Rage Powder, Psychic Fangs, Solar Beam (handlers) and the four abilities of ENGINE_ROWS ----
RAGE_POWDER = move_entry(
    'ragepowder', 'Rage Powder', "volatileStatus: 'ragepowder',", 'onTry(source) {', '\treturn this.activePerHalf > 1;', '},',
    'condition: {', '\tduration: 1,', '\tonStart(pokemon) {', "\t\tthis.add('-singleturn', pokemon, 'move: Rage Powder');", '\t},',
    '\tonFoeRedirectTargetPriority: 1,', '\tonFoeRedirectTarget(target, source, source2, move) {',
    '\t\tconst ragePowderUser = this.effectState.target;', '\t\tif (ragePowderUser.isSkyDropped()) return;', '',
    "\t\tif (source.runStatusImmunity('powder') && this.validTarget(ragePowderUser, source, move.target)) {",
    '\t\t\tif (move.smartTarget) move.smartTarget = false;', '\t\t\tthis.debug("Rage Powder redirected target of move");',
    '\t\t\treturn ragePowderUser;', '\t\t}', '\t},', '},', pp=20, flags='noassist: 1, failcopycat: 1, powder: 1', target='self',
    type_='Bug').replace('priority: 0', 'priority: 2')
PSYCHIC_FANGS = move_entry(
    'psychicfangs', 'Psychic Fangs', 'onTryHit(pokemon) {', '\t// will shatter screens through sub, before you hit',
    "\tpokemon.side.removeSideCondition('reflect');", "\tpokemon.side.removeSideCondition('lightscreen');",
    "\tpokemon.side.removeSideCondition('auroraveil');", '},', category='Physical', base_power=85,
    flags='contact: 1, protect: 1, mirror: 1, metronome: 1, bite: 1', type_='Psychic')
SOLAR_BEAM = move_entry(
    'solarbeam', 'Solar Beam', 'onTryMove(attacker, defender, move) {', '\tif (attacker.removeVolatile(move.id)) {', '\t\treturn;', '\t}',
    "\tthis.add('-prepare', attacker, move.name);",
    "\tif (['sunnyday', 'desolateland'].includes(attacker.effectiveWeather(undefined, true))) {",
    "\t\tthis.attrLastMove('[still]');", "\t\tthis.addMove('-anim', attacker, move.name, defender);", '\t\treturn;', '\t}',
    "\tif (!this.runEvent('ChargeMove', attacker, defender, move)) {", '\t\treturn;', '\t}',
    "\tattacker.addVolatile('twoturnmove', defender);", '\treturn null;', '},', 'onBasePower(basePower, pokemon, target) {',
    "\tconst weakWeathers = ['raindance', 'primordialsea', 'sandstorm', 'hail', 'snowscape'];",
    '\tif (weakWeathers.includes(pokemon.effectiveWeather())) {', "\t\tthis.debug('weakened by weather');",
    '\t\treturn this.chainModify(0.5);', '\t}', '},', category='Special', base_power=120, pp=10,
    flags='charge: 1, protect: 1, mirror: 1, metronome: 1, nosleeptalk: 1, failinstruct: 1', type_='Grass')


def parse_pool(mid, text, pool=True, ext=True):
    base = TextSource('data/moves.ts', text)
    return gen_closure.parse_move(mid, base, TextSource('data/mods/champions/moves.ts', ''), ext, pool)


class PoolMoves(unittest.TestCase):
    def refused(self, mid, text, message, **kwargs):
        with self.assertRaises(SystemExit) as cm:
            parse_pool(mid, text, **kwargs)
        self.assertEqual(cm.exception.code, 'gen_closure: move %s: %s' % (mid, message))

    def test_a_handler_move_parses_in_the_pool_mode_with_its_special(self):
        for mid, text, special in (('soak', SOAK, 'SOAK'), ('expandingforce', EXPANDING_FORCE, 'EXPANDING_FORCE')):
            with self.subTest(mid):
                rec = parse_pool(mid, text)
                self.assertEqual(rec['special'], gen_closure.SPECIAL_IDS_P.index(special))
                # What the handler owns is not encoded in the generic columns.
                self.assertEqual((rec['sec_kind'], rec['sec_param'], rec['primary_status'], rec['side_condition']),
                                 (0, 0, 0, 0))

    def test_scald_and_recover_are_data_in_the_pool_mode(self):
        # Step G10: thawsTarget is bit 4 of the second flags byte and heal is the heal column; no handler id.
        scald = parse_pool('scald', SCALD)
        self.assertEqual((scald['special'], scald['flags2'], scald['heal']), (0, gen_closure.FLAG2_THAWS_TARGET, [0, 0]))
        self.assertEqual((scald['sec_chance'], scald['sec_kind'], scald['sec_param']), (30, 2, 1))
        self.assertTrue(scald['flags'] & gen_closure.FLAG_BITS_C['defrost'])
        recover = parse_pool('recover', RECOVER)
        self.assertEqual((recover['special'], recover['flags2'], recover['heal']), (0, 2, [1, 2]))
        self.assertEqual(parse_pool('recover', RECOVER.replace('[1, 2]', '[1, 4]'))['heal'], [1, 4])
        self.assertEqual(parse_pool('plain', PLAIN)['heal'], [0, 0])
        # The heal column bytes: numerator and denominator per move, and the flags2 bytes before them.
        d = {'moves': [{'heal': [1, 2], 'flags2': 2}, {'flags2': 4}, {'heal': [0, 0], 'flags2': 0}]}
        self.assertEqual(gen_closure.heal_bytes(d), bytes([1, 2, 0, 0, 0, 0]))
        self.assertEqual(gen_closure.flags2_bytes(d), bytes([2, 4, 0]))

    def test_throat_chop_and_psychic_noise_are_modelled_not_handlers(self):
        # Step G8: their secondaries are secondary kinds of their own (chance 100), and no handler id.
        for mid, text, kind, flags2 in (('throatchop', THROAT_CHOP, gen_closure.SECONDARY_LOCKOUT, 0),
                                        ('psychicnoise', PSYCHIC_NOISE, gen_closure.SECONDARY_HEAL_BLOCK, 1)):
            with self.subTest(mid):
                rec = parse_pool(mid, text)
                self.assertEqual((rec['special'], rec['sec_chance'], rec['sec_kind'], rec['sec_param'], rec['flags2']),
                                 (0, 100, kind, 0, flags2))
        # The two kinds are numbers that the engine reads: DFI_SECONDARY_LOCKOUT and DFI_SECONDARY_HEAL_BLOCK.
        self.assertEqual((gen_closure.SECONDARY_LOCKOUT, gen_closure.SECONDARY_HEAL_BLOCK), (5, 6))
        # Deviations: another volatile, another chance, no condition block for Throat Chop.
        self.refused('throatchop', THROAT_CHOP.replace("addVolatile('throatchop')", "addVolatile('taunt')"),
                     'unknown secondary')
        self.refused('throatchop', THROAT_CHOP.replace('chance: 100', 'chance: 50'), 'unknown secondary')
        self.refused('throatchop', THROAT_CHOP.replace('\t\tcondition: {\n\t\t\tduration: 2,\n\t\t},\n', ''),
                     'expected a condition block')
        self.refused('psychicnoise', PSYCHIC_NOISE.replace('chance: 100', 'chance: 50'),
                     'secondary volatile healblock is not modelled')
        self.refused('psychicnoise', PSYCHIC_NOISE.replace("'healblock'", "'taunt'"),
                     'secondary volatile taunt is not modelled')

    def test_the_second_flags_byte_has_the_sound_and_heal_flags(self):
        plain = move_entry('plain', 'Plain', category='Physical', base_power=50, flags='contact: 1, sound: 1')
        self.assertEqual(parse_pool('plain', plain)['flags2'], 1)
        self.assertEqual(parse_pool('recover', RECOVER)['flags2'], 2)
        both = move_entry('plain', 'Plain', category='Physical', base_power=50, flags='sound: 1, heal: 1')
        self.assertEqual(parse_pool('plain', both)['flags2'], 3)
        self.assertEqual(parse_pool('icepunch', ICE_PUNCH)['flags2'], 32)  # step G34: the punch flag is the byte's bit 32
        slicing = move_entry('plain', 'Plain', category='Physical', base_power=50, flags='slicing: 1')
        self.assertEqual(parse_pool('plain', slicing)['flags2'], 64)  # and slicing is bit 64
        # The CLOSURE and extended parses carry the value too (their bytes do not).
        self.assertEqual(parse_pool('plain', plain, pool=False, ext=False)['flags2'], 1)

    def test_the_conditions_that_the_engine_hard_codes_are_checked(self):
        facts = dict(gen_closure.G8_CONDITION_FACTS)

        def entries(skip=(None, None)):
            # Every fact on its own line; the braces of a line that opens a block are closed on the next line.
            out = []
            for mid, needed in facts.items():
                lines = ['\t%s: {' % mid]
                for i, n in enumerate(needed):
                    if (mid, i) != skip:
                        lines.append('\t\t' + n)
                        lines.append('\t\t' + '}' * max(0, n.count('{') - n.count('}')))
                lines.append('\t},')
                out.append('\n'.join(lines))
            return TextSource('data/moves.ts', '\n'.join(out))

        gen_closure.check_g8_conditions(entries(), gen_closure.G8_CONDITION_FACTS)
        for mid, needed in facts.items():
            for i in range(len(needed)):
                with self.subTest(mid=mid, fact=needed[i]):
                    with self.assertRaises(SystemExit) as cm:
                        gen_closure.check_g8_conditions(entries((mid, i)), gen_closure.G8_CONDITION_FACTS)
                    self.assertIn('move %s: the condition no longer has' % mid, str(cm.exception.code))

    def test_the_handlers_are_the_seven_new_specials_in_order(self):
        seven = len(gen_closure.SPECIAL_IDS_C) + len(gen_closure.G2_HANDLERS)
        self.assertEqual(gen_closure.SPECIAL_IDS_P[len(gen_closure.SPECIAL_IDS_C):seven], gen_closure.G2_HANDLERS)
        # UNMODELED (decision 0015 section 4.2) follows them, as the last id.
        self.assertEqual(gen_closure.SPECIAL_IDS_P[seven:], ['SANDSTORM', 'SNOWSCAPE', 'KNOCK_OFF', 'EXPANDING_FORCE', 'GLAIVE_RUSH', 'AURORA_VEIL', 'SPIKY_SHIELD',
                          'SHELL_SMASH', 'ACROBATICS', 'BLIZZARD', 'FEINT', 'RAGE_POWDER', 'PSYCHIC_FANGS', 'SOLAR_BEAM',
                          'HP_POWER', 'BODY_PRESS', 'FOUL_PLAY', 'PSYSHOCK',
                          'RAIN_DANCE', 'SUNNY_DAY', 'FREEZE_DRY', 'CLANGING_SCALES',
                          'STEEL_ROLLER', 'CLANGOROUS_SOUL', 'BRICK_BREAK', 'DISABLE',
                          'ELECTRIC_TERRAIN', 'MISTY_TERRAIN', 'RISING_VOLTAGE', 'TERRAIN_PULSE', 'PERISH_SONG', 'MULTI_HIT_2', 'TRIPLE_AXEL', 'IMPRISON',
                          'TRICK', 'SWITCHEROO', 'THIEF', 'COVET', 'SUPER_FANG', 'TAUNT', 'YAWN',
                          'RAGE_FIST', 'STONE_AXE', 'CEASELESS_EDGE', 'MULTI_HIT_10', 'POWER_TRIP', 'THUNDER', 'ICE_FANG', 'TRI_ATTACK', 'DOUBLE_SHOCK', 'ROOST', 'STOMPING_TANTRUM',
                          'LOCKED_MOVE', 'REVIVAL_BLESSING',
                          'MULTI_HIT_2_5', 'SCALE_SHOT', 'QUICK_GUARD', 'UPPER_HAND', 'HEAL_PULSE', 'STRENGTH_SAP', 'PHANTOM_FORCE', 'UNMODELED'])
        self.assertEqual(len(gen_closure.G2_HANDLERS), 7)
        # Step G16: Knock Off's handler is 24 in the tables; step G15's Expanding Force is 25, step G19's Glaive Rush 26,
        # step G20's Aurora Veil 27, Spiky Shield 28, the four of step G28 29 to 32, the eight of step G32 33 to 40 and
        # the three of step G34 44 to 46, the four of step G25 48 to 51, Perish Song (step G26) 52 and UNMODELED 53.
        self.assertEqual(gen_closure.G16_HANDLERS, ['KNOCK_OFF'])
        self.assertEqual(gen_closure.G20_HANDLERS, ['AURORA_VEIL'])
        self.assertEqual(gen_closure.G20_PROTECT_HANDLERS, ['SPIKY_SHIELD'])
        self.assertEqual(gen_closure.G27_HANDLERS, ['DISABLE'])
        self.assertEqual(gen_closure.SPECIAL_IDS_P.index('KNOCK_OFF'), 24)
        self.assertEqual(gen_closure.SPECIAL_IDS_P.index('EXPANDING_FORCE'), 25)
        self.assertEqual(gen_closure.SPECIAL_IDS_P.index('GLAIVE_RUSH'), 26)  # step G19
        self.assertEqual(gen_closure.SPECIAL_IDS_P.index('AURORA_VEIL'), 27)
        self.assertEqual(gen_closure.G26_HANDLERS, ['PERISH_SONG'])
        self.assertEqual(gen_closure.SPECIAL_IDS_P.index('SPIKY_SHIELD'), 28)
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G28_HANDLERS], [29, 30, 31, 32])
        self.assertEqual(gen_closure.G30_HANDLERS, ['RAGE_POWDER', 'PSYCHIC_FANGS', 'SOLAR_BEAM'])  # step G30
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G30_HANDLERS], [33, 34, 35])
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G32_HANDLERS], list(range(36, 44)))
        self.assertEqual(gen_closure.G34_HANDLERS, ['STEEL_ROLLER', 'CLANGOROUS_SOUL', 'BRICK_BREAK'])  # step G34
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G34_HANDLERS], [44, 45, 46])
        self.assertEqual(gen_closure.SPECIAL_IDS_P.index('DISABLE'), 47)  # step G27, after the others
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G25_HANDLERS], [48, 49, 50, 51])  # step G25
        self.assertEqual(gen_closure.SPECIAL_IDS_P.index('PERISH_SONG'), 52)  # step G26, after the four of step G25
        self.assertEqual(gen_closure.G33_HANDLERS, ['MULTI_HIT_2', 'TRIPLE_AXEL'])  # step G33
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G33_HANDLERS], [53, 54])
        self.assertEqual(gen_closure.G38_HANDLERS, ['IMPRISON'])  # step G38
        self.assertEqual(gen_closure.SPECIAL_IDS_P.index('IMPRISON'), 55)
        self.assertEqual(gen_closure.G29_HANDLERS, ['TRICK', 'SWITCHEROO', 'THIEF', 'COVET'])  # step G29
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G29_HANDLERS], [56, 57, 58, 59])
        self.assertEqual(gen_closure.G39_HANDLERS, ['SUPER_FANG'])  # step G39
        self.assertEqual(gen_closure.SPECIAL_IDS_P.index('SUPER_FANG'), 60)
        self.assertEqual(gen_closure.G31_HANDLERS, ['TAUNT', 'YAWN'])  # step G31, after step G39's
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G31_HANDLERS], [61, 62])
        # step G48: Rage Fist, Stone Axe, Ceaseless Edge and Population Bomb follow Taunt and Yawn (63 to 66)
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G48_HANDLERS], [63, 64, 65, 66])
        # step G50: Double Shock follows the eight of steps G48 and G44 (71); Roost and Stomping Tantrum (72, 73); Locked Move (74); Revival Blessing (75); the six of step G54 (76 to 81); UNMODELED moves to 82
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G50_HANDLERS], [71])
        self.assertEqual(gen_closure.G52_HANDLERS, ['REVIVAL_BLESSING'])  # step G52
        self.assertEqual(gen_closure.SPECIAL_IDS_P.index('REVIVAL_BLESSING'), 75)
        # step G42: Roost and Stomping Tantrum follow Double Shock (72, 73); Revival Blessing (G52) 74; UNMODELED moves to 75
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G42_HANDLERS], [72, 73])
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G56_HANDLERS], [74])  # G56: LOCKED_MOVE
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G52_HANDLERS], [75])  # G52: REVIVAL_BLESSING
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G54_HANDLERS], [76, 77, 78, 79, 80, 81])
        # step G58: Phantom Force follows the six of step G54 (82); UNMODELED moves to 83
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G58_HANDLERS], [82])
        self.assertEqual(gen_closure.SPECIAL_IDS_P.index('UNMODELED'), 83)
        # Scald and Recover became data in step G10: their ids stay defined and no move maps to them.
        self.assertEqual({v[0] for k, v in gen_closure.SPECIAL_P.items() if k not in gen_closure.SPECIAL_C},
                         (set(gen_closure.G2_HANDLERS) - {'SCALD', 'RECOVER'}) | set(gen_closure.WEATHER_HANDLERS) |
                         set(gen_closure.G16_HANDLERS) | set(gen_closure.G15_HANDLERS) | set(gen_closure.G19_HANDLERS) |
                         set(gen_closure.G20_HANDLERS) | set(gen_closure.G20_PROTECT_HANDLERS) | set(gen_closure.G28_HANDLERS) |
                         set(gen_closure.G30_HANDLERS) | set(gen_closure.G32_HANDLERS) | set(gen_closure.G34_HANDLERS) |
                         set(gen_closure.G27_HANDLERS) | set(gen_closure.G25_HANDLERS) | set(gen_closure.G26_HANDLERS) | set(gen_closure.G33_HANDLERS) | set(gen_closure.G38_HANDLERS) | set(gen_closure.G29_HANDLERS) | set(gen_closure.G39_HANDLERS) | set(gen_closure.G31_HANDLERS) | set(gen_closure.G48_HANDLERS) | set(gen_closure.G44_HANDLERS) | set(gen_closure.G50_HANDLERS) | set(gen_closure.G42_HANDLERS) | set(gen_closure.G56_HANDLERS) | set(gen_closure.G52_HANDLERS) | set(gen_closure.G54_HANDLERS) | set(gen_closure.G58_HANDLERS) | {'DARKEST_LARIAT'})

    def test_taunt_and_yawn_are_handlers_whose_conditions_are_the_pinned_text(self):
        for mid, text, special in (('taunt', TAUNT, 'TAUNT'), ('yawn', YAWN, 'YAWN')):
            rec = parse_pool(mid, text)
            self.assertEqual(rec['special'], gen_closure.SPECIAL_IDS_P.index(special))
            self.assertEqual((rec['side_condition'], rec['sec_kind'], rec['primary_status']), (0, 0, 0))
        self.refused('taunt', TAUNT.replace('duration: 3', 'duration: 4'), 'the condition is not the pinned text')
        self.refused('taunt', TAUNT.replace('onResidualOrder: 15', 'onResidualOrder: 16'), 'the condition is not the pinned text')
        self.refused('taunt', TAUNT.replace('onBeforeMovePriority: 5', 'onBeforeMovePriority: 6'), 'the condition is not the pinned text')
        self.refused('taunt', TAUNT.replace("move.category === 'Status'", "move.category === 'Physical'"), 'the condition is not the pinned text')
        self.refused('yawn', YAWN.replace('duration: 2', 'duration: 3'), 'the condition is not the pinned text')
        self.refused('yawn', YAWN.replace('onResidualOrder: 23', 'onResidualOrder: 22'), 'the condition is not the pinned text')
        self.refused('yawn', YAWN.replace("target.trySetStatus('slp'", "target.trySetStatus('par'"), 'the condition is not the pinned text')
        self.refused('yawn', YAWN.replace('target.status ||', ''), 'onTryHit is not the pinned text')
        self.refused('taunt', TAUNT.replace("volatileStatus: 'taunt',", "volatileStatus: 'yawn',"),
                     "volatileStatus is not \"volatileStatus: 'taunt',\"")

    def test_aurora_veil_is_a_handler_whose_onTry_and_condition_are_the_pinned_text(self):
        rec = parse_pool('auroraveil', AURORA_VEIL)
        self.assertEqual(rec['special'], gen_closure.SPECIAL_IDS_P.index('AURORA_VEIL'))
        # The side condition is the handler's: no column has it.
        self.assertEqual((rec['side_condition'], rec['sec_kind'], rec['primary_status'], rec['pseudo_weather']),
                         (0, 0, 0, 0))
        self.refused('auroraveil', AURORA_VEIL.replace("'hail', ", ''), 'onTry is not the pinned text')
        self.refused('auroraveil', AURORA_VEIL.replace("'snowscape'", "'sunnyday'"), 'onTry is not the pinned text')
        self.refused('auroraveil', AURORA_VEIL.replace("sideCondition: 'auroraveil',", "sideCondition: 'reflect',"),
                     "sideCondition is not \"sideCondition: 'auroraveil',\"")
        self.refused('auroraveil', AURORA_VEIL.replace('\t\tcondition: {\n\t\t\tduration: 5,\n\t\t},\n', ''),
                     'expected a condition block')
        # Outside the pool mode the move is refused for its callback.
        for ext in (False, True):
            self.refused('auroraveil', AURORA_VEIL, 'callback onTry is not mapped to a handler', pool=False, ext=ext)

    def test_perish_song_is_a_handler_whose_onHitField_and_condition_are_the_pinned_text(self):
        rec = parse_pool('perishsong', PERISH_SONG)
        self.assertEqual(rec['special'], gen_closure.SPECIAL_IDS_P.index('PERISH_SONG'))
        self.assertEqual((rec['side_condition'], rec['sec_kind'], rec['primary_status'], rec['pseudo_weather']), (0, 0, 0, 0))
        self.assertEqual(rec['target_class'], gen_closure.TARGET_CLASS_POOL['all'])
        for old, new in (('duration: 4,', 'duration: 3,'), ('onResidualOrder: 24,', 'onResidualOrder: 25,'),
                         ("'perish0'", "'perish1'"), ('target.faint();', 'target.damage(1);')):
            self.refused('perishsong', PERISH_SONG.replace(old, new), 'the condition is not the pinned text')
        for old, new in (('message = true;', 'message = false;'), ('result = true;', 'result = false;'),
                         ("=== null", "=== undefined")):
            self.refused('perishsong', PERISH_SONG.replace(old, new, 1), 'onHitField is not the pinned text')
        self.refused('perishsong', PERISH_SONG.replace('\t\tduration: 4,\n', ''), 'the condition is not the pinned text')
        # Outside the pool mode the move is refused for its callback.
        for ext in (False, True):
            self.refused('perishsong', PERISH_SONG, 'callback onHitField is not mapped to a handler', pool=False, ext=ext)

    def test_the_aurora_veil_condition_that_the_engine_hard_codes_is_checked(self):
        (mid, needed), = gen_closure.G20_CONDITION_FACTS

        def entry(skip=None):
            lines = ['\t%s: {' % mid]
            for i, n in enumerate(needed):
                if i != skip:
                    lines.append('\t\t' + n)
            lines.append('\t},')
            return TextSource('data/moves.ts', '\n'.join(lines))

        gen_closure.check_g8_conditions(entry(), gen_closure.G20_CONDITION_FACTS)
        for i in range(len(needed)):
            with self.subTest(fact=needed[i]):
                with self.assertRaises(SystemExit) as cm:
                    gen_closure.check_g8_conditions(entry(i), gen_closure.G20_CONDITION_FACTS)
                self.assertIn('move auroraveil: the condition no longer has', str(cm.exception.code))

    def test_disable_is_a_handler_whose_texts_are_the_pinned_ones(self):
        rec = parse_pool('disable', DISABLE)
        self.assertEqual(rec['special'], gen_closure.SPECIAL_IDS_P.index('DISABLE'))
        self.assertEqual((rec['side_condition'], rec['sec_kind'], rec['primary_status'], rec['accuracy']), (0, 0, 0, 100))
        # The onTryHit, the condition (duration, the onStart, the lines, the order, the BeforeMove and DisableMove
        # handlers) and the volatile that it owns must be the pinned text.
        self.refused('disable', DISABLE.replace("'struggle'", "'tackle'"), 'onTryHit is not the pinned text')
        self.refused('disable', DISABLE.replace('duration: 5,', 'duration: 4,'), 'the condition is not the pinned text')
        self.refused('disable', DISABLE.replace('onResidualOrder: 17,', 'onResidualOrder: 16,'),
                     'the condition is not the pinned text')
        self.refused('disable', DISABLE.replace('onBeforeMovePriority: 7,', 'onBeforeMovePriority: 6,'),
                     'the condition is not the pinned text')
        self.refused('disable', DISABLE.replace("volatileStatus: 'disable',", "volatileStatus: 'taunt',"),
                     "volatileStatus is not \"volatileStatus: 'disable',\"")
        # Outside the pool mode the callback is refused.
        for ext in (False, True):
            self.refused('disable', DISABLE, 'callback onTryHit is not mapped to a handler', pool=False, ext=ext)

    def test_the_champions_disable_condition_is_the_pinned_one_too(self):
        base = TextSource('data/moves.ts', DISABLE)
        champ_text = move_entry(
            'disable', 'Disable', 'inherit: true,', 'condition: {', '\tinherit: true,', '\tonBeforeMove(attacker, defender, move) {',
            '\t\tif (!(move.isZ && move.isZOrMaxPowered) && move.id === this.effectState.move && !move.flags[\'cantusetwice\']) {',
            "\t\t\tthis.add('cant', attacker, 'Disable', move);", '\t\t\treturn false;', '\t\t}', '\t},', '},')
        champ = TextSource('data/mods/champions/moves.ts', champ_text)
        rec = gen_closure.parse_move('disable', base, champ, True, True)
        self.assertEqual(rec['special'], gen_closure.SPECIAL_IDS_P.index('DISABLE'))
        # A Champions condition that changes anything else is refused.
        changed = TextSource('data/mods/champions/moves.ts', champ_text.replace('return false;', 'return true;'))
        with self.assertRaises(SystemExit) as cm:
            gen_closure.parse_move('disable', base, changed, True, True)
        self.assertEqual(cm.exception.code, 'gen_closure: move disable: the Champions condition is not the pinned text')
    def test_spiky_shield_is_a_handler_whose_condition_is_the_pinned_text_and_the_rest_is_protects(self):
        rec = parse_pool('spikyshield', PROTECT_BASE + '\n' + SPIKY_SHIELD)
        self.assertEqual(rec['special'], gen_closure.SPECIAL_IDS_P.index('SPIKY_SHIELD'))
        self.assertEqual((rec['side_condition'], rec['sec_kind'], rec['primary_status']), (0, 0, 0))
        both = PROTECT_BASE + '\n'
        # A punishment that is not the pinned one (a fraction, another effect), a callback that is not Protect's, a
        # field that is not Protect's, and a volatile that is not its own are refused.
        self.refused('spikyshield', both + SPIKY_SHIELD.replace('/ 8', '/ 16'), 'the condition is not the pinned text')
        self.refused('spikyshield', both + SPIKY_SHIELD.replace('this.damage(source.baseMaxhp / 8, source, target);',
                                                                 "source.trySetStatus('psn', target);"),
                     'the condition is not the pinned text')
        self.refused('spikyshield', both + SPIKY_SHIELD.replace("addVolatile('stall')", "addVolatile('stalls')"),
                     'onHit is not that of protect')
        self.refused('spikyshield', both + SPIKY_SHIELD.replace('flags: { noassist: 1, failcopycat: 1 }', 'flags: { noassist: 1 }'),
                     'flags is not that of protect')
        self.refused('spikyshield', both + SPIKY_SHIELD.replace("volatileStatus: 'spikyshield',", "volatileStatus: 'protect',"),
                     "volatileStatus is not \"volatileStatus: 'spikyshield',\"")
        # Outside the pool mode the callbacks are refused.
        for ext in (False, True):
            self.refused('spikyshield', both + SPIKY_SHIELD, 'callback onPrepareHit is not mapped to a handler', pool=False, ext=ext)

    def lenient(self, mid, text):
        """The whole-pool mode (the rows of step G30 are read in it: the flags of the pin are not all modelled)."""
        base = TextSource('data/moves.ts', text)
        return gen_closure.parse_move(mid, base, TextSource('data/mods/champions/moves.ts', ''), True, True, [])

    def test_the_step_g30_handlers_are_read_from_the_pinned_text(self):
        # Rage Powder: the volatile is the handler's, the powder flag is the second flags byte's bit 16 and the public static bit.
        rage = self.lenient('ragepowder', RAGE_POWDER)
        self.assertEqual(rage['special'], gen_closure.SPECIAL_IDS_P.index('RAGE_POWDER'))
        self.assertEqual((rage['flags2'] & 16, rage['static_flags'] & 512, rage['priority']), (16, 512, 8 + 2))
        with self.assertRaises(SystemExit) as cm:
            self.lenient('ragepowder', RAGE_POWDER.replace('this.activePerHalf > 1', 'this.activePerHalf > 2'))
        self.assertEqual(cm.exception.code, 'gen_closure: move ragepowder: onTry is not the pinned text')
        with self.assertRaises(SystemExit) as cm:
            self.lenient('ragepowder', RAGE_POWDER.replace("source.runStatusImmunity('powder') && ", ''))
        self.assertEqual(cm.exception.code, 'gen_closure: move ragepowder: ' + 'the condition is not the pinned text')
        with self.assertRaises(SystemExit) as cm:
            self.lenient('ragepowder', RAGE_POWDER.replace("volatileStatus: 'ragepowder',", "volatileStatus: 'followme',"))
        self.assertEqual(cm.exception.code, 'gen_closure: move ragepowder: ' + "volatileStatus is not \"volatileStatus: 'ragepowder',\"")
        # Psychic Fangs: the three screens, in this order.
        fangs = self.lenient('psychicfangs', PSYCHIC_FANGS)
        self.assertEqual(fangs['special'], gen_closure.SPECIAL_IDS_P.index('PSYCHIC_FANGS'))
        with self.assertRaises(SystemExit) as cm:
            self.lenient('psychicfangs', PSYCHIC_FANGS.replace("\t\tpokemon.side.removeSideCondition('auroraveil');\n", ''))
        self.assertEqual(cm.exception.code, 'gen_closure: move psychicfangs: ' + 'onTryHit is not the pinned text')
        # Solar Beam: the charge with the sun and the weather's half.
        beam = self.lenient('solarbeam', SOLAR_BEAM)
        self.assertEqual(beam['special'], gen_closure.SPECIAL_IDS_P.index('SOLAR_BEAM'))
        with self.assertRaises(SystemExit) as cm:
            self.lenient('solarbeam', SOLAR_BEAM.replace("'desolateland'", "'raindance'"))
        self.assertEqual(cm.exception.code, 'gen_closure: move solarbeam: onTryMove is not the pinned text')
        with self.assertRaises(SystemExit) as cm:
            self.lenient('solarbeam', SOLAR_BEAM.replace("'snowscape'", "'sunnyday'"))
        self.assertEqual(cm.exception.code, 'gen_closure: move solarbeam: onBasePower is not the pinned text')
        with self.assertRaises(SystemExit) as cm:
            self.lenient('solarbeam', SOLAR_BEAM.replace('chainModify(0.5)', 'chainModify(0.25)'))
        self.assertEqual(cm.exception.code, 'gen_closure: move solarbeam: onBasePower is not the pinned text')
        # The pool mode alone knows them: outside it each callback is refused.
        for mid, text, callback in (('ragepowder', RAGE_POWDER, 'onTry'), ('psychicfangs', PSYCHIC_FANGS, 'onTryHit'),
                                    ('solarbeam', SOLAR_BEAM, 'onTryMove')):
            self.refused(mid, text, 'callback %s is not mapped to a handler' % callback, pool=False, ext=True)

    def test_the_abilities_that_step_g30_runs_by_id_are_checked_against_the_pin(self):
        def entries(replace=None, skip=None):
            lines = []
            for aid, facts in gen_closure.G30_ABILITY_FACTS:
                if aid == skip:
                    continue
                lines.append('\t%s: {' % aid)
                for fact in facts:
                    lines.append('\t\t' + (fact.replace(*replace) if replace and replace[0] in fact else fact))
                lines.append('\t\tname: "X",')
                lines.append('\t},')
            return TextSource('data/abilities.ts', '\n'.join(lines))

        none = TextSource('data/mods/champions/abilities.ts', '')
        gen_closure.check_g30_facts(entries(), none)
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_g30_facts(entries(('randomChance(3, 10)', 'randomChance(1, 10)')), none)
        self.assertIn('ability flamebody: the entry no longer has', str(cm.exception.code))
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_g30_facts(entries(('/ 4', '/ 8')), none)
        self.assertIn('ability hospitality: the entry no longer has', str(cm.exception.code))
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_g30_facts(entries(skip='overcoat'), none)
        self.assertEqual(str(cm.exception.code), 'gen_closure: ability overcoat not found')
        # A Champions override of one of them would change what the engine reads.
        override = TextSource('data/mods/champions/abilities.ts', '\tclearbody: {\n\t\tinherit: true,\n\t},')
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_g30_facts(entries(), override)
        self.assertIn('the champions mod overrides the entry', str(cm.exception.code))

    def test_knock_off_is_a_handler_whose_callbacks_are_the_pinned_text(self):
        rec = parse_pool('knockoff', KNOCK_OFF)
        self.assertEqual(rec['special'], gen_closure.SPECIAL_IDS_P.index('KNOCK_OFF'))
        self.assertEqual((rec['base_power'], rec['sec_kind'], rec['sec_param'], rec['primary_status']), (65, 0, 0, 0))
        # A callback that is not the pinned text, or is missing, is refused.
        self.refused('knockoff', KNOCK_OFF.replace('chainModify(1.5)', 'chainModify(2)'),
                     'onBasePower is not the pinned text')
        self.refused('knockoff', KNOCK_OFF.replace("'[from] move: Knock Off'", "'[from] move: Thief'"),
                     'onAfterHit is not the pinned text')
        self.refused('knockoff', KNOCK_OFF.replace('onAfterHit(target, source) {', 'onTryHit(target, source) {'),
                     'callback onTryHit is not mapped to a handler')
        # Outside the pool mode the move is refused for its callbacks.
        for ext in (False, True):
            self.refused('knockoff', KNOCK_OFF, 'callback onBasePower is not mapped to a handler', pool=False, ext=ext)

    def test_glaive_rush_is_a_handler_whose_self_effect_and_condition_are_the_pinned_text(self):
        rec = parse_pool('glaiverush', GLAIVE_RUSH)
        self.assertEqual(rec['special'], gen_closure.SPECIAL_IDS_P.index('GLAIVE_RUSH'))
        self.assertEqual((rec['base_power'], rec['boost_role'], rec['flags2']), (120, 0, 0))
        self.refused('glaiverush', GLAIVE_RUSH.replace('chainModify(2)', 'chainModify(1.5)'),
                     'the condition is not the pinned text')
        self.refused('glaiverush', GLAIVE_RUSH.replace("volatileStatus: 'glaiverush'", "volatileStatus: 'mustrecharge'"),
                     'self is not "self: { volatileStatus: \'glaiverush\', },"')

    def test_coaching_is_a_status_move_with_primary_boosts_for_the_ally(self):
        rec = parse_pool('coaching', COACHING)
        self.assertEqual((rec['boost_role'], rec['target_class'], rec['special']),
                         (gen_closure.BOOST_ROLE['PRIMARY_ALLY'], gen_closure.TARGET_CLASS['adjacentAlly'], 0))
        self.assertEqual(rec['boosts'][:2], [1, 1])  # atk and def
        # The same boosts on a foe (a Physical or Status move aimed at the opponent) stay refused.
        self.refused('coaching', COACHING.replace('adjacentAlly', 'allAdjacentFoes'), 'primary boosts on a non-self target')  # step G39: 'normal' is Charm's class

    def test_the_item_transfer_moves_are_handlers_whose_callbacks_are_the_pinned_text(self):
        """Step G29: Trick, Switcheroo, Thief and Covet keep their callbacks as handlers of their own, and the generator
        checks the whole text of each (whitespace aside, data/moves.ts) against the one that the turn code implements."""
        def entry(mid, name, category, target_type, base_power, **kw):
            lines = ['%s %s' % (cb, '') if False else text for cb, text in gen_closure.G29_CALLBACKS[mid.upper()].items()]
            return move_entry(mid, name, *lines, category=category, base_power=base_power, **kw)
        trick = entry('trick', 'Trick', 'Status', 'Psychic', 0, type_='Psychic', pp=10,
                      flags='protect: 1, mirror: 1, allyanim: 1, noassist: 1, failcopycat: 1')
        thief = entry('thief', 'Thief', 'Physical', 'Dark', 60, type_='Dark', pp=25,
                      flags='contact: 1, protect: 1, mirror: 1, failmefirst: 1, noassist: 1, failcopycat: 1')
        for mid, text in (('trick', trick), ('thief', thief)):
            rec = parse_pool(mid, text)
            self.assertEqual(rec['special'], gen_closure.SPECIAL_IDS_P.index(mid.upper()))
        self.refused('trick', trick.replace("this.add('-activate', source, 'move: Trick'", "this.add('-activate', source, 'move: Tricky'"),
                     'onHit is not the pinned text')
        self.refused('trick', trick.replace("hasAbility('stickyhold')", "hasAbility('stickyhoold')"),
                     'onTryImmunity is not the pinned text')
        self.refused('thief', thief.replace('if (source.item ||', 'if (!source.item ||'), 'onAfterHit is not the pinned text')
        self.refused('thief', thief.replace('onAfterHit(', 'onHit('), 'callback onHit is not mapped to a handler')
        for mid in ('trick', 'thief'):
            self.refused(mid, trick if mid == 'trick' else thief, 'callback %s is not mapped to a handler' %
                         ('onTryImmunity' if mid == 'trick' else 'onAfterHit'), pool=False, ext=False)

    def test_the_same_move_is_refused_outside_the_pool_mode(self):
        # The closure and extended tables keep failing for what they do not model: no handler leaks into them.
        for mid, text, message in (('soak', SOAK, 'callback onHit is not mapped to a handler'),
                                   ('scald', SCALD, 'unknown field thawsTarget'),
                                   ('recover', RECOVER, 'unknown field heal'),
                                   ('psychicnoise', PSYCHIC_NOISE, 'secondary volatile healblock is not modelled'),
                                   ('throatchop', THROAT_CHOP, 'unknown secondary')):  # G8: only the pool mode models them
            for ext in (False, True):
                with self.subTest(mid=mid, ext=ext):
                    self.refused(mid, text, message, pool=False, ext=ext)

    def test_a_handler_owns_only_what_it_names(self):
        self.refused('scald', SCALD.replace('thawsTarget: true', 'thawsTarget: false'),
                     'thawsTarget is not "thawsTarget: true,"')
        self.refused('recover', RECOVER.replace('[1, 2]', '[3, 2]'), 'heal is not a fraction "heal: [a, b],"')
        self.refused('recover', RECOVER.replace('[1, 2]', '[0, 2]'), 'heal is not a fraction "heal: [a, b],"')
        self.refused('recover', RECOVER.replace('[1, 2]', '[1, 2, 3]'), 'heal is not a fraction "heal: [a, b],"')
        # A callback the handler does not name, and one it names that is absent.
        self.refused('soak', SOAK.replace('target: "normal",', 'onTryHit() { },\n\t\ttarget: "normal",'),
                     'callback onTryHit is not mapped to a handler')
        self.refused('soak', SOAK.replace('onHit(target) {', 'onHitX(target) {'), 'callback onHitX is not mapped to a handler')
        # A condition block needs an owner: recover has none.
        self.refused('recover', RECOVER.replace('heal: [1, 2],', 'heal: [1, 2],\n\t\tcondition: { },'),
                     'condition block without a known owner')

    def test_the_flags_that_no_row_reads(self):
        # punch (Ice Punch, read only by Iron Fist) and allyanim (Soak, read by nothing) are ignored in the pool mode only.
        rec = parse_pool('icepunch', ICE_PUNCH)
        self.assertEqual((rec['flags'], rec['sec_kind'], rec['sec_param']), (3, 2, gen_closure.STATUS['frz']))
        for ext in (False, True):
            with self.subTest(ext=ext):
                self.refused('icepunch', ICE_PUNCH, 'unknown flag punch', pool=False, ext=ext)
        self.refused('soak', SOAK.replace('allyanim: 1', 'telekinesis: 1'), 'unknown flag telekinesis')

    def test_an_unmodelled_name_is_a_message_never_a_key_error(self):
        # Psychic Noise's Heal Block, a primary status, a side condition and a pseudo weather that the tables lack.
        for ext in (False, True):
            with self.subTest(ext=ext):
                self.refused('psychicnoise', PSYCHIC_NOISE, 'secondary volatile healblock is not modelled', pool=False,
                             ext=ext)
                self.refused('plain', PLAIN.replace('target: "normal",', "status: 'tox',\n\t\ttarget: \"normal\","),
                             'primary status tox is not modelled', pool=False, ext=ext)
                self.refused('plain', PLAIN.replace('target: "normal",', "sideCondition: 'toxicspikes',\n\t\ttarget: \"normal\","),
                             'side condition toxicspikes is not modelled', pool=False, ext=ext)
                self.refused('plain', PLAIN.replace('target: "normal",', "pseudoWeather: 'gravity',\n\t\ttarget: \"normal\","),
                             'pseudo weather gravity is not modelled', pool=False, ext=ext)

    def test_the_rows_of_the_step(self):
        every = gen_closure.G2_MOVES + gen_closure.G2_ITEMS + gen_closure.G2_ABILITIES
        self.assertEqual(len(gen_closure.G2_MOVES), 22)
        self.assertEqual((len(gen_closure.G2_ITEMS), len(gen_closure.G2_ABILITIES)), (3, 3))
        self.assertEqual(len(set(gen_closure.G2_MOVES)), 22)
        self.assertEqual(len(set(every)), len(every))
        self.assertEqual([s[0] for s in gen_closure.SETS_G2], ['pelipper', 'arcaninehisui', 'annihilape', 'floetteeternal'])
        # Every handler move is one of the rows, and every set move is a pool move or one of the rows.
        self.assertTrue({k for k in gen_closure.SPECIAL_P if k not in gen_closure.SPECIAL_C} <=
                        set(gen_closure.G2_MOVES) | {'outrage', 'thrash', 'petaldance', 'sandstorm', 'snowscape', 'knockoff', 'expandingforce', 'glaiverush', 'auroraveil', 'spikyshield',
                                                                'shellsmash', 'acrobatics', 'blizzard', 'feint',
                                                                'ragepowder', 'psychicfangs', 'solarbeam', 'eruption', 'waterspout',
                                                                'bodypress', 'foulplay', 'psyshock', 'raindance', 'sunnyday', 'freezedry',
                                                                'clangingscales', 'steelroller', 'clangoroussoul', 'brickbreak', 'disable',
                                                                'electricterrain', 'mistyterrain', 'risingvoltage', 'terrainpulse', 'perishsong',
                                                                'dualwingbeat', 'twinbeam', 'tripleaxel', 'imprison',
                                                                'trick', 'switcheroo', 'thief', 'covet', 'sacredsword', 'superfang', 'taunt', 'yawn',
                                                                'ragefist', 'stoneaxe', 'ceaselessedge', 'populationbomb',
                                                                'powertrip', 'thunder', 'icefang', 'triattack', 'doubleshock', 'roost', 'stompingtantrum', 'revivalblessing',
                                                                'iciclespear', 'scaleshot', 'quickguard', 'upperhand', 'healpulse', 'strengthsap', 'phantomforce'})
        self.assertEqual(gen_closure.WEATHER_HANDLERS, ['SANDSTORM', 'SNOWSCAPE'])
        for _sp, _ab, item, moves, _mega in gen_closure.SETS_G2:
            self.assertTrue(item in gen_closure.G2_ITEMS or item not in gen_closure.POOL_ITEMS)
            self.assertTrue(set(moves) <= set(gen_closure.MOVES + gen_closure.MOVES_C + gen_closure.G2_MOVES))


# ---- step G13: Detect is Protect, the tags of Light of Ruin, and a poison secondary ----
PROTECT_ENTRY = move_entry('protect', 'Protect', 'stallingMove: true,', "volatileStatus: 'protect',",
                           'onPrepareHit(pokemon) {', "\treturn !!this.queue.willAct() && this.runEvent('StallMove', pokemon);",
                           '},', 'onHit(pokemon) {', "\tpokemon.addVolatile('stall');", '},', 'condition: {', '\tduration: 1,', '},',
                           flags='noassist: 1, failcopycat: 1', target='self', type_='Normal').replace('priority: 0', 'priority: 4')
DETECT_ENTRY = (PROTECT_ENTRY.replace('protect: {', 'detect: {', 1).replace('"Protect"', '"Detect"')
                .replace('type: "Normal"', 'type: "Fighting"').replace('\t\tcondition: {\n\t\t\tduration: 1,\n\t\t},\n', ''))
POISON_JAB = move_entry('poisonjab', 'Poison Jab', 'secondary: {', '\tchance: 30,', "\tstatus: 'psn',", '},',
                        category='Physical', base_power=80, pp=20, type_='Poison', flags='contact: 1, protect: 1')
LIGHT_OF_RUIN = move_entry('lightofruin', 'Light of Ruin', 'recoil: [1, 2],', 'tags: ["Past Unobtainable"],',
                           category='Special', base_power=140, pp=5, type_='Fairy', flags='protect: 1, mirror: 1')


class G13Rows(unittest.TestCase):
    def detect(self, text):
        base = TextSource('data/moves.ts', text)
        return gen_closure.parse_move('detect', base, TextSource('data/mods/champions/moves.ts', ''), True, True)

    def refused(self, text, message):
        with self.assertRaises(SystemExit) as cm:
            self.detect(text)
        self.assertEqual(cm.exception.code, 'gen_closure: move detect: %s' % message)

    def test_detect_is_protect_with_the_same_handler_and_nothing_of_its_own(self):
        rec = self.detect(PROTECT_ENTRY + '\n' + DETECT_ENTRY)
        self.assertEqual(rec['special'], gen_closure.SPECIAL_IDS_P.index('PROTECT'))
        self.assertEqual((rec['priority'], rec['sec_kind'], rec['primary_status'], rec['side_condition']), (12, 0, 0, 0))
        # Only the pool mode maps it: the closure and extended modes never saw Detect.
        self.assertNotIn('detect', gen_closure.SPECIAL_P)
        self.assertNotIn('detect', gen_closure.SPECIAL_C)

    def test_detect_must_equal_protect(self):
        self.refused(PROTECT_ENTRY + '\n' + DETECT_ENTRY.replace("pokemon.addVolatile('stall');", "pokemon.addVolatile('other');"),
                     'onHit is not that of protect')
        self.refused(PROTECT_ENTRY + '\n' + DETECT_ENTRY.replace('priority: 4', 'priority: 3'),
                     'priority is not that of protect')
        self.refused(PROTECT_ENTRY + '\n' + DETECT_ENTRY.replace("volatileStatus: 'protect',", "volatileStatus: 'spikyshield',"),
                     'volatileStatus is not that of protect')

    def test_the_tags_of_light_of_ruin_are_ignored_in_the_pool_mode_only(self):
        rec = parse_pool('lightofruin', LIGHT_OF_RUIN)
        self.assertEqual((rec['recoil'], rec['special']), ([1, 2], 0))
        with self.assertRaises(SystemExit) as cm:
            parse_pool('lightofruin', LIGHT_OF_RUIN.replace('Past Unobtainable', 'Something Else'))
        self.assertEqual(cm.exception.code, 'gen_closure: move lightofruin: unknown field tags')
        for ext in (False, True):
            with self.subTest(ext=ext):
                with self.assertRaises(SystemExit) as cm:
                    parse_pool('lightofruin', LIGHT_OF_RUIN, pool=False, ext=ext)
                self.assertEqual(cm.exception.code, 'gen_closure: move lightofruin: unknown field tags')

    def test_a_poison_secondary_is_modelled_in_the_pool_mode_only(self):
        rec = parse_pool('poisonjab', POISON_JAB)
        self.assertEqual((rec['sec_chance'], rec['sec_kind'], rec['sec_param']), (30, 2, gen_closure.STATUS_C['psn']))
        for ext in (False, True):
            with self.subTest(ext=ext):
                with self.assertRaises(SystemExit) as cm:
                    parse_pool('poisonjab', POISON_JAB, pool=False, ext=ext)
                self.assertEqual(cm.exception.code, 'gen_closure: move poisonjab: secondary status psn is not modelled')
        # Badly poisoned is the pool's alone (step G36); a status that the tables lack stays unmodelled.
        rec = parse_pool('poisonjab', POISON_JAB.replace("'psn'", "'tox'"))
        self.assertEqual((rec['sec_chance'], rec['sec_kind'], rec['sec_param']), (30, 2, gen_closure.STATUS_P['tox']))
        self.assertEqual(gen_closure.STATUS_P['tox'], 6)
        for ext in (False, True):
            with self.subTest(ext=ext):
                with self.assertRaises(SystemExit) as cm:
                    parse_pool('poisonjab', POISON_JAB.replace("'psn'", "'tox'"), pool=False, ext=ext)
                self.assertEqual(cm.exception.code, 'gen_closure: move poisonjab: secondary status tox is not modelled')
        features = []
        base = TextSource('data/moves.ts', POISON_JAB.replace("'psn'", "'frostbite'"))
        gen_closure.parse_move('poisonjab', base, TextSource('data/mods/champions/moves.ts', ''), True, True, features)
        self.assertEqual(features, ['secondary status frostbite'])


# ---- the whole legal pool (decision 0015 section 4.2): the lenient mode and what the tables model ----
def lenient(mid, text):
    """parse_move of the pool in the lenient mode: the record and its features."""
    features = []
    base = TextSource('data/moves.ts', text)
    rec = gen_closure.parse_move(mid, base, TextSource('data/mods/champions/moves.ts', ''), pool=True, unmodeled=features)
    return rec, sorted(set(features))


def with_line(text, line):
    return text.replace('target: "normal",', line + '\n\t\ttarget: "normal",')


class LenientMoves(unittest.TestCase):
    def refused(self, mid, text, message):
        with self.assertRaises(SystemExit) as cm:
            lenient(mid, text)
        self.assertEqual(cm.exception.code, 'gen_closure: move %s: %s' % (mid, message))

    def test_a_move_that_the_tables_model_is_encoded_as_in_the_strict_mode(self):
        strict = parse_pool('plain', PLAIN)
        rec, features = lenient('plain', PLAIN)
        self.assertEqual(features, [])
        self.assertEqual(rec, strict)
        self.assertEqual(rec['special'], 0)
        # With a secondary status, a recoil and a drop, all modelled.
        text = with_line(PLAIN, "recoil: [1, 4],\n\t\tsecondary: { chance: 10, status: 'par', },")
        self.assertEqual(lenient('plain', text), (parse_pool('plain', text), []))

    def test_the_static_flags_and_hit_counts_of_every_row_come_from_the_pin_text(self):
        """Decision 0020 items 4 and 5: the static flags (one bit per Showdown flag name of the public set, plus POWER_RULE
        for a basePowerCallback) and the hit counts (multihit: n, [min, max], 1 and 1 otherwise) of every row, modelled or
        not, with their bits in include/duoforge/duoforge.h order."""
        bits = gen_closure.STATIC_FLAG_BITS
        self.assertEqual(sorted(bits.values()), [1, 2, 4, 8, 16, 32, 64, 128, 256, 512])
        self.assertEqual(gen_closure.STATIC_FLAG_POWER_RULE, 1024)
        for flag in bits:
            text = move_entry('plain', 'Plain', category='Physical', base_power=50, flags='%s: 1, protect: 1' % flag)
            rec, _features = lenient('plain', text)
            self.assertEqual(rec['static_flags'], bits[flag], flag)
        text = move_entry('plain', 'Plain', category='Physical', base_power=50,
                          flags='contact: 1, protect: 1, punch: 1, mirror: 1, metronome: 1')
        self.assertEqual(lenient('plain', text)[0]['static_flags'], bits['contact'] | bits['punch'])
        self.assertEqual(lenient('plain', PLAIN)[0]['static_flags'], bits['contact'])
        self.assertEqual(lenient('plain', PLAIN)[0]['hits'], [1, 1])
        callback = with_line(PLAIN, 'basePowerCallback(pokemon, target) { return 1; },')
        rec, features = lenient('plain', callback)
        self.assertEqual(rec['static_flags'], bits['contact'] | gen_closure.STATIC_FLAG_POWER_RULE)
        self.assertIn('callback basePowerCallback', features)  # the row stays UNMODELED: the column is data only
        for line, hits in (('multihit: 2,', [2, 2]), ('multihit: 3,', [3, 3]), ('multihit: 10,', [10, 10]),
                           ('multihit: [2, 5],', [2, 5])):
            rec, features = lenient('plain', with_line(PLAIN, line))
            self.assertEqual(rec['hits'], hits, line)
            self.assertIn('field multihit', features)  # likewise
        self.refused('plain', with_line(PLAIN, 'multihit: [5, 2],'), 'multihit [5, 2] is not 1 <= min <= max <= 255')
        self.refused('plain', with_line(PLAIN, 'multihit: true,'), 'multihit is not "multihit: n," or "multihit: [min, max],"')

    def test_what_the_tables_do_not_model_is_a_feature_not_a_failure(self):
        cases = (
            ('callback onHit', with_line(PLAIN, 'onHit(target) { },')),
            ('callback basePowerCallback', with_line(PLAIN, 'basePowerCallback() { return 1; },')),
            ('field multihit', with_line(PLAIN, 'multihit: 2,')),
            ('field ohko', with_line(PLAIN, 'ohko: true,')),
            ('condition block', with_line(PLAIN, 'condition: { },')),
            ('primary status frostbite', with_line(PLAIN, "status: 'frostbite',")),
            ('primary volatile confusion', with_line(PLAIN, "volatileStatus: 'confusion',")),
            ('side condition mist', with_line(PLAIN, "sideCondition: 'mist',")),
            ('pseudo weather gravity', with_line(PLAIN, "pseudoWeather: 'gravity',")),
            ('secondary', with_line(PLAIN, 'secondary: { chance: 10, onHit() { }, },')),
            ('secondary self effect', with_line(PLAIN, "secondary: { chance: 100, self: { volatileStatus: 'lockedmove', }, },")),
            ('self effect', with_line(PLAIN, "self: { volatileStatus: 'lockedmove', },")),
            ('recharge flag', with_line(PLAIN, "self: { volatileStatus: 'mustrecharge', },")),
            ('primary boosts on a non-self target', with_line(PLAIN, 'boosts: { atk: -1, },')),
        )
        for feature, text in cases:
            with self.subTest(feature):
                rec, features = lenient('plain', text)
                self.assertEqual(features, [feature], text)

    def test_every_unmodelled_feature_of_a_move_is_listed(self):
        text = with_line(PLAIN, "multihit: 2,\n\t\tonHit() { },\n\t\tcondition: { },\n\t\tstatus: 'frostbite',")
        _rec, features = lenient('plain', text)
        self.assertEqual(features, ['callback onHit', 'condition block', 'field multihit', 'primary status frostbite'])

    def test_a_target_class_is_encoded_and_unmodelled_when_the_turn_code_lacks_it(self):
        # allAdjacent (Earthquake) is a class of the pool, code 11, which the turn code has since step G28, allies (Life
        # Dew) code 14 since step G32 and foeSide (the four hazards) code 15 since step G37; the others (12 and 13) have none.
        rec, features = lenient('plain', PLAIN.replace('target: "normal"', 'target: "allAdjacent"'))
        self.assertEqual((rec['target_class'], features), (11, []))
        rec, features = lenient('plain', PLAIN.replace('target: "normal"', 'target: "allies"'))
        self.assertEqual((rec['target_class'], features), (14, []))
        rec, features = lenient('plain', PLAIN.replace('target: "normal"', 'target: "foeSide"'))
        self.assertEqual((rec['target_class'], features), (15, []))
        for name, code in (('scripted', 12), ('allyTeam', 13)):
            with self.subTest(name):
                rec, features = lenient('plain', PLAIN.replace('target: "normal"', 'target: "%s"' % name))
                self.assertEqual((rec['target_class'], features), (code, ['target %s' % name]))
        # The classes of the closure stay modelled.
        for name in ('normal', 'any', 'self', 'allAdjacentFoes', 'allySide', 'all', 'adjacentFoe', 'adjacentAlly'):
            with self.subTest(name):
                rec, features = lenient('plain', PLAIN.replace('target: "normal"', 'target: "%s"' % name))
                self.assertEqual((rec['target_class'], features), (gen_closure.TARGET_CLASS[name], []))
        self.assertEqual(sorted(gen_closure.TARGET_CLASS_POOL_NAMES), [11, 12, 13, 14, 15])
        self.assertTrue(set(gen_closure.TARGET_CLASS_POOL) - set(gen_closure.TARGET_CLASS) == {
            'allAdjacent', 'scripted', 'allyTeam', 'allies', 'foeSide'})
        self.assertTrue(gen_closure.ENGINE_TARGETS <= set(gen_closure.TARGET_CLASS_POOL))
        self.assertEqual(gen_closure.ENGINE_TARGETS - set(gen_closure.TARGET_CLASS), {'allAdjacent', 'allies', 'foeSide'})  # G28, G32, G37

    def test_what_the_generator_cannot_read_still_fails(self):
        self.refused('plain', PLAIN.replace('target: "normal"', 'target: "nowhere"'), 'unknown target class nowhere')
        self.refused('plain', PLAIN.replace('type: "Water"', 'type: "Cosmic"'), 'unknown type Cosmic')
        self.refused('plain', PLAIN.replace('category: "Physical"', 'category: "Mental"'), 'unknown category Mental')
        self.refused('plain', PLAIN.replace('pp: 10', 'pp: 12'), 'pp 12 is not a multiple of 5')
        self.refused('plain', PLAIN.replace('basePower: 50', 'basePower: 300'), 'base_power out of range')
        self.refused('plain', PLAIN.replace('flags: { contact: 1 }', 'flags: { contact: 1, telekinesis: 1 }'),
                     'unknown flag telekinesis')
        with self.assertRaises(SystemExit):
            lenient('missing', PLAIN)
        # A Champions override that does not inherit.
        base = TextSource('data/moves.ts', PLAIN)
        with self.assertRaises(SystemExit) as cm:
            gen_closure.parse_move('plain', base, TextSource('data/mods/champions/moves.ts', entry('plain', 'basePower: 40,')),
                                   pool=True, unmodeled=[])
        self.assertIn('does not inherit', str(cm.exception.code))

    def test_the_lenient_mode_is_for_the_pool_tables_only(self):
        for kwargs in ({}, {'ext': True}):
            with self.subTest(kwargs):
                with self.assertRaises(SystemExit) as cm:
                    gen_closure.parse_move('plain', TextSource('data/moves.ts', PLAIN),
                                           TextSource('data/mods/champions/moves.ts', ''), unmodeled=[], **kwargs)
                self.assertIn('the lenient mode is for the pool tables only', str(cm.exception.code))

    def test_an_unencoded_flag_matters_only_when_a_modelled_row_reads_it(self):
        sound = PLAIN.replace('flags: { contact: 1 }', 'flags: { contact: 1, sound: 1, punch: 1 }')
        self.assertEqual(lenient('plain', sound)[1], [])
        gen_closure.FLAGS_THAT_MATTER.add('sound')
        try:
            self.assertEqual(lenient('plain', sound)[1], ['flag sound'])
        finally:
            gen_closure.FLAGS_THAT_MATTER.discard('sound')
        # The flag set of the pool: every encoded or ignored flag, and the ones of the pool moves.
        self.assertTrue({'contact', 'protect', 'charge', 'defrost', 'sound', 'punch', 'bite', 'powder'} <= gen_closure.POOL_FLAGS)

    def test_a_row_with_an_unmodelled_feature_gets_the_unmodeled_handler_and_neutral_effects(self):
        text = PLAIN.replace('flags: { contact: 1 }', 'flags: { contact: 1 }').replace(
            'target: "normal",', "multihit: 2,\n\t\tsecondary: { chance: 30, status: 'par', },\n\t\ttarget: \"normal\",")
        # Written to a file-like source for parse_pool_move.
        rec = gen_closure.parse_pool_move('plain', TextSource('data/moves.ts', text),
                                          TextSource('data/mods/champions/moves.ts', ''))
        self.assertEqual(rec['special'], gen_closure.SPECIAL_IDS_P.index('UNMODELED'))
        self.assertEqual(rec['unmodeled'], ['field multihit'])
        self.assertEqual((rec['sec_chance'], rec['sec_kind'], rec['sec_param'], rec['boost_role'], rec['primary_status'],
                          rec['side_condition'], rec['pseudo_weather']), (0, 0, 0, 0, 0, 0, 0))
        self.assertEqual(rec['base_power'], 50)  # the plain data stays
        # A modelled move keeps the NONE handler and an empty list.
        ok = gen_closure.parse_pool_move('plain', TextSource('data/moves.ts', PLAIN),
                                         TextSource('data/mods/champions/moves.ts', ''))
        self.assertEqual((ok['special'], ok['unmodeled']), (0, []))


class ItemAbilityFeatures(unittest.TestCase):
    def features(self, text, rid, inert, stone=False, readers=None):
        src = TextSource('data/items.ts', text)
        return gen_closure.entry_features(src, TextSource('data/mods/champions/items.ts', ''), rid, inert, stone, readers)

    def test_an_entry_without_callbacks_is_inert(self):
        text = entry('leek', 'name: "Leek",', 'spritenum: 475,', 'fling: {', '\tbasePower: 60,', '},', 'num: 259,', 'gen: 8,')
        self.assertEqual(self.features(text, 'leek', gen_closure.INERT_ITEM_KEYS), [])

    def test_a_callback_a_condition_or_another_field_is_a_feature(self):
        text = entry('thing', 'name: "Thing",', 'onModifyAtk(atk) { return atk; },', 'onModifyAtkPriority: 1,',
                     'condition: { },', 'boosts: { atk: 1, },', 'num: 1,')
        self.assertEqual(sorted(self.features(text, 'thing', gen_closure.INERT_ITEM_KEYS)),
                         ['callback onModifyAtk', 'callback onModifyAtkPriority', 'condition block', 'field boosts'])

    def test_a_mega_stone_may_keep_its_take_item_handler(self):
        take = ('onTakeItem(item, source) {', '\treturn !item.megaStone?.[source.baseSpecies.baseSpecies];', '},')
        text = entry('abomasite', 'name: "Abomasite",', 'megaStone: { "Abomasnow": "Abomasnow-Mega" },',
                     'itemUser: ["Abomasnow"],', *take, 'num: 674,')
        self.assertEqual(self.features(text, 'abomasite', gen_closure.INERT_ITEM_KEYS, stone=True), [])
        self.assertEqual(self.features(text, 'abomasite', gen_closure.INERT_ITEM_KEYS, stone=False),
                         ['callback onTakeItem'])
        other = text.replace('baseSpecies.baseSpecies', 'name')
        self.assertEqual(self.features(other, 'abomasite', gen_closure.INERT_ITEM_KEYS, stone=True),
                         ['callback onTakeItem'])

    def test_an_id_that_other_code_reads_is_a_feature_even_without_a_callback(self):
        # Damp Rock: no callback of its own, read by the rain condition (data/conditions.ts).
        text = entry('damprock', 'name: "Damp Rock",', 'num: 285,')
        loaded = {rel: TextSource(rel, '') for rel in ('data/abilities.ts', 'data/items.ts', 'data/moves.ts',
                                                        'data/mods/champions/abilities.ts', 'data/mods/champions/items.ts',
                                                        'data/mods/champions/moves.ts', 'data/mods/champions/scripts.ts')}
        loaded['data/items.ts'] = TextSource('data/items.ts', text)
        readers = object.__new__(gen_closure.ReaderIndex)
        readers.lines = {'data/conditions.ts': ["\tif (source?.hasItem('damprock')) return 8;"], 'data/items.ts': text.split('\n')}
        readers.index = {}
        for rel, lines in readers.lines.items():
            for n, line in enumerate(lines, 1):
                for tok in gen_closure.ReaderIndex.QUOTED.findall(line):
                    readers.index.setdefault(tok, []).append((rel, n))
        self.assertEqual(self.features(text, 'damprock', gen_closure.INERT_ITEM_KEYS, readers=readers),
                         ['read by id in data/conditions.ts'])
        # The id inside its own entry is not a reader.
        own = entry('selfref', 'name: "Self",', "onStart() { return 'selfref'; },")
        readers.lines['data/items.ts'] = own.split('\n')
        readers.index = {}
        for rel, lines in readers.lines.items():
            for n, line in enumerate(lines, 1):
                for tok in gen_closure.ReaderIndex.QUOTED.findall(line):
                    readers.index.setdefault(tok, []).append((rel, n))
        self.assertEqual(self.features(own, 'selfref', gen_closure.INERT_ITEM_KEYS, readers=readers), ['callback onStart'])

    def test_an_ability_with_flags_only_is_inert(self):
        src = TextSource('data/abilities.ts', entry('illuminate', 'name: "Illuminate",', 'flags: {},', 'rating: 0,', 'num: 35,'))
        champ = TextSource('data/mods/champions/abilities.ts', '')
        self.assertEqual(gen_closure.entry_features(src, champ, 'illuminate', gen_closure.INERT_ABILITY_KEYS), [])
        src = TextSource('data/abilities.ts', entry('rockhead', 'onDamage(damage, target, source, effect) { },', 'flags: {},',
                                                      'name: "Rock Head",', 'num: 69,'))
        self.assertEqual(gen_closure.entry_features(src, champ, 'rockhead', gen_closure.INERT_ABILITY_KEYS),
                         ['callback onDamage'])

    def test_the_champions_mod_adds_what_it_changes(self):
        src = TextSource('data/abilities.ts', entry('plain', 'name: "Plain",', 'num: 1,'))
        champ = TextSource('data/mods/champions/abilities.ts', entry('plain', 'inherit: true,', 'onStart() { },'))
        self.assertEqual(gen_closure.entry_features(src, champ, 'plain', gen_closure.INERT_ABILITY_KEYS),
                         ['callback onStart'])

    def test_the_handler_columns_follow_the_feature_lists(self):
        self.assertEqual(gen_closure.handler_of({'unmodeled': []}), 0)
        self.assertEqual(gen_closure.handler_of({'unmodeled': ['callback onStart']}), 1)
        self.assertEqual(gen_closure.HANDLER_IDS, ['NONE', 'UNMODELED'])

    def test_the_rows_that_a_step_implements_by_id_are_listed(self):
        self.assertEqual(gen_closure.ENGINE_ROWS, {'items': ['focussash', 'floettite', 'psychicseed', 'electricseed', 'mistyseed', 'expertbelt',
                                                           'ejectbutton', 'widelens', 'muscleband', 'wiseglasses', 'brightpowder', 'redcard', 'lumberry', 'mentalherb'],
                                                   'abilities': ['rockhead', 'flowerveil', 'fairyaura', 'roughskin',
                                                                 'poisontouch', 'thermalexchange', 'stickyhold', 'trace',
                                                                 'levitate', 'sandrush', 'swiftswim', 'slushrush',
                                                                 'chlorophyll', 'innerfocus', 'liquidvoice',
                                                                 'flamebody', 'clearbody', 'hospitality', 'overcoat', 'soundproof',
                                                                 'unnerve', 'speedboost', 'compoundeyes', 'ironfist',
                                                                 'sharpness', 'solidrock', 'technician', 'multiscale',
                                                                 'galewings', 'raindish', 'friendguard', 'cursedbody', 'mirrorarmor', 'auraguard', 'hypercutter', 'scrappy', 'infiltrator', 'queenlymajesty', 'damp', 'sturdy',
                                                                 'snowcloak', 'sandveil', 'static', 'justified', 'limber',
                                                                 'solarpower', 'regenerator', 'toxicdebris', 'shadowtag', 'suctioncups', 'guarddog',
                                                                 'steadfast', 'weakarmor', 'telepathy', 'voltabsorb', 'punkrock', 'moxie',
                                                                 'synchronize', 'oblivious', 'keeneye', 'bigpecks']})


class Bounds(unittest.TestCase):
    """check_bounds reads the widths from the sources that own them (a copy of the repository's three files)."""

    def setUp(self):
        import tempfile
        self.repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for rel in gen_closure.BOUND_SOURCES.values():
            dst = os.path.join(self.tmp.name, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with io.open(os.path.join(self.repo, rel), encoding='utf-8') as fh:
                text = fh.read()
            with io.open(dst, 'w', encoding='utf-8', newline='\n') as fh:
                fh.write(text)

    def data(self, formes=3, moves=5, items=4, abilities=6):
        row = {'set_moves': [], 'set_item': 0xFF, 'dex_num': 1, 'weight_hg': 1, 'base': [1] * 6, 'id': 'x'}
        return {'formes': [dict(row, id='f%d' % i) for i in range(formes)], 'moves': [{}] * moves, 'items': [{}] * items,
                'abilities': [{}] * abilities, 'forme_legal': [{'learnable': [0] * ((moves + 7) // 8)}] * formes}

    def edit(self, key, old, new):
        path = os.path.join(self.tmp.name, gen_closure.BOUND_SOURCES[key])
        with io.open(path, encoding='utf-8') as fh:
            text = fh.read()
        self.assertIn(old, text)
        with io.open(path, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text.replace(old, new, 1))

    def refused(self, d, message):
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_bounds(d, self.tmp.name)
        self.assertIn(message, str(cm.exception.code))

    def test_the_pool_fits_the_widths_of_this_repository(self):
        gen_closure.check_bounds(self.data(), self.tmp.name)
        gen_closure.check_bounds(self.data(formes=346, moves=511, items=166, abilities=215), self.tmp.name)

    def test_the_counts_of_the_ids_are_bounded(self):
        self.refused(self.data(abilities=255), 'a u8 id field holds at most 254')
        self.refused(self.data(items=255), 'a u8 id field holds at most 254')
        self.refused(self.data(moves=513), 'DUOFORGE_DATA_MAX_FORME_MOVES')
        self.refused(self.data(formes=65536), 'bounds')

    def test_a_narrower_field_fails_loudly(self):
        self.edit('state', 'uint16_t species_id; /* SYNTHETIC', 'uint8_t species_id; /* SYNTHETIC')
        self.refused(self.data(formes=346), 'species_id of dfi_member is 8 bits, the pool needs 345')

    def test_a_narrower_move_slot_fails_loudly(self):
        self.edit('state', 'uint16_t move_id;', 'uint8_t move_id;')
        self.refused(self.data(moves=511), 'move_id of dfi_move_slot is 8 bits, the pool needs 510')

    def test_a_narrower_item_or_ability_field_fails_loudly(self):
        self.edit('state', 'uint8_t item;           /* 0 = none */', 'uint8_t item;           /* 0 = none */')
        self.refused(self.data(items=255), 'bounds')
        self.edit('api', 'uint8_t ability;                            /* open: current ability + 1', 'uint8_t abilityx;')
        self.refused(self.data(), 'no integer field ability')

    def test_a_missing_struct_fails_loudly(self):
        self.edit('context', 'struct duoforge_context {', 'struct duoforge_context_renamed {')
        self.refused(self.data(), 'bounds: struct duoforge_context { not found')

    def test_a_row_that_does_not_fit_its_u8_fields_fails(self):
        d = self.data()
        d['formes'][0]['set_moves'] = [255]
        self.refused(d, 'the set of f0 does not fit')
        d = self.data()
        d['formes'][0]['weight_hg'] = 70000
        self.refused(d, 'outside its field')
        d = self.data()
        d['formes'][0]['base'] = [1, 1, 1, 1, 1, 256]
        self.refused(d, 'outside its field')
        d = self.data()
        d['forme_legal'] = [{'learnable': [0]}] * 3
        self.refused(dict(d, moves=[{}] * 9), 'the learnable bitset is too short')


class WholePoolNames(unittest.TestCase):
    def rows(self, ids):
        return [{'id': i} for i in ids]

    def pool(self, aliases=(), formes=('a', 'b')):
        return {'formes': self.rows(formes), 'moves': self.rows(['m']), 'items': self.rows(['i']),
                'abilities': self.rows(['x']), 'natures': self.rows(['hardy']), 'aliases': list(aliases)}

    def test_an_alias_is_a_showdown_id_that_no_row_has(self):
        gen_closure.check_names(self.pool([('apattern', 'a'), ('bpattern', 'b')]))
        for aliases, why in (([('a', 'b')], 'the name of a row'),
                             ([('z', 'a'), ('z', 'b')], 'a name twice'), ([('Z!', 'a')], 'not a Showdown id')):
            with self.subTest(why):
                with self.assertRaises(SystemExit):
                    gen_closure.check_names(self.pool(aliases))

    def test_the_closure_projection_maps_none_to_the_closures_byte(self):
        row = {'mega_forme': None, 'id': 'x'}
        self.assertEqual(gen_closure.closure_projection([row], 'formes')[0]['mega_forme'], 0xFF)
        self.assertEqual(gen_closure.closure_projection([{'mega_base': None, 'mega_forme': 7}], 'items')[0],
                         {'mega_base': 0xFF, 'mega_forme': 7})
        self.assertEqual(gen_closure.forme_id16(None), 0xFFFF)
        self.assertEqual(gen_closure.forme_id16(345), 345)

    def test_a_forme_without_its_own_learnset_learns_what_its_base_learns(self):
        learn = TextSource('data/mods/champions/learnsets.ts', learnset('gourgeist', 'woodhammer'))
        self.assertEqual(gen_closure.learnset_moves(learn, 'gourgeistsmall', 'gourgeist'), {'woodhammer'})
        # An empty entry (Gourgeist-Super) is no learnset of its own.
        learn = TextSource('data/mods/champions/learnsets.ts', learnset('gourgeist', 'protect') + '\n\tgourgeistsuper: {},')
        self.assertEqual(gen_closure.learnset_moves(learn, 'gourgeistsuper', 'gourgeist'), {'protect'})
        # Without a base, or with a base that has none either, it is still refused.
        with self.assertRaises(SystemExit):
            gen_closure.learnset_moves(learn, 'gourgeistsmall')
        with self.assertRaises(SystemExit):
            gen_closure.learnset_moves(learn, 'gourgeistsmall', 'nobody')

    def test_one_ability_may_be_legal_though_the_pin_tags_it(self):
        future = FormeLegal.ABILITIES.replace('name: "Mega Ability",', 'isNonstandard: "Future",\n\t\tname: "Mega Ability",')
        abil = TextSource('data/abilities.ts', future)
        champ = TextSource('data/mods/champions/abilities.ts', '')
        with self.assertRaises(SystemExit):
            gen_closure.ability_released(abil, champ, 'megaability')
        gen_closure.LEGAL_DESPITE_TAG['megaability'] = 'Future'
        try:
            gen_closure.ability_released(abil, champ, 'megaability')
            gen_closure.LEGAL_DESPITE_TAG['megaability'] = 'Past'
            with self.assertRaises(SystemExit):
                gen_closure.ability_released(abil, champ, 'megaability')
        finally:
            del gen_closure.LEGAL_DESPITE_TAG['megaability']
        self.assertEqual(gen_closure.LEGAL_DESPITE_TAG, {'auraguard': 'Future'})

    def test_the_source_index_finds_an_entry_and_demands_its_end(self):
        src = TextSource('data/items.ts', entry('a', 'name: "A",') + '\n' + entry('b', 'name: "B",'))
        self.assertEqual(src.entry('b')[:2], (4, 6))
        self.assertIsNone(src.entry('c'))
        bad = TextSource('data/items.ts', '\ta: {\n\t\tname: "A",\n\t},\n\tb: {\n\t\tname: "B",')
        with self.assertRaises(SystemExit):
            bad.entry('b')
        wrong = TextSource('data/items.ts', '\ta: {\n\t\tname: "A", }\n\t},\n')
        with self.assertRaises(SystemExit):
            wrong.entry('a')

    def test_the_inert_reads_name_the_move_whose_modelling_would_matter(self):
        self.assertEqual(gen_closure.INERT_FLAG_READS, {'bypasssub': 'substitute', 'pledgecombo': None})


class WeatherFacts(unittest.TestCase):
    """The facts about Sandstorm, Snowscape and Weather Ball that the engine hard-codes are read from the pinned
    entries (check_weather_facts); every one of them is demanded, and a condition that grows or loses a handler is
    refused."""

    def sources(self, drop=None, extra=None):
        cond = chr(10).join(entry(cid, *[f for f in facts if f != drop] + ([extra[1]] if extra and extra[0] == cid else []))
                         for cid, facts in gen_closure.WEATHER_FACTS + gen_closure.G32_WEATHER_FACTS)
        ball = entry('weatherball', *[f for f in gen_closure.WEATHER_BALL_FACTS if f != drop])
        return TextSource('data/conditions.ts', cond), TextSource('data/moves.ts', ball)

    def test_the_facts_of_the_pin_are_accepted(self):
        gen_closure.check_weather_facts(*self.sources())

    def test_every_fact_is_demanded(self):
        every = [f for _cid, facts in gen_closure.WEATHER_FACTS + gen_closure.G32_WEATHER_FACTS for f in facts] + list(gen_closure.WEATHER_BALL_FACTS)
        self.assertGreaterEqual(len(every), 17)
        for fact in every:
            with self.subTest(fact=fact), self.assertRaises(SystemExit) as cm:
                gen_closure.check_weather_facts(*self.sources(drop=fact))
            self.assertIn('no longer has', str(cm.exception.code))

    def test_snowscape_does_no_damage(self):
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_weather_facts(*self.sources(extra=('snowscape', 'onWeather(target) {}')))
        self.assertIn('now has onWeather', str(cm.exception.code))

    def test_the_immunity_to_sandstorm_is_a_pool_bit(self):
        self.assertEqual(gen_closure.STATUS_IMMUNITY_P['sandstorm'], 32)
        self.assertNotIn('sandstorm', gen_closure.IGNORED_TYPE_KEYS_P)
        self.assertIn('sandstorm', gen_closure.IGNORED_TYPE_KEYS_C)  # the extended tables do not have it
        self.assertEqual(gen_closure.SAND_IMMUNE_TYPES, ['Ground', 'Rock', 'Steel'])


class PsychicTerrainFacts(unittest.TestCase):
    """Step G15: what the engine hard-codes about Expanding Force, Psychic Terrain and the terrain seeds is read from the
    pinned entries (check_g15_facts); every fact is demanded and Psychic Seed must be Grassy Seed for its terrain."""

    GRASSY = ('name: "Grassy Seed",', 'spritenum: 667,', 'fling: {', '\tbasePower: 10,', '},', 'onSwitchInPriority: -1,',
              'onStart(pokemon) {',
              "\tif (!pokemon.ignoringItem() && this.field.isTerrain('grassyterrain')) {", '\t\tpokemon.useItem();', '\t}',
              '},', 'onTerrainChange(pokemon) {', "\tif (this.field.isTerrain('grassyterrain')) {",
              '\t\tpokemon.useItem();', '\t}', '},', 'boosts: {', '\tdef: 1,', '},', 'num: 884,', 'gen: 7,')

    def seed(self, word, terrain, stat, number, edit=lambda text: text):
        return tuple(edit(line.replace('grassyterrain', terrain).replace('Grassy', word)
                          .replace('def: 1', stat + ': 1').replace('667', number)) for line in self.GRASSY)

    def psychic(self, edit=lambda text: text):
        return self.seed('Psychic', 'psychicterrain', 'spd', '665', edit)

    def sources(self, drop=None, seed=None):
        def facts_entry(mid, facts):
            return entry(mid, *[fact for fact in facts if fact != drop])
        moves = TextSource('data/moves.ts', chr(10).join([
            facts_entry('expandingforce', gen_closure.EXPANDING_FORCE_FACTS),
            facts_entry('psychicterrain', gen_closure.PSYCHIC_TERRAIN_FACTS)]))
        items = TextSource('data/items.ts', chr(10).join([
            entry('grassyseed', *self.GRASSY), entry('psychicseed', *(seed if seed is not None else self.psychic())),
            entry('electricseed', *self.seed('Electric', 'electricterrain', 'def', '664')),
            entry('mistyseed', *self.seed('Misty', 'mistyterrain', 'spd', '666'))]))
        return moves, items

    def test_the_facts_of_the_pin_are_accepted(self):
        gen_closure.check_g15_facts(*self.sources())

    def test_every_fact_is_demanded(self):
        every = list(gen_closure.EXPANDING_FORCE_FACTS) + list(gen_closure.PSYCHIC_TERRAIN_FACTS)
        self.assertEqual(len(every), 11)
        for fact in every:
            with self.subTest(fact=fact), self.assertRaises(SystemExit) as cm:
                gen_closure.check_g15_facts(*self.sources(drop=fact))
            self.assertIn('the entry no longer has', str(cm.exception.code))

    def test_psychic_seed_is_grassy_seed_for_the_other_terrain(self):
        for what, seed in (('another terrain', self.psychic(lambda t: t.replace('psychicterrain', 'electricterrain'))),
                           ('the Defense', self.psychic(lambda t: t.replace('spd: 1', 'def: 1'))),
                           ('two stages', self.psychic(lambda t: t.replace('spd: 1', 'spd: 2'))),
                           ('another priority', self.psychic(lambda t: t.replace('-1,', '0,'))),
                           ('another field', self.psychic() + ('isBerry: true,',))):
            with self.subTest(what), self.assertRaises(SystemExit) as cm:
                gen_closure.check_g15_facts(*self.sources(seed=seed))
            self.assertIn('item psychicseed', str(cm.exception.code))

    def test_the_rows_of_the_step(self):
        self.assertEqual(gen_closure.G15_HANDLERS, ['EXPANDING_FORCE'])
        self.assertEqual(gen_closure.SPECIAL_P['expandingforce'], ('EXPANDING_FORCE', {'onBasePower', 'onModifyMove'}))
        self.assertEqual(gen_closure.SEED_PAIRS, (('psychicseed', 'psychicterrain', 'spd'), ('electricseed', 'electricterrain', 'def'),
                                                  ('mistyseed', 'mistyterrain', 'spd')))
        for seed in ('psychicseed', 'electricseed', 'mistyseed'):
            self.assertIn(seed, gen_closure.ENGINE_ROWS['items'])


class MoveRules(unittest.TestCase):
    """Step G28: what the engine hard-codes about Shell Smash, Acrobatics, Blizzard, Feint, Ancient Power and Expert Belt is read from
    the pinned entries (G28_FACTS, G28_ITEM_FACTS); every fact is demanded, and Ancient Power's secondary is the new
    secondary kind of the pool mode."""

    def source(self, skip=(None, None)):
        out = []
        for mid, needed in gen_closure.G28_FACTS:
            lines = ['\t%s: {' % mid]
            for i, n in enumerate(needed):
                if (mid, i) != skip:
                    lines.append('\t\t' + n)
                    lines.append('\t\t' + '}' * max(0, n.count('{') - n.count('}')))
            lines.append('\t},')
            out.append('\n'.join(lines))
        return TextSource('data/moves.ts', '\n'.join(out))

    def test_the_facts_of_the_pin_are_accepted(self):
        gen_closure.check_g8_conditions(self.source(), gen_closure.G28_FACTS)
        items = TextSource('data/items.ts', entry('expertbelt', *gen_closure.G28_ITEM_FACTS[0][1]))
        gen_closure.check_g28_items(items)

    def test_every_fact_is_demanded(self):
        self.assertEqual([mid for mid, _ in gen_closure.G28_FACTS], ['shellsmash', 'acrobatics', 'blizzard', 'feint', 'grassyterrain', 'earthquake', 'ancientpower'])
        for mid, needed in gen_closure.G28_FACTS:
            for i in range(len(needed)):
                with self.subTest(mid=mid, fact=needed[i]), self.assertRaises(SystemExit) as cm:
                    gen_closure.check_g8_conditions(self.source((mid, i)), gen_closure.G28_FACTS)
                self.assertIn('move %s: the condition no longer has' % mid, str(cm.exception.code))
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_g28_items(TextSource('data/items.ts', entry('expertbelt', 'name: "Expert Belt",')))
        self.assertIn('item expertbelt: the entry no longer has', str(cm.exception.code))

    def test_the_boost_order_of_shell_smash_is_the_pinned_one(self):
        facts = dict(gen_closure.G28_FACTS)
        self.assertIn('boosts: { def: -1, spd: -1, atk: 2, spa: 2, spe: 2, },', facts['shellsmash'])
        self.assertEqual(gen_closure.G2_OWNED_FIELDS['SHELL_SMASH'], {'boosts': 'boosts: { def: -1, spd: -1, atk: 2, spa: 2, spe: 2, },'})

    def test_a_secondary_that_boosts_the_user_is_a_kind_of_the_pool_mode(self):
        text = move_entry('ancientpower', 'Ancient Power', 'secondary: {', '\tchance: 10,', '\tself: {', '\t\tboosts: {', '\t\t\tatk: 1,',
                          '\t\t\tdef: 1,', '\t\t\tspa: 1,', '\t\t\tspd: 1,', '\t\t\tspe: 1,', '\t\t},', '\t},', '},',
                          category='Special', base_power=60, pp=5, type_='Rock', flags='protect: 1, mirror: 1, metronome: 1')
        rec = parse_pool('ancientpower', text)
        self.assertEqual((rec['sec_kind'], rec['sec_chance'], rec['boost_role']), (7, 10, gen_closure.BOOST_ROLE['SECONDARY_SELF']))
        self.assertEqual(rec['boosts'], [1, 1, 1, 1, 1, 0, 0])
        self.assertEqual(rec['special'], 0)
        # The CLOSURE and extended modes keep refusing it.
        for ext in (False, True):
            with self.subTest(ext=ext), self.assertRaises(SystemExit) as cm:
                parse_pool('ancientpower', text, pool=False, ext=ext)
            self.assertIn('secondary self effects are not supported', str(cm.exception.code))

    def test_the_rows_of_the_step(self):
        self.assertEqual(gen_closure.G28_HANDLERS, ['SHELL_SMASH', 'ACROBATICS', 'BLIZZARD', 'FEINT'])
        self.assertEqual(gen_closure.SPECIAL_P['acrobatics'], ('ACROBATICS', {'basePowerCallback'}))
        self.assertEqual(gen_closure.SPECIAL_P['blizzard'], ('BLIZZARD', {'onModifyMove'}))
        self.assertEqual(gen_closure.G2_OWNED_FIELDS['FEINT']['breaksProtect'], 'breaksProtect: true, // Breaking protection implemented in scripts.js')
        self.assertIn('expertbelt', gen_closure.ENGINE_ROWS['items'])
        self.assertEqual(gen_closure.SECONDARY_SELF_BOOST, 7)


class SmallRules(unittest.TestCase):
    """Step G32: what the engine hard-codes about the moves, abilities and the item of the batch is read from the pinned
    entries (G32_FACTS, G32_WEATHER_FACTS, G32_ENTRY_FACTS); every fact is demanded."""

    def moves(self, skip=(None, None)):
        out = []
        for mid, needed in gen_closure.G32_FACTS:
            lines = ['\t%s: {' % mid]
            for i, n in enumerate(needed):
                if (mid, i) != skip:
                    lines.append('\t\t' + n)
                    lines.append('\t\t' + '}' * max(0, n.count('{') - n.count('}')))
            lines.append('\t},')
            out.append('\n'.join(lines))
        return TextSource('data/moves.ts', '\n'.join(out))

    def test_the_facts_of_the_pin_are_accepted(self):
        gen_closure.check_g8_conditions(self.moves(), gen_closure.G32_FACTS)

    def test_every_move_fact_is_demanded(self):
        self.assertEqual([mid for mid, _ in gen_closure.G32_FACTS],
                         ['eruption', 'waterspout', 'bodypress', 'foulplay', 'psyshock', 'raindance', 'sunnyday', 'freezedry',
                          'clangingscales', 'voltswitch', 'lifedew'])
        for mid, needed in gen_closure.G32_FACTS:
            for i in range(len(needed)):
                with self.subTest(mid=mid, fact=needed[i]), self.assertRaises(SystemExit) as cm:
                    gen_closure.check_g8_conditions(self.moves((mid, i)), gen_closure.G32_FACTS)
                self.assertIn('move %s: the condition no longer has' % mid, str(cm.exception.code))

    def test_every_fact_of_the_ability_and_item_entries_is_demanded(self):
        for kind, eid, champ, facts in gen_closure.G32_ENTRY_FACTS:
            whole = TextSource('x.ts', entry(eid, *facts))
            gen_closure.check_g32_entries(whole, whole, whole, whole, only=((kind, eid, champ, facts),))
            for i in range(len(facts)):
                short = TextSource('x.ts', entry(eid, *(facts[:i] + facts[i + 1:])))
                with self.subTest(entry=eid, fact=facts[i]), self.assertRaises(SystemExit) as cm:
                    gen_closure.check_g32_entries(short, short, short, short, only=((kind, eid, champ, facts),))
                self.assertIn('the entry no longer has', str(cm.exception.code))

    def test_the_weather_moves_are_handlers_with_their_weather_as_an_owned_field(self):
        self.assertEqual(gen_closure.SPECIAL_P['raindance'], ('RAIN_DANCE', set()))
        self.assertEqual(gen_closure.SPECIAL_P['sunnyday'], ('SUNNY_DAY', set()))
        self.assertEqual(gen_closure.G2_OWNED_FIELDS['RAIN_DANCE'], {'weather': "weather: 'RainDance',"})
        self.assertEqual(gen_closure.G2_OWNED_FIELDS['SUNNY_DAY'], {'weather': "weather: 'sunnyday',"})
        self.assertEqual([c for c, _ in gen_closure.G32_WEATHER_FACTS], ['raindance', 'sunnyday'])

    def test_the_rows_of_the_step(self):
        self.assertEqual(gen_closure.G32_HANDLERS, ['HP_POWER', 'BODY_PRESS', 'FOUL_PLAY', 'PSYSHOCK', 'RAIN_DANCE', 'SUNNY_DAY',
                                                    'FREEZE_DRY', 'CLANGING_SCALES'])
        self.assertEqual(gen_closure.SPECIAL_P['eruption'], ('HP_POWER', {'basePowerCallback'}))
        self.assertEqual(gen_closure.SPECIAL_P['waterspout'], ('HP_POWER', {'basePowerCallback'}))
        self.assertEqual(gen_closure.SPECIAL_P['freezedry'], ('FREEZE_DRY', {'onEffectiveness'}))
        self.assertEqual(gen_closure.ENGINE_PIVOT_MOVES, ('voltswitch', 'revivalblessing'))
        self.assertIn('allies', gen_closure.ENGINE_TARGETS)
        self.assertIn('ejectbutton', gen_closure.ENGINE_ROWS['items'])
        for ability in ('soundproof', 'unnerve', 'speedboost'):
            self.assertIn(ability, gen_closure.ENGINE_ROWS['abilities'])


class SmallRulesG35(unittest.TestCase):
    """Step G35: Friend Guard and Rain Dish are engine rows whose pinned texts are demanded whole (G35_ABILITY_FACTS)."""

    def sources(self, skip=(None, None)):
        abilities = []
        for aid, facts in gen_closure.G34_ABILITY_FACTS + gen_closure.G35_ABILITY_FACTS + gen_closure.MEGA2_ABILITY_FACTS + gen_closure.G39_ABILITY_FACTS + gen_closure.G41_ABILITY_FACTS + gen_closure.G45_ABILITY_FACTS + gen_closure.G46_ABILITY_FACTS + gen_closure.G47_ABILITY_FACTS + gen_closure.G51_ABILITY_FACTS:
            kept = [f for i, f in enumerate(facts) if (aid, i) != skip]
            abilities.append(entry(aid, *kept))
        items = [entry(iid, *facts) for iid, facts in gen_closure.G34_ITEM_FACTS + gen_closure.G46_ITEM_FACTS + gen_closure.G47_ITEM_FACTS]
        return (TextSource('data/abilities.ts', '\n'.join(abilities)), TextSource('data/mods/champions/abilities.ts', ''),
                TextSource('data/items.ts', '\n'.join(items)), TextSource('data/mods/champions/items.ts', ''))

    def test_the_facts_of_the_pin_are_accepted(self):
        gen_closure.check_g34_facts(*self.sources())

    def test_every_fact_is_demanded(self):
        self.assertEqual([aid for aid, _ in gen_closure.G35_ABILITY_FACTS], ['friendguard', 'raindish'])
        for aid, facts in gen_closure.G35_ABILITY_FACTS:
            for i in range(len(facts)):
                with self.subTest(ability=aid, fact=facts[i]), self.assertRaises(SystemExit) as cm:
                    gen_closure.check_g34_facts(*self.sources((aid, i)))
                self.assertIn('the entry no longer has', str(cm.exception.code))

    def test_the_rows_of_the_step(self):
        for ability in ('raindish', 'friendguard'):
            self.assertIn(ability, gen_closure.ENGINE_ROWS['abilities'])

    def test_aura_guard_of_mega_batch_2_is_demanded_whole(self):
        self.assertEqual([aid for aid, _ in gen_closure.MEGA2_ABILITY_FACTS], ['auraguard'])
        self.assertIn('auraguard', gen_closure.ENGINE_ROWS['abilities'])
        for aid, facts in gen_closure.MEGA2_ABILITY_FACTS:
            for i in range(len(facts)):
                with self.subTest(ability=aid, fact=facts[i]), self.assertRaises(SystemExit) as cm:
                    gen_closure.check_g34_facts(*self.sources((aid, i)))
                self.assertIn('the entry no longer has', str(cm.exception.code))


class TerrainFacts(unittest.TestCase):
    """Step G25: what the engine hard-codes about Electric Terrain, Misty Terrain, Rising Voltage and Terrain Pulse is read
    from the pinned entries (G25_FACTS, checked with the conditions of steps G8 and G20); every fact is demanded."""

    def source(self, skip=(None, None)):
        out = []
        for mid, needed in gen_closure.G25_FACTS:
            lines = ['\t%s: {' % mid]
            for i, n in enumerate(needed):
                if (mid, i) != skip:
                    lines.append('\t\t' + n)
                    lines.append('\t\t' + '}' * max(0, n.count('{') - n.count('}')))
            lines.append('\t},')
            out.append('\n'.join(lines))
        return TextSource('data/moves.ts', '\n'.join(out))

    def test_the_facts_of_the_pin_are_accepted(self):
        gen_closure.check_g8_conditions(self.source(), gen_closure.G25_FACTS)

    def test_every_fact_is_demanded(self):
        self.assertEqual([mid for mid, _ in gen_closure.G25_FACTS],
                         ['electricterrain', 'mistyterrain', 'risingvoltage', 'terrainpulse'])
        for mid, needed in gen_closure.G25_FACTS:
            for i in range(len(needed)):
                with self.subTest(mid=mid, fact=needed[i]), self.assertRaises(SystemExit) as cm:
                    gen_closure.check_g8_conditions(self.source((mid, i)), gen_closure.G25_FACTS)
                self.assertIn('move %s: the condition no longer has' % mid, str(cm.exception.code))

    def test_the_two_terrains_differ_in_what_the_engine_reads(self):
        facts = dict(gen_closure.G25_FACTS)
        self.assertTrue(any("'slp'" in f for f in facts['electricterrain']))
        self.assertTrue(any('[5325, 4096]' in f for f in facts['electricterrain']))
        self.assertTrue(any('chainModify(0.5)' in f for f in facts['mistyterrain']))
        self.assertIn("onFieldEnd() { this.add('-fieldend', 'Misty Terrain'); },", facts['mistyterrain'])  # no "move: "

    def test_the_rows_of_the_step(self):
        self.assertEqual(gen_closure.G25_HANDLERS, ['ELECTRIC_TERRAIN', 'MISTY_TERRAIN', 'RISING_VOLTAGE', 'TERRAIN_PULSE'])
        self.assertEqual(gen_closure.SPECIAL_P['risingvoltage'], ('RISING_VOLTAGE', {'basePowerCallback'}))
        self.assertEqual(gen_closure.SPECIAL_P['terrainpulse'], ('TERRAIN_PULSE', {'onModifyType', 'onModifyMove'}))
        self.assertEqual(gen_closure.G2_OWNED_FIELDS['ELECTRIC_TERRAIN'], {'terrain': "terrain: 'electricterrain',"})
        self.assertEqual(gen_closure.G2_OWNED_FIELDS['MISTY_TERRAIN'], {'terrain': "terrain: 'mistyterrain',"})
        self.assertIn('ELECTRIC_TERRAIN', gen_closure.G2_OWNED_CONDITION)
        self.assertIn('MISTY_TERRAIN', gen_closure.G2_OWNED_CONDITION)
        self.assertEqual(gen_closure.TERRAIN_CODES['electricterrain'], ('ELECTRIC', 3))
        self.assertEqual(gen_closure.TERRAIN_CODES['mistyterrain'], ('MISTY', 4))


class SmallRulesG39(unittest.TestCase):
    """Step G39: thirteen abilities and four moves; the pinned texts that the engine hard-codes are demanded whole."""

    def abilities(self, skip=(None, None)):
        out = []
        for aid, facts in gen_closure.G34_ABILITY_FACTS + gen_closure.G35_ABILITY_FACTS + gen_closure.MEGA2_ABILITY_FACTS + gen_closure.G39_ABILITY_FACTS + gen_closure.G41_ABILITY_FACTS + gen_closure.G45_ABILITY_FACTS + gen_closure.G46_ABILITY_FACTS + gen_closure.G47_ABILITY_FACTS + gen_closure.G51_ABILITY_FACTS:
            kept = [f for i, f in enumerate(facts) if (aid, i) != skip]
            out.append(entry(aid, *kept))
        items = [entry(iid, *facts) for iid, facts in gen_closure.G34_ITEM_FACTS + gen_closure.G46_ITEM_FACTS + gen_closure.G47_ITEM_FACTS]
        return (TextSource('data/abilities.ts', '\n'.join(out)), TextSource('data/mods/champions/abilities.ts', ''),
                TextSource('data/items.ts', '\n'.join(items)), TextSource('data/mods/champions/items.ts', ''))

    def moves(self, skip=(None, None)):
        out = []
        for mid, needed in gen_closure.G39_FACTS:
            lines = ['\t%s: {' % mid]
            for i, n in enumerate(needed):
                if (mid, i) != skip:
                    lines.append('\t\t' + n)
                    lines.append('\t\t' + '}' * max(0, n.count('{') - n.count('}')))
            lines.append('\t},')
            out.append('\n'.join(lines))
        return TextSource('data/moves.ts', '\n'.join(out))

    def test_the_facts_of_the_pin_are_accepted(self):
        gen_closure.check_g34_facts(*self.abilities())
        gen_closure.check_g8_conditions(self.moves(), gen_closure.G39_FACTS)

    def test_every_fact_is_demanded(self):
        self.assertEqual([a for a, _ in gen_closure.G39_ABILITY_FACTS],
                         ['hypercutter', 'scrappy', 'infiltrator', 'queenlymajesty', 'damp', 'sturdy', 'snowcloak', 'sandveil',
                          'static', 'justified', 'limber', 'solarpower'])
        for aid, facts in gen_closure.G39_ABILITY_FACTS:
            for i in range(len(facts)):
                with self.subTest(ability=aid, fact=facts[i]), self.assertRaises(SystemExit) as cm:
                    gen_closure.check_g34_facts(*self.abilities((aid, i)))
                self.assertIn('the entry no longer has', str(cm.exception.code))
        for mid, needed in gen_closure.G39_FACTS:
            for i in range(len(needed)):
                with self.subTest(move=mid, fact=needed[i]), self.assertRaises(SystemExit) as cm:
                    gen_closure.check_g8_conditions(self.moves((mid, i)), gen_closure.G39_FACTS)
                self.assertIn('move %s: the condition no longer has' % mid, str(cm.exception.code))

    def test_regenerator_is_read_from_the_champions_entry(self):
        facts = [f for f in gen_closure.G32_ENTRY_FACTS if f[1] == 'regenerator']
        self.assertEqual(len(facts), 1)
        self.assertEqual((facts[0][0], facts[0][2]), ('ability', True))
        self.assertIn('[silent]', facts[0][3][0])

    def test_the_rows_of_the_step(self):
        for ability in ('hypercutter', 'scrappy', 'infiltrator', 'queenlymajesty', 'damp', 'sturdy', 'snowcloak', 'sandveil',
                        'static', 'justified', 'limber', 'solarpower', 'regenerator'):
            self.assertIn(ability, gen_closure.ENGINE_ROWS['abilities'])
        self.assertEqual(gen_closure.SPECIAL_P['sacredsword'], ('DARKEST_LARIAT', set()))  # Darkest Lariat's handler
        self.assertEqual(gen_closure.SPECIAL_P['superfang'], ('SUPER_FANG', {'damageCallback'}))
        self.assertEqual(gen_closure.BOOST_ROLE['PRIMARY_TARGET'], 6)


class SimpleMovesG44(unittest.TestCase):
    """Step G44: the four handlers (Power Trip, Thunder, Ice Fang, Tri Attack) and the texts they own."""

    def test_the_rows_of_the_step(self):
        self.assertEqual(gen_closure.G44_HANDLERS, ['POWER_TRIP', 'THUNDER', 'ICE_FANG', 'TRI_ATTACK'])
        self.assertEqual(gen_closure.SPECIAL_P['powertrip'], ('POWER_TRIP', {'basePowerCallback'}))
        self.assertEqual(gen_closure.SPECIAL_P['thunder'], ('THUNDER', {'onModifyMove'}))
        self.assertEqual(gen_closure.SPECIAL_P['icefang'], ('ICE_FANG', set()))
        self.assertEqual(gen_closure.SPECIAL_P['triattack'], ('TRI_ATTACK', set()))
        self.assertIn('secondaries', gen_closure.G2_OWNED_FIELDS['ICE_FANG'])
        self.assertIn('TRI_ATTACK', gen_closure.G2_OWNED_SECONDARY)
        self.assertEqual([mid for mid, _ in gen_closure.G44_FACTS], ['powertrip', 'thunder', 'icefang', 'triattack'])


if __name__ == '__main__':
    unittest.main()
