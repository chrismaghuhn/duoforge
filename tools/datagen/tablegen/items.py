"""Items: the item families (type boosters, resist berries and the rest), their matchers and parameters, the
item facts by step and their checks.

Part of the table generator tools/datagen/gen_closure.py (restructure step 5: split by area from
gen_closure.py@8800b625).
"""
import re

from .source import fail, field_is, field_match, fields, NoMatch, norm, shape, TYPES
from .families import FAMILY_PARAM_NONE

# The new items in their fixed order: the families in the order of decision 0015 section 3 (type boosters, then
# resist berries), each by Showdown id (which is also by name). Mystic Water and Miracle Seed (type boosters) and
# Chople Berry (a resist berry) are in the prefix.
POOL_TYPE_BOOSTERS = ['blackbelt', 'blackglasses', 'charcoal', 'dragonfang', 'fairyfeather', 'hardstone', 'magnet',
                      'metalcoat', 'nevermeltice', 'poisonbarb', 'sharpbeak', 'silkscarf', 'silverpowder', 'softsand',
                      'spelltag', 'twistedspoon']
POOL_RESIST_BERRIES = ['babiriberry', 'chartiberry', 'chilanberry', 'cobaberry', 'colburberry', 'habanberry',
                       'kasibberry', 'kebiaberry', 'occaberry', 'passhoberry', 'payapaberry', 'rindoberry',
                       'roseliberry', 'shucaberry', 'tangaberry', 'wacanberry', 'yacheberry']
POOL_ITEMS = POOL_TYPE_BOOSTERS + POOL_RESIST_BERRIES
G2_ITEMS = ['focussash', 'expertbelt', 'floettite']
G47_ITEM_FACTS = (
    ('lumberry', ('onAfterSetStatusPriority: -1,',
                  'onAfterSetStatus(status, pokemon) { pokemon.eatItem(); },',
                  "onUpdate(pokemon) { if (pokemon.status || pokemon.volatiles['confusion']) { pokemon.eatItem(); } },",
                  "onEat(pokemon) { pokemon.cureStatus(); pokemon.removeVolatile('confusion'); },")),
    ('mentalherb', ("const conditions = ['attract', 'taunt', 'encore', 'torment', 'disable', 'healblock'];",
                    'if (!pokemon.useItem()) return;',
                    'pokemon.removeVolatile(secondCondition);',
                    "this.add('-end', pokemon, 'move: Attract', '[from] item: Mental Herb');")),
)
G67_ITEM_FACTS = (
    ('airballoon', ("onStart(target) { if (!target.ignoringItem() && !this.field.getPseudoWeather('gravity')) { "
                    "this.add('-item', target, 'Air Balloon'); } },",
                    "onDamagingHit(damage, target, source, move) { this.add('-enditem', target, 'Air Balloon'); "
                    "target.item = ''; this.clearEffectState(target.itemState); "
                    "this.runEvent('AfterUseItem', target, null, null, this.dex.items.get('airballoon')); },",
                    "onAfterSubDamage(damage, target, source, effect) { this.debug('effect: ' + effect.id); "
                    "if (effect.effectType === 'Move') { this.add('-enditem', target, 'Air Balloon'); "
                    "target.item = ''; this.clearEffectState(target.itemState); "
                    "this.runEvent('AfterUseItem', target, null, null, this.dex.items.get('airballoon')); } },")),
)
G83_ITEM_FACTS = (
    ('ironball', ("onEffectiveness(typeMod, target, type, move) { if (!target) return; if (target.volatiles['ingrain'] || "
                  "target.volatiles['smackdown'] || this.field.getPseudoWeather('gravity')) return; "
                  "if (move.type === 'Ground' && target.hasType('Flying')) return 0; },",
                  'onModifySpe(spe) { return this.chainModify(0.5); },')),
)
G34_ITEM_FACTS = (
    ('widelens',('onSourceModifyAccuracyPriority: -2,',
                  "onSourceModifyAccuracy(accuracy) { if (typeof accuracy === 'number') { return this.chainModify([4505, 4096]); } },")),
)
G28_ITEM_FACTS = (
    ('expertbelt', ["onModifyDamage(damage, source, target, move) { if (move && target.getMoveHitData(move).typeMod > 0) { "
                    "return this.chainModify([4915, 4096]); } },"]),
)
# Step G49 (duration and boost items, part): Muscle Band and Wise Glasses (their base power x4505/4096 by category, priority 16,
# data/items.ts:4239-4251 and :7754-7766) and Bright Powder (the target's accuracy x3686/4096, priority -2, data/items.ts:659-670)
# are engine rows (ENGINE_ROWS): the turn code reads the item by id and hard-codes these texts. The duration rows of Damp Rock
# and its kind and of Terrain Extender are not marked by this step.
G49_ITEM_FACTS = (
    ('muscleband', ('onBasePowerPriority: 16,',
                    "onBasePower(basePower, user, target, move) { if (move.category === 'Physical') { return this.chainModify([4505, 4096]); } },")),
    ('wiseglasses', ('onBasePowerPriority: 16,',
                     "onBasePower(basePower, user, target, move) { if (move.category === 'Special') { return this.chainModify([4505, 4096]); } },")),
    ('brightpowder', ('onModifyAccuracyPriority: -2,',
                      "onModifyAccuracy(accuracy) { if (typeof accuracy !== 'number') return; this.debug('brightpowder - decreasing accuracy'); "
                      "return this.chainModify([3686, 4096]); },")),
)
G55_ITEMS = ('damprock', 'heatrock', 'smoothrock', 'icyrock', 'terrainextender')

