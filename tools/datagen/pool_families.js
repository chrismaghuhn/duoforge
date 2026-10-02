#!/usr/bin/env node
// The family columns of the pool tables against the pinned handlers (decision
// 0015 section 2): an independent check of what tools/datagen/gen_closure.py
// --pool derived from the sources of Pokemon Showdown.
//
// usage: node tools/datagen/pool_families.js <pinned checkout> <repo root>
//
// It reads the committed src/data/pool_tables.{h,c}, so it checks the columns
// that the engine reads, and calls the pinned handlers themselves (the Item
// and Ability objects of the format's dex) with a probe for each of the 18
// types:
//   - type booster: onBasePower with a move of each type; exactly one type
//     gets a modifier, x4915/4096, and it is the generated type;
//   - resist berry: onSourceModifyDamage with a hit of each type at each type
//     effectiveness; the target eats the berry and the damage is x0.5 for the
//     generated type only, and only on a super effective hit, except for the
//     Normal berry (Chilan), which halves every Normal hit;
//   - "-ate": onModifyType turns a Normal move into the generated type and
//     onBasePower gives it x4915/4096; no other type changes;
//   - pinch: onModifyAtk and onModifySpA give x1.5 to the generated type at a
//     third of the HP and not above it;
//   - weather and terrain setters: onStart sets the generated condition (the
//     Primal guard of Drizzle and Drought aside).
// Every id without a family must not behave like a member. The ids of the
// pool are also validated by the pinned TeamValidator (the check of
// docs/research/expansion/tools/build_legal_pool.js): every item holds on
// two probe species and every new ability on a species that has it.
'use strict';

const fs = require('fs');
const path = require('path');

const PIN = 'b2cb775b0616115b775534eaeff50300e1fc81fc';
const FORMAT_ID = 'gen9championsvgc2026regmc';
// The 18 battle types in the order of the tables (Stellar is not part of Champions).
const TYPES = ['Bug', 'Dark', 'Dragon', 'Electric', 'Fairy', 'Fighting', 'Fire', 'Flying', 'Ghost', 'Grass', 'Ground',
    'Ice', 'Normal', 'Poison', 'Psychic', 'Rock', 'Steel', 'Water'];
const ITEM_FAMILIES = ['NONE', 'TYPE_BOOSTER', 'RESIST_BERRY'];
const ABILITY_FAMILIES = ['NONE', 'ATE', 'PINCH', 'WEATHER_SETTER', 'TERRAIN_SETTER'];
// The names of the generated weather and terrain codes, as Showdown calls them.
const WEATHER = {RAIN: 'raindance', SUN: 'sunnyday'};
const TERRAIN = {GRASSY: 'grassyterrain', PSYCHIC: 'psychicterrain'};
// The Primal Pokemon that Drizzle and Drought leave alone.
const PRIMAL = {raindance: ['kyogre', 'blueorb'], sunnyday: ['groudon', 'redorb']};

let failures = 0;
function bad(message) {
    failures += 1;
    process.stderr.write('pool_families: ' + message + '\n');
}
function same(a, b) {
    return JSON.stringify(a) === JSON.stringify(b);
}
function expect(what, got, want) {
    if (!same(got, want)) {
        bad(what + ': got ' + JSON.stringify(got) + ', expected ' + JSON.stringify(want));
    }
}

// ---------------------------------------------------------------- the tables
function readText(file) {
    return fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n');
}

function defineOf(text, name) {
    const m = text.match(new RegExp('^#define ' + name + ' (\\d+)u$', 'm'));
    if (m === null) {
        throw new Error('#define ' + name + ' not found');
    }
    return Number(m[1]);
}

// The rows of a family array: [DFI_<KIND>_<ID>] = {DFI_<KIND>_FAMILY_<FAMILY>, <parameter>},
function familyRows(source, kind, arrayName, count) {
    const start = source.indexOf(arrayName + '[');
    if (start < 0) {
        throw new Error(arrayName + ' not found');
    }
    const end = source.indexOf('\n};', start);
    const rows = [];
    const re = new RegExp('^\\s*\\[DFI_' + kind + '_(\\w+)\\] = \\{DFI_' + kind + '_FAMILY_(\\w+), (\\w+)\\},$', 'gm');
    for (const m of source.slice(start, end).matchAll(re)) {
        rows.push({id: m[1].toLowerCase(), family: m[2], param: m[3]});
    }
    if (rows.length !== count || new Set(rows.map((r) => r.id)).size !== count) {
        throw new Error(arrayName + ': ' + rows.length + ' rows, expected ' + count + ' different ids');
    }
    return rows;
}

