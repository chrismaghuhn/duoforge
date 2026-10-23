"""Abilities: the ability families (-ate, pinch, weather and terrain setters), their matchers and
parameters, the ability facts by step and their checks.

Part of the table generator tools/datagen/gen_closure.py (restructure step 5: split by area from
gen_closure.py@8800b625).
"""
import os
import re

from .source import fail, field_is, field_match, NoMatch, norm, scalar, shape, TYPES
from .families import FAMILY_PARAM_NONE, PRIMAL_GUARD, TERRAIN_CODES, WEATHER_CODES

# The new abilities in the order of decision 0015 section 3: "-ate", then pinch. Aerilate (the "-ate" member),
# Blaze (the pinch member) and the weather and terrain setters are in the prefix.
POOL_ABILITIES = ['pixilate', 'refrigerate', 'overgrow', 'torrent', 'swarm']
G2_ABILITIES = ['rockhead', 'flowerveil', 'fairyaura']
G37_ABILITY_FACTS = (
    ('toxicdebris', ("onDamagingHit(damage, target, source, move) { const side = source.isAlly(target) ? source.side.foe : source.side; "
                     "const toxicSpikes = side.sideConditions['toxicspikes']; "
                     "if (move.category === 'Physical' && (!toxicSpikes || toxicSpikes.layers < 2)) { "
                     "this.add('-activate', target, 'ability: Toxic Debris'); side.addSideCondition('toxicspikes', target); } },",)),
)
G34_ABILITY_FACTS = (
    ('compoundeyes', ('onSourceModifyAccuracyPriority: -1,',
                      "onSourceModifyAccuracy(accuracy) { if (typeof accuracy !== 'number') return; "
                      "this.debug('compoundeyes - enhancing accuracy'); return this.chainModify([5325, 4096]); },")),
    ('ironfist', ('onBasePowerPriority: 23,',
                  "onBasePower(basePower, attacker, defender, move) { if (move.flags['punch']) { this.debug('Iron Fist boost'); "
                  "return this.chainModify([4915, 4096]); } },")),
    ('sharpness', ('onBasePowerPriority: 19,',
                   "onBasePower(basePower, attacker, defender, move) { if (move.flags['slicing']) { this.debug('Sharpness boost'); "
                   "return this.chainModify(1.5); } },")),
    ('solidrock', ("onSourceModifyDamage(damage, source, target, move) { if (target.getMoveHitData(move).typeMod > 0) { "
                   "this.debug('Solid Rock neutralize'); return this.chainModify(0.75); } },",)),
    ('technician', ('onBasePowerPriority: 30,',
                    "onBasePower(basePower, attacker, defender, move) { const basePowerAfterMultiplier = "
                    "this.modify(basePower, this.event.modifier); this.debug(`Base Power: ${basePowerAfterMultiplier}`); "
                    "if (basePowerAfterMultiplier <= 60) { this.debug('Technician boost'); return this.chainModify(1.5); } },")),
    ('multiscale', ("onSourceModifyDamage(damage, source, target, move) { if (target.hp >= target.maxhp) { "
                    "this.debug('Multiscale weaken'); return this.chainModify(0.5); } },",)),
    ('galewings', ("onModifyPriority(priority, pokemon, target, move) { if (move?.type === 'Flying' && pokemon.hp === pokemon.maxhp) "
                   "return priority + 1; },",)),
)
# Step G35: Friend Guard (the target's partner weakens every hit on it: a ModifyDamage modifier, 3072 of the chain) and Rain Dish (a
# sixteenth of the HP in rain, eachEvent('Weather')) are engine rows (ENGINE_ROWS) read by id; the pinned texts they hard-code are
# checked here, the Champions mod overriding neither. Mold Breaker (Friend Guard is breakable) is not marked.
G35_ABILITY_FACTS = (
    ('friendguard', ("onAnyModifyDamage(damage, source, target, move) { if (target !== this.effectState.target && "
                     "target.isAlly(this.effectState.target)) { this.debug('Friend Guard weaken'); return this.chainModify(0.75); } },",
                     'flags: { breakable: 1 },')),
    ('raindish', ("onWeather(target, source, effect) { if (target.effectiveWeather() !== effect.id) return; "
                  "if (effect.id === 'raindance' || effect.id === 'primordialsea') { this.heal(target.baseMaxhp / 16); } },",)),
)
# Mega batch 2: Aura Guard (a contact hit on its holder: a ModifyDamage modifier, 2048 of the chain; the Mega ability of
# Lucario-Mega-Z) is an engine row read by id; the pinned text it hard-codes is checked here, the Champions mod not overriding it.
# Mold Breaker (Aura Guard is breakable) is not marked.
MEGA2_ABILITY_FACTS = (
    ('auraguard', ("onSourceModifyDamage(damage, source, target, move) { if (move.flags['contact']) return this.chainModify(0.5); },",
                   'flags: { breakable: 1 },')),
)
# Step G39 (thirteen abilities, four moves): the abilities Hyper Cutter, Scrappy, Infiltrator, Queenly Majesty, Damp, Sturdy,
# Snow Cloak, Sand Veil, Static, Justified, Limber, Solar Power and Regenerator are engine rows (ENGINE_ROWS) that the turn code
# reads by id; the pinned callbacks they hard-code are checked here, whole, whitespace aside (Regenerator's is the Champions mod's
# own entry: G32_ENTRY_FACTS-style, champ=True). Mold Breaker, which Hyper Cutter, Queenly Majesty, Damp, Sturdy, Snow Cloak, Sand
# Veil and Limber are breakable against, is not marked. Damp is inert: its callbacks stop Explosion, Mind Blown, Misty Explosion,
# Self-Destruct and Aftermath, none of which is marked (tests/test_pool_g39.c pins it, and Sturdy's OHKO immunity likewise).
G39_ABILITY_FACTS = (
    ('hypercutter', ("onTryBoost(boost, target, source, effect) { if (source && target === source) return; "
                     "if (boost.atk && boost.atk < 0) { delete boost.atk; if (!(effect as ActiveMove).secondaries) { "
                     "this.add('-fail', target, 'unboost', 'atk', '[from] ability: Hyper Cutter', `[of] ${target}`); } } },",
                     'flags: { breakable: 1 },')),
    ('scrappy', ("onModifyMovePriority: -5,",
                 "onModifyMove(move) { if (!move.ignoreImmunity) move.ignoreImmunity = {}; if (move.ignoreImmunity !== true) { "
                 "move.ignoreImmunity['Fighting'] = true; move.ignoreImmunity['Normal'] = true; } },",
                 "onTryBoost(boost, target, source, effect) { if (effect.name === 'Intimidate' && boost.atk) { delete boost.atk; "
                 "this.add('-fail', target, 'unboost', 'atk', '[from] ability: Scrappy', `[of] ${target}`); } },")),
    ('infiltrator', ("onModifyMove(move) { move.infiltrates = true; },",)),
    ('queenlymajesty', ("onFoeTryMove(target, source, move) { const targetAllExceptions = ['perishsong', 'flowershield', 'rototiller']; "
                        "if (move.target === 'foeSide' || (move.target === 'all' && !targetAllExceptions.includes(move.id))) { return; } "
                        "const dazzlingHolder = this.effectState.target; if ((source.isAlly(dazzlingHolder) || move.target === 'all') && "
                        "move.priority > 0.1) { this.attrLastMove('[still]'); this.add('cant', dazzlingHolder, 'ability: Queenly Majesty', "
                        "move, `[of] ${target}`); return false; } },",
                        'flags: { breakable: 1 },')),
    ('damp', ("onAnyTryMove(target, source, effect) { if (['explosion', 'mindblown', 'mistyexplosion', 'selfdestruct']"
              ".includes(effect.id)) { this.attrLastMove('[still]'); this.add('cant', this.effectState.target, 'ability: Damp', "
              "effect, `[of] ${target}`); return false; } },",
              "onAnyDamage(damage, target, source, effect) { if (effect && effect.name === 'Aftermath') { return false; } },")),
    ('sturdy', ("onTryHit(pokemon, target, move) { if (move.ohko) { this.add('-immune', pokemon, '[from] ability: Sturdy'); return null; } },",
                "onDamagePriority: -30,",
                "onDamage(damage, target, source, effect) { if (target.hp === target.maxhp && damage >= target.hp && effect && "
                "effect.effectType === 'Move') { this.add('-ability', target, 'Sturdy'); return target.hp - 1; } },")),
    ('snowcloak', ("onImmunity(type, pokemon) { if (type === 'hail') return false; },", 'onModifyAccuracyPriority: -1,',
                   "onModifyAccuracy(accuracy) { if (typeof accuracy !== 'number') return; if (this.field.isWeather(['hail', 'snowscape'])) { "
                   "this.debug('Snow Cloak - decreasing accuracy'); return this.chainModify([3277, 4096]); } },")),
    ('sandveil', ("onImmunity(type, pokemon) { if (type === 'sandstorm') return false; },", 'onModifyAccuracyPriority: -1,',
                  "onModifyAccuracy(accuracy) { if (typeof accuracy !== 'number') return; if (this.field.isWeather('sandstorm')) { "
                  "this.debug('Sand Veil - decreasing accuracy'); return this.chainModify([3277, 4096]); } },")),
    ('static', ("onDamagingHit(damage, target, source, move) { if (this.checkMoveMakesContact(move, source, target)) { "
                "if (this.randomChance(3, 10)) { source.trySetStatus('par', target); } } },",)),
    ('justified', ("onDamagingHit(damage, target, source, move) { if (move.type === 'Dark') { this.boost({ atk: 1 }); } },",)),
    ('limber', ("onUpdate(pokemon) { if (pokemon.status === 'par') { this.add('-activate', pokemon, 'ability: Limber'); "
                "pokemon.cureStatus(); } },",
                "onSetStatus(status, target, source, effect) { if (status.id !== 'par') return; if ((effect as Move)?.status) { "
                "this.add('-immune', target, '[from] ability: Limber'); } return false; },")),
    ('solarpower', ("onModifySpAPriority: 5,",
                    "onModifySpA(spa, pokemon) { if (['sunnyday', 'desolateland'].includes(pokemon.effectiveWeather())) { "
                    "return this.chainModify(1.5); } },",
                    "onWeather(target, source, effect) { if (target.effectiveWeather() !== effect.id) return; "
                    "if (effect.id === 'sunnyday' || effect.id === 'desolateland') { this.damage(target.baseMaxhp / 8, target, target); } },")),
)
# Step G41: Shadow Tag (the Mega ability of Gengar) is an engine row read by id: a foe's switch is refused at the TURN boundary
# (src/combat/turn.c dfi_switch_trapped, read by the request builder), no event and no state. The Champions mod overrides it
# nowhere; Shed Shell and Run Away, which free their holders (the mod's runaway), are not marked, so they never meet it.
G41_ABILITY_FACTS = (
    ('shadowtag', ("onFoeTrapPokemon(pokemon) { if (!pokemon.hasAbility('shadowtag') && "
                   "pokemon.isAdjacent(this.effectState.target)) { pokemon.tryTrap(true); } },",
                   "onFoeMaybeTrapPokemon(pokemon, source) { if (!source) source = this.effectState.target; "
                   "if (!source || !pokemon.isAdjacent(source)) return; if (!pokemon.hasAbility('shadowtag')) { "
                   "pokemon.maybeTrapped = true; } },",
                   'flags: {},')),
)
# Step G53: Pressure is an engine row read by id (dfi_pressure_extra, src/combat/turn.c). Its onStart is the announcement at
# switch-in (as Unnerve's); its onDeductPP is the extra PP that a foe's move costs (useMoveInner, sim/battle-actions.ts:473-484).
# The move flag mustpressure is the engine column dfi_pool_move_flags3 (DFI_MOVE_FLAG3_MUST_PRESSURE); the public static flag
# DUOFORGE_MOVE_STATIC_FLAG_MUST_PRESSURE gives it out (decision 0020: no engine reader). The Champions mod has no entry.
G53_ABILITY_FACTS = (
    ('pressure', ("onStart(pokemon) { this.add('-ability', pokemon, 'Pressure'); },",
                  "onDeductPP(target, source) { if (target.isAlly(source)) return; return 1; },",
                  'flags: {},')),
)
# Step G45 (six abilities of the simple kind): Steadfast, Moxie, Weak Armor, Telepathy, Volt Absorb and Punk Rock
# are engine rows (ENGINE_ROWS) that the turn code reads by id; the pinned callbacks they hard-code are checked here, whole,
# whitespace aside. The Champions mod overrides none of them (check_g34_facts). Mold Breaker, Teravolt and Turboblaze are not
# marked, and Mycelium Might is not in the pool, so no marked ability ignores the `breakable` flag of Telepathy, Volt Absorb or
# Punk Rock (tests/abilities/test_simple_ability_rows.c pins the refusals).
G45_ABILITY_FACTS = (
    ('steadfast', ("onFlinch(pokemon) { this.boost({ spe: 1 }); },", 'flags: {},')),
    ('weakarmor', ("onDamagingHit(damage, target, source, move) { if (move.category === 'Physical') { "
                   "this.boost({ def: -1, spe: 2 }, target, target); } },", 'flags: {},')),
    ('telepathy', ("onTryHit(target, source, move) { if (target !== source && target.isAlly(source) && move.category !== 'Status') { "
                   "this.add('-activate', target, 'ability: Telepathy'); return null; } },", 'flags: { breakable: 1 },')),
    ('voltabsorb', ("onTryHit(target, source, move) { if (target !== source && move.type === 'Electric') { "
                    "if (!this.heal(target.baseMaxhp / 4)) { this.add('-immune', target, '[from] ability: Volt Absorb'); } return null; } },",
                    'flags: { breakable: 1 },')),
    ('punkrock', ('onBasePowerPriority: 7,',
                  "onBasePower(basePower, attacker, defender, move) { if (move.flags['sound']) { this.debug('Punk Rock boost'); "
                  "return this.chainModify([5325, 4096]); } },",
                  "onSourceModifyDamage(damage, source, target, move) { if (move.flags['sound']) { this.debug('Punk Rock weaken'); "
                  "return this.chainModify(0.5); } },",
                  'flags: { breakable: 1 },')),
    ('moxie', ("onSourceAfterFaint(length, target, source, effect) { if (effect && effect.effectType === 'Move') { "
                   "this.boost({ atk: length }, source); } },", 'flags: {},')),
)
# Step G47, the status and volatile cures: Synchronize and Oblivious (abilities) and Lum Berry and Mental Herb (items) are engine
# rows read by id (src/combat/turn.c dfi_synchronize, dfi_lum_berry, dfi_mental_herb; Oblivious in dfi_try_status' TryHit chain,
# the Intimidate guard and dfi_trace). Their texts, whitespace aside, are the facts the engine hard-codes; the Champions mod
# has no entry for any of the four (check_g34_facts). The Champions Encore override (moves.ts:330) is a move, checked by hand.
# Each fact is a balanced statement or block of the pinned entry (the entry's own parser counts the braces), without the
# comment lines between the statements that the pin has.
G47_ABILITY_FACTS = (
    ('synchronize', ('if (!source || source === target) return;',
                     "if (effect && effect.id === 'toxicspikes') return;",
                     "if (status.id === 'slp' || status.id === 'frz') return;",
                     "this.add('-activate', target, 'ability: Synchronize');",
                     "source.trySetStatus(status, target, { status: status.id, id: 'synchronize' } as Effect);",
                     'flags: {},')),
    ('oblivious', ("if (pokemon.volatiles['attract']) { this.add('-activate', pokemon, 'ability: Oblivious'); "
                   "pokemon.removeVolatile('attract'); this.add('-end', pokemon, 'move: Attract', '[from] ability: Oblivious'); }",
                   "pokemon.removeVolatile('taunt');",
                   "if (type === 'attract') return false;",
                   "if (move.id === 'attract' || move.id === 'captivate' || move.id === 'taunt') { "
                   "this.add('-immune', pokemon, '[from] ability: Oblivious'); return null; }",
                   "if (effect.name === 'Intimidate' && boost.atk) { delete boost.atk; "
                   "this.add('-fail', target, 'unboost', 'atk', '[from] ability: Oblivious', `[of] ${target}`); }",
                   'flags: { breakable: 1 },')),
)
# Step G71 (decision 0034, decision 0015 5bn): Cute Charm is an engine row (ENGINE_ROWS, once the draws of Cute Charm and Attract are
# wired). Its pinned callback, whole: the contact test, the 3/10 roll and the infatuation of the attacker by the holder
# (data/abilities.ts:798-810). The Attract volatile's facts (data/moves.ts:706-761) and the Oblivious and Mental Herb halves are the
# G47 facts above. The Champions mod has no entry for Cute Charm (check_g34_facts).
G71_ABILITY_FACTS = (
    ('cutecharm', ('onDamagingHit(damage, target, source, move) {',
                   'if (this.checkMoveMakesContact(move, source, target)) {',
                   'if (this.randomChance(3, 10)) {',
                   "source.addVolatile('attract', this.effectState.target);",
                   '}',
                   '}',
                   '},',
                   'flags: {},')),
)
# Step G59, six Mega abilities: Mega Launcher (Blastoise-Mega), Huge Power (Mawile-Mega), Thick Fat (Venusaur-Mega), Fire Mane
# (Pyroar-Mega), Spicy Spray (Scovillain-Mega) and Mega Sol (Meganium-Mega) are engine rows (ENGINE_ROWS) that the turn code reads
# by id (src/combat/turn.c: the BasePower chain at priority 19, the ModifyAtk and ModifySpA chain, the weather modifier of the
# holder's moves, dfi_spicy_spray, dfi_mega_sol_refused). Their pinned callbacks, whole and whitespace-collapsed, are the facts the
# engine hard-codes. The Champions mod has no entry for Mega Launcher, Huge Power or Thick Fat; Fire Mane, Spicy Spray and Mega
# Sol have one that only inherits and un-marks the Future tag (`inherit: true`, `isNonstandard: null`), which
# G59_INHERIT_ONLY allows and nothing else. Mega Sol's effectiveWeather side (sim/pokemon.ts) is read by the refusal of
# dfi_mega_sol_refused, checked by check_g59_pokemon.
G59_ABILITY_FACTS = (
    ('megalauncher', ('onBasePowerPriority: 19,',
                      "onBasePower(basePower, attacker, defender, move) { if (move.flags['pulse']) { return this.chainModify(1.5); } },",
                      'flags: {},')),
    ('hugepower', ('onModifyAtkPriority: 5,', 'onModifyAtk(atk) { return this.chainModify(2); },', 'flags: {},')),
    ('thickfat', ('onSourceModifyAtkPriority: 6,',
                  "onSourceModifyAtk(atk, attacker, defender, move) { if (move.type === 'Ice' || move.type === 'Fire') { "
                  "this.debug('Thick Fat weaken'); return this.chainModify(0.5); } },",
                  'onSourceModifySpAPriority: 5,',
                  "onSourceModifySpA(atk, attacker, defender, move) { if (move.type === 'Ice' || move.type === 'Fire') { "
                  "this.debug('Thick Fat weaken'); return this.chainModify(0.5); } },",
                  'flags: { breakable: 1 },')),
    ('firemane', ('onModifyAtkPriority: 5,',
                  "onModifyAtk(atk, attacker, defender, move) { if (move.type === 'Fire') { this.debug('Fire Mane boost'); "
                  "return this.chainModify(1.5); } },",
                  'onModifySpAPriority: 5,',
                  "onModifySpA(atk, attacker, defender, move) { if (move.type === 'Fire') { this.debug('Fire Mane boost'); "
                  "return this.chainModify(1.5); } },",
                  'flags: {},')),
    ('spicyspray', ("onDamagingHit(damage, target, source, move) { source.trySetStatus('brn', target); },", 'flags: {},')),
    ('megasol', ('onWeatherModifyDamagePriority: 1,',
                 "(this.dex.conditions.getByID('sunnyday' as ID) as any).onWeatherModifyDamage .call(this, damage, attacker, defender, move);",
                 'return damage; // fast exit from event',
                 'flags: {},')),
)

