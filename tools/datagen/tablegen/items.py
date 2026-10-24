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


# Batch I1 (decision 0015 entry 5ef): six items with one clause each at an existing hook, engine rows (ENGINE_ROWS): the turn code
# reads them by id and hard-codes these pinned texts. None has a Champions entry; the rules are format-independent (the same rows
# serve every table set). Normal Gem: the attacker's TryPrimaryHit and the gem volatile (I1_OTHER_FACTS); King's Rock: the added
# flinch secondary (combat/items/kings_rock.h; pool_families.js checkI1 checks the flinch secondaries of every pool move); Zoom
# Lens: the accuracy of the priority -2 group at a target that will not move (queue.willMove); Shell Bell: the after-move heal of
# totalDamage / 8; Big Root: the TryHeal of the five effects; Shed Shell: the two trap handlers.
I1_ITEM_FACTS = (
    ('normalgem', ('isGem: true,',
                   "onSourceTryPrimaryHit(target, source, move) { if (target === source || move.category === 'Status' || "
                   "move.flags['pledgecombo']) return; if (move.type === 'Normal' && source.useItem()) { source.addVolatile('gem'); } },")),
    ('kingsrock', ('onModifyMovePriority: -1,',
                   'onModifyMove(move) { if (move.category !== "Status") { if (!move.secondaries) move.secondaries = []; '
                   "for (const secondary of move.secondaries) { if (secondary.volatileStatus === 'flinch') return; } "
                   "move.secondaries.push({ chance: 10, volatileStatus: 'flinch', }); } },")),
    ('zoomlens', ('onSourceModifyAccuracyPriority: -2,',
                  "onSourceModifyAccuracy(accuracy, target) { if (typeof accuracy === 'number' && !this.queue.willMove(target)) { "
                  "this.debug('Zoom Lens boosting accuracy'); return this.chainModify([4915, 4096]); } },")),
    ('shellbell', ('onAfterMoveSecondarySelfPriority: -1,',
                   'onAfterMoveSecondarySelf(pokemon, target, move) { if (move.totalDamage && !pokemon.forceSwitchFlag) { '
                   'this.heal(move.totalDamage / 8, pokemon); } },')),
    ('bigroot', ('onTryHealPriority: 1,',
                 "onTryHeal(damage, target, source, effect) { const heals = ['drain', 'leechseed', 'ingrain', 'aquaring', 'strengthsap']; "
                 'if (heals.includes(effect.id)) { return this.chainModify([5324, 4096]); } },')),
    ('shedshell', ('onTrapPokemonPriority: -10,', 'onTrapPokemon(pokemon) { pokemon.trapped = false; },',
                   'onMaybeTrapPokemonPriority: -10,', 'onMaybeTrapPokemon(pokemon) { pokemon.maybeTrapped = false; },')),
)
# The rules outside the item entries that the engine hard-codes with them: the gem volatile (data/conditions.ts:463-472), useItem's
# gem line (sim/pokemon.ts:1828-1829), queue.willMove (sim/battle-queue.ts:324-332), heal()'s minimum and TryHeal
# (sim/battle.ts:2268-2271) and runEvent's final modify (sim/battle.ts:929-933), the secondaries() loop (sim/battle-actions.ts:
# 1336-1354), the AfterMoveSecondarySelf gate (sim/battle-actions.ts:536-539), Leech Seed's heal (data/moves.ts:10223-10226) and
# Strength Sap's (data/moves.ts:18187).
I1_OTHER_FACTS = (
    ('data/conditions.ts', ("gem: { name: 'gem', duration: 1, affectsFainted: true, onBasePowerPriority: 14, "
                            "onBasePower(basePower, user, target, move) { this.debug('Gem Boost'); return this.chainModify([5325, 4096]); }, },",)),
    ('sim/pokemon.ts', ("if (item.isGem) { this.battle.add('-enditem', this, item, '[from] gem', `[move] ${this.battle.activeMove!.name}`); }",)),
    ('sim/battle-queue.ts', ("willMove(pokemon: Pokemon) { if (pokemon.fainted) return null; for (const action of this.list) { "
                             "if (action.choice === 'move' && action.pokemon === pokemon) { return action; } } return null; }",)),
    ('sim/battle.ts', ("if (damage && damage <= 1) damage = 1; damage = this.trunc(damage); // for things like Liquid Ooze, the Heal "
                       "event still happens when nothing is healed. damage = this.runEvent('TryHeal', target, source, effect, damage);",
                       "if (typeof relayVar === 'number' && relayVar === Math.abs(Math.floor(relayVar))) {")),
    ('sim/battle-actions.ts', ("for (const secondary of secondaries) { const secondaryRoll = this.battle.random(100);",
                               "if (!(move.hasSheerForce && pokemon.hasAbility('sheerforce')) && !move.flags['futuremove']) { "
                               "const originalHp = pokemon.hp; this.battle.singleEvent('AfterMoveSecondarySelf', move, null, pokemon, "
                               "target, move); this.battle.runEvent('AfterMoveSecondarySelf', pokemon, target, move);")),
    ('data/moves.ts', ('const damage = this.damage(pokemon.baseMaxhp / 8, pokemon, target); if (damage) { this.heal(damage, target, pokemon); }',
                       'return !!(this.heal(atk, source, target) || success);')),
)
# Starminite, the Mega Stone of Starmie (Starmie-Mega: Huge Power), through the generic Mega path (data/items.ts:6021-6032,
# data/mods/champions/items.ts:906-909): the pinned megaStone, itemUser and standard onTakeItem, a Champions entry of `inherit`
# and `isNonstandard: null` only (the stone's legality in the Champions table set; the row is the same in every set).
I1_STONES = {'starminite': ('Starmie', 'Starmie-Mega')}


def check_i1_facts(items_ts, champ_items, others, only=None):
    """Batch I1 (decision 0015 entry 5ef): every fact of I1_ITEM_FACTS is in the pinned item entry, whitespace aside, and the
    Champions mod has no entry of its own for it; the facts of I1_OTHER_FACTS are in their files (`others`: rel -> Source);
    each stone of I1_STONES has the pinned megaStone, itemUser and standard onTakeItem and no other field, and a Champions entry
    of `inherit` and `isNonstandard: null` only. `only`: (item facts, other facts, stones) to check instead (the generator's tests)."""
    items, other, stones = (I1_ITEM_FACTS, I1_OTHER_FACTS, I1_STONES) if only is None else only
    for iid, facts in items:
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
    for iid, (base, mega) in sorted(stones.items()):
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
        extra = sorted(set(got) - {'name', 'spritenum', 'megaStone', 'itemUser', 'onTakeItem', 'num', 'gen', 'isNonstandard'})
        if extra:
            fail('item %s: the pin has fields the I1 facts do not list: %s' % (iid, ', '.join(extra)))
        ci = champ_items.entry(iid)
        if ci is None:
            fail('item %s: the Champions entry is missing' % iid)
        cf = fields(ci[2])
        if set(cf) - {'inherit', 'isNonstandard'} or norm(cf.get('isNonstandard', (0, ''))[1]) != 'isNonstandard: null,':
            fail('item %s: the Champions entry is not inherit and isNonstandard null' % iid)
