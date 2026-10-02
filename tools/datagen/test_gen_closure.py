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
        self.refused(setter('sandstream', 'Sand Stream', "this.field.setWeather('sandstorm');"), 'WEATHER_SETTER',
                     'sandstream is listed as WEATHER_SETTER but deviates', what='ability')

    def test_a_terrain_setter_gives_its_terrain(self):
        self.assertEqual(self.derive(GRASSY_SURGE, 'TERRAIN_SETTER', what='ability'), ('TERRAIN_SETTER', 'grassyterrain'))
        self.refused(setter('electricsurge', 'Electric Surge', "this.field.setTerrain('electricterrain');"),
                     'TERRAIN_SETTER', 'electricsurge is listed as TERRAIN_SETTER but deviates', what='ability')

    def test_the_members_of_the_decision_are_what_the_tables_list(self):
        # 18 type boosters and 18 resist berries, three "-ate", four pinch, two weather and two terrain setters.
        self.assertEqual((len(gen_closure.ITEM_MEMBERS['TYPE_BOOSTER']), len(gen_closure.ITEM_MEMBERS['RESIST_BERRY'])),
                         (18, 18))
        self.assertEqual({k: len(v) for k, v in gen_closure.ABILITY_MEMBERS.items()},
                         {'ATE': 3, 'PINCH': 4, 'WEATHER_SETTER': 2, 'TERRAIN_SETTER': 2})
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
ICE_PUNCH = move_entry('icepunch', 'Ice Punch', 'secondary: {', '\tchance: 10,', "\tstatus: 'frz',", '},',
                       category='Physical', base_power=75, pp=15, type_='Ice', flags='contact: 1, protect: 1, punch: 1')


PLAIN = move_entry('plain', 'Plain', category='Physical', base_power=50, flags='contact: 1')


def parse_pool(mid, text, pool=True, ext=True):
    base = TextSource('data/moves.ts', text)
    return gen_closure.parse_move(mid, base, TextSource('data/mods/champions/moves.ts', ''), ext, pool)


class PoolMoves(unittest.TestCase):
    def refused(self, mid, text, message, **kwargs):
        with self.assertRaises(SystemExit) as cm:
            parse_pool(mid, text, **kwargs)
        self.assertEqual(cm.exception.code, 'gen_closure: move %s: %s' % (mid, message))

    def test_a_handler_move_parses_in_the_pool_mode_with_its_special(self):
        for mid, text, special in (('soak', SOAK, 'SOAK'), ('scald', SCALD, 'SCALD'), ('recover', RECOVER, 'RECOVER'),
                                   ('psychicnoise', PSYCHIC_NOISE, 'PSYCHIC_NOISE'),
                                   ('throatchop', THROAT_CHOP, 'THROAT_CHOP')):
            with self.subTest(mid):
                rec = parse_pool(mid, text)
                self.assertEqual(rec['special'], gen_closure.SPECIAL_IDS_P.index(special))
                # What the handler owns is not encoded in the generic columns.
                self.assertEqual((rec['sec_kind'], rec['sec_param'], rec['primary_status'], rec['side_condition']),
                                 (2, 1, 0, 0) if mid == 'scald' else (0, 0, 0, 0))
        self.assertEqual(parse_pool('throatchop', THROAT_CHOP)['sec_chance'], 0)
        self.assertEqual(parse_pool('psychicnoise', PSYCHIC_NOISE)['sec_chance'], 0)

    def test_the_handlers_are_the_nine_new_specials_in_order(self):
        self.assertEqual(gen_closure.SPECIAL_IDS_P[len(gen_closure.SPECIAL_IDS_C):], gen_closure.G2_HANDLERS)
        self.assertEqual(len(gen_closure.G2_HANDLERS), 9)
        self.assertEqual({v[0] for k, v in gen_closure.SPECIAL_P.items() if k not in gen_closure.SPECIAL_C},
                         set(gen_closure.G2_HANDLERS))

    def test_the_same_move_is_refused_outside_the_pool_mode(self):
        # The closure and extended tables keep failing for what they do not model: no handler leaks into them.
        for mid, text, message in (('soak', SOAK, 'callback onHit is not mapped to a handler'),
                                   ('scald', SCALD, 'unknown field thawsTarget'),
                                   ('recover', RECOVER, 'unknown field heal'),
                                   ('psychicnoise', PSYCHIC_NOISE, 'secondary volatile healblock is not modelled'),
                                   ('throatchop', THROAT_CHOP, 'unknown secondary')):
            for ext in (False, True):
                with self.subTest(mid=mid, ext=ext):
                    self.refused(mid, text, message, pool=False, ext=ext)

    def test_a_handler_owns_only_what_it_names(self):
        self.refused('scald', SCALD.replace('thawsTarget: true', 'thawsTarget: false'),
                     'thawsTarget is not "thawsTarget: true,"')
        self.refused('recover', RECOVER.replace('[1, 2]', '[1, 4]'), 'heal is not "heal: [1, 2],"')
        self.refused('recover', RECOVER.replace('\t\theal: [1, 2],\n', ''), 'heal is not "heal: [1, 2],"')
        self.refused('psychicnoise', PSYCHIC_NOISE.replace('chance: 100', 'chance: 50'),
                     'the secondary is not "secondary: { chance: 100, volatileStatus: \'healblock\', },"')
        self.refused('throatchop', THROAT_CHOP.replace("addVolatile('throatchop')", "addVolatile('taunt')"),
                     'the secondary is not "secondary: { chance: 100, onHit(target) { target.addVolatile('
                     '\'throatchop\'); }, },"')
        self.refused('throatchop', THROAT_CHOP.replace('\t\tcondition: {\n\t\t\tduration: 2,\n\t\t},\n', ''),
                     'expected a condition block')
        # A callback the handler does not name, and one it names that is absent.
        self.refused('soak', SOAK.replace('target: "normal",', 'onTryHit() { },\n\t\ttarget: "normal",'),
                     'callback onTryHit is not mapped to a handler')
        self.refused('soak', SOAK.replace('onHit(target) {', 'onHitX(target) {'), 'callback onHitX is not mapped to a handler')
        # Another move does not get the handler of a move: scald's field on soak, a condition block on recover.
        self.refused('recover', RECOVER.replace('heal: [1, 2],', 'heal: [1, 2],\n\t\tthawsTarget: true,'),
                     'unknown field thawsTarget')
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

    def test_an_ignored_flag_fails_when_its_reader_enters_the_pool(self):
        gen_closure.check_flag_readers([{'id': 'drizzle'}, {'id': 'rockhead'}])
        for reader in ('ironfist', 'sharpness'):
            with self.subTest(reader):
                with self.assertRaises(SystemExit) as cm:
                    gen_closure.check_flag_readers([{'id': 'drizzle'}, {'id': reader}])
                self.assertIn('ability %s reads the move flag' % reader, str(cm.exception.code))

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
        self.assertTrue({k for k in gen_closure.SPECIAL_P if k not in gen_closure.SPECIAL_C} <= set(gen_closure.G2_MOVES))
        for _sp, _ab, item, moves, _mega in gen_closure.SETS_G2:
            self.assertTrue(item in gen_closure.G2_ITEMS or item not in gen_closure.POOL_ITEMS)
            self.assertTrue(set(moves) <= set(gen_closure.MOVES + gen_closure.MOVES_C + gen_closure.G2_MOVES))


if __name__ == '__main__':
    unittest.main()