// The type, weather or terrain a parameter names, as Showdown's type name or id; null for none.
function typeOf(param) {
    const m = param.match(/^DFI_TYPE_(\w+)$/);
    const name = m === null ? undefined : TYPES.find((t) => t.toUpperCase() === m[1]);
    return name === undefined ? undefined : name;
}
function weatherOf(param) {
    const m = param.match(/^DFI_FAMILY_WEATHER_(\w+)$/);
    return m === null ? undefined : WEATHER[m[1]];
}
function terrainOf(param) {
    const m = param.match(/^DFI_FAMILY_TERRAIN_(\w+)$/);
    return m === null ? undefined : TERRAIN[m[1]];
}

// ------------------------------------------------------------------- probes
// What a handler sees as `this`: chainModify returns the modifier it was given.
function battle(effect, extra) {
    return Object.assign({chainModify: (m) => ({chain: m}), debug() {}, add() {}, effect, gen: 9, activeMove: null}, extra);
}
function moveOf(type, extra) {
    return Object.assign({type, id: 'probe', name: 'Probe', category: 'Physical', flags: {}, isZ: false,
        infiltrates: false}, extra);
}
// A handler that throws needs more of the battle than the family rule uses, so it is no member: undefined.
function call(fn, thisArg, args) {
    try {
        return fn.apply(thisArg, args);
    } catch (e) {
        return undefined;
    }
}

// The types for which an item's onBasePower gives a modifier, and the modifiers.
function boostedTypes(item) {
    const fired = [];
    const modifiers = new Set();
    for (const type of TYPES) {
        const r = call(item.onBasePower, battle(item), [100, {}, {}, moveOf(type)]);
        if (r !== undefined) {
            fired.push(type);
            modifiers.add(JSON.stringify(r.chain));
        }
    }
    return {fired, modifiers: [...modifiers]};
}

// The types for which a resist berry is eaten and halves the damage, at a type effectiveness.
function resistedTypes(item, typeMod) {
    const fired = [];
    for (const type of TYPES) {
        let eaten = 0;
        const target = {volatiles: {}, getMoveHitData: () => ({typeMod}), eatItem() { eaten += 1; return true; }};
        const r = call(item.onSourceModifyDamage, battle(item), [100, {}, target, moveOf(type)]);
        if (r !== undefined) {
            if (r.chain !== 0.5 || eaten !== 1) {
                bad(item.id + ': a hit of ' + type + ' is not x0.5 with one eaten berry');
            }
            fired.push(type);
        } else if (eaten !== 0) {
            bad(item.id + ': the berry is eaten without a modifier');
        }
    }
    return fired;
}

// What an "-ate" ability does to a move of each type: {type: new type} for the changed ones, and the
// BasePower modifier of the changed move.
function ateChanges(ability) {
    const changed = {};
    const boosts = {};
    for (const type of TYPES) {
        const ctx = battle(ability);
        const move = moveOf(type);
        call(ability.onModifyType, ctx, [move, {terastallized: false}]);
        if (move.type !== type) {
            changed[type] = move.type;
        }
        const r = call(ability.onBasePower, ctx, [100, {}, {}, move]);
        if (r !== undefined) {
            boosts[type] = r.chain;
        }
    }
    return {changed, boosts};
}

// The types for which a pinch ability gives x1.5 at the HP, from both callbacks.
function pinchTypes(ability, hp, maxhp) {
    const out = {};
    for (const callback of ['onModifyAtk', 'onModifySpA']) {
        out[callback] = [];
        for (const type of TYPES) {
            const r = call(ability[callback], battle(ability), [100, {hp, maxhp}, {}, moveOf(type)]);
            if (r !== undefined) {
                if (r.chain !== 1.5) {
                    bad(ability.id + ': ' + callback + ' gives ' + JSON.stringify(r.chain) + ', not x1.5');
                }
                out[callback].push(type);
            }
        }
    }
    return out;
}

// What an entry ability sets for a source Pokemon.
function setterEffect(ability, speciesId, itemId) {
    const set = {weather: null, terrain: null};
    const ctx = battle(ability, {field: {
        setWeather(id) { set.weather = id; return true; },
        setTerrain(id) { set.terrain = id; return true; },
    }});
    call(ability.onStart, ctx, [{species: {id: speciesId}, item: itemId}]);
    return set;
}