ITEM_FAMILIES = ['NONE', 'TYPE_BOOSTER', 'RESIST_BERRY']
# The members of each family, as decision 0015 section 3 names them (prefix and new rows). The parameter of a member
# is never listed here: it comes from the pinned handler. Every id of the pool that is not listed has no family.
ITEM_MEMBERS = {'TYPE_BOOSTER': ['miracleseed', 'mysticwater'] + POOL_TYPE_BOOSTERS,
                'RESIST_BERRY': ['chopleberry'] + POOL_RESIST_BERRIES}
# Chilan Berry halves any Normal hit; every other resist berry needs a super effective hit (decision 0015 section 3).
# A Normal move is never super effective, so the variant is the Normal berry.
RESIST_BERRY_NORMAL = ('chilanberry',)
INERT_ITEM_KEYS = {'name', 'spritenum', 'fling', 'num', 'gen', 'isNonstandard', 'naturalGift', 'isBerry', 'isChoice',
                   'isGem', 'isPokeball', 'megaStone', 'itemUser', 'megaEvolves'}
# The onTakeItem of every Mega Stone at the pin (it only stops Knock Off and Trick on the holder): data for the
# Mega link, not a mechanic of the tables.
STONE_TAKE_ITEM = ("onTakeItem(item, source) { return !item.megaStone?.[source.baseSpecies.baseSpecies]; },",
                   "onTakeItem(item, source) { return !item.megaStone || (!item.megaStone[source.baseSpecies.name] && "
                   "!Object.values(item.megaStone).includes(source.baseSpecies.name)); },")


# Items. Type booster: BasePower x4915/4096 for a move of the type, priority 15. The `move &&` guard of seven of the
# eighteen is the only textual variation and has no effect.
ITEM_BOOSTER_KEYS = {'name', 'spritenum', 'fling', 'onBasePowerPriority', 'onBasePower', 'num', 'gen'}
ITEM_BOOSTER_BASE_POWER = (r"onBasePower\(basePower, user, target, move\) \{ if \((?:move && )?move\.type === '(\w+)'\) "
                           r"\{ return this\.chainModify\(\[4915, 4096\]\); \} \},")


def type_booster_type(f, _iid):
    shape(f, ITEM_BOOSTER_KEYS)
    field_is(f, 'onBasePowerPriority', 'onBasePowerPriority: 15,')
    return field_match(f, 'onBasePower', ITEM_BOOSTER_BASE_POWER).group(1)