# Step G79 (decision 0015 5br): Cloud Nine (data/abilities.ts:543-562) suppresses the weather while a holder stands, its
# onSwitchIn prints -ability and its onStart and onEnd only set the ending flag and run WeatherChange (no line). It is an engine
# row (ENGINE_ROWS): the turn code reads it by id (dfi_weather_suppressed) and prints its switch-in line itself.
G79_ABILITY_FACTS = (
    ('cloudnine', ("this.add('-ability', pokemon, 'Cloud Nine');",
                   'pokemon.abilityState.ending = false;',
                   "this.eachEvent('WeatherChange', this.effect);",
                   'pokemon.abilityState.ending = true;',
                   'suppressWeather: true,',
                   'flags: {},')),
)

# Step G51 (Pidgeotite: Keen Eye and Big Pecks, the base abilities of Pidgeot): both are engine rows (ENGINE_ROWS) that dfi_boost
# (src/combat/turn.c) reads by id, Hyper Cutter's shape: the pinned TryBoost of the target itself deletes one drop that another
# Pokemon causes (accuracy for Keen Eye, Defense for Big Pecks), with the line unless the move's secondary. Keen Eye's
# onModifyMove (move.ignoreEvasion for the holder's own moves) is read by dfi_accuracy_check. Both are breakable, and Mold Breaker is
# not marked. The Champions mod overrides neither entry.
G51_ABILITY_FACTS = (
    ('keeneye', ("onTryBoost(boost, target, source, effect) { if (source && target === source) return; "
                 "if (boost.accuracy && boost.accuracy < 0) { delete boost.accuracy; if (!(effect as ActiveMove).secondaries) { "
                 "this.add('-fail', target, 'unboost', 'accuracy', '[from] ability: Keen Eye', `[of] ${target}`); } } },",
                 "onModifyMove(move) { move.ignoreEvasion = true; },",
                 'flags: { breakable: 1 },')),
    ('bigpecks', ("onTryBoost(boost, target, source, effect) { if (source && target === source) return; "
                  "if (boost.def && boost.def < 0) { delete boost.def; if (!(effect as ActiveMove).secondaries && "
                  "effect.id !== 'octolock') { this.add('-fail', target, 'unboost', 'def', '[from] ability: Big Pecks', "
                  "`[of] ${target}`); } } },",
                  'flags: { breakable: 1 },')),
)
# Step G67 (decision 0015 entry 5bl): Magic Guard and Air Balloon are engine rows read by id. Magic Guard's callback blocks a
# damage whose effect is not a Move (the Damage event, which a directDamage never reaches: the turn code classes every
# indirect damage, src/combat/turn.c dfi_deal); Air Balloon's three callbacks are the ground immunity (isGrounded, sim/pokemon.ts),
# the announcement at switch-in (ITEM_SHOWN), the pop on a damaging hit and the pop on a substitute hit (AfterSubDamage).
G67_ABILITY_FACTS = (
    ('magicguard', ("onDamage(damage, target, source, effect) { if (effect.effectType !== 'Move') { "
                    "if (effect.effectType === 'Ability') this.add('-activate', source, 'ability: ' + effect.name); "
                    "return false; } },",
                    'flags: {},')),
)
# Step G83 (decision 0015 entry 5bt): Bulletproof, Rivalry, Leaf Guard and Iron Ball are engine rows read by id. Bulletproof's TryHit
# stops a bullet move at its holder (dfi_try_hit_abilities); Rivalry is the base power chain (dfi_base_power, priority 24); Leaf
# Guard refuses the statuses and the Yawn volatile in sun (dfi_try_status, dfi_yawn); Iron Ball is grounded (isGrounded, which
# the Ground immunity reads) and halves the Speed (the item chain of dfi_speed_key). Its onEffectiveness returns 0 for the Flying
# component of a Ground move, which the chart's immunity already counts as 0 in dfi_type_mod.
G83_ABILITY_FACTS = (
    ('bulletproof', ("onTryHit(pokemon, target, move) { if (move.flags['bullet']) { this.add('-immune', pokemon, '[from] ability: Bulletproof'); "
                     "return null; } },",
                     'flags: { breakable: 1 },')),
    ('rivalry', ('onBasePowerPriority: 24,',
                 "onBasePower(basePower, attacker, defender, move) { if (attacker.gender && defender.gender) { "
                 "if (attacker.gender === defender.gender) { this.debug('Rivalry boost'); return this.chainModify(1.25); } "
                 "else { this.debug('Rivalry weaken'); return this.chainModify(0.75); } } },",
                 'flags: {},')),
    ('leafguard', ("onSetStatus(status, target, source, effect) { if (['sunnyday', 'desolateland'].includes(target.effectiveWeather())) { "
                   "if ((effect as Move)?.status) { this.add('-immune', target, '[from] ability: Leaf Guard'); } return false; } },",
                   "onTryAddVolatile(status, target) { if (status.id === 'yawn' && ['sunnyday', 'desolateland'].includes(target.effectiveWeather())) { "
                   "this.add('-immune', target, '[from] ability: Leaf Guard'); return null; } },",
                   'flags: { breakable: 1 },')),
)
# Step G81 (decision 0015 entry 5bs): Frisk is an engine row read by id. Its onStart announces, for each foe in foes() order that
# holds an item, `-item|X|Item|[from] ability: Frisk|[of] Y` (no [identify]: the pin prints none). The turn code emits ITEM_SHOWN
# with the Frisk form (decision 0033), no state change.
G81_ABILITY_FACTS = (
    ('frisk', ("onStart(pokemon) { for (const target of pokemon.foes()) { if (target.item) { "
               "this.add('-item', target, target.getItem().name, '[from] ability: Frisk', `[of] ${pokemon}`); } } },",
               'flags: {},')),
)
# Step G30: the abilities that the turn code implements by id (ENGINE_ROWS), as whole callbacks of the pinned entries, whitespace
# aside; the Champions mod overrides none of them (data/mods/champions/abilities.ts). The engine reads Flame Body's 3 in 10 as
# one draw (DFI_SITE_FLAME_BODY), Clear Body's drop filter for the sources other than the holder, Hospitality's quarter heal of
# the adjacent allies at the switch-in priority -2, and Overcoat's immunity to sand and powder.
G30_ABILITY_FACTS = (
    ('flamebody', ("onDamagingHit(damage, target, source, move) { if (this.checkMoveMakesContact(move, source, target)) { "
                   "if (this.randomChance(3, 10)) { source.trySetStatus('brn', target); } } },",)),
    ('clearbody', ("onTryBoost(boost, target, source, effect) { if (source && target === source) return; "
                   "let showMsg = false; let i: BoostID; for (i in boost) { if (boost[i]! < 0) { delete boost[i]; showMsg = true; } } "
                   "if (showMsg && !(effect as ActiveMove).secondaries && effect.id !== 'octolock') { "
                   "this.add('-fail', target, 'unboost', '[from] ability: Clear Body', `[of] ${target}`); } },",)),
    ('hospitality', ("onSwitchInPriority: -2,",
                     "onStart(pokemon) { for (const ally of pokemon.adjacentAllies()) { this.heal(ally.baseMaxhp / 4, ally, pokemon); } },")),
    ('overcoat', ("onImmunity(type, pokemon) { if (type === 'sandstorm' || type === 'hail' || type === 'powder') return false; },",
                  "onTryHitPriority: 1,",
                  "onTryHit(target, source, move) { if (move.flags['powder'] && target !== source && "
                  "this.dex.getImmunity('powder', target)) { this.add('-immune', target, '[from] ability: Overcoat'); return null; } },")),
)
ABILITY_FAMILIES = ['NONE', 'ATE', 'PINCH', 'WEATHER_SETTER', 'TERRAIN_SETTER']
ABILITY_MEMBERS = {'ATE': ['aerilate', 'pixilate', 'refrigerate', 'dragonize'],
                   'PINCH': ['blaze', 'overgrow', 'torrent', 'swarm'],
                   'WEATHER_SETTER': ['drizzle', 'drought', 'sandstream', 'snowwarning'],
                   'TERRAIN_SETTER': ['grassysurge', 'psychicsurge', 'electricsurge']}
