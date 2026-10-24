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

usage: python3 tools/datagen/tests/test_gen_closure.py
"""
import sys
import io
import json
import os
import re
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
                         {'ATE': 4, 'PINCH': 4, 'WEATHER_SETTER': 4, 'TERRAIN_SETTER': 3})  # step G61: Dragonize joins the ATE family
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
                                       TextSource('data/mods/champions/abilities.ts', champ),
                                       (len(self.POOL_MOVES) + 7) // 8, 'the test pool')

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

    def test_the_handlers_are_the_new_specials_in_order(self):
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
                          'MULTI_HIT_2_5', 'SCALE_SHOT', 'QUICK_GUARD', 'UPPER_HAND', 'HEAL_PULSE', 'STRENGTH_SAP', 'BEAT_UP', 'BUG_BITE', 'POLTERGEIST', 'SHEER_COLD', 'HAZE', 'AFTER_YOU', 'QUASH', 'SUBSTITUTE', 'PHANTOM_FORCE', 'STEEL_BEAM', 'THUNDER_WAVE', 'SKILL_SWAP', 'KINGS_SHIELD', 'ALLURING_VOICE', 'DRAGON_CHEER', 'BATON_PASS', 'DESTINY_BOND', 'FINAL_GAMBIT', 'DRAGON_DARTS', 'LASH_OUT', 'ASSURANCE', 'BANEFUL_BUNKER', 'HEAVY_SLAM', 'HARD_PRESS', 'ICE_SPINNER', 'BELLY_DRUM', 'WILL_CRIT', 'LEECH_SEED', 'CURSE', 'CONFUSE', 'OHKO', 'MEMENTO', 'LEVEL_DAMAGE', 'HEALING_WISH', 'PARTIAL_TRAP', 'ENDEAVOR', 'PSYCH_UP', 'ALLY_SWITCH', 'PSYCHIC_TERRAIN', 'SPEED_SWAP', 'UNMODELED'])  # G88 (decision 0046) adds two, G94 (decision 0015 5cv) one, G82 (decision 0045) one, G90 (decision 0060) one, before UNMODELED
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
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G64_HANDLERS], [82, 83, 84, 85])  # G64: Beat Up, Bug Bite, Poltergeist, Sheer Cold
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G62_HANDLERS], [86, 87, 88])  # G62: Haze, After You, Quash
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G60_HANDLERS], [89])  # G60: SUBSTITUTE
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G58_HANDLERS], [90])  # G58: Phantom Force
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G68_HANDLERS], [91, 92])  # G68: Steel Beam, Thunder Wave
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G70_HANDLERS], [93])  # G70: Skill Swap (decision 0041)
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G66_HANDLERS], [94])  # G66: King's Shield (decision 0015 5cb)
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G72B_HANDLERS], [95, 96])  # G72b: Alluring Voice, Dragon Cheer
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G74_HANDLERS], [97])  # G74: Baton Pass (decision 0042)
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G76_HANDLERS], [98, 99])  # G76: Destiny Bond, Final Gambit (decision 0015 5cg)
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G78_HANDLERS], [100])  # G78: Dragon Darts (decision 0043)
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G88_HANDLERS], [101, 102])  # G88: Lash Out, Assurance (decision 0046)
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G84_HANDLERS], [109, 110])  # G84 (decision 0047)
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G92_HANDLERS], [111, 112, 113, 114])  # G92 (decision 0062)
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G86_HANDLERS], [104, 105, 106, 107])  # G86 (5cn, decision 0048)
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.C4_HANDLERS], [108])  # C4 (decision 0015 5ct)
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G94_HANDLERS], [103])  # G94: Baneful Bunker (decision 0015 5cv)
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G82_HANDLERS], [115])
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G90_HANDLERS], [116])  # G90: the partial trap (decision 0060)
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G96_HANDLERS], [120])  # G96 (decision 0015 5cz): Psychic Terrain
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.K3_HANDLERS], [121])  # K3 (decision 0015 5de): Speed Swap
        self.assertEqual(gen_closure.SPECIAL_IDS_P.index('UNMODELED'), 122)
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.C5_HANDLERS], [117])  # C5: Endeavor (decision 0015 entry 5cy)
        self.assertEqual([gen_closure.SPECIAL_IDS_P.index(h) for h in gen_closure.G80_HANDLERS], [118, 119])  # G80: Psych Up, Ally Switch (decision 0044)
        # Scald and Recover became data in step G10: their ids stay defined and no move maps to them.
        self.assertEqual({v[0] for k, v in gen_closure.SPECIAL_P.items() if k not in gen_closure.SPECIAL_C},
                         (set(gen_closure.G2_HANDLERS) - {'SCALD', 'RECOVER'}) | set(gen_closure.G70_HANDLERS) | set(gen_closure.G66_HANDLERS) | set(gen_closure.G72B_HANDLERS) | set(gen_closure.G74_HANDLERS) | set(gen_closure.G76_HANDLERS) | set(gen_closure.G78_HANDLERS) | set(gen_closure.G88_HANDLERS) | set(gen_closure.G86_HANDLERS) | set(gen_closure.C4_HANDLERS) | set(gen_closure.G84_HANDLERS) | set(gen_closure.G92_HANDLERS) | set(gen_closure.G64_HANDLERS) | set(gen_closure.WEATHER_HANDLERS) |
                         set(gen_closure.G16_HANDLERS) | set(gen_closure.G15_HANDLERS) | set(gen_closure.G19_HANDLERS) |
                         set(gen_closure.G20_HANDLERS) | set(gen_closure.G20_PROTECT_HANDLERS) | set(gen_closure.G94_HANDLERS) | set(gen_closure.C5_HANDLERS) | set(gen_closure.G96_HANDLERS) | set(gen_closure.K3_HANDLERS) | set(gen_closure.G28_HANDLERS) |
                         set(gen_closure.G30_HANDLERS) | set(gen_closure.G32_HANDLERS) | set(gen_closure.G34_HANDLERS) |
                         set(gen_closure.G27_HANDLERS) | set(gen_closure.G25_HANDLERS) | set(gen_closure.G26_HANDLERS) | set(gen_closure.G33_HANDLERS) | set(gen_closure.G38_HANDLERS) | set(gen_closure.G29_HANDLERS) | set(gen_closure.G39_HANDLERS) | set(gen_closure.G31_HANDLERS) | set(gen_closure.G48_HANDLERS) | set(gen_closure.G44_HANDLERS) | set(gen_closure.G50_HANDLERS) | set(gen_closure.G42_HANDLERS) | set(gen_closure.G56_HANDLERS) | set(gen_closure.G52_HANDLERS) | set(gen_closure.G54_HANDLERS) | set(gen_closure.G62_HANDLERS) | set(gen_closure.G60_HANDLERS) | set(gen_closure.G58_HANDLERS) | set(gen_closure.G68_HANDLERS) | set(gen_closure.G66_HANDLERS) | set(gen_closure.G82_HANDLERS) | set(gen_closure.G90_HANDLERS) | set(gen_closure.G80_HANDLERS) | {'DARKEST_LARIAT'})


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
                # K4 (#475): Gravity is modelled; Magic Room (K5) is the unmodelled pseudo weather here
                self.refused('plain', PLAIN.replace('target: "normal",', "pseudoWeather: 'magicroom',\n\t\ttarget: \"normal\","),
                             'pseudo weather magicroom is not modelled', pool=False, ext=ext)

    def test_the_rows_of_the_step(self):
        every = gen_closure.G2_MOVES + gen_closure.G2_ITEMS + gen_closure.G2_ABILITIES
        self.assertEqual(len(gen_closure.G2_MOVES), 22)
        self.assertEqual((len(gen_closure.G2_ITEMS), len(gen_closure.G2_ABILITIES)), (3, 3))
        self.assertEqual(len(set(gen_closure.G2_MOVES)), 22)
        self.assertEqual(len(set(every)), len(every))
        self.assertEqual([s[0] for s in gen_closure.SETS_G2], ['pelipper', 'arcaninehisui', 'annihilape', 'floetteeternal'])
        # Every handler move is one of the rows, and every set move is a pool move or one of the rows.
        self.assertTrue({k for k in gen_closure.SPECIAL_P if k not in gen_closure.SPECIAL_C} <=
                        set(gen_closure.G2_MOVES) | {'ragingfury', 'doublehit', 'tailslap', 'bonerush', 'solarblade', 'snaptrap'} |
                        {'storedpower', 'bulletseed', 'rockblast', 'pinmissile', 'watershuriken', 'heatcrash'} | {'outrage', 'thrash', 'petaldance','sandstorm', 'snowscape', 'knockoff', 'expandingforce', 'glaiverush', 'auroraveil', 'spikyshield',
                                                                'substitute', 'kingsshield', 'banefulbunker', 'psychicterrain', 'speedswap', 'shellsmash', 'acrobatics', 'blizzard', 'feint', 'alluringvoice', 'dragoncheer', 'dragondarts', 'psychup', 'allyswitch', 'bind', 'wrap', 'firespin', 'sandtomb', 'snaptrap', 'infestation', 'lashout', 'assurance', 'leechseed', 'curse',
                                                                'substitute', 'kingsshield', 'shellsmash', 'acrobatics', 'blizzard', 'feint', 'alluringvoice', 'dragoncheer', 'dragondarts',
                                                                'confuseray', 'swagger', 'flatter', 'teeterdance', 'fissure', 'guillotine', 'horndrill', 'memento', 'nightshade',
                                                                'ragepowder', 'psychicfangs', 'solarbeam', 'eruption', 'waterspout',
                                                                'bodypress', 'foulplay', 'psyshock', 'raindance', 'sunnyday', 'freezedry',
                                                                'clangingscales', 'steelroller', 'clangoroussoul', 'brickbreak', 'disable',
                                                                'electricterrain', 'mistyterrain', 'risingvoltage', 'terrainpulse', 'perishsong',
                                                                'dualwingbeat', 'twinbeam', 'tripleaxel', 'imprison', 'batonpass',
                                                                'trick', 'switcheroo', 'thief', 'covet', 'sacredsword', 'superfang', 'taunt', 'yawn',
                                                                'ragefist', 'stoneaxe', 'ceaselessedge', 'populationbomb',
                                                                'stormthrow', 'flowertrick', 'frostbreath', 'endeavor',
                                                                'powertrip', 'thunder', 'icefang', 'triattack', 'doubleshock', 'roost', 'stompingtantrum', 'temperflare', 'revivalblessing',
                                                                'iciclespear', 'scaleshot', 'quickguard', 'upperhand', 'healpulse', 'strengthsap', 'beatup', 'bugbite', 'poltergeist', 'sheercold',
                                                                'haze', 'afteryou', 'quash', 'phantomforce',
                                                                'steelbeam', 'thunderwave', 'skillswap', 'destinybond', 'finalgambit',
                                                                'heavyslam', 'hardpress', 'icespinner', 'bellydrum', 'healingwish',
                                                                'seismictoss', 'sweetkiss'})  # G86 (decision 0015 5cn); G82 (decision 0045); A0 (batch A0 part 2)
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
        self.assertEqual(sorted(bits.values()), [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 2048])  # 2048: mustpressure (step G53)
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
            ('pseudo weather magicroom', with_line(PLAIN, "pseudoWeather: 'magicroom',")),
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
        self.assertEqual(gen_closure.ENGINE_ROWS, {'items': ['airballoon', 'ironball', 'bindingband', 'focussash', 'floettite', 'psychicseed', 'electricseed', 'mistyseed', 'expertbelt',
                                                           'ejectbutton', 'widelens', 'muscleband', 'wiseglasses', 'brightpowder', 'redcard', 'lumberry', 'mentalherb',
                                                           'damprock', 'heatrock', 'smoothrock', 'icyrock', 'terrainextender', 'scopelens', 'leek',
                                                           'quickclaw', 'focusband'],
                                                   'abilities': ['magicguard', 'bulletproof', 'rivalry', 'leafguard', 'rockhead', 'flowerveil', 'fairyaura', 'roughskin',
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
                                                                 'synchronize', 'oblivious', 'keeneye', 'bigpecks', 'magicbounce', 'pressure', 'stancechange',
                                                                 'sandforce', 'shellarmor', 'filter', 'stalwart', 'megalauncher', 'hugepower', 'thickfat', 'firemane', 'spicyspray', 'megasol', 'cloudnine', 'sheerforce', 'illusion', 'symbiosis', 'frisk',
                                                                 'unaware', 'marvelscale', 'waterbubble', 'reckless', 'superluck', 'moody', 'cutecharm', 'purepower', 'battlearmor', 'magmaarmor', 'angerpoint', 'sniper', 'piercingdrill',
                                                                 # A2a (decision 0015 entry 5dy)
                                                                 'illuminate', 'whitesmoke', 'waterabsorb', 'eartheater', 'motordrive',
                                                                 'icebody', 'surgesurfer', 'quickfeet', 'corrosion', 'purifyingsalt',
                                                                 'gooey', 'poisonpoint', 'tangledfeet', 'naturalcure']})


# The id bounds of Reg M-C's table set, read from its definition (tables.bounds of data/formats/reg-mc.json).
with io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                          'data', 'formats', 'reg-mc.json'), encoding='utf-8') as _fh:
    REG_MC_BOUNDS = json.load(_fh)['tables']['bounds']


class Bounds(unittest.TestCase):
    """check_bounds reads the widths from the sources that own them (a copy of the repository's three files)."""

    def setUp(self):
        import tempfile
        self.repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
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
                'abilities': [{}] * abilities, 'forme_legal': [{'learnable': [0] * ((moves + 7) // 8), 'moves': []}] * formes}

    def edit(self, key, old, new):
        path = os.path.join(self.tmp.name, gen_closure.BOUND_SOURCES[key])
        with io.open(path, encoding='utf-8') as fh:
            text = fh.read()
        self.assertIn(old, text)
        with io.open(path, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text.replace(old, new, 1))

    def refused(self, d, message):
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_bounds(d, self.tmp.name, REG_MC_BOUNDS)
        self.assertIn(message, str(cm.exception.code))

    def test_the_pool_fits_the_widths_of_this_repository(self):
        gen_closure.check_bounds(self.data(), self.tmp.name, REG_MC_BOUNDS)
        gen_closure.check_bounds(self.data(formes=346, moves=511, items=166, abilities=215), self.tmp.name, REG_MC_BOUNDS)

    def test_the_counts_of_the_ids_are_bounded(self):
        self.refused(self.data(abilities=255), 'the table set holds at most 254 and 254')
        self.refused(self.data(items=255), 'the table set holds at most 254 and 254')
        # W2 (O8): DUOFORGE_DATA_MAX_FORME_MOVES bounds the legal moves of one forme, not the moves in total.
        many = self.data(moves=513)
        gen_closure.check_bounds(many, self.tmp.name, REG_MC_BOUNDS)
        many['forme_legal'] = [dict(many['forme_legal'][0], moves=['m'] * 513)] * 3
        self.refused(many, 'a forme has 513 legal moves, the bound moves_per_forme is 512')
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
        d['forme_legal'] = [{'learnable': [0], 'moves': []}] * 3
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
        self.assertEqual(gen_closure.INERT_FLAG_READS, {'pledgecombo': None})
        # step G60: bypasssub is no column of its own; it is bit 2 (value 4) of the third flags byte, FLAGS3_BITS
        self.assertEqual(gen_closure.FLAGS3_BITS['bypasssub'], 4)  # held by dfi_pool_move_bypasssub


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
        self.assertEqual(gen_closure.ENGINE_PIVOT_MOVES, ('voltswitch', 'revivalblessing', 'batonpass'))
        self.assertIn('allies', gen_closure.ENGINE_TARGETS)
        self.assertIn('ejectbutton', gen_closure.ENGINE_ROWS['items'])
        for ability in ('soundproof', 'unnerve', 'speedboost'):
            self.assertIn(ability, gen_closure.ENGINE_ROWS['abilities'])


class A2aFacts(unittest.TestCase):
    """A2a (decision 0015 entry 5dy): the fourteen engine rows' pinned texts are demanded whole (A2A_ABILITY_FACTS, Natural Cure's
    Champions entry, A2A_OTHER_FACTS); each one dropped from its source fails the generator."""

    def sources(self, skip=None):
        base = [entry(aid, *[f for i, f in enumerate(facts) if ('base', aid, i) != skip])
                for aid, facts in gen_closure.A2A_ABILITY_FACTS]
        champ = [entry(aid, *[f for i, f in enumerate(facts) if ('champ', aid, i) != skip])
                 for aid, facts in gen_closure.A2A_CHAMPIONS_FACTS]
        others = {rel: TextSource(rel, '\n'.join(f for i, f in enumerate(facts) if ('other', rel, i) != skip))
                  for rel, facts in gen_closure.A2A_OTHER_FACTS}
        return (TextSource('data/abilities.ts', '\n'.join(base)), TextSource('data/mods/champions/abilities.ts', '\n'.join(champ)),
                others)

    def test_the_facts_are_accepted(self):
        gen_closure.check_a2a_facts(*self.sources())

    def test_the_rows_of_the_batch(self):
        ids = [aid for aid, _ in gen_closure.A2A_ABILITY_FACTS] + [aid for aid, _ in gen_closure.A2A_CHAMPIONS_FACTS]
        self.assertEqual(sorted(ids), sorted(['illuminate', 'whitesmoke', 'waterabsorb', 'eartheater', 'motordrive', 'icebody',
                                              'surgesurfer', 'quickfeet', 'corrosion', 'purifyingsalt', 'gooey', 'poisonpoint',
                                              'tangledfeet', 'naturalcure']))
        for aid in ids:
            self.assertIn(aid, gen_closure.ENGINE_ROWS['abilities'])

    def test_every_fact_is_demanded(self):
        cases = [('base', aid, i) for aid, facts in gen_closure.A2A_ABILITY_FACTS for i in range(len(facts))]
        cases += [('champ', aid, i) for aid, facts in gen_closure.A2A_CHAMPIONS_FACTS for i in range(len(facts))]
        cases += [('other', rel, i) for rel, facts in gen_closure.A2A_OTHER_FACTS for i in range(len(facts))]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(SystemExit) as cm:
                gen_closure.check_a2a_facts(*self.sources(case))
            self.assertIn('no longer has', str(cm.exception.code))

    def test_a_champions_override_of_a_base_row_fails(self):
        abil, champ, others = self.sources()
        champ = TextSource('data/mods/champions/abilities.ts', entry('gooey', 'inherit: true,', 'flags: {},'))
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_a2a_facts(abil, champ, others)
        self.assertIn('overrides', str(cm.exception.code))


class SmallRulesG35(unittest.TestCase):
    """Step G35: Friend Guard and Rain Dish are engine rows whose pinned texts are demanded whole (G35_ABILITY_FACTS)."""

    def sources(self, skip=(None, None)):
        abilities = []
        for aid, facts in gen_closure.G34_ABILITY_FACTS + gen_closure.G35_ABILITY_FACTS + gen_closure.MEGA2_ABILITY_FACTS + gen_closure.G39_ABILITY_FACTS + gen_closure.G41_ABILITY_FACTS + gen_closure.G67_ABILITY_FACTS + gen_closure.G83_ABILITY_FACTS + gen_closure.G81_ABILITY_FACTS + gen_closure.G79_ABILITY_FACTS + gen_closure.G75_ABILITY_FACTS + gen_closure.G71_ABILITY_FACTS + gen_closure.G45_ABILITY_FACTS + gen_closure.G46_ABILITY_FACTS + gen_closure.G47_ABILITY_FACTS + gen_closure.G51_ABILITY_FACTS + gen_closure.G53_ABILITY_FACTS + gen_closure.G63_ABILITY_FACTS + gen_closure.G59_ABILITY_FACTS + gen_closure.G69_ABILITY_FACTS + gen_closure.G65_ABILITY_FACTS + gen_closure.G73_ABILITY_FACTS + gen_closure.G77_ABILITY_FACTS + gen_closure.K2_ABILITY_FACTS:
            kept = [f for i, f in enumerate(facts) if (aid, i) != skip]
            abilities.append(entry(aid, *kept))
        items = [entry(iid, *facts) for iid, facts in gen_closure.G34_ITEM_FACTS + gen_closure.G46_ITEM_FACTS + gen_closure.G47_ITEM_FACTS + gen_closure.G67_ITEM_FACTS + gen_closure.G83_ITEM_FACTS + gen_closure.G75_ITEM_FACTS + gen_closure.G77_ITEM_FACTS]
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
        for aid, facts in gen_closure.G34_ABILITY_FACTS + gen_closure.G35_ABILITY_FACTS + gen_closure.MEGA2_ABILITY_FACTS + gen_closure.G39_ABILITY_FACTS + gen_closure.G41_ABILITY_FACTS + gen_closure.G67_ABILITY_FACTS + gen_closure.G83_ABILITY_FACTS + gen_closure.G81_ABILITY_FACTS + gen_closure.G79_ABILITY_FACTS + gen_closure.G75_ABILITY_FACTS + gen_closure.G71_ABILITY_FACTS + gen_closure.G45_ABILITY_FACTS + gen_closure.G46_ABILITY_FACTS + gen_closure.G47_ABILITY_FACTS + gen_closure.G51_ABILITY_FACTS + gen_closure.G53_ABILITY_FACTS + gen_closure.G63_ABILITY_FACTS + gen_closure.G59_ABILITY_FACTS + gen_closure.G69_ABILITY_FACTS + gen_closure.G65_ABILITY_FACTS + gen_closure.G73_ABILITY_FACTS + gen_closure.G77_ABILITY_FACTS + gen_closure.K2_ABILITY_FACTS:
            kept = [f for i, f in enumerate(facts) if (aid, i) != skip]
            out.append(entry(aid, *kept))
        items = [entry(iid, *facts) for iid, facts in gen_closure.G34_ITEM_FACTS + gen_closure.G46_ITEM_FACTS + gen_closure.G47_ITEM_FACTS + gen_closure.G67_ITEM_FACTS + gen_closure.G83_ITEM_FACTS + gen_closure.G75_ITEM_FACTS + gen_closure.G77_ITEM_FACTS]
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

class SmallRulesG59(unittest.TestCase):
    """Step G59: six Mega abilities are engine rows whose pinned texts are demanded whole (G59_ABILITY_FACTS); the Champions mod
    may only inherit three of them (G59_INHERIT_ONLY); Mega Sol's effectiveWeather side and the sunnyday handler it calls are
    demanded (check_g59_facts)."""

    def abilities(self, skip=(None, None)):
        out = []
        for aid, facts in gen_closure.G34_ABILITY_FACTS + gen_closure.G35_ABILITY_FACTS + gen_closure.MEGA2_ABILITY_FACTS + gen_closure.G39_ABILITY_FACTS + gen_closure.G41_ABILITY_FACTS + gen_closure.G67_ABILITY_FACTS + gen_closure.G83_ABILITY_FACTS + gen_closure.G81_ABILITY_FACTS + gen_closure.G79_ABILITY_FACTS + gen_closure.G75_ABILITY_FACTS + gen_closure.G71_ABILITY_FACTS + gen_closure.G45_ABILITY_FACTS + gen_closure.G46_ABILITY_FACTS + gen_closure.G47_ABILITY_FACTS + gen_closure.G51_ABILITY_FACTS + gen_closure.G53_ABILITY_FACTS + gen_closure.G59_ABILITY_FACTS + gen_closure.G63_ABILITY_FACTS + gen_closure.G69_ABILITY_FACTS + gen_closure.G65_ABILITY_FACTS + gen_closure.G73_ABILITY_FACTS + gen_closure.G77_ABILITY_FACTS + gen_closure.K2_ABILITY_FACTS:
            kept = [f for i, f in enumerate(facts) if (aid, i) != skip]
            out.append(entry(aid, *kept))
        return out

    def champ(self, extra=()):
        out = [entry(aid, 'inherit: true,', 'isNonstandard: null,') for aid in gen_closure.G59_INHERIT_ONLY]
        return TextSource('data/mods/champions/abilities.ts', '\n'.join(out + list(extra)))

    def sources(self, skip=(None, None), champ=None):
        items = [entry(iid, *facts) for iid, facts in gen_closure.G34_ITEM_FACTS + gen_closure.G46_ITEM_FACTS + gen_closure.G47_ITEM_FACTS + gen_closure.G67_ITEM_FACTS + gen_closure.G83_ITEM_FACTS + gen_closure.G75_ITEM_FACTS + gen_closure.G77_ITEM_FACTS]
        return (TextSource('data/abilities.ts', '\n'.join(self.abilities(skip))),
                self.champ() if champ is None else champ,
                TextSource('data/items.ts', '\n'.join(items)), TextSource('data/mods/champions/items.ts', ''))

    def test_the_facts_of_the_pin_are_accepted(self):
        gen_closure.check_g34_facts(*self.sources())

    def test_every_fact_is_demanded(self):
        self.assertEqual([aid for aid, _ in gen_closure.G59_ABILITY_FACTS],
                         ['megalauncher', 'hugepower', 'thickfat', 'firemane', 'spicyspray', 'megasol'])
        for aid, facts in gen_closure.G59_ABILITY_FACTS:
            for i in range(len(facts)):
                with self.subTest(ability=aid, fact=facts[i]), self.assertRaises(SystemExit) as cm:
                    gen_closure.check_g34_facts(*self.sources((aid, i)))
                self.assertIn('the entry no longer has', str(cm.exception.code))

    def test_the_rows_of_the_step(self):
        for aid, _ in gen_closure.G59_ABILITY_FACTS:
            self.assertIn(aid, gen_closure.ENGINE_ROWS['abilities'])

    def test_the_champions_mod_may_only_inherit_three(self):
        # Control: the three inherit-only entries are accepted.
        gen_closure.check_g34_facts(*self.sources())
        # A Champions entry of a row that has none is an override.
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_g34_facts(*self.sources(champ=TextSource('data/mods/champions/abilities.ts',
                                                                       entry('hugepower', 'inherit: true,'))))
        self.assertIn('the champions mod overrides the entry', str(cm.exception.code))
        # An entry of an inherit-only row that also changes a callback is an override too.
        bad = entry('firemane', 'inherit: true,', 'isNonstandard: null,', 'onModifyAtk() { return 1; },')
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_g34_facts(*self.sources(champ=TextSource('data/mods/champions/abilities.ts', bad)))
        self.assertIn('the champions mod overrides the entry', str(cm.exception.code))

    def test_mega_sol_side_facts_are_demanded(self):
        pokemon = TextSource('sim/pokemon.ts', '\n'.join(gen_closure.G59_POKEMON_FACTS))
        conditions = TextSource('data/conditions.ts', '\n'.join(gen_closure.G59_SUNNY_FACTS))
        gen_closure.check_g59_facts(None, None, pokemon, conditions)
        for fact in gen_closure.G59_POKEMON_FACTS:
            cut = TextSource('sim/pokemon.ts', '\n'.join(f for f in gen_closure.G59_POKEMON_FACTS if f != fact))
            with self.subTest(fact=fact), self.assertRaises(SystemExit) as cm:
                gen_closure.check_g59_facts(None, None, cut, conditions)
            self.assertIn('the pin no longer has', str(cm.exception.code))
        for fact in gen_closure.G59_SUNNY_FACTS:
            cut = TextSource('data/conditions.ts', '\n'.join(f for f in gen_closure.G59_SUNNY_FACTS if f != fact))
            with self.subTest(fact=fact), self.assertRaises(SystemExit) as cm:
                gen_closure.check_g59_facts(None, None, pokemon, cut)
            self.assertIn('the pin no longer has', str(cm.exception.code))


class SmallRulesG53(unittest.TestCase):
    """Step G53: Pressure is an engine row whose pinned texts (the switch-in line and the foe's DeductPP) are demanded whole, and
    the mustpressure flag is a static bit of the move table (DUOFORGE_MOVE_STATIC_FLAG_MUST_PRESSURE) and the engine bit
    DFI_MOVE_FLAG3_MUST_PRESSURE."""

    def abilities(self, skip=(None, None)):
        out = []
        # check_g34_facts reads every family of the facts, so the fixture carries all of them
        for aid, facts in (gen_closure.G34_ABILITY_FACTS + gen_closure.G35_ABILITY_FACTS + gen_closure.MEGA2_ABILITY_FACTS +
                           gen_closure.G39_ABILITY_FACTS + gen_closure.G41_ABILITY_FACTS + gen_closure.G67_ABILITY_FACTS + gen_closure.G83_ABILITY_FACTS + gen_closure.G81_ABILITY_FACTS + gen_closure.G45_ABILITY_FACTS + gen_closure.G77_ABILITY_FACTS +
                           gen_closure.G46_ABILITY_FACTS + gen_closure.G47_ABILITY_FACTS + gen_closure.G51_ABILITY_FACTS +
                           gen_closure.G53_ABILITY_FACTS + gen_closure.G63_ABILITY_FACTS + gen_closure.G59_ABILITY_FACTS + gen_closure.G69_ABILITY_FACTS + gen_closure.G65_ABILITY_FACTS + gen_closure.G73_ABILITY_FACTS + gen_closure.G71_ABILITY_FACTS + gen_closure.G75_ABILITY_FACTS + gen_closure.G79_ABILITY_FACTS + gen_closure.K2_ABILITY_FACTS):
            kept = [f for i, f in enumerate(facts) if (aid, i) != skip]
            out.append(entry(aid, *kept))
        items = [entry(iid, *facts) for iid, facts in gen_closure.G34_ITEM_FACTS + gen_closure.G46_ITEM_FACTS + gen_closure.G47_ITEM_FACTS + gen_closure.G67_ITEM_FACTS + gen_closure.G83_ITEM_FACTS + gen_closure.G75_ITEM_FACTS + gen_closure.G77_ITEM_FACTS]
        return (TextSource('data/abilities.ts', '\n'.join(out)), TextSource('data/mods/champions/abilities.ts', ''),
                TextSource('data/items.ts', '\n'.join(items)), TextSource('data/mods/champions/items.ts', ''))

    def test_the_facts_of_the_pin_are_accepted(self):
        gen_closure.check_g34_facts(*self.abilities())

    def test_every_fact_is_demanded(self):
        self.assertEqual([aid for aid, _ in gen_closure.G53_ABILITY_FACTS], ['pressure'])
        for aid, facts in gen_closure.G53_ABILITY_FACTS:
            self.assertIn(aid, gen_closure.ENGINE_ROWS['abilities'])
            for i in range(len(facts)):
                with self.subTest(ability=aid, fact=facts[i]), self.assertRaises(SystemExit) as cm:
                    gen_closure.check_g34_facts(*self.abilities((aid, i)))
                self.assertIn('the entry no longer has', str(cm.exception.code))

    def test_the_mustpressure_flag_is_the_public_bit(self):
        self.assertEqual(gen_closure.STATIC_FLAG_BITS['mustpressure'], 2048)
        self.assertNotIn('mustpressure', gen_closure.FLAGS2_BITS)


class CheapMoveFactsC2(unittest.TestCase):
    """Step C2: the pin facts of the 30 cheap moves (gen_closure.C2_FACTS) are the fields of the pinned entry, each with its
    value, nested objects included; a wrong value, a field the facts do not list, a missing field and a Champions override
    fail the generator."""

    @staticmethod
    def value_text(v):
        if isinstance(v, set):
            return '{ %s }' % ', '.join('%s: 1' % f for f in sorted(v))
        if isinstance(v, dict):
            return '{ %s }' % ', '.join('%s: %s' % (k, CheapMoveFactsC2.value_text(x)) for k, x in v.items())
        if isinstance(v, list):
            return '[%s]' % ', '.join(CheapMoveFactsC2.value_text(x) for x in v)
        if v is True:
            return 'true'
        if isinstance(v, str):
            return "'%s'" % v
        return str(v)

    @classmethod
    def render(cls, mid, expected, drop=None, change=None, extra=None):
        lines = ['\t%s: {' % mid, '\t\tnum: 1,', '\t\tname: "Name",']
        for key, want in expected.items():
            if key == drop:
                continue
            if change and change[0] == key:
                want = change[1]
            lines.append('\t\t%s: %s,' % (key, cls.value_text(want)))
        if extra:
            lines.append('\t\t%s' % extra)
        lines.append('\t\tzMove: { effect: \'clearnegativeboost\' },')
        lines.append('\t},')
        return '\n'.join(lines)

    @staticmethod
    def override_text(mid, base):
        return '\t%s: {\n\t\tinherit: true,\n\t\tbasePower: %d,\n\t},' % (mid, base)

    def champ(self):
        """The Champions mod with its three base power overrides, as the pin has them."""
        return TextSource('data/mods/champions/moves.ts', '\n'.join(
            self.override_text(mid, base) for mid, base in gen_closure.C2_CHAMPIONS_OVERRIDES.items()))

    def source(self):
        return TextSource('data/moves.ts', '\n'.join(self.render(mid, exp) for mid, exp in gen_closure.C2_FACTS))

    def test_the_pin_facts_are_accepted(self):
        gen_closure.check_c2_facts(self.source(), self.champ())

    def test_every_move_is_listed_once_with_its_thirty_names(self):
        ids = [mid for mid, _ in gen_closure.C2_FACTS]
        self.assertEqual(len(ids), 30)
        self.assertEqual(len(set(ids)), 30)

    def test_a_wrong_value_fails(self):
        exp = dict(gen_closure.C2_FACTS)['lunge']
        moves = TextSource('data/moves.ts', self.render('lunge', exp, change=('basePower', 70)))
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_c2_facts(moves, self.champ(), only=(('lunge', exp),))
        self.assertIn('move lunge: basePower is 70 in the pin, not 80', str(cm.exception.code))

    def test_a_wrong_nested_value_fails(self):
        exp = dict(gen_closure.C2_FACTS)['torchsong']
        moves = TextSource('data/moves.ts', self.render('torchsong', exp, change=('secondary', {
            'chance': 100, 'self': {'boosts': {'spa': 2}}})))
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_c2_facts(moves, self.champ(), only=(('torchsong', exp),))
        self.assertIn('move torchsong: secondary is', str(cm.exception.code))

    def test_a_wrong_secondary_chance_in_a_list_fails(self):
        exp = dict(gen_closure.C2_FACTS)['thunderfang']
        moves = TextSource('data/moves.ts', self.render('thunderfang', exp, change=('secondaries', [
            {'chance': 10, 'status': 'par'}, {'chance': 20, 'volatileStatus': 'flinch'}])))
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_c2_facts(moves, self.champ(), only=(('thunderfang', exp),))
        self.assertIn('move thunderfang: secondaries is', str(cm.exception.code))

    def test_a_missing_field_fails(self):
        for mid, exp in gen_closure.C2_FACTS:
            for key in exp:
                with self.subTest(mid=mid, field=key), self.assertRaises(SystemExit) as cm:
                    gen_closure.check_c2_facts(TextSource('data/moves.ts', self.render(mid, exp, drop=key)),
                                               self.champ(), only=((mid, exp),))
                self.assertIn('move %s: the pin has no %s' % (mid, key), str(cm.exception.code))

    def test_a_field_the_facts_do_not_list_fails(self):
        mid, exp = gen_closure.C2_FACTS[0]
        moves = TextSource('data/moves.ts', self.render(mid, exp, extra='critRatio: 2,'))
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_c2_facts(moves, self.champ(), only=((mid, exp),))
        self.assertIn('the pin has fields the C2 facts do not list: critRatio', str(cm.exception.code))

    def test_a_champions_override_fails_unless_it_is_a_base_power_override(self):
        mid, exp = gen_closure.C2_FACTS[0]
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_c2_facts(TextSource('data/moves.ts', self.render(mid, exp)),
                                       TextSource('data/mods/champions/moves.ts', self.render(mid, exp)), only=((mid, exp),))
        self.assertIn('the Champions mod overrides it', str(cm.exception.code))
        appleacid = dict(gen_closure.C2_FACTS)['appleacid']
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_c2_facts(TextSource('data/moves.ts', self.render('appleacid', appleacid)),
                                       TextSource('data/mods/champions/moves.ts', self.override_text('appleacid', 85)),
                                       only=(('appleacid', appleacid),))
        self.assertIn('the Champions mod entry is not the base power override 90', str(cm.exception.code))

    def test_a_reader_refuses_what_it_does_not_know(self):
        with self.assertRaises(SystemExit):
            gen_closure.c2_literal('{ flags: { protect: 1 }, basePower: 1 + 2 }')
        self.assertEqual(gen_closure.c2_literal('{ a: [1, -2,], b: { c: true, }, }'), {'a': [1, -2], 'b': {'c': True}})


class C1Part4Facts(unittest.TestCase):
    """Step A0 part 4: the C1 row Shelter (gen_closure.C1_PART4_FACTS) is the pinned entry, field by field, through the same
    reader as the C2 rows (the helpers of CheapMoveFactsC2); a wrong boost fails, and the Champions mod must not override it."""

    @staticmethod
    def render(mid, exp, change=None):
        return CheapMoveFactsC2.render(mid, exp, change=change)

    @staticmethod
    def no_champions():
        return TextSource('data/mods/champions/moves.ts', '')

    def test_the_pin_fact_of_shelter_is_accepted(self):
        moves = TextSource('data/moves.ts', self.render('shelter', dict(gen_closure.C1_PART4_FACTS)['shelter']))
        gen_closure.check_c2_facts(moves, self.no_champions(), only=gen_closure.C1_PART4_FACTS)

    def test_a_wrong_boost_of_shelter_fails(self):
        exp = dict(gen_closure.C1_PART4_FACTS)['shelter']
        moves = TextSource('data/moves.ts', self.render('shelter', exp, change=('boosts', {'def': 1})))
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_c2_facts(moves, self.no_champions(), only=(('shelter', exp),))
        self.assertIn('move shelter: boosts is', str(cm.exception.code))

    def test_a_champions_override_of_shelter_fails(self):
        exp = dict(gen_closure.C1_PART4_FACTS)['shelter']
        moves = TextSource('data/moves.ts', self.render('shelter', exp))
        champ = TextSource('data/mods/champions/moves.ts', '\tshelter: {\n\t\tinherit: true,\n\t\tbasePower: 1,\n\t},')
        with self.assertRaises(SystemExit):
            gen_closure.check_c2_facts(moves, champ, only=(('shelter', exp),))


class C4Facts(unittest.TestCase):
    """Step C4: the pinned fields of the twelve data-only moves, rendered as the pin writes them (no checkout needed)."""

    def render(self, mid, fields):
        lines = ['\t%s: {' % mid]
        for key, want in fields.items():
            if key == 'flags':
                lines.append('\t\tflags: { %s },' % ' '.join('%s: 1,' % f for f in sorted(want)))
            elif key == 'secondary':
                chance, boosts = want
                lines.append('\t\tsecondary: {\n\t\t\tchance: %d,\n\t\t\tself: {\n\t\t\t\tboosts: {\n%s\n\t\t\t\t},\n'
                             '\t\t\t},\n\t\t},' % (chance, '\n'.join('\t\t\t\t\t%s: %d,' % kv for kv in boosts.items())))
            elif key == 'boosts':
                lines.append('\t\tboosts: { %s },' % ' '.join('%s: %d,' % kv for kv in want.items()))
            elif isinstance(want, bool):
                lines.append('\t\t%s: %s,' % (key, 'true' if want else 'false'))
            elif isinstance(want, int):
                lines.append('\t\t%s: %d,' % (key, want))
            else:
                lines.append('\t\t%s: "%s",' % (key, want))
        lines.append('\t},')
        return '\n'.join(lines)

    def sources(self, change=None):
        """The pin text of every fact; `change` = (move, field, value) replaces one value."""
        out = []
        for mid, fields in gen_closure.C4_FACTS:
            fields = dict(fields)
            if change is not None and change[0] == mid:
                fields[change[1]] = change[2]
            out.append(self.render(mid, fields))
        base = TextSource('data/moves.ts', '\n'.join(out))
        champ = TextSource('data/mods/champions/moves.ts',
                           '\n'.join(['\tpsyshieldbash: {', '\t\tinherit: true,', '\t\tbasePower: 90,', '\t},',
                                      '\tstormthrow: {', '\t\tinherit: true,', '\t\tisNonstandard: null,', '\t},']))
        return base, champ

    def test_the_pinned_facts_are_accepted(self):
        gen_closure.check_c4_facts(*self.sources())

    def test_a_changed_value_is_refused(self):
        for mid, key, value in (('flamecharge', 'basePower', 60), ('steelwing', 'accuracy', 100),
                                ('screech', 'flags', {'protect', 'reflectable', 'mirror', 'metronome'}),
                                ('spicyextract', 'boosts', {'atk': 2, 'def': -1})):
            with self.subTest(move=mid, field=key):
                with self.assertRaises(SystemExit) as cm:
                    gen_closure.check_c4_facts(*self.sources((mid, key, value)))
                self.assertIn('move %s' % mid, str(cm.exception.code))

    def test_an_unlisted_champions_override_is_refused(self):
        base, _ = self.sources()
        champ = TextSource('data/mods/champions/moves.ts', '\tflamecharge: {\n\t\tinherit: true,\n\t},')
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_c4_facts(base, champ)
        self.assertIn('move flamecharge: the Champions mod overrides it', str(cm.exception.code))


class C5Facts(unittest.TestCase):
    """Step C5 (decision 0015 entry 5cy): the pinned fields of Surf, rendered as the pin writes them (no checkout needed)."""

    def render(self, mid, fields):
        lines = ['\t%s: {' % mid]
        for key, want in fields.items():
            if key == 'flags':
                lines.append('\t\tflags: { %s },' % ' '.join('%s: 1,' % f for f in sorted(want)))
            elif isinstance(want, int):
                lines.append('\t\t%s: %d,' % (key, want))
            else:
                lines.append('\t\t%s: "%s",' % (key, want))
        lines.append('\t},')
        return '\n'.join(lines)

    def sources(self, change=None):
        out = []
        for mid, fields in gen_closure.C5_FACTS:
            fields = dict(fields)
            if change is not None and change[0] == mid:
                fields[change[1]] = change[2]
            out.append(self.render(mid, fields))
        return TextSource('data/moves.ts', '\n'.join(out)), TextSource('data/mods/champions/moves.ts', '')

    def test_the_pinned_facts_are_accepted(self):
        gen_closure.check_c5_facts(*self.sources())

    def test_a_changed_value_is_refused(self):
        for mid, key, value in (('surf', 'basePower', 95), ('surf', 'target', 'normal'),
                                ('surf', 'flags', {'protect', 'mirror', 'metronome'})):
            with self.subTest(move=mid, field=key), self.assertRaises(SystemExit) as cm:
                gen_closure.check_c5_facts(*self.sources((mid, key, value)))
            self.assertIn('move %s' % mid, str(cm.exception.code))

    def test_a_champions_override_is_refused(self):
        base, _ = self.sources()
        champ = TextSource('data/mods/champions/moves.ts', '\tsurf: {\n\t\tinherit: true,\n\t\tbasePower: 95,\n\t},')
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_c5_facts(base, champ)
        self.assertIn('move surf: the Champions mod overrides it', str(cm.exception.code))


class A0Facts(unittest.TestCase):
    """Step A0 (decision 0015, batch A0 part 2): the pinned fields of the twelve data-only moves, rendered as the pin writes them
    (no checkout needed)."""

    def value_text(self, want):
        if isinstance(want, dict):
            return '{ %s }' % ' '.join('%s: %s,' % (k, self.value_text(v)) for k, v in want.items())
        if isinstance(want, bool):
            return 'true' if want else 'false'
        if isinstance(want, int):
            return str(want)
        return "'%s'" % want

    def render(self, mid, fields):
        lines = ['\t%s: {' % mid]
        for key, want in fields.items():
            if key == 'flags':
                lines.append('\t\tflags: { %s },' % ' '.join('%s: 1,' % f for f in sorted(want)))
            else:
                lines.append('\t\t%s: %s,' % (key, self.value_text(want)))
        lines.append('\t},')
        return '\n'.join(lines)

    def sources(self, change=None, champ_text=None):
        """The pin text of every fact; `change` = (move, field, value) replaces one value of the base entry."""
        out = []
        for mid, fields in gen_closure.A0_FACTS:
            fields = dict(fields)
            if change is not None and change[0] == mid:
                fields[change[1]] = change[2]
            out.append(self.render(mid, fields))
        if champ_text is None:
            champ_text = '\n'.join(['\tcrabhammer: {', '\t\tinherit: true,', '\t\taccuracy: 95,', '\t},',
                                    '\tcrushclaw: {', '\t\tinherit: true,',
                                    '\t\tflags: { contact: 1, protect: 1, mirror: 1, metronome: 1, slicing: 1 },', '\t},',
                                    '\tfirelash: {', '\t\tinherit: true,', '\t\tbasePower: 90,', '\t},'])
        return TextSource('data/moves.ts', '\n'.join(out)), TextSource('data/mods/champions/moves.ts', champ_text)

    def test_the_pinned_facts_are_accepted(self):
        gen_closure.check_a0_facts(*self.sources())

    def test_a_changed_value_is_refused(self):
        for mid, key, value in (('dragonrush', 'basePower', 95), ('crabhammer', 'critRatio', 1),
                                ('firelash', 'secondary', {'chance': 100, 'boosts': {'def': -2}}),
                                ('bite', 'secondary', {'chance': 30, 'status': 'par'}),
                                ('seismictoss', 'damage', 'user'), ('sweetkiss', 'volatileStatus', 'flinch'),
                                ('aromaticmist', 'target', 'adjacentAllyOrSelf')):
            with self.subTest(move=mid, field=key):
                with self.assertRaises(SystemExit) as cm:
                    gen_closure.check_a0_facts(*self.sources((mid, key, value)))
                self.assertIn('move %s' % mid, str(cm.exception.code))

    def test_an_unlisted_champions_override_is_refused(self):
        base, _ = self.sources()
        champ = TextSource('data/mods/champions/moves.ts', '\tdragonrush: {\n\t\tinherit: true,\n\t\tbasePower: 110,\n\t},')
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_a0_facts(base, champ)
        self.assertIn('move dragonrush: the Champions mod overrides it', str(cm.exception.code))

    def test_a_changed_champions_override_is_refused(self):
        base, champ = self.sources(champ_text='\tcrabhammer: {\n\t\tinherit: true,\n\t\taccuracy: 90,\n\t},')
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_a0_facts(base, champ)
        self.assertIn('move crabhammer: the Champions mod entry is not the override', str(cm.exception.code))

    def base_with(self, edits):
        """The base pin text with `edits` = {move: {field: value or None (drop the field)}} applied."""
        out = []
        for mid, fields in gen_closure.A0_FACTS:
            fields = dict(fields)
            for key, value in edits.get(mid, {}).items():
                if value is None:
                    fields.pop(key)
                else:
                    fields[key] = value
            out.append(self.render(mid, fields))
        return TextSource('data/moves.ts', '\n'.join(out))

    def test_the_champions_overrides_replace_the_base_values(self):
        # The base pin entries carry the values before the Champions mod (data/moves.ts at b2cb775: Crabhammer accuracy 90,
        # Fire Lash basePower 80, Crush Claw without slicing); the facts hold only after the override is merged.
        base = self.base_with({'crabhammer': {'accuracy': 90}, 'firelash': {'basePower': 80},
                               'crushclaw': {'flags': {'contact', 'protect', 'mirror', 'metronome'}}})
        gen_closure.check_a0_facts(base, self.sources()[1])

    def test_an_unlisted_or_missing_field_is_refused(self):
        for edits, message in (({'bite': {'drain': [1, 2]}}, 'move bite: the pin has fields the A0 facts do not list: drain'),
                               ({'crabhammer': {'critRatio': None}}, 'move crabhammer: the pin has no critRatio')):
            with self.subTest(message=message):
                with self.assertRaises(SystemExit) as cm:
                    gen_closure.check_a0_facts(self.base_with(edits), self.sources()[1])
                self.assertIn(message, str(cm.exception.code))


class MoveHandlerTables(unittest.TestCase):
    """The step-4 tables retain frozen phase semantics and fail closed on drift."""

    def test_committed_tables_pass_check(self):
        import subprocess
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        subprocess.run([sys.executable, os.path.join(root, 'tools', 'datagen', 'gen_move_handlers.py'), '--check'],
                       check=True)

    def test_existing_lists_have_frozen_phase_counts(self):
        import move_handler_source
        rows = move_handler_source.rows()
        self.assertEqual(len(rows), 123)  # K3: Speed Swap is the 123rd row
        self.assertEqual(sum(r.hit_guard for r in rows), 97)  # K3: Speed Swap is a late-guard row
        self.assertEqual(sum(r.status_hit for r in rows), 19)  # K3: Speed Swap is a status-hit row
        self.assertEqual([r.name for r in rows], gen_closure.SPECIAL_IDS_P)
        self.assertEqual([r.value for r in rows], list(range(123)))

    def test_writer_rejects_bad_rows(self):
        from dataclasses import replace
        import gen_move_handlers
        import move_handler_source
        rows = move_handler_source.rows()
        bad_firsts = [replace(rows[0], value=1), replace(rows[0], name='lowercase'),
                      replace(rows[0], name=rows[1].name), replace(rows[0], hit_guard=1)]
        for first in bad_firsts:
            with self.subTest(row=first), self.assertRaises(ValueError):
                gen_move_handlers.render((first, *rows[1:]))
        with self.assertRaises(ValueError):
            gen_move_handlers.render(())

    def test_generator_refuses_a_new_unclassified_special_by_name(self):
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        import gen_move_handlers
        import move_handler_source
        name = 'REVIEW_UNCLASSIFIED'
        ids = [*move_handler_source.SPECIAL_IDS_P, name]
        mapped = dict(move_handler_source.SPECIAL_POOL, review_unclassified=(name, set()))
        with tempfile.TemporaryDirectory(prefix='move-handler-unclassified-') as temp:
            root = Path(temp)
            script = root / 'tools/datagen/gen_move_handlers.py'
            with patch.object(move_handler_source, 'SPECIAL_IDS_P', ids), \
                    patch.object(move_handler_source, 'SPECIAL_POOL', mapped), \
                    patch.object(gen_move_handlers, '__file__', str(script)), \
                    patch.object(sys, 'argv', [str(script)]), \
                    self.assertRaisesRegex(ValueError, name):
                gen_move_handlers.main()
            self.assertFalse((root / 'src/combat/generated/move_handlers.h').exists())

    def test_special_in_two_phase_classes_is_refused_by_name(self):
        from unittest.mock import patch
        import move_handler_source
        with patch.object(move_handler_source, '_DATA_ONLY', move_handler_source._DATA_ONLY | {'NONE'}), \
                self.assertRaisesRegex(ValueError, 'NONE'):
            move_handler_source.rows()

    def test_missing_phase_class_does_not_default_to_a_late_handler(self):
        from unittest.mock import patch
        import move_handler_source
        with patch.object(move_handler_source, '_BEFORE_GUARD',
                          move_handler_source._BEFORE_GUARD - {'HELPING_HAND'}), \
                self.assertRaisesRegex(ValueError, 'HELPING_HAND'):
            move_handler_source.rows()

    def test_check_rejects_missing_and_stale_output(self):
        from contextlib import redirect_stderr, redirect_stdout
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        import gen_move_handlers
        with tempfile.TemporaryDirectory(prefix='move-handler-check-') as temp:
            root = Path(temp)
            script = root / 'tools/datagen/gen_move_handlers.py'
            target = root / 'src/combat/generated/move_handlers.h'
            for stale in (None, b'/* stale */\n'):
                if stale is not None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(stale)
                with self.subTest(stale=stale), patch.object(gen_move_handlers, '__file__', str(script)), \
                        patch.object(sys, 'argv', [str(script), '--check']), redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit) as error:
                    gen_move_handlers.main()
                self.assertEqual(error.exception.code, 1)
            target.write_bytes(gen_move_handlers.render(gen_move_handlers.rows()).encode('ascii'))
            with patch.object(gen_move_handlers, '__file__', str(script)), \
                    patch.object(sys, 'argv', [str(script), '--check']), redirect_stdout(io.StringIO()):
                gen_move_handlers.main()



class StompingTantrumCallbacks(unittest.TestCase):
    """Step K1 (#476, entry 5dc): Temper Flare has Stomping Tantrum's basePowerCallback with its own debug text
    (data/moves.ts:19189-19195 and :18053-18059). The handler STOMPING_TANTRUM serves both moves, and the generator checks
    the whole text of each callback against its own move, so a change of either text, or the other move's text, is refused."""
    TEMPER = move_entry('temperflare', 'Temper Flare', *[
        "basePowerCallback(pokemon, target, move) { if (pokemon.moveLastTurnResult === false) { "
        "this.debug('doubling Temper Flare BP due to previous move failure'); return move.basePower * 2; } "
        "return move.basePower; },"], category='Physical', base_power=75, type_='Fire', pp=10,
        flags='contact: 1, protect: 1, mirror: 1, metronome: 1', target='normal')
    STOMPING = move_entry('stompingtantrum', 'Stomping Tantrum', *[
        "basePowerCallback(pokemon, target, move) { if (pokemon.moveLastTurnResult === false) { "
        "this.debug('doubling Stomping Tantrum BP due to previous move failure'); return move.basePower * 2; } "
        "return move.basePower; },"], category='Physical', base_power=75, type_='Ground', pp=10,
        flags='contact: 1, protect: 1, mirror: 1, metronome: 1', target='normal')

    def refused(self, mid, text, message, **kwargs):
        with self.assertRaises(SystemExit) as cm:
            parse_pool(mid, text, **kwargs)
        self.assertEqual(cm.exception.code, 'gen_closure: move %s: %s' % (mid, message))

    def test_temper_flare_and_stomping_tantrum_map_to_the_one_handler(self):
        for mid, text in (('temperflare', self.TEMPER), ('stompingtantrum', self.STOMPING)):
            with self.subTest(mid):
                rec = parse_pool(mid, text)
                self.assertEqual(rec['special'], gen_closure.SPECIAL_IDS_P.index('STOMPING_TANTRUM'))
                self.assertEqual(rec['special'], 73)

    def test_a_changed_debug_text_or_comparison_is_refused(self):
        self.refused('temperflare', self.TEMPER.replace('doubling Temper Flare BP', 'doubling Temper Flares BP'),
                     'basePowerCallback is not the pinned text')
        self.refused('temperflare', self.TEMPER.replace('=== false', '!== false'),
                     'basePowerCallback is not the pinned text')
        self.refused('stompingtantrum', self.STOMPING.replace('doubling Stomping Tantrum BP', 'doubling Tantrum BP'),
                     'basePowerCallback is not the pinned text')

    def test_the_callback_of_the_other_move_is_refused(self):
        # Each move is checked against its own text: Temper Flare's debug line is not Stomping Tantrum's, and the reverse.
        self.refused('temperflare', self.TEMPER.replace('doubling Temper Flare BP', 'doubling Stomping Tantrum BP'),
                     'basePowerCallback is not the pinned text')
        self.refused('stompingtantrum', self.STOMPING.replace('doubling Stomping Tantrum BP', 'doubling Temper Flare BP'),
                     'basePowerCallback is not the pinned text')


class BulletFlag(unittest.TestCase):
    """Step G83 (approved by HauptSession): the bullet bit of the third flags byte (DFI_MOVE_FLAG3_BULLET, 0x10) marks exactly
    the pool moves that carry flags.bullet in the pin. The pin (data/moves.ts) has 26 bullet moves; 8 of them are not pool
    moves, so the pool table marks the other 18. Bulletproof reads that bit, so the set is pinned by name."""
    PIN_BULLET_POOL_MOVES = {'acidspray', 'aurasphere', 'beakblast', 'bulletseed', 'electroball', 'energyball', 'focusblast',
                             'gyroball', 'pollenpuff', 'pyroball', 'rockblast', 'rockwrecker', 'seedbomb', 'shadowball',
                             'sludgebomb', 'syrupbomb', 'weatherball', 'zapcannon'}
    PIN_BULLET_OTHER_MOVES = {'barrage', 'eggbomb', 'iceball', 'magnetbomb', 'mistball', 'mudbomb', 'octazooka', 'searingshot'}

    @staticmethod
    def committed_table(name):
        # the body of a pool table in pool_tables.c, or with name None the move count of pool_tables.h
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        with open(os.path.join(root, 'src', 'data', 'formats', 'reg-mc', 'pool_tables.%s' % ('h' if name is None else 'c')), encoding='utf-8') as f:
            text = f.read()
        if name is None:
            return int(re.search(r'#define DFI_POOL_MOVE_COUNT (\d+)u', text).group(1))
        m = re.search(r'const %s\[DFI_POOL_MOVE_COUNT\] = \{(.*?)\n\};' % re.escape(name), text, re.S)
        return None if m is None else m.group(1)

    def test_the_bit_is_assigned_to_the_bullet_flag(self):
        self.assertEqual(gen_closure.FLAGS3_BITS['bullet'], 16)
        self.assertEqual(gen_closure.FLAGS3_BITS['pulse'], 8)

    def test_the_pin_has_26_bullet_moves(self):
        self.assertEqual(len(self.PIN_BULLET_POOL_MOVES | self.PIN_BULLET_OTHER_MOVES), 26)
        self.assertFalse(self.PIN_BULLET_POOL_MOVES & self.PIN_BULLET_OTHER_MOVES)

    def test_the_committed_table_marks_the_pins_18_bullet_pool_moves(self):
        names_body = self.committed_table('char *const dfi_pool_move_names')
        flags_body = self.committed_table('uint8_t dfi_pool_move_flags3')
        self.assertIsNotNone(names_body)
        self.assertIsNotNone(flags_body)
        names = dict(re.findall(r'\[DFI_MOVE_(\w+)\] = "(\w+)",', names_body))
        self.assertEqual(len(names), self.committed_table(None))  # every pool move has its name
        pool = set(names.values())
        self.assertLessEqual(self.PIN_BULLET_POOL_MOVES, pool)
        self.assertFalse(self.PIN_BULLET_OTHER_MOVES & pool)
        marked = {names[k] for k, v in re.findall(r'\[DFI_MOVE_(\w+)\] = (\d+)u,', flags_body) if int(v) & 16}
        self.assertEqual(marked, self.PIN_BULLET_POOL_MOVES)


class CheapMoveFacts(unittest.TestCase):
    """Step C1: the pin facts of the 21 cheap moves (gen_closure.C1_FACTS) are the fields of the pinned entry, each with its
    value; a wrong value, a field that the facts do not list, or a Champions override fails the generator."""

    @staticmethod
    def render(mid, expected, drop=None, change=None):
        lines = ['\t%s: {' % mid, '\t\tnum: 1,']
        for key, want in expected.items():
            if key == drop:
                continue
            if key == 'flags':
                text = 'flags: { %s }' % ', '.join('%s: 1' % f for f in sorted(want))
            elif key == 'heal':
                text = 'heal: [%d, %d],' % want
            elif key == 'boosts':
                lines.append('\t\tboosts: {')
                lines.extend('\t\t\t%s: %d,' % (n, v) for n, v in want.items())
                lines.append('\t\t},')
                continue
            elif key in ('accuracy',) and want is True:
                text = 'accuracy: true,'
            elif key == 'status':
                text = "status: '%s'," % want
            elif isinstance(want, str):
                text = '%s: "%s",' % (key, want)
            else:
                text = '%s: %d,' % (key, want)
            if change and change[0] == key:
                text = text.replace(str(want), str(change[1]))
            lines.append('\t\t' + text)
        lines.append('\t\tzMove: { effect: \'clearnegativeboost\' },')
        lines.append('\t},')
        return '\n'.join(lines)

    def source(self):
        return TextSource('data/moves.ts', '\n'.join(self.render(mid, exp) for mid, exp in gen_closure.C1_FACTS))

    def test_the_pin_facts_are_accepted(self):
        gen_closure.check_c1_facts(self.source(), TextSource('data/mods/champions/moves.ts', ''))

    def test_every_move_is_listed_once(self):
        ids = [mid for mid, _ in gen_closure.C1_FACTS]
        self.assertEqual(len(ids), 21)
        self.assertEqual(len(set(ids)), 21)

    def test_a_wrong_value_fails(self):
        moves = TextSource('data/moves.ts', self.render('jetpunch', dict(gen_closure.C1_FACTS)['jetpunch'],
                                                        change=('priority', 0)))
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_c1_facts(moves, TextSource('data/mods/champions/moves.ts', ''),
                                       only=(('jetpunch', dict(gen_closure.C1_FACTS)['jetpunch']),))
        self.assertIn('move jetpunch: priority is 0 in the pin, not 1', str(cm.exception.code))

    def test_a_missing_field_fails(self):
        for mid, exp in gen_closure.C1_FACTS:
            for key in exp:
                with self.subTest(mid=mid, field=key), self.assertRaises(SystemExit) as cm:
                    gen_closure.check_c1_facts(TextSource('data/moves.ts', self.render(mid, exp, drop=key)),
                                               TextSource('data/mods/champions/moves.ts', ''), only=((mid, exp),))
                self.assertIn('move %s: the pin has no %s' % (mid, key), str(cm.exception.code))

    def test_a_field_the_facts_do_not_list_fails(self):
        mid, exp = gen_closure.C1_FACTS[0]
        text = self.render(mid, exp).replace('\t},', '\t\tsecondary: { chance: 10, status: \'brn\' },\n\t},')
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_c1_facts(TextSource('data/moves.ts', text), TextSource('data/mods/champions/moves.ts', ''),
                                       only=((mid, exp),))
        self.assertIn('the pin has fields the C1 facts do not list: secondary', str(cm.exception.code))

    def test_a_champions_override_fails(self):
        mid, exp = gen_closure.C1_FACTS[0]
        champ = TextSource('data/mods/champions/moves.ts', self.render(mid, exp))
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_c1_facts(TextSource('data/moves.ts', self.render(mid, exp)), champ, only=((mid, exp),))
        self.assertIn('the Champions mod overrides it', str(cm.exception.code))




A0P1_POWER_CALLBACK = ("\t\tbasePowerCallback(pokemon, target, move) {\n\t\t\tconst bp = move.basePower + 20 * pokemon.positiveBoosts();\n"
                  "\t\t\tthis.debug(`BP: ${bp}`);\n\t\t\treturn bp;\n\t\t},")
A0P1_HEAVY_CALLBACK = ("\t\tbasePowerCallback(pokemon, target) {\n\t\t\tconst targetWeight = target.getWeight();\n"
                  "\t\t\tif (pokemon.getWeight() >= targetWeight * 5) { bp = 120; }\n\t\t\treturn bp;\n\t\t},")
A0P1_ON_TRY_HIT = ("\t\tonTryHit(target, pokemon, move) {\n\t\t\tif (target.volatiles['dynamax']) {\n"
              "\t\t\t\treturn null;\n\t\t\t}\n\t\t},")
A0P1_WATER_CALLBACK = ("\t\tbasePowerCallback(pokemon, target, move) {\n\t\t\tif (pokemon.species.name === 'Greninja-Ash' && "
                  "pokemon.hasAbility('battlebond') &&\n\t\t\t\t!pokemon.transformed) {\n\t\t\t\treturn move.basePower + 5;\n"
                  "\t\t\t}\n\t\t\treturn move.basePower;\n\t\t},")
A0P1_CALLBACK_TEXT = {'storedpower': {'basePowerCallback': A0P1_POWER_CALLBACK},
                    'watershuriken': {'basePowerCallback': A0P1_WATER_CALLBACK},
                    'heatcrash': {'basePowerCallback': A0P1_HEAVY_CALLBACK, 'onTryHit': A0P1_ON_TRY_HIT}}
A0P1_CHAMP_TEXT = '\n'.join(['\tmeteorassault: {', '\t\tinherit: true,', '\t\tbasePower: 170,', '\t\tisNonstandard: null,', '\t},'])
A0P1_ITEMS_TEXT = '\n'.join([
    '\tchesnaughtite: {', '\t\tname: "Chesnaughtite",', '\t\tspritenum: 558,',
    '\t\tmegaStone: { "Chesnaught": "Chesnaught-Mega" },', '\t\titemUser: ["Chesnaught"],',
    '\t\tonTakeItem(item, source) {', '\t\t\treturn !item.megaStone?.[source.baseSpecies.baseSpecies];', '\t\t},',
    '\t\tnum: 2575,', '\t\tgen: 9,', '\t\tisNonstandard: "Future",', '\t},',
    '\taltarianite: {', '\t\tname: "Altarianite",', '\t\tspritenum: 615,',
    '\t\tmegaStone: { "Altaria": "Altaria-Mega" },', '\t\titemUser: ["Altaria"],',
    '\t\tonTakeItem(item, source) {', '\t\t\treturn !item.megaStone?.[source.baseSpecies.baseSpecies];', '\t\t},',
    '\t\tnum: 755,', '\t\tgen: 6,', '\t\tisNonstandard: "Past",', '\t},'])
A0P1_CHAMP_ITEMS_TEXT = '\n'.join(['\tchesnaughtite: {', '\t\tinherit: true,', '\t\tisNonstandard: null,', '\t},',
                                 '\taltarianite: {', '\t\tinherit: true,', '\t\tisNonstandard: null,', '\t},'])


class A0Part1Facts(unittest.TestCase):
    """Step A0 (decision 0015, batch A0 part 1): the pinned fields of the ten moves, their callbacks and the two Mega Stones,
    rendered as the pin writes them (no checkout needed)."""

    def render(self, mid, fields, callbacks):
        lines = ['\t%s: {' % mid] + [text for text in callbacks.values()]
        for key, want in fields.items():
            if key == 'flags':
                lines.append('\t\tflags: { %s },' % ' '.join('%s: 1,' % f for f in sorted(want)))
            elif key == 'boosts':
                lines.append('\t\tboosts: { %s },' % ' '.join('%s: %d,' % kv for kv in want.items()))
            elif key in ('multihit', 'drain'):
                lines.append('\t\t%s: [%d, %d],' % (key, want[0], want[1]))
            elif key == 'self':
                lines.append('\t\t' + want)
            elif isinstance(want, bool):
                lines.append('\t\t%s: %s,' % (key, 'true' if want else 'false'))
            elif isinstance(want, int):
                lines.append('\t\t%s: %d,' % (key, want))
            else:
                lines.append('\t\t%s: "%s",' % (key, want))
        lines.append('\t},')
        return '\n'.join(lines)

    def legal(self, abilities=(), items=(), stones=None):
        if stones is None:
            stones = {'chesnaughtite': [('chesnaught', 'chesnaughtmega')], 'altarianite': [('altaria', 'altariamega')]}
        return {'abilities': set(abilities), 'items': set(items) | {'chesnaughtite', 'altarianite'},
                'species': {'chesnaught': {}, 'altaria': {}}, 'stones': stones}

    def sources(self, change=None, heatcrash_on_try_hit=None):
        """The pin texts. `change` = (move, field, value) replaces one value of the pin; `heatcrash_on_try_hit` replaces the
        text of Heat Crash's onTryHit."""
        out = []
        for mid, fields in gen_closure.A0P1_FACTS:
            fields = dict(fields)
            if change is not None and change[0] == mid:
                fields[change[1]] = change[2]
            callbacks = dict(A0P1_CALLBACK_TEXT.get(mid, {}))
            if mid == 'heatcrash' and heatcrash_on_try_hit is not None:
                callbacks['onTryHit'] = heatcrash_on_try_hit
            out.append(self.render(mid, fields, callbacks))
        out.append('\tpowertrip: {\n%s\n\t},' % A0P1_POWER_CALLBACK)
        out.append('\theavyslam: {\n%s\n%s\n\t},' % (A0P1_HEAVY_CALLBACK, A0P1_ON_TRY_HIT))
        return (TextSource('data/moves.ts', '\n'.join(out)), TextSource('data/mods/champions/moves.ts', A0P1_CHAMP_TEXT),
                TextSource('data/items.ts', A0P1_ITEMS_TEXT), TextSource('data/mods/champions/items.ts', A0P1_CHAMP_ITEMS_TEXT))

    def check(self, change=None, heatcrash_on_try_hit=None, legal=None):
        base, champ, items, champ_items = self.sources(change, heatcrash_on_try_hit)
        gen_closure.check_a0p1_facts(base, champ, items, champ_items, legal or self.legal())

    def test_the_pinned_facts_are_accepted(self):
        self.check()

    def test_a_changed_value_is_refused(self):
        for mid, key, value in (('aircutter', 'critRatio', 1), ('storedpower', 'basePower', 25),
                                ('decorate', 'boosts', {'atk': 2, 'spa': 1}), ('rockblast', 'multihit', (2, 3))):
            with self.subTest(move=mid, field=key), self.assertRaises(SystemExit) as cm:
                self.check((mid, key, value))
            self.assertIn('move %s' % mid, str(cm.exception.code))

    def test_a_callback_that_differs_from_its_donor_is_refused(self):
        with self.assertRaises(SystemExit) as cm:
            self.check(heatcrash_on_try_hit="\t\tonTryHit(target, pokemon, move) {\n\t\t\treturn null;\n\t\t},")
        self.assertIn('move heatcrash: onTryHit is not the text of heavyslam', str(cm.exception.code))

    def test_a_champions_override_outside_the_list_is_refused(self):
        base, champ, items, champ_items = self.sources()
        champ = TextSource('data/mods/champions/moves.ts', A0P1_CHAMP_TEXT + '\n\thornleech: {\n\t\tinherit: true,\n\t},')
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_a0p1_facts(base, champ, items, champ_items, self.legal())
        self.assertIn('move hornleech: the Champions mod overrides it', str(cm.exception.code))

    def test_the_pool_guards_are_checked(self):
        with self.assertRaises(SystemExit) as cm:
            self.check(legal=self.legal(abilities={'battlebond'}))
        self.assertIn('Battle Bond or Greninja-Ash is legal', str(cm.exception.code))
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_a0p1_pool(self.legal(items={'loadeddice'}))
        self.assertIn('Loaded Dice is legal', str(cm.exception.code))
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_a0p1_pool(self.legal(stones={'chesnaughtite': [('chesnaught', 'chesnaughtmega')], 'altarianite': []}))
        self.assertIn('altarianite is not the Mega Stone', str(cm.exception.code))

    def test_a_stone_with_another_mega_link_is_refused(self):
        base, champ, items, champ_items = self.sources()
        items = TextSource('data/items.ts', '\n'.join(items.lines).replace('"Chesnaught-Mega"', '"Chesnaught-Mega2"'))
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_a0p1_facts(base, champ, items, champ_items, self.legal())
        self.assertIn('item chesnaughtite: megaStone is not', str(cm.exception.code))


# ---- issue #620: the pool abilities with failskillswap (Skill Swap fails on either side), read from the pin, and the ids that
# the turn code's dfi_fails_skillswap reads ----
C_BODY = """/* the comment above */
static bool dfi_fails_skillswap(const struct duoforge_battle *b, const dfi_member *m)
{
    return dfi_ability(b, m, DFI_ABILITY_DISGUISE) || dfi_ability(b, m, DFI_ABILITY_HUNGERSWITCH) ||
           dfi_ability(b, m, DFI_ABILITY_ILLUSION) || dfi_ability(b, m, DFI_ABILITY_STANCECHANGE) ||
           dfi_ability(b, m, DFI_ABILITY_ZEROTOHERO);
}

static bool dfi_next(void)
{
    return DFI_ABILITY_LIMBER != 0u;
}
"""


class FailSkillSwap(unittest.TestCase):
    FLAGS = 'flags: { failroleplay: 1, noreceiver: 1, noentrain: 1, notrace: 1, failskillswap: 1 },'

    def sources(self, extra='', champ=''):
        text = '\n'.join([entry(aid, 'name: "%s",' % aid, self.FLAGS) for aid in gen_closure.FAILSKILLSWAP_ABILITIES] +
                         [entry('levitate', 'name: "Levitate",', 'flags: { breakable: 1 }, // TODO check breakable'),
                          entry('pressure', 'name: "Pressure",', 'onStart(pokemon) {', '},')] + ([extra] if extra else []))
        return (TextSource('data/abilities.ts', text), TextSource('data/mods/champions/abilities.ts', champ))

    def pool(self, *more):
        return list(gen_closure.FAILSKILLSWAP_ABILITIES) + ['levitate', 'pressure'] + list(more)

    def refused(self, pool, abil, champ, c_text=C_BODY):
        with self.assertRaises(SystemExit) as cm:
            gen_closure.check_failskillswap(pool, abil, champ, c_text)
        return str(cm.exception.code)

    def test_the_list_is_the_pin_set(self):
        abil, champ = self.sources()
        gen_closure.check_failskillswap(self.pool(), abil, champ, C_BODY)
        self.assertEqual(gen_closure.ability_flags(abil, champ, 'levitate'), {'breakable'})
        self.assertEqual(gen_closure.ability_flags(abil, champ, 'pressure'), set())

    def test_multi_line_flags_with_a_trailing_comma(self):
        # Disguise's shape at the pin (data/abilities.ts:1009-1012): the flags over four lines, the last pair with a comma.
        abil, champ = self.sources(entry('disguised', 'name: "Disguised",', 'flags: {',
                                         '\tfailroleplay: 1, noreceiver: 1, noentrain: 1, notrace: 1, failskillswap: 1, '
                                         'cantsuppress: 1,', '\tbreakable: 1, notransform: 1,', '},'))
        self.assertEqual(gen_closure.ability_flags(abil, champ, 'disguised'),
                         {'failroleplay', 'noreceiver', 'noentrain', 'notrace', 'failskillswap', 'cantsuppress', 'breakable',
                          'notransform'})
        self.assertIn('the pool abilities with failskillswap are', self.refused(self.pool('disguised'), abil, champ))

    def test_another_pool_ability_with_the_flag_is_refused(self):
        abil, champ = self.sources(entry('commander', 'name: "Commander",', self.FLAGS))
        self.assertIn('the pool abilities with failskillswap are', self.refused(self.pool('commander'), abil, champ))
        gen_closure.check_failskillswap(self.pool(), abil, champ, C_BODY)  # not a pool row: no matter

    def test_a_listed_ability_without_the_flag_is_refused(self):
        abil, champ = self.sources()
        abil = TextSource('data/abilities.ts', '\n'.join(abil.lines).replace(
            '\tillusion: {\n\t\tname: "illusion",\n\t\t' + self.FLAGS, '\tillusion: {\n\t\tname: "illusion",\n\t\tflags: {},'))
        self.assertIn("'illusion'", self.refused(self.pool(), abil, champ))

    def test_a_champions_entry_with_its_own_flags_wins(self):
        abil, _ = self.sources()
        champ = TextSource('data/mods/champions/abilities.ts', entry('illusion', 'inherit: true,', 'flags: {},'))
        self.assertIn("the pool abilities with failskillswap are ['disguise', 'hungerswitch', 'stancechange', 'zerotohero']",
                      self.refused(self.pool(), abil, champ))
        champ = TextSource('data/mods/champions/abilities.ts', entry('illusion', 'inherit: true,', 'onStart() {', '},'))
        gen_closure.check_failskillswap(self.pool(), abil, champ, C_BODY)
        champ = TextSource('data/mods/champions/abilities.ts', entry('illusion', 'name: "Illusion",'))
        self.assertIn('neither inherits nor has flags', self.refused(self.pool(), abil, champ))

    def test_the_c_body_names_the_list(self):
        self.assertEqual(gen_closure.failskillswap_c_ids(C_BODY), list(gen_closure.FAILSKILLSWAP_ABILITIES))

    def test_a_c_body_with_an_id_missing_is_refused(self):
        abil, champ = self.sources()
        missing = C_BODY.replace(' || dfi_ability(b, m, DFI_ABILITY_HUNGERSWITCH)', '')
        self.assertNotEqual(missing, C_BODY)
        self.assertIn("dfi_fails_skillswap reads ['disguise', 'illusion', 'stancechange', 'zerotohero']",
                      self.refused(self.pool(), abil, champ, missing))

    def test_a_c_body_with_another_or_a_repeated_id_is_refused(self):
        abil, champ = self.sources()
        extra = C_BODY.replace('DFI_ABILITY_ZEROTOHERO);', 'DFI_ABILITY_ZEROTOHERO) || dfi_ability(b, m, DFI_ABILITY_TRACE);')
        self.assertIn('dfi_fails_skillswap reads', self.refused(self.pool(), abil, champ, extra))
        twice = C_BODY.replace('DFI_ABILITY_ZEROTOHERO);',
                               'DFI_ABILITY_ZEROTOHERO) || dfi_ability(b, m, DFI_ABILITY_ILLUSION);')
        self.assertIn('dfi_fails_skillswap reads', self.refused(self.pool(), abil, champ, twice))

    def test_a_source_without_the_function_is_refused(self):
        abil, champ = self.sources()
        self.assertIn('no definition of dfi_fails_skillswap',
                      self.refused(self.pool(), abil, champ, C_BODY.replace('dfi_fails_skillswap', 'dfi_other')))


if __name__ == '__main__':
    unittest.main()