// ----------------------------------------------------------------- the check
function checkItems(dex, rows) {
    const counts = {};
    for (const row of rows) {
        const item = dex.items.get(row.id);
        if (!item.exists) {
            bad('item ' + row.id + ' does not exist');
            continue;
        }
        if (!ITEM_FAMILIES.includes(row.family)) {
            bad(row.id + ': unknown family ' + row.family);
            continue;
        }
        counts[row.family] = (counts[row.family] || 0) + 1;
        if (row.family === 'NONE') {
            expect(row.id + ' parameter', row.param, 'DFI_FAMILY_PARAM_NONE');
            if (typeof item.onBasePower === 'function') {
                expect(row.id + ' (no family) type booster probe', boostedTypes(item).fired, []);
            }
            if (typeof item.onSourceModifyDamage === 'function') {
                expect(row.id + ' (no family) resist berry probe', resistedTypes(item, 1), []);
            }
            continue;
        }
        const type = typeOf(row.param);
        if (type === undefined) {
            bad(row.id + ': ' + row.param + ' is not a type');
            continue;
        }
        if (row.family === 'TYPE_BOOSTER') {
            expect(row.id + ' onBasePowerPriority', item.onBasePowerPriority, 15);
            const probe = boostedTypes(item);
            expect(row.id + ' boosted types', probe.fired, [type]);
            expect(row.id + ' modifier', probe.modifiers, [JSON.stringify([4915, 4096])]);
        } else {
            // A Normal move is never super effective, so the Normal berry halves every Normal hit; the others
            // need a super effective hit of their type.
            const everyHit = type === 'Normal';
            expect(row.id + ' berry on a super effective hit', resistedTypes(item, 1), [type]);
            expect(row.id + ' berry on a neutral hit', resistedTypes(item, 0), everyHit ? [type] : []);
            expect(row.id + ' berry on a resisted hit', resistedTypes(item, -1), everyHit ? [type] : []);
            expect(row.id + ' natural gift type', item.naturalGift.type, type);
        }
    }
    return counts;
}

function checkAbilities(dex, rows) {
    const counts = {};
    for (const row of rows) {
        const ability = dex.abilities.get(row.id);
        if (!ability.exists) {
            bad('ability ' + row.id + ' does not exist');
            continue;
        }
        if (!ABILITY_FAMILIES.includes(row.family)) {
            bad(row.id + ': unknown family ' + row.family);
            continue;
        }
        counts[row.family] = (counts[row.family] || 0) + 1;
        if (row.family === 'NONE') {
            expect(row.id + ' parameter', row.param, 'DFI_FAMILY_PARAM_NONE');
            if (typeof ability.onModifyType === 'function') {
                expect(row.id + ' (no family) "-ate" probe', ateChanges(ability).changed, {});
            }
            for (const callback of ['onModifyAtk', 'onModifySpA']) {
                if (typeof ability[callback] === 'function') {
                    expect(row.id + ' (no family) pinch probe ' + callback, pinchTypes(ability, 10, 30)[callback], []);
                }
            }
            if (typeof ability.onStart === 'function' && /\.field\.set(Weather|Terrain)\(/.test(ability.onStart.toString())) {
                bad(row.id + ' (no family) sets weather or terrain on entry');
            }
            continue;
        }
        if (row.family === 'ATE') {
            const type = typeOf(row.param);
            const probe = ateChanges(ability);
            expect(row.id + ' "-ate" changes', probe.changed, {Normal: type});
            // The BasePower modifier follows the changed move only (Normal, now typed).
            expect(row.id + ' "-ate" BasePower', probe.boosts, {Normal: [4915, 4096]});
            expect(row.id + ' onModifyTypePriority', ability.onModifyTypePriority, -1);
            expect(row.id + ' onBasePowerPriority', ability.onBasePowerPriority, 23);
        } else if (row.family === 'PINCH') {
            const type = typeOf(row.param);
            expect(row.id + ' pinch at a third', pinchTypes(ability, 10, 30), {onModifyAtk: [type], onModifySpA: [type]});
            expect(row.id + ' pinch above a third', pinchTypes(ability, 11, 30), {onModifyAtk: [], onModifySpA: []});
            expect(row.id + ' pinch at full HP', pinchTypes(ability, 30, 30), {onModifyAtk: [], onModifySpA: []});
            expect(row.id + ' onModifyAtkPriority', ability.onModifyAtkPriority, 5);
            expect(row.id + ' onModifySpAPriority', ability.onModifySpAPriority, 5);
        } else if (row.family === 'WEATHER_SETTER') {
            const weather = weatherOf(row.param);
            expect(row.id + ' sets', setterEffect(ability, 'garchomp', ''), {weather, terrain: null});
            // The Primal Pokemon with their orb are left alone, nothing else is.
            const [species, orb] = PRIMAL[weather] || ['', ''];
            expect(row.id + ' with the Primal orb', setterEffect(ability, species, orb), {weather: null, terrain: null});
            expect(row.id + ' without the orb', setterEffect(ability, species, ''), {weather, terrain: null});
        } else {
            const terrain = terrainOf(row.param);
            expect(row.id + ' sets', setterEffect(ability, 'garchomp', ''), {weather: null, terrain});
        }
    }
    return counts;
}

// The pinned TeamValidator accepts every item of the pool on two species and every new ability on a species
// that has it (the method of build_legal_pool.js).
function checkLegal(dex, validator, itemRows, abilityRows, extendedAbilities) {
    const set = (species, ability, item, moves) => ({
        name: '', species, item, ability, moves, nature: 'Adamant', gender: '',
        evs: {hp: 2, atk: 0, def: 0, spa: 0, spd: 0, spe: 0}, ivs: {hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31},
        level: 50,
    });
    const toId = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, '');
    for (const row of itemRows) {
        const item = dex.items.get(row.id);
        const first = validator.validateSet(set('Garchomp', 'Rough Skin', item.name, ['protect']), {});
        const second = validator.validateSet(set('Charizard', 'Blaze', item.name, ['protect']), {});
        if (first || second) {
            bad('item ' + row.id + ' is not legal in ' + FORMAT_ID + ': ' + JSON.stringify(first || second));
        }
    }
    const probeMove = (species) => {
        for (const {learnset} of dex.species.getFullLearnset(species.id)) {
            for (const m of Object.keys(learnset)) {
                const move = dex.moves.get(m);
                if (move.exists && !validator.checkMove({name: 'x'}, move, {})) {
                    return m;
                }
            }
        }
        return 'protect';
    };
    for (const row of abilityRows.slice(extendedAbilities)) {
        const holders = dex.species.all().filter((s) => s.exists && !s.battleOnly &&
            Object.values(s.abilities).some((a) => toId(a) === row.id));
        const name = dex.abilities.get(row.id).name;
        const legal = holders.some((s) => !validator.validateSet(set(s.name, name, '', [probeMove(s)]), {}));
        if (!legal) {
            bad('ability ' + row.id + ' is not legal on any species of ' + FORMAT_ID + ' (' + holders.length + ' declare it)');
        }
    }
}