# Resist berry: the target eats it on a super effective hit of the type (Chilan: on any Normal hit), ModifyDamage
# x0.5. The natural gift type is a second statement of the type and must agree.
ITEM_BERRY_KEYS = {'name', 'spritenum', 'isBerry', 'naturalGift', 'onSourceModifyDamage', 'onEat', 'num', 'gen'}
BERRY_NATURAL_GIFT = r'naturalGift: \{ basePower: 80, type: "(\w+)", \},'
BERRY_HEAD = r"onSourceModifyDamage\(damage, source, target, move\) \{ "
BERRY_EAT = (r"if \(target\.eatItem\(\)\) \{ this\.debug\('-50% reduction'\); "
             r"this\.add\('-enditem', target, this\.effect, '\[weaken\]'\); return this\.chainModify\(0\.5\); "
             r"\} \} \},")
BERRY_SUPER_EFFECTIVE = (BERRY_HEAD + r"if \(move\.type === '(\w+)' && target\.getMoveHitData\(move\)\.typeMod > 0\) \{ "
                         r"const hitSub = target\.volatiles\['substitute'\] && !move\.flags\['bypasssub'\] && "
                         r"!\(move\.infiltrates && this\.gen >= 6\); if \(hitSub\) return; " + BERRY_EAT)
BERRY_NORMAL_HIT = (BERRY_HEAD + r"if \( move\.type === '(Normal)' && \(!target\.volatiles\['substitute'\] \|\| "
                    r"move\.flags\['bypasssub'\] \|\| \(move\.infiltrates && this\.gen >= 6\)\) \) \{ " + BERRY_EAT)


def resist_berry_type(f, iid):
    shape(f, ITEM_BERRY_KEYS)
    field_is(f, 'isBerry', 'isBerry: true,')
    field_is(f, 'onEat', 'onEat() { },')
    gift = field_match(f, 'naturalGift', BERRY_NATURAL_GIFT).group(1)
    pattern = BERRY_NORMAL_HIT if iid in RESIST_BERRY_NORMAL else BERRY_SUPER_EFFECTIVE
    t = field_match(f, 'onSourceModifyDamage', pattern).group(1)
    if t != gift:
        raise NoMatch('the natural gift type %s differs from the handler type %s' % (gift, t))
    return t


ITEM_MATCHERS = [('TYPE_BOOSTER', type_booster_type), ('RESIST_BERRY', resist_berry_type)]


def item_param(family, fact):
    """(parameter byte, its name in C) of an item's family column: the type."""
    if family == 'NONE':
        return FAMILY_PARAM_NONE, 'DFI_FAMILY_PARAM_NONE'
    return TYPES.index(fact), 'DFI_TYPE_' + fact.upper()


def entry_features(src, champ, rid, inert_keys, stone=False, readers=None):
    """The features of an item or ability entry that the tables do not model: every callback (a function field, or
    any field named onX), a condition block and every field outside the inert keys. The Champions mod adds or
    replaces fields of the same entry. A Mega Stone's onTakeItem is data of its Mega link (STONE_TAKE_ITEM)."""
    e = src.entry(rid)
    if e is None:
        fail('%s not found in %s' % (rid, src.rel))
    f = fields(e[2])
    ce = champ.entry(rid)
    if ce is not None:
        f.update({k: v for k, v in fields(ce[2]).items() if k != 'inherit'})
    feats = []
    for name, (is_fn, text) in sorted(f.items()):
        if name == 'condition':
            feats.append('condition block')
        elif is_fn or re.match(r'on[A-Z]', name):
            if stone and name == 'onTakeItem' and norm(re.sub(r'//[^\n]*', '', text)) in STONE_TAKE_ITEM:
                continue
            feats.append('callback %s' % name)
        elif name not in inert_keys:
            feats.append('field %s' % name)
    if readers is not None:
        own = [(src.rel, e[0], e[1])] + ([(champ.rel, ce[0], ce[1])] if ce is not None else [])
        feats += ['read by id in %s' % rel for rel in readers.files(rid, own)]
    return feats


SEED_PAIRS = (('psychicseed', 'psychicterrain', 'spd'), ('electricseed', 'electricterrain', 'def'),
              ('mistyseed', 'mistyterrain', 'spd'))