# What an ability or item entry may have and still be pure data. Anything else is a callback or a field that the
# tables do not model.
INERT_ABILITY_KEYS = {'name', 'num', 'rating', 'gen', 'isNonstandard', 'flags'}

# Abilities. "-ate": Normal moves become the type (ModifyType, priority -1) and get BasePower x4915/4096 (priority 23).
# isNonstandard is metadata: Dragonize (data/abilities.ts:1036, "Future") is an -ate member the Champions mod makes standard.
ABILITY_ATE_KEYS = {'onModifyTypePriority', 'onModifyType', 'onBasePowerPriority', 'onBasePower', 'flags', 'name',
                    'rating', 'num', 'isNonstandard'}
ATE_MODIFY_TYPE = (r"onModifyType\(move, pokemon\) \{ const noModifyType = \[ 'judgment', 'multiattack', 'naturalgift', "
                   r"'revelationdance', 'technoblast', 'terrainpulse', 'weatherball', \]; "
                   r"if \(move\.type === 'Normal' && \(!noModifyType\.includes\(move\.id\) \|\| "
                   r"this\.activeMove\?\.isMax\) && !\(move\.isZ && move\.category !== 'Status'\) && "
                   r"!\(move\.name === 'Tera Blast' && pokemon\.terastallized\)\) \{ "
                   r"move\.type = '(\w+)'; move\.typeChangerBoosted = this\.effect; \} \},")