function main() {
    const args = process.argv.slice(2);
    if (args.length !== 2) {
        process.stderr.write('usage: pool_families.js <pinned checkout> <repo root>\n');
        process.exit(2);
    }
    const root = path.resolve(args[0]);
    const repo = path.resolve(args[1]);
    const header = readText(path.join(repo, 'src', 'data', 'pool_tables.h'));
    const source = readText(path.join(repo, 'src', 'data', 'pool_tables.c'));
    const itemCount = defineOf(header, 'DFI_POOL_ITEM_COUNT');
    const abilityCount = defineOf(header, 'DFI_POOL_ABILITY_COUNT');
    const extendedAbilities = defineOf(readText(path.join(repo, 'src', 'data', 'extended_tables.h')),
        'DFI_EXT_ABILITY_COUNT');
    const itemRows = familyRows(source, 'ITEM', 'dfi_pool_item_family', itemCount);
    const abilityRows = familyRows(source, 'ABILITY', 'dfi_pool_ability_family', abilityCount);

    const {Dex, TeamValidator} = require(path.join(root, 'dist', 'sim'));
    const format = Dex.formats.get(FORMAT_ID);
    if (!format.exists) {
        throw new Error('format ' + FORMAT_ID + ' missing: is ' + root + ' the pinned checkout (' + PIN + ')?');
    }
    const dex = Dex.forFormat(format);
    for (const type of TYPES) {
        if (!dex.types.get(type).exists) {
            bad('type ' + type + ' does not exist in the format');
        }
    }
    const items = checkItems(dex, itemRows);
    const abilities = checkAbilities(dex, abilityRows);
    // "All 18": a booster and a resist berry for each type, and nothing else in the families.
    expect('type boosters', items.TYPE_BOOSTER, 18);
    expect('resist berries', items.RESIST_BERRY, 18);
    expect('"-ate" abilities', abilities.ATE, 3);
    expect('pinch abilities', abilities.PINCH, 4);
    expect('weather setters', abilities.WEATHER_SETTER, 2);
    expect('terrain setters', abilities.TERRAIN_SETTER, 2);
    checkLegal(dex, TeamValidator.get(FORMAT_ID), itemRows, abilityRows, extendedAbilities);

    if (failures > 0) {
        process.stderr.write('pool_families: ' + failures + ' mismatch(es)\n');
        process.exit(1);
    }
    process.stdout.write('pool_families: ' + itemRows.length + ' items and ' + abilityRows.length +
        ' abilities agree with the pinned handlers (' + JSON.stringify(items) + ', ' + JSON.stringify(abilities) +
        '); every pool item and the new abilities pass the validator\n');
}

main();