def check_g28_items(items_ts, only=None):
    """Step G28: the text of Expert Belt's onModifyDamage (G28_ITEM_FACTS) is in the pinned entry, whole."""
    for iid, facts in (G28_ITEM_FACTS if only is None else only):
        e = items_ts.entry(iid)
        if e is None:
            fail('item %s not found' % iid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('item %s: the entry no longer has "%s"' % (iid, fact))


G46_ITEM_FACTS = (
    ('redcard', ("onAfterMoveSecondary(target, source, move) { if (source && source !== target && source.hp && target.hp && "
                 "move && move.category !== 'Status') { if (!source.isActive || !this.canSwitch(source.side) || "
                 "source.forceSwitchFlag || target.forceSwitchFlag) { return; } // The item is used up even against a pokemon "
                 "with Ingrain or that otherwise can't be forced out if (target.useItem(source)) { if (this.runEvent('DragOut', "
                 "source, target, move)) { source.forceSwitchFlag = true; } } } },",)),
)
G75_ITEM_FACTS = (
    ('scopelens', ('onModifyCritRatio(critRatio) {',
                   'return critRatio + 1;',
                   '},')),
)
G77_ITEM_FACTS = (
    ('leek', ('onModifyCritRatio(critRatio, user) {',
              'if (["farfetchd", "sirfetchd"].includes(this.toID(user.baseSpecies.baseSpecies))) {',
              'return critRatio + 2;',
              '}',
              '},',
              'itemUser: ["Farfetch\\u2019d", "Farfetch\\u2019d-Galar", "Sirfetch\\u2019d"],')),
)


def check_g49_facts(items_ts, champ_items):
    """Step G49: the texts of Muscle Band, Wise Glasses and Bright Powder that the engine hard-codes (G49_ITEM_FACTS) are in
    the pinned entries, whitespace aside, and the Champions mod has no entry of its own for them."""
    for rid, facts in G49_ITEM_FACTS:
        e = items_ts.entry(rid)
        if e is None:
            fail('item %s not found' % rid)
        if champ_items.entry(rid) is not None:
            fail('item %s: the champions mod overrides the entry' % rid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('item %s: the entry no longer has "%s"' % (rid, fact))


def check_g55_items(items_ts, champ_items):
    """Step G55: the five rock items and Terrain Extender are data rows of the pinned items.ts (no callback of their own: the
    durations are the callbacks of the weather and terrain conditions), and the Champions mod has no entry for them."""
    for rid in G55_ITEMS:
        e = items_ts.entry(rid)
        if e is None:
            fail('item %s not found' % rid)
        if champ_items.entry(rid) is not None:
            fail('item %s: the champions mod overrides the entry' % rid)
        if re.search(r'on[A-Z]\w*\(|durationCallback|condition:', chr(10).join(e[2])):
            fail('item %s: a callback, which the rows of G55 do not model' % rid)


# Decision 0015 entry 5eh: Quick Claw and Focus Band are engine rows (ENGINE_ROWS) with a roll of their own (draw sites
# QUICK_CLAW 27 and FOCUS_BAND 28, src/combat/items/draw_items.h). Their pinned callbacks are demanded whole, whitespace aside,
# and the Champions mod has no entry for them (the rows hold in every format). E5H_OTHER_FACTS are the lines of the simulator
# that the engine's places for the rolls follow: resolveAction runs FractionalPriority with the relay value 0 (the `priority`
# that Quick Claw tests), getActionSpeed adds the fraction to the priority, Champions' Encore re-resolves the replaced action,
# and spreadDamage runs the Damage event for every damage but Struggle's recoil.
E5H_ITEM_FACTS = (
    ('quickclaw', ('onFractionalPriorityPriority: -2,',
                   "onFractionalPriority(priority, pokemon, target, move) { if (move.category === 'Status' && "
                   "pokemon.hasAbility('myceliummight')) return; if (priority <= 0 && this.randomChance(1, 5)) { "
                   "this.add('-activate', pokemon, 'item: Quick Claw'); return 0.1; } },")),
    ('focusband', ('onDamagePriority: -40,',
                   "onDamage(damage, target, source, effect) { if (this.randomChance(1, 10) && damage >= target.hp && effect && "
                   "effect.effectType === 'Move') { this.add(\"-activate\", target, \"item: Focus Band\"); return target.hp - 1; } },")),
)
E5H_OTHER_FACTS = (
    ('sim/battle-queue.ts', ("action.fractionalPriority = this.battle.runEvent('FractionalPriority', action.pokemon, null, "
                             "action.move, 0);",)),
    ('sim/battle.ts', ('action.priority = priority + action.fractionalPriority;',
                       "if (effect.id !== 'strugglerecoil') { // Struggle recoil is not affected by effects",
                       "targetDamage = this.runEvent('Damage', target, source, effect, targetDamage, true);")),
    ('data/mods/champions/moves.ts', ('this.queue.changeAction(target, {',)),
)
# Every entry of the pin with a FractionalPriority or a Damage handler (on, onAny, onFoe, onSource, onAlly, or its priority), by
# file: the engine models the rolls against exactly these (draw_items.h names what each one does; the white-box test
# duoforge.items.quick_claw_focus_band pins that the rows it does not model stay unmarked). A new handler fails here.
E5H_FRACTIONAL_HANDLERS = {'data/items.ts': ['custapberry', 'fullincense', 'laggingtail', 'quickclaw'],
                           'data/abilities.ts': ['myceliummight', 'quickdraw', 'stall']}
E5H_DAMAGE_HANDLERS = {'data/items.ts': ['focusband', 'focussash'],
                       'data/abilities.ts': ['angershell', 'berserk', 'damp', 'disguise', 'gluttony', 'heatproof', 'iceface',
                                             'magicguard', 'mountaineer', 'poisonheal', 'rockhead', 'sturdy'],
                       'data/mods/champions/abilities.ts': ['angershell', 'berserk'],
                       'data/moves.ts': ['bide', 'endure', 'falseswipe', 'holdback']}
E5H_SCANNED = ('data/items.ts', 'data/abilities.ts', 'data/mods/champions/abilities.ts', 'data/moves.ts',
               'data/mods/champions/items.ts')
E5H_FRACTIONAL = re.compile(r'\bonFractionalPriority(?:Priority)?\b')
E5H_DAMAGE = re.compile(r'\bon(?:Any|Foe|Source|Ally)?Damage(?:Priority)?\b')


def e5h_handler_entries(src, pattern):
    """The top-level entries of `src` that have a line matching `pattern`, sorted."""
    found, owner = set(), None
    for line in src.lines:
        m = re.match(r'^\t(\w+): \{', line)
        if m is not None:
            owner = m.group(1)
        if owner is not None and pattern.search(line):
            found.add(owner)
    return sorted(found)


def check_5eh_facts(items_ts, champ_items, others, only=None):
    """Decision 0015 entry 5eh: the facts of E5H_ITEM_FACTS are in the pinned item entries, whitespace aside, and the Champions mod
    has no entry for them; E5H_OTHER_FACTS are in their files, and the entries with a FractionalPriority or Damage handler in the
    files of E5H_SCANNED are exactly those of E5H_FRACTIONAL_HANDLERS and E5H_DAMAGE_HANDLERS (`others`: rel -> Source for the
    files of both). `only`: (item facts, other facts, fractional handlers, damage handlers, scanned files) to check instead (the
    generator's tests)."""
    facts_by_id, other, fractional, damage, scanned = (
        (E5H_ITEM_FACTS, E5H_OTHER_FACTS, E5H_FRACTIONAL_HANDLERS, E5H_DAMAGE_HANDLERS, E5H_SCANNED) if only is None else only)
    for iid, facts in facts_by_id:
        e = items_ts.entry(iid)
        if e is None:
            fail('item %s not found' % iid)
        if champ_items.entry(iid) is not None:
            fail('item %s: the champions mod overrides the entry' % iid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('item %s: the entry no longer has "%s"' % (iid, fact))
    for rel, facts in other:
        text = norm(chr(10).join(others[rel].lines))
        for fact in facts:
            if norm(fact) not in text:
                fail('%s: the pin no longer has "%s"' % (rel, fact))
    for what, pattern, expected in (('FractionalPriority', E5H_FRACTIONAL, fractional), ('Damage', E5H_DAMAGE, damage)):
        for rel in scanned:
            got = e5h_handler_entries(others[rel], pattern)
            if got != sorted(expected.get(rel, [])):
                fail('%s: the entries with a %s handler are %s, not %s (src/combat/items/draw_items.h)'
                     % (rel, what, got, sorted(expected.get(rel, []))))