ATE_BASE_POWER = (r"onBasePower\(basePower, pokemon, target, move\) \{ "
                  r"if \(move\.typeChangerBoosted === this\.effect\) return this\.chainModify\(\[4915, 4096\]\); \},")


def ate_type(f):
    # isNonstandard is optional: only Dragonize has it, as "Future" in the pin
    shape(f, ABILITY_ATE_KEYS if 'isNonstandard' in f else ABILITY_ATE_KEYS - {'isNonstandard'})
    field_is(f, 'onModifyTypePriority', 'onModifyTypePriority: -1,')
    field_is(f, 'onBasePowerPriority', 'onBasePowerPriority: 23,')
    field_is(f, 'flags', 'flags: {},')
    t = field_match(f, 'onModifyType', ATE_MODIFY_TYPE).group(1)
    field_match(f, 'onBasePower', ATE_BASE_POWER)
    return t


# Pinch: Atk and SpA x1.5 for a move of the type at a third of the HP or less (priority 5 for both).
ABILITY_PINCH_KEYS = {'onModifyAtkPriority', 'onModifyAtk', 'onModifySpAPriority', 'onModifySpA', 'flags', 'name',
                      'rating', 'num'}


def pinch_handler(callback, name):
    return (r"%s\(atk, attacker, defender, move\) \{ if \(move\.type === '(\w+)' && attacker\.hp <= attacker\.maxhp / 3\) "
            r"\{ this\.debug\('%s boost'\); return this\.chainModify\(1\.5\); \} \}," % (callback, re.escape(name)))


def pinch_type(f):
    shape(f, ABILITY_PINCH_KEYS)
    field_is(f, 'onModifyAtkPriority', 'onModifyAtkPriority: 5,')
    field_is(f, 'onModifySpAPriority', 'onModifySpAPriority: 5,')
    field_is(f, 'flags', 'flags: {},')
    name = scalar(f['name'][1])
    atk = field_match(f, 'onModifyAtk', pinch_handler('onModifyAtk', name)).group(1)
    spa = field_match(f, 'onModifySpA', pinch_handler('onModifySpA', name)).group(1)
    if atk != spa:
        raise NoMatch('Atk type %s, SpA type %s' % (atk, spa))
    return atk


# Weather and terrain setters: onStart sets the field condition (the weather setters with the Primal guard).
ABILITY_FIELD_KEYS = {'onStart', 'flags', 'name', 'rating', 'num'}


