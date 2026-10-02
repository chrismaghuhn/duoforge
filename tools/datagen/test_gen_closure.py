#!/usr/bin/env python3
"""Refusal checks for gen_closure.py's move parser: a secondary effect the
tables do not model must fail instead of being encoded as something else.
The same for the family patterns of the pool tables (decision 0015): an item or
ability that deviates from the one pattern of its family must fail, and so must
one that follows a pattern without being listed as a member. The texts copy the
pinned data/moves.ts, data/items.ts and data/abilities.ts layout, so no
checkout is needed.

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


if __name__ == '__main__':
    unittest.main()