def weather_setter_weather(f):
    shape(f, ABILITY_FIELD_KEYS)
    field_is(f, 'flags', 'flags: {},')
    m = field_match(f, 'onStart', r"onStart\(source\) \{ (?:if \(source\.species\.id === '(\w+)' && "
                                  r"source\.item === '(\w+)'\) return; )?this\.field\.setWeather\('(\w+)'\); \},")
    species, orb, weather = m.groups()
    if weather not in WEATHER_CODES:
        raise NoMatch('weather %s has no state code' % weather)
    if (species, orb) != PRIMAL_GUARD.get(weather, (None, None)):
        raise NoMatch('the Primal guard (%s, %s) is not the one of %s' % (species, orb, weather))
    return weather


def terrain_setter_terrain(f):
    shape(f, ABILITY_FIELD_KEYS)
    field_is(f, 'flags', 'flags: {},')
    terrain = field_match(f, 'onStart', r"onStart\(source\) \{ this\.field\.setTerrain\('(\w+)'\); \},").group(1)
    if terrain not in TERRAIN_CODES:
        raise NoMatch('terrain %s has no state code' % terrain)
    return terrain


ABILITY_MATCHERS = [('ATE', lambda f, _aid: ate_type(f)), ('PINCH', lambda f, _aid: pinch_type(f)),
                    ('WEATHER_SETTER', lambda f, _aid: weather_setter_weather(f)),
                    ('TERRAIN_SETTER', lambda f, _aid: terrain_setter_terrain(f))]


def ability_param(family, fact):
    """(parameter byte, its name in C) of an ability's family column: a type, a weather or a terrain."""
    if family in ('ATE', 'PINCH'):
        return TYPES.index(fact), 'DFI_TYPE_' + fact.upper()
    if family == 'WEATHER_SETTER':
        return WEATHER_CODES[fact][1], 'DFI_FAMILY_WEATHER_' + WEATHER_CODES[fact][0]
    if family == 'TERRAIN_SETTER':
        return TERRAIN_CODES[fact][1], 'DFI_FAMILY_TERRAIN_' + TERRAIN_CODES[fact][0]
    return FAMILY_PARAM_NONE, 'DFI_FAMILY_PARAM_NONE'


# Step K2, Piercing Drill (decision 0015 5dd; data/abilities.ts:3282-3294; the Champions mod inherits it,
# data/mods/champions/abilities.ts:59-62). Its onHitProtect marks a contact move of the holder, and checkMoveBypassesProtect
# (sim/battle.ts:1300-1309) then lets the move through every protection whose check calls it (Protect, Detect, King's Shield,
# Spiky Shield, Baneful Bunker, Wide Guard, Quick Guard). The Champions modifyDamage (data/mods/champions/scripts.ts) then
# multiplies the hit by 0.25 after its ModifyDamage chain, and prints -ability and -zbroken. Piercing Drill is an engine row
# (ENGINE_ROWS) that the turn code reads by id; the texts below are the ones it hard-codes.
K2_ABILITY_FACTS = (
    ('piercingdrill', ('onHitProtect(source, target, move) {',
                       "if (move.flags['contact']) {",
                       "target.getMoveHitData(move).bypassProtect = this.effect;",
                       'return false;',
                       '}',
                       '},',
                       '// breaking protect handled in Battle#checkMoveBypassesProtect()',
                       'flags: {},')),
)


def check_g30_facts(abil_ts, champ_abil):
    """Every fact of G30_ABILITY_FACTS is in the pinned ability entry, whitespace aside, and the Champions mod has no
    entry of its own for it (an override would change what the engine reads)."""
    for aid, facts in G30_ABILITY_FACTS:
        e = abil_ts.entry(aid)
        if e is None:
            fail('ability %s not found' % aid)
        if champ_abil.entry(aid) is not None:
            fail('ability %s: the champions mod overrides the entry' % aid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('ability %s: the entry no longer has "%s"' % (aid, fact))


# Step G46: the blockers of a forced switch and Red Card (the turn code runs them by id). Suction Cups and Guard Dog return
# null from onDragOut (data/abilities.ts:4693-4698 and :1728-1732), so the drag is not made, and print -activate. Red Card:
# data/items.ts:5152-5171 (its gates, the consumption before the attacker's DragOut, and the flag it sets).
G46_ABILITY_FACTS = (
    ('suctioncups', ('onDragOutPriority: 1,',
                     "onDragOut(pokemon) { this.add('-activate', pokemon, 'ability: Suction Cups'); return null; },")),
    ('guarddog', ('onDragOutPriority: 1,',
                  "onDragOut(pokemon) { this.add('-activate', pokemon, 'ability: Guard Dog'); return null; },",
                  'onTryBoostPriority: 2,',
                  "onTryBoost(boost, target, source, effect) { if (effect.name === 'Intimidate' && boost.atk) { "
                  "delete boost.atk; this.boost({ atk: 1 }, target, target, null, false, true); } },")),
)


# Step I2a: Illusion (decision 0026) is an engine row (ENGINE_ROWS): the turn code implements its four callbacks by id and
# hard-codes these texts. The disguise is the last non-fainted member to the right (onBeforeSwitchIn, data/abilities.ts:2056-2069),
# the break is the damaging hit (onDamagingHit, which the DamagingHit event of sim/battle-actions.ts:1118-1130 runs), the end
# prints `replace` and `-end|Illusion` (onEnd), and the faint clears it (onFaint). Its flags are the notrace of Trace's rule.
I2_ABILITY_FACTS = (
    ('illusion', (
        "onBeforeSwitchIn(pokemon) { pokemon.illusion = null;",
        "for (let i = pokemon.side.pokemon.length - 1; i > pokemon.position; i--) {",
        "if (!possibleTarget.fainted) {",
        "pokemon.illusion = possibleTarget;",
        "onDamagingHit(damage, target, source, move) { if (target.illusion) { "
        "this.singleEvent('End', this.dex.abilities.get('Illusion'), target.abilityState, target, source, move); } },",
        "onEnd(pokemon) { if (pokemon.illusion && !pokemon.beingCalledBack) {",
        "this.add('replace', pokemon, details);",
        "this.add('-end', pokemon, 'Illusion');",
        "onFaint(pokemon) { pokemon.illusion = null; },",
        "flags: { failroleplay: 1, noreceiver: 1, noentrain: 1, notrace: 1, failskillswap: 1 },",
    )),
)


# Step G61, Sheer Force (an engine row read by id, data/abilities.ts:4202-4221): the pinned texts the turn code hard-codes.
# Its onModifyMove strips a move's secondaries and self effects, and sets hasSheerForce, only when the move has secondaries
# and is not hasSheerForceBoost (Electro Shot); onBasePower is x5325/4096 for either flag, at priority 21. The engine's
# predicate (turn.c dfi_sf_strips) and the generator's strip check (pool_families.js checkG61) follow these texts.
G61_ABILITY_FACTS = (
    ('sheerforce', ('onModifyMove(move, pokemon) {',
                    'if (move.secondaries && !move.hasSheerForceBoost) {',
                    'delete move.secondaries;',
                    'delete move.self;',
                    'if (move.id === \'clangoroussoulblaze\') delete move.selfBoost;',
                    'move.hasSheerForce = true;',
                    'onBasePowerPriority: 21,',
                    'if (move.hasSheerForce || move.hasSheerForceBoost) return this.chainModify([5325, 4096]);',
                    'flags: {},')),
)
# Step G57: Magic Bounce is an engine row read by id (src/combat/turn.c, the bounced path of dfi_run_move_body). The turn code
# hard-codes the pinned callbacks it reproduces: the TryHit priority, the single-target bounce and the side bounce of a
# foeSide move (data/abilities.ts:2437-2464). Its flags are breakable only: a Mold Breaker attacker would suppress it, and no
# Mold Breaker move is marked. The Champions mod overrides the entry nowhere.
G57_ABILITY_FACTS = (
    ('magicbounce', ('onTryHitPriority: 1,',
                     "onTryHit(target, source, move) { if (target === source || move.hasBounced || !move.flags['reflectable'] || "
                     "target.isSemiInvulnerable()) { return; } const newMove = this.dex.getActiveMove(move.id); "
                     "newMove.hasBounced = true; newMove.pranksterBoosted = false; "
                     "this.actions.useMove(newMove, target, { target: source }); return null; },",
                     "onAllyTryHitSide(target, source, move) { if (target.isAlly(source) || move.hasBounced || "
                     "!move.flags['reflectable'] || target.isSemiInvulnerable()) { return; } const newMove = "
                     "this.dex.getActiveMove(move.id); newMove.hasBounced = true; newMove.pranksterBoosted = false; "
                     "this.actions.useMove(newMove, this.effectState.target, { target: source });",
                     'move.hasBounced = true; // only bounce once in free-for-all battles',
                     'return null; },',
                     'flags: { breakable: 1 },')),
)


# Step G63 (simple Mega abilities): Sand Force, Shell Armor, Filter and Stalwart are engine rows (ENGINE_ROWS) that the turn code reads
# by id. The pinned callbacks they hard-code are checked here, whole: Sand Force's BasePower (priority 21, Rock, Ground and Steel in
# sandstorm, chainModify 5325/4096) and its sandstorm immunity (data/abilities.ts:3956-3973); Shell Armor's onCriticalHit false
# (4222-4228); Filter's damage step, the same as Solid Rock's (1283-1294); Stalwart's tracksTarget (4503-4513). Sand Force, Shell
# Armor and Filter are breakable (Mold Breaker is not marked); Stalwart is not. No entry is overridden by the Champions mod.
G63_ABILITY_FACTS = (
    ('sandforce', ('onBasePowerPriority: 21,',
                   "onBasePower(basePower, attacker, defender, move) { if (this.field.isWeather('sandstorm')) { "
                   "if (move.type === 'Rock' || move.type === 'Ground' || move.type === 'Steel') { "
                   "this.debug('Sand Force boost'); return this.chainModify([5325, 4096]); } } },",
                   "onImmunity(type, pokemon) { if (type === 'sandstorm') return false; },")),
    ('shellarmor', ('onCriticalHit: false,', 'flags: { breakable: 1 },')),
    ('filter', ("onSourceModifyDamage(damage, source, target, move) { if (target.getMoveHitData(move).typeMod > 0) { "
                "this.debug('Filter neutralize'); return this.chainModify(0.75); } },",
                'flags: { breakable: 1 },')),
    ('stalwart', ('onModifyMovePriority: 1,',
                  'onModifyMove(move) {',
                  '// most of the implementation is in Battle#getTarget',
                  "move.tracksTarget = move.target !== 'scripted';",
                  '},')),
)


# Issue #620 (decision 0015 entry 5dx, decision 0041): Skill Swap fails when either ability has the failskillswap flag
# (sim/battle.ts:1316). The turn code reads the flag by id (abilities/skill_swap.h dfi_fails_skillswap, one DFI_ABILITY_* per name below),
# so the pool's abilities with the flag are exactly these; check_failskillswap reads the flag of every pool row from the pin
# (the Champions entry's own flags where it has them, else the inherited base entry's) and fails on any other set. It also
# reads the DFI_ABILITY_* names of the body of dfi_fails_skillswap in FAILSKILLSWAP_SOURCE and fails when they are not this
# list (the path moves with the function when the ability code leaves turn.c).
FAILSKILLSWAP_ABILITIES = ('disguise', 'hungerswitch', 'illusion', 'stancechange', 'zerotohero')
FAILSKILLSWAP_SOURCE = os.path.join('src', 'combat', 'abilities', 'skill_swap.h')


def failskillswap_c_ids(c_text):
    """The ability ids that the body of dfi_fails_skillswap names (DFI_ABILITY_HUNGERSWITCH -> 'hungerswitch'), in order."""
    text = c_text.replace('\r\n', '\n')
    a = text.find('\nstatic bool dfi_fails_skillswap(')
    if a < 0:
        fail('%s: no definition of dfi_fails_skillswap' % FAILSKILLSWAP_SOURCE)
    b = text.find('\n}\n', a)
    if b < 0:
        fail('%s: the body of dfi_fails_skillswap is not closed' % FAILSKILLSWAP_SOURCE)
    body = text[text.index('{', a):b]
    ids = [name.lower() for name in re.findall(r'\bDFI_ABILITY_([A-Z0-9_]+)\b', body)]
    if not ids:
        fail('%s: dfi_fails_skillswap names no DFI_ABILITY_*' % FAILSKILLSWAP_SOURCE)
    return [i.replace('_', '') for i in ids]


def check_i2_facts(abil_ts, champ_abil):
    """Step I2 (decision 0026): the Illusion texts that the turn code hard-codes (I2_ABILITY_FACTS) are in the pinned entry,
    whitespace aside, and the Champions mod has no entry of its own for it (an override would change what the engine reads)."""
    for rid, facts in I2_ABILITY_FACTS:
        e = abil_ts.entry(rid)
        if e is None:
            fail('ability %s not found' % rid)
        if champ_abil.entry(rid) is not None:
            fail('ability %s: the champions mod overrides the entry' % rid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('ability %s: the entry no longer has "%s"' % (rid, fact))


# Step G65 (simple modifier abilities): Unaware, Marvel Scale, Water Bubble, Reckless and Super Luck are engine rows (ENGINE_ROWS)
# that the turn code reads by id. The pinned callbacks they hard-code are checked here, whole: Unaware's onAnyModifyBoost (the
# zeroed stages of the two sides, data/abilities.ts:5214-5234); Marvel Scale's onModifyDef (priority 6, x1.5 with a status,
# 2534-2545); Water Bubble's Fire halves, Water doubles, the burn refusal and its cure (5377-5417); Reckless's recoil modifier
# (priority 23, 3799-3811); Super Luck's ratio (4703-4711). None is overridden by the Champions mod; all but Reckless and Super
# Luck are breakable and Mold Breaker is not marked.
G65_ABILITY_FACTS = (
    ('unaware', ('onAnyModifyBoost(boosts, pokemon) {',
                 'if (unawareUser === pokemon) return;',
                 'if (unawareUser === this.activePokemon && pokemon === this.activeTarget) {',
                 "boosts['def'] = 0;",
                 "boosts['spd'] = 0;",
                 "boosts['evasion'] = 0;",
                 '}',
                 'if (pokemon === this.activePokemon && unawareUser === this.activeTarget) {',
                 "boosts['atk'] = 0;",
                 "boosts['def'] = 0;",
                 "boosts['spa'] = 0;",
                 "boosts['accuracy'] = 0;",
                 '}',
                 '},',
                 'flags: { breakable: 1 },')),
    ('marvelscale', ('onModifyDefPriority: 6,',
                     'onModifyDef(def, pokemon) {',
                     'if (pokemon.status) {',
                     'return this.chainModify(1.5);',
                     '}',
                     '},',
                     'flags: { breakable: 1 },')),
    ('waterbubble', ('onSourceModifyAtkPriority: 5,',
                     'onSourceModifyAtk(atk, attacker, defender, move) {',
                     "if (move.type === 'Fire') {",
                     'return this.chainModify(0.5);',
                     '}',
                     '},',
                     'onSourceModifySpAPriority: 5,',
                     'onSourceModifySpA(atk, attacker, defender, move) {',
                     "if (move.type === 'Fire') {",
                     'return this.chainModify(0.5);',
                     '}',
                     '},',
                     'onModifyAtk(atk, attacker, defender, move) {',
                     "if (move.type === 'Water') {",
                     'return this.chainModify(2);',
                     '}',
                     '},',
                     'onUpdate(pokemon) {',
                     "if (pokemon.status === 'brn') {",
                     "this.add('-activate', pokemon, 'ability: Water Bubble');",
                     'pokemon.cureStatus();',
                     '}',
                     '},',
                     'onSetStatus(status, target, source, effect) {',
                     "if (status.id !== 'brn') return;",
                     'if ((effect as Move)?.status) {',
                     "this.add('-immune', target, '[from] ability: Water Bubble');",
                     '}',
                     'return false;',
                     '},',
                     'flags: { breakable: 1 },')),
    ('reckless', ('onBasePowerPriority: 23,',
                  'onBasePower(basePower, attacker, defender, move) {',
                  'if (move.recoil || move.hasCrashDamage) {',
                  "this.debug('Reckless boost');",
                  'return this.chainModify([4915, 4096]);',
                  '}',
                  '},',
                  'flags: {},')),
    ('superluck', ('onModifyCritRatio(critRatio) {',
                   'return critRatio + 1;',
                   '},',
                   'flags: {},')),
)


# Step G73 (Moody): an engine row (ENGINE_ROWS) that the turn code runs by id (dfi_moody, src/combat/turn.c). Its onResidual is
# checked whole, whitespace aside: the order (28, sub-order 2, as Speed Boost's), the stat loops over pokemon.boosts with the
# accuracy and evasion skips and the +6 and -6 tests, the two draws of this.sample, the one boost of {raised: 2, lowered: -1}
# (data/abilities.ts:2701-2734). No Champions override (check_g34_facts), and no breakable flag: Mold Breaker does not reach it.
G73_ABILITY_FACTS = (
    ('moody', ('onResidualOrder: 28,',
               'onResidualSubOrder: 2,',
               'onResidual(pokemon) {',
               'let stats: BoostID[] = [];',
               'const boost: SparseBoostsTable = {};',
               'for (statPlus in pokemon.boosts) {',
               "if (statPlus === 'accuracy' || statPlus === 'evasion') continue;",
               'if (pokemon.boosts[statPlus] < 6) {',
               'stats.push(statPlus);',
               '}',
               '}',
               'let randomStat: BoostID | undefined = stats.length ? this.sample(stats) : undefined;',
               'if (randomStat) boost[randomStat] = 2;',
               'stats = [];',
               'for (statMinus in pokemon.boosts) {',
               "if (statMinus === 'accuracy' || statMinus === 'evasion') continue;",
               'if (pokemon.boosts[statMinus] > -6 && statMinus !== randomStat) {',
               'stats.push(statMinus);',
               '}',
               '}',
               'randomStat = stats.length ? this.sample(stats) : undefined;',
               'if (randomStat) boost[randomStat] = -1;',
               'this.boost(boost, pokemon, pokemon);',
               '},',
               'flags: {},',
               'name: "Moody",')),
)


# Step G75 (cheap set): Pure Power (x2 Attack, the Huge Power callback text, data/abilities.ts:3608-3617) and Battle Armor (no
# critical hit against the holder, the Shell Armor text, :355-361) are engine rows (ENGINE_ROWS) that the turn code reads by id;
# Scope Lens (+1 to the holder's critical ratio, data/items.ts:5554-5565) is an engine row of the items. None is overridden by
# the Champions mod, and Mold Breaker is not marked, so no breakable flag has an interaction.
G75_ABILITY_FACTS = (
    ('purepower', ('onModifyAtkPriority: 5,',
                   'onModifyAtk(atk) {',
                   'return this.chainModify(2);',
                   '},',
                   'flags: {},')),
    ('battlearmor', ('onCriticalHit: false,',
                     'flags: { breakable: 1 },')),
)


# Step G77 (crit package): Magma Armor, Anger Point and Sniper are engine rows (ENGINE_ROWS) that the turn code reads by id, and
# Leek (an item row) is read by the crit ratio. The pinned callbacks they hard-code are checked here, whole: Anger Point's onHit
# (data/abilities.ts:131-142; the boost of +12 is set by the line -setboost, sim/battle.ts:2050-2053); Magma Armor's onImmunity
# and onUpdate (2501-2515); Sniper's onModifyDamage (4358-4369); Leek's onModifyCritRatio and itemUser (items.ts:3322-3337).
# None is overridden by the Champions mod; Leek inherits (G77_INHERIT_ONLY); Magma Armor is breakable, Mold Breaker is not marked.
G77_ABILITY_FACTS = (
    ('angerpoint', ('onHit(target, source, move) {',
                    'if (!target.hp) return;',
                    "if (move?.effectType === 'Move' && target.getMoveHitData(move).crit) {",
                    'this.boost({ atk: 12 }, target, target);',
                    '}',
                    '},',
                    'flags: {},')),
    ('magmaarmor', ('onUpdate(pokemon) {',
                    "if (pokemon.status === 'frz') {",
                    "this.add('-activate', pokemon, 'ability: Magma Armor');",
                    'pokemon.cureStatus();',
                    '}',
                    '},',
                    'onImmunity(type, pokemon) {',
                    "if (type === 'frz') return false;",
                    '},',
                    'flags: { breakable: 1 },')),
    ('sniper', ('onModifyDamage(damage, source, target, move) {',
                'if (target.getMoveHitData(move).crit) {',
                "this.debug('Sniper boost');",
                'return this.chainModify(1.5);',
                '}',
                '},',
                'flags: {},')),
)


def check_g57_facts(abil_ts, champ_abil):
    """Step G57: the texts of Magic Bounce that the engine reproduces (G57_ABILITY_FACTS) are in the pinned entry, whitespace
    aside, and the Champions mod has no entry of its own for it."""
    for rid, facts in G57_ABILITY_FACTS:
        e = abil_ts.entry(rid)
        if e is None:
            fail('ability %s not found' % rid)
        if champ_abil.entry(rid) is not None:
            fail('ability %s: the champions mod overrides the entry' % rid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('ability %s: the entry no longer has "%s"' % (rid, fact))


# Step G69, Symbiosis (data/abilities.ts:4837-4856, onAllyAfterUseItem): the pinned texts that dfi_symbiosis (src/combat/turn.c)
# hard-codes: the switch-flag return, the holder's takeItem and its TakeItem check with the user as the second argument, setItem
# on the user, the holder's item cleared, and the one line `-activate|holder|ability: Symbiosis|Item|[of] user` (no item line).
# The Champions mod has no entry of its own (checked by check_g34_facts for every G-step ability).
G69_ABILITY_FACTS = (
    ('symbiosis', ('onAllyAfterUseItem(item, pokemon) { if (pokemon.switchFlag) return; '
                   'const source = this.effectState.target; const myItem = source.takeItem(); if (!myItem) return; '
                   "if ( !this.singleEvent('TakeItem', myItem, source.itemState, pokemon, source, this.effect, myItem) || "
                   '!pokemon.setItem(myItem) ) { source.item = myItem.id; return; } '
                   "this.add('-activate', source, 'ability: Symbiosis', myItem, `[of] ${pokemon}`); },",
                   'flags: {},')),
)


def check_g37_facts(abil_ts, champ_abil):
    """Step G37: the text of Toxic Debris that the engine hard-codes (G37_ABILITY_FACTS) is in the pinned entry, whitespace aside, and
    the Champions mod has no entry of its own for it."""
    for rid, facts in G37_ABILITY_FACTS:
        e = abil_ts.entry(rid)
        if e is None:
            fail('ability %s not found' % rid)
        if champ_abil.entry(rid) is not None:
            fail('ability %s: the champions mod overrides the entry' % rid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('ability %s: the entry no longer has "%s"' % (rid, fact))


# A2a (Champions-100 batch A2, decision 0015 entry 5dy): fourteen abilities with one clause each at an existing hook, engine rows
# (ENGINE_ROWS) that the turn code reads by id. Their pinned callbacks are demanded whole, whitespace aside, and the Champions mod
# has no entry of its own for any of them except Natural Cure (A2A_CHAMPIONS_FACTS). The engine reads: Illuminate as Keen Eye
# (dfi_boost, dfi_accuracy_check), White Smoke as Clear Body (dfi_boost), Water Absorb and Earth Eater as Volt Absorb and Motor
# Drive as Lightning Rod without the redirect (dfi_try_hit_abilities), Ice Body as Rain Dish under snow (dfi_weather_heal),
# Surge Surfer and Quick Feet in dfi_speed_key (with par's Quick Feet test, A2A_OTHER_FACTS), Corrosion in dfi_try_status
# (setStatus's source test, A2A_OTHER_FACTS), Purifying Salt in dfi_try_status, dfi_yawn and the attack chain, Gooey and Poison
# Point at DamagingHit (Poison Point's draw is site 26), Tangled Feet in the accuracy chain, Natural Cure at the switch-out
# (combat/flow/switch.h). Mold Breaker, the one pool ability that ignores the breakable flag, is not marked.
A2A_ABILITY_FACTS = (
    ('illuminate', ("onTryBoost(boost, target, source, effect) { if (source && target === source) return; "
                    "if (boost.accuracy && boost.accuracy < 0) { delete boost.accuracy; if (!(effect as ActiveMove).secondaries) { "
                    "this.add('-fail', target, 'unboost', 'accuracy', '[from] ability: Illuminate', `[of] ${target}`); } } },",
                    "onModifyMove(move) { move.ignoreEvasion = true; },",
                    'flags: { breakable: 1 },')),
    ('whitesmoke', ("onTryBoost(boost, target, source, effect) { if (source && target === source) return; "
                    "let showMsg = false; let i: BoostID; for (i in boost) { if (boost[i]! < 0) { delete boost[i]; showMsg = true; } } "
                    "if (showMsg && !(effect as ActiveMove).secondaries && effect.id !== 'octolock') { "
                    "this.add('-fail', target, 'unboost', '[from] ability: White Smoke', `[of] ${target}`); } },",
                    'flags: { breakable: 1 },')),
    ('waterabsorb', ("onTryHit(target, source, move) { if (target !== source && move.type === 'Water') { "
                     "if (!this.heal(target.baseMaxhp / 4)) { this.add('-immune', target, '[from] ability: Water Absorb'); } "
                     "return null; } },",
                     'flags: { breakable: 1 },')),
    ('eartheater', ("onTryHit(target, source, move) { if (target !== source && move.type === 'Ground') { "
                    "if (!this.heal(target.baseMaxhp / 4)) { this.add('-immune', target, '[from] ability: Earth Eater'); } "
                    "return null; } },",
                    'flags: { breakable: 1 },')),
    ('motordrive', ("onTryHit(target, source, move) { if (target !== source && move.type === 'Electric') { "
                    "if (!this.boost({ spe: 1 })) { this.add('-immune', target, '[from] ability: Motor Drive'); } "
                    "return null; } },",
                    'flags: { breakable: 1 },')),
    ('icebody', ("onWeather(target, source, effect) { if (effect.id === 'hail' || effect.id === 'snowscape') { "
                 "this.heal(target.baseMaxhp / 16); } },",
                 "onImmunity(type, pokemon) { if (type === 'hail') return false; },",
                 'flags: {},')),
    ('surgesurfer', ("onModifySpe(spe) { if (this.field.isTerrain('electricterrain')) { return this.chainModify(2); } },",
                     'flags: {},')),
    ('quickfeet', ("onModifySpe(spe, pokemon) { if (pokemon.status) { return this.chainModify(1.5); } },",
                   'flags: {},')),
    ('corrosion', ('// Implemented in sim/pokemon.js:Pokemon#setStatus', 'flags: {},')),
    ('purifyingsalt', ("onSetStatus(status, target, source, effect) { if ((effect as Move)?.status) { "
                       "this.add('-immune', target, '[from] ability: Purifying Salt'); } return false; },",
                       "onTryAddVolatile(status, target) { if (status.id === 'yawn') { "
                       "this.add('-immune', target, '[from] ability: Purifying Salt'); return null; } },",
                       'onSourceModifyAtkPriority: 6,',
                       "onSourceModifyAtk(atk, attacker, defender, move) { if (move.type === 'Ghost') { "
                       "this.debug('Purifying Salt weaken'); return this.chainModify(0.5); } },",
                       'onSourceModifySpAPriority: 5,',
                       "onSourceModifySpA(spa, attacker, defender, move) { if (move.type === 'Ghost') { "
                       "this.debug('Purifying Salt weaken'); return this.chainModify(0.5); } },",
                       'flags: { breakable: 1 },')),
    ('gooey', ("onDamagingHit(damage, target, source, move) { if (this.checkMoveMakesContact(move, source, target, true)) { "
               "this.add('-ability', target, 'Gooey'); this.boost({ spe: -1 }, source, target, null, true); } },",
               'flags: {},')),
    ('poisonpoint', ("onDamagingHit(damage, target, source, move) { if (this.checkMoveMakesContact(move, source, target)) { "
                     "if (this.randomChance(3, 10)) { source.trySetStatus('psn', target); } } },",
                     'flags: {},')),
    ('tangledfeet', ('onModifyAccuracyPriority: -1,',
                     "onModifyAccuracy(accuracy, target) { if (typeof accuracy !== 'number') return; "
                     "if (target?.volatiles['confusion']) { this.debug('Tangled Feet - decreasing accuracy'); "
                     "return this.chainModify(0.5); } },",
                     'flags: { breakable: 1 },')),
)
# Natural Cure: the Champions entry replaces the base one's onCheckShow and onSwitchOut (data/mods/champions/abilities.ts:49-58).
A2A_CHAMPIONS_FACTS = (
    ('naturalcure', ('inherit: true,', 'onCheckShow: undefined, // no inherit',
                     "onSwitchOut(pokemon) { if (!pokemon.status || pokemon.status === 'fnt') return; "
                     "this.add('-curestatus', pokemon, pokemon.status, '[from] ability: Natural Cure', '[silent]'); "
                     'pokemon.clearStatus(); },')),
)
# The rules outside the ability entries that the engine hard-codes with them: Corrosion is setStatus's source test before the status
# immunity (sim/pokemon.ts:1709-1713), Quick Feet is par's test (data/conditions.ts:30-38), clearStatus is setStatus('')
# (sim/pokemon.ts:1755-1762), and Snowscape's upkeep runs eachEvent('Weather') (data/conditions.ts:721-724).
A2A_OTHER_FACTS = (
    ('sim/pokemon.ts', ("!ignoreImmunities && status.id && !(source?.hasAbility('corrosion') && ['tox', 'psn'].includes(status.id))",
                        "if (!this.runStatusImmunity(status.id === 'tox' ? 'psn' : status.id)) {",
                        "clearStatus() { if (!this.hp || !this.status) return false; if (this.status === 'slp' && "
                        "this.removeVolatile('nightmare')) { this.battle.add('-end', this, 'Nightmare', '[silent]'); } "
                        "this.setStatus(''); return true; }")),
    ('data/conditions.ts', ("onModifySpePriority: -101, onModifySpe(spe, pokemon) { // Paralysis occurs after all other Speed "
                            "modifiers, so evaluate all modifiers up to this point first spe = this.finalModify(spe); "
                            "if (!pokemon.hasAbility('quickfeet')) { spe = Math.floor(spe * 50 / 100); } return spe; },",
                            "this.add('-weather', 'Snowscape', '[upkeep]'); if (this.field.isWeather('snowscape')) this.eachEvent('Weather');")),
)


def check_a2a_facts(abil_ts, champ_abil, others, only=None):
    """A2a (decision 0015 entry 5dy): every fact of A2A_ABILITY_FACTS is in the pinned ability entry, whitespace aside, and the
    Champions mod has no entry of its own for it; Natural Cure's facts are in the Champions entry (A2A_CHAMPIONS_FACTS); the
    facts of A2A_OTHER_FACTS are in their files (`others`: rel -> Source). `only`: (ability facts, champions facts, other
    facts) to check instead (the generator's tests)."""
    base, champ, other = (A2A_ABILITY_FACTS, A2A_CHAMPIONS_FACTS, A2A_OTHER_FACTS) if only is None else only
    for aid, facts in base:
        e = abil_ts.entry(aid)
        if e is None:
            fail('ability %s not found' % aid)
        if champ_abil.entry(aid) is not None:
            fail('ability %s: the champions mod overrides the entry' % aid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('ability %s: the entry no longer has "%s"' % (aid, fact))
    for aid, facts in champ:
        e = champ_abil.entry(aid)
        if e is None:
            fail('ability %s: the champions entry is not found' % aid)
        text = norm(chr(10).join(e[2]))
        for fact in facts:
            if norm(fact) not in text:
                fail('ability %s: the champions entry no longer has "%s"' % (aid, fact))
    for rel, facts in other:
        text = norm(chr(10).join(others[rel].lines))
        for fact in facts:
            if norm(fact) not in text:
                fail('%s: the pin no longer has "%s"' % (rel, fact))
