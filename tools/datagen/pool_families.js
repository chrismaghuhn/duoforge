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
//
// The legal moves and abilities of the formes (the learnable bitset and the
// ability list of dfi_pool_forme_legal) are checked against the validator
// too: for every base forme and every pool move, a set of the forme with that
// one move is accepted exactly when the bit is set; for every pool ability, a
// set of the forme with that ability is accepted exactly when it is in the
// forme's list. A Mega forme has no learnable move and its one ability.
//
// The names of the data query API (the dfi_pool_*_names arrays: forme, move,
// item, ability and nature) are checked against the pinned dex: each is the id
// that the format's dex gives the entry it names, and the macro of its row.
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
const WEATHER = {RAIN: 'raindance', SUN: 'sunnyday', SAND: 'sandstorm', SNOW: 'snowscape'};
const TERRAIN = {GRASSY: 'grassyterrain', PSYCHIC: 'psychicterrain', ELECTRIC: 'electricterrain', MISTY: 'mistyterrain'};
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
// The ids of the DFI_<KIND>_<ID> defines of the tables' headers, by number.
function definedIds(headers, kind) {
    const byNumber = new Map();
    const re = new RegExp('^#define DFI_' + kind + '_(\\w+) (\\d+)u$', 'gm');
    for (const text of headers) {
        for (const m of text.matchAll(re)) {
            if (m[1] !== 'COUNT' && !m[1].startsWith('FLAG_') && !m[1].startsWith('FAMILY_')) {
                byNumber.set(Number(m[2]), m[1].toLowerCase());
            }
        }
    }
    return byNumber;
}

// The rows of dfi_pool_forme_legal: [DFI_FORME_<ID>] = {{learnable bytes}, count, {abilities}},
function formeRows(source, count, learnBytes) {
    const start = source.indexOf('dfi_pool_forme_legal[');
    if (start < 0) {
        throw new Error('dfi_pool_forme_legal not found');
    }
    const end = source.indexOf('\n};', start);
    const rows = [];
    const re = /^\s*\[DFI_FORME_(\w+)\] = \{\{([^}]*)\}, (\d+)u, \{([^}]*)\}\},$/gm;
    for (const m of source.slice(start, end).matchAll(re)) {
        const bytes = m[2].split(',').map((x) => parseInt(x.trim(), 16));
        const abilities = m[4].split(',').map((x) => x.trim()).filter((x) => x !== 'DFI_CLOSURE_NONE')
            .map((x) => x.replace(/^DFI_ABILITY_/, '').toLowerCase());
        if (bytes.length !== learnBytes || abilities.length !== Number(m[3])) {
            throw new Error('dfi_pool_forme_legal row ' + m[1] + ': ' + bytes.length + ' bytes, ' + abilities.length + ' abilities');
        }
        rows.push({id: m[1].toLowerCase(), bytes, abilities});
    }
    if (rows.length !== count || new Set(rows.map((r) => r.id)).size !== count) {
        throw new Error('dfi_pool_forme_legal: ' + rows.length + ' rows, expected ' + count + ' different formes');
    }
    return rows;
}

// The names of the data query API (duoforge_data_find, duoforge_data_name): one array per table of
// [DFI_<KIND>_<ID>] = "name", as gen_closure.py --pool writes them, against the pinned dex.
function nameRows(source, kind, arrayName) {
    const start = source.indexOf('const char *const ' + arrayName + '[');
    if (start < 0) {
        throw new Error(arrayName + ' not found');
    }
    const end = source.indexOf('\n};', start);
    const rows = [];
    const re = new RegExp('^\\s*\\[DFI_' + kind + '_(\\w+)\\] = "([^"]*)",$', 'gm');
    for (const m of source.slice(start, end).matchAll(re)) {
        rows.push({macro: m[1], name: m[2]});
    }
    return rows;
}

// Every name is the id that the pinned dex gives the entry it names (a Showdown id), the same name
// as the macro of its row, and the macros are exactly the headers' ids.
function checkNames(dex, source, headers) {
    const tables = [
        ['FORME', 'dfi_pool_forme_names', (n) => dex.species.get(n)],
        ['MOVE', 'dfi_pool_move_names', (n) => dex.moves.get(n)],
        ['ITEM', 'dfi_pool_item_names', (n) => dex.items.get(n)],
        ['ABILITY', 'dfi_pool_ability_names', (n) => dex.abilities.get(n)],
        ['NATURE', 'dfi_pool_nature_names', (n) => dex.natures.get(n)],
    ];
    let checked = 0;
    for (const [kind, array, lookup] of tables) {
        const rows = nameRows(source, kind, array);
        const ids = definedIds(headers, kind);
        expect(kind + ' names: the macros', rows.map((r) => r.macro.toLowerCase()).sort(),
            Array.from(ids.values()).sort());
        for (const row of rows) {
            const entry = lookup(row.name);
            if (!entry.exists || entry.id !== row.name || row.macro.toLowerCase() !== row.name) {
                bad(kind + ' name ' + row.name + ' (' + row.macro + ') is not a pinned dex id');
            }
            checked += 1;
        }
    }
    return checked;
}

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

// Step G49, Muscle Band and Wise Glasses: the base power of every move of their category (whatever its type) gets the same
// modifier, and no other category does. They are engine rows (ENGINE_ROWS), not families.
const CATEGORY_BOOSTERS = {muscleband: 'Physical', wiseglasses: 'Special'};
function categoryBoosted(item) {
    const categories = new Set();
    const modifiers = new Set();
    let fired = 0;
    for (const category of ['Physical', 'Special', 'Status']) {
        for (const type of TYPES) {
            const r = call(item.onBasePower, battle(item), [100, {}, {}, moveOf(type, {category})]);
            if (r !== undefined) {
                fired += 1;
                categories.add(category);
                modifiers.add(JSON.stringify(r.chain));
            }
        }
    }
    return {categories: [...categories], modifiers: [...modifiers], fired};
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

// The moves an "-ate" ability leaves alone by id (the noModifyType list of its onModifyType handler). The
// engine skips two of them: Weather Ball and, since step G25, Terrain Pulse, the only ones that the pool has (checked below
// against the pool ids).
const NO_MODIFY_TYPE = ['judgment', 'multiattack', 'naturalgift', 'revelationdance', 'technoblast', 'terrainpulse',
    'weatherball'];
function ateLeavesAlone(ability, id) {
    const move = moveOf('Normal', {id, name: id});
    call(ability.onModifyType, battle(ability), [move, {terastallized: false}]);
    return move.type === 'Normal';
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

// Sandstorm and Snowscape, Weather Ball: what the engine reads about them (src/combat/turn.c), called on the pinned
// handlers: the types immune to Sandstorm damage (the type chart's sandstorm key, against the generated immunity bit
// 32 of dfi_pool_type_immunity), the damage of onWeather, Snowscape's lack of any, the Rock and Ice stat boosts, and
// the type and the power of Weather Ball in each weather.
function checkWeather(dex, source) {
    const start = source.indexOf('const uint8_t dfi_pool_type_immunity[');
    const bits = source.slice(start, source.indexOf('};', start)).match(/\{([^}]*)/)[1].split(',').map((x) => parseInt(x, 10));
    TYPES.forEach((type, i) => {
        const immune = dex.types.get(type).damageTaken.sandstorm === 3;
        expect('type ' + type + ' immune to Sandstorm', (bits[i] & 32) !== 0, immune);
    });
    expect('the types immune to Sandstorm', TYPES.filter((t) => dex.types.get(t).damageTaken.sandstorm === 3),
        ['Ground', 'Rock', 'Steel']);
    const sand = dex.conditions.get('sandstorm');
    const snow = dex.conditions.get('snowscape');
    let damage = null;
    call(sand.onWeather, battle(sand, {damage(n) { damage = n; }}), [{baseMaxhp: 160}]);
    expect('Sandstorm damage', damage, 10);
    expect('Snowscape has no onWeather', snow.onWeather, undefined);
    expect('Sandstorm duration', [sand.duration, snow.duration], [5, 5]);
    expect('Sandstorm onFieldResidualOrder', [sand.onFieldResidualOrder, snow.onFieldResidualOrder], [1, 1]);
    const user = (w) => ({effectiveWeather: () => w});
    const modify = (spd, m) => ({modified: [spd, m]});
    const rock = {hasType: (t) => t === 'Rock', effectiveWeather: () => 'sandstorm'};
    const ice = {hasType: (t) => t === 'Ice', effectiveWeather: () => 'snowscape'};
    expect('Sandstorm SpD of a Rock type', call(sand.onModifySpD, battle(sand, {modify}), [100, rock]), {modified: [100, 1.5]});
    expect('Sandstorm SpD of a non-Rock type', call(sand.onModifySpD, battle(sand, {modify}), [100, ice]), undefined);
    expect('Snowscape Def of an Ice type', call(snow.onModifyDef, battle(snow, {modify}), [100, ice]), {modified: [100, 1.5]});
    expect('Snowscape Def of a non-Ice type', call(snow.onModifyDef, battle(snow, {modify}), [100, rock]), undefined);
    expect('Sandstorm onModifySpDPriority', sand.onModifySpDPriority, 10);
    expect('Snowscape onModifyDefPriority', snow.onModifyDefPriority, 10);
    const ball = dex.moves.get('weatherball');
    for (const [w, type] of [['raindance', 'Water'], ['sunnyday', 'Fire'], ['sandstorm', 'Rock'], ['snowscape', 'Ice']]) {
        const move = moveOf('Normal', {basePower: 50});
        call(ball.onModifyType, battle(ball), [move, user(w)]);
        call(ball.onModifyMove, battle(ball), [move, user(w)]);
        expect('Weather Ball in ' + w, [move.type, move.basePower], [type, 100]);
    }
    const none = moveOf('Normal', {basePower: 50});
    call(ball.onModifyType, battle(ball), [none, user('')]);
    call(ball.onModifyMove, battle(ball), [none, user('')]);
    expect('Weather Ball without weather', [none.type, none.basePower], ['Normal', 50]);
}

// Step G28, Expert Belt, Acrobatics, Blizzard, Shell Smash, Ancient Power and Feint: what the engine reads about them
// (src/combat/turn.c), called on the pinned handlers and read from the pinned data.
function checkG28(dex) {
    const belt = dex.items.get('expertbelt');
    for (const typeMod of [-2, -1, 0, 1, 2]) {
        expect('Expert Belt at a type modifier of ' + typeMod,
            call(belt.onModifyDamage, battle(belt), [100, {}, {getMoveHitData: () => ({typeMod})}, moveOf('Fire')]),
            typeMod > 0 ? {chain: [4915, 4096]} : undefined);
    }
    const acrobatics = dex.moves.get('acrobatics');
    expect('Acrobatics without an item', call(acrobatics.basePowerCallback, battle(acrobatics), [{item: ''}, {}, {basePower: 55}]), 110);
    expect('Acrobatics with an item', call(acrobatics.basePowerCallback, battle(acrobatics), [{item: 'leftovers'}, {}, {basePower: 55}]), 55);
    const blizzard = dex.moves.get('blizzard');
    for (const [weather, never] of [['', false], ['sandstorm', false], ['raindance', false], ['sunnyday', false], ['snowscape', true]]) {
        const move = {accuracy: 70};
        call(blizzard.onModifyMove, {field: {isWeather: (list) => list.includes(weather)}}, [move]);
        expect('Blizzard in ' + (weather || 'no weather'), move.accuracy, never ? true : 70);
    }
    const smash = dex.moves.get('shellsmash');
    expect('the boosts of Shell Smash, in the order of the entry', Object.entries(smash.boosts),
        [['def', -1], ['spd', -1], ['atk', 2], ['spa', 2], ['spe', 2]]);
    const ancient = dex.moves.get('ancientpower');
    expect('the secondary of Ancient Power', [ancient.secondary.chance, ancient.secondary.self],
        [10, {boosts: {atk: 1, def: 1, spa: 1, spd: 1, spe: 1}}]);
    const feint = dex.moves.get('feint');
    expect('Feint', [feint.breaksProtect, feint.priority, feint.basePower, feint.flags.protect], [true, 2, 30, undefined]);
}

// Step G25, Electric Terrain, Misty Terrain, Rising Voltage, Terrain Pulse and the four terrain seeds: what the engine
// reads about them (src/combat/turn.c), called on the pinned handlers.
function checkTerrains(dex) {
    const grounded = {isGrounded: () => true, isSemiInvulnerable: () => false};
    const airborne = {isGrounded: () => false, isSemiInvulnerable: () => false};
    const electric = dex.moves.get('electricterrain').condition;
    const misty = dex.moves.get('mistyterrain').condition;
    for (const [name, terrain] of [['Electric Terrain', electric], ['Misty Terrain', misty]]) {
        expect(name + ' duration, Terrain Extender', [terrain.duration, call(terrain.durationCallback, battle(terrain), [{hasItem: () => false}]),
            call(terrain.durationCallback, battle(terrain), [{hasItem: (i) => i === 'terrainextender'}])], [5, 5, 8]);
        expect(name + ' residual order', [terrain.onFieldResidualOrder, terrain.onFieldResidualSubOrder], [27, 7]);
        expect(name + ' onBasePowerPriority', terrain.onBasePowerPriority, 6);
    }
    // the base power modifiers: Electric's for a grounded user's Electric move, Misty's for a Dragon move at a grounded target
    for (const type of TYPES) {
        const move = moveOf(type);
        expect('Electric Terrain, ' + type + ' move of a grounded user', call(electric.onBasePower, battle(electric), [100, grounded, airborne, move]),
            type === 'Electric' ? {chain: [5325, 4096]} : undefined);
        expect('Electric Terrain, ' + type + ' move of an airborne user', call(electric.onBasePower, battle(electric), [100, airborne, grounded, move]), undefined);
        expect('Misty Terrain, ' + type + ' move at a grounded target', call(misty.onBasePower, battle(misty), [100, airborne, grounded, move]),
            type === 'Dragon' ? {chain: 0.5} : undefined);
        expect('Misty Terrain, ' + type + ' move at an airborne target', call(misty.onBasePower, battle(misty), [100, grounded, airborne, move]), undefined);
    }
    // onSetStatus: the refusal (return false), and the -activate line for a move's own status only
    const lines = [];
    const logger = (effect) => battle(effect, {add: (...a) => lines.push([a[0], a[2]])});
    const effects = {
        'a move with no secondaries': {effectType: 'Move', id: 'probe', status: 'slp'},
        'a damaging move with a secondary': {effectType: 'Move', id: 'probe', secondaries: [{}]},
        'an ability': {effectType: 'Ability', id: 'poisontouch'},
        'Yawn': {effectType: 'Move', id: 'yawn'},
    };
    for (const status of ['slp', 'par', 'brn', 'frz', 'psn', 'tox']) {
        for (const [what, effect] of Object.entries(effects)) {
            for (const [tname, terrain, name] of [['electric', electric, 'Electric Terrain'], ['misty', misty, 'Misty Terrain']]) {
                lines.length = 0;
                const got = call(terrain.onSetStatus, logger(terrain), [{id: status}, grounded, {}, effect]);
                const own = what === 'a move with no secondaries' || what === 'Yawn';
                const refuses = tname === 'misty' || status === 'slp';
                expect(name + ' onSetStatus ' + status + ' by ' + what, [got, lines.length],
                    [refuses ? false : undefined, refuses && own ? 1 : 0]);
                if (refuses && own) {
                    expect(name + ' line', lines[0], ['-activate', 'move: ' + name]);
                }
                lines.length = 0;
                expect(name + ' onSetStatus at an airborne target', call(terrain.onSetStatus, logger(terrain), [{id: status}, airborne, {}, effect]), undefined);
            }
        }
    }
    // onTryAddVolatile: Electric's is Yawn only, Misty's is confusion (the line for a move without secondaries)
    for (const id of ['yawn', 'confusion', 'flinch']) {
        for (const [what, effect] of [['a move with no secondaries', {effectType: 'Move', id: 'probe'}],
            ['a move with a secondary', {effectType: 'Move', id: 'probe', secondaries: [{}]}]]) {
            lines.length = 0;
            expect('Electric Terrain onTryAddVolatile ' + id, call(electric.onTryAddVolatile, logger(electric), [{id}, grounded, {}, effect]),
                id === 'yawn' ? null : undefined);
            expect('Electric Terrain onTryAddVolatile ' + id + ' lines', lines.length, id === 'yawn' ? 1 : 0);
            lines.length = 0;
            expect('Misty Terrain onTryAddVolatile ' + id + ' by ' + what, call(misty.onTryAddVolatile, logger(misty), [{id}, grounded, {}, effect]),
                id === 'confusion' ? null : undefined);
            expect('Misty Terrain onTryAddVolatile ' + id + ' by ' + what + ' lines', lines.length,
                id === 'confusion' && effect.secondaries === undefined ? 1 : 0);
            expect('Misty Terrain onTryAddVolatile at an airborne target', call(misty.onTryAddVolatile, logger(misty), [{id}, airborne, {}, effect]), undefined);
        }
    }
    // Rising Voltage: doubled at a grounded target in Electric Terrain
    const voltage = dex.moves.get('risingvoltage');
    const field = (terrain) => ({isTerrain: (t) => t === terrain});
    const base = () => ({basePower: 70, name: 'Rising Voltage'});
    expect('Rising Voltage in Electric Terrain', call(voltage.basePowerCallback, {field: field('electricterrain'), hint() {}}, [{isAlly: () => false}, grounded, base()]), 140);
    expect('Rising Voltage at an airborne target', call(voltage.basePowerCallback, {field: field('electricterrain'), hint() {}}, [{isAlly: () => false}, airborne, base()]), 70);
    expect('Rising Voltage in another terrain', call(voltage.basePowerCallback, {field: field('mistyterrain'), hint() {}}, [{isAlly: () => false}, grounded, base()]), 70);
    // Terrain Pulse: the type of the terrain and double power for a grounded user
    const pulse = dex.moves.get('terrainpulse');
    const types = {electricterrain: 'Electric', grassyterrain: 'Grass', mistyterrain: 'Fairy', psychicterrain: 'Psychic', '': 'Normal'};
    for (const [terrain, type] of Object.entries(types)) {
        for (const [who, user] of [['grounded', grounded], ['airborne', airborne]]) {
            const move = {type: 'Normal', basePower: 50};
            call(pulse.onModifyType, {field: {terrain}}, [move, user]);
            call(pulse.onModifyMove, {field: {terrain}, debug() {}}, [move, user]);
            expect('Terrain Pulse in ' + (terrain || 'no terrain') + ', ' + who + ' user', [move.type, move.basePower],
                [who === 'grounded' ? type : 'Normal', who === 'grounded' && terrain !== '' ? 100 : 50]);
        }
    }
    // the four seeds: onStart and onTerrainChange use the item while their terrain is up, the boost is one stage
    for (const [id, terrain, stat] of [['grassyseed', 'grassyterrain', 'def'], ['psychicseed', 'psychicterrain', 'spd'],
        ['electricseed', 'electricterrain', 'def'], ['mistyseed', 'mistyterrain', 'spd']]) {
        const item = dex.items.get(id);
        expect(id + ' boosts', item.boosts, {[stat]: 1});
        expect(id + ' onSwitchInPriority', item.onSwitchInPriority, -1);
        for (const fn of ['onStart', 'onTerrainChange']) {
            for (const up of Object.keys(types).filter((t) => t !== '')) {
                let used = 0;
                call(item[fn], {field: field(up)}, [{ignoringItem: () => false, useItem() { used += 1; }}]);
                expect(id + ' ' + fn + ' in ' + up, used, up === terrain ? 1 : 0);
            }
        }
    }
}

// ----------------------------------------------------------------- the check
function checkItems(dex, rows, unmodeled) {
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
            // A modelled row without a family must not behave like a member: a type booster has exactly one boosted
            // type, a resist berry exactly one resisted type. An UNMODELED row is refused whatever it does (Muscle Band
            // boosts every Physical move, Occa-like berries of other families are not in the pool).
            if (!unmodeled.has(row.id)) {
                if (row.id in CATEGORY_BOOSTERS) {
                    expect(row.id + ' category booster probe', categoryBoosted(item),
                        {categories: [CATEGORY_BOOSTERS[row.id]], modifiers: ['[4505,4096]'], fired: TYPES.length});
                } else if (typeof item.onBasePower === 'function') {
                    expect(row.id + ' (no family) type booster probe', boostedTypes(item).fired, []);
                }
                if (typeof item.onSourceModifyDamage === 'function') {
                    expect(row.id + ' (no family) resist berry probe', resistedTypes(item, 1), []);
                }
            } else if (typeof item.onBasePower === 'function') {
                const probe = boostedTypes(item);
                if (probe.fired.length === 1 && probe.modifiers.length === 1 && probe.modifiers[0] === JSON.stringify([4915, 4096])) {
                    bad(row.id + ' behaves like a type booster of ' + probe.fired[0] + ' but is no family member');
                }
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

// Focus Sash (no family column; the engine names it): its onDamage is called with the effect of each kind of
// damage the engine deals. Only an effect whose effectType is 'Move' (a move's hit and the confusion self-hit,
// which the source passes as { id: 'confused', effectType: 'Move' }) uses the sash, at full HP and a lethal hit.
function checkFocusSash(dex, root) {
    const sash = dex.items.get('focussash');
    if (!sash.exists) {
        bad('item focussash does not exist');
        return;
    }
    const fire = (effect, hp, maxhp, damage) => {
        let used = false;
        const target = {hp, maxhp, useItem() { used = true; return true; }};
        const result = call(sash.onDamage, battle(sash), [damage, target, {}, effect]);
        return {result, used};
    };
    const move = {effectType: 'Move'};
    expect('focussash lethal move hit at full HP', fire(move, 100, 100, 100), {result: 99, used: true});
    expect('focussash larger hit', fire(move, 100, 100, 900), {result: 99, used: true});
    expect('focussash smaller hit', fire(move, 100, 100, 99), {result: undefined, used: false});
    expect('focussash below full HP', fire(move, 99, 100, 900), {result: undefined, used: false});
    expect('focussash onDamagePriority', sash.onDamagePriority, -40);
    // The effect types of the other damage the engine deals, as the dex builds them.
    const types = {
        recoil: dex.conditions.getByID('recoil').effectType, drain: dex.conditions.getByID('drain').effectType,
        lifeorb: dex.items.get('lifeorb').effectType, rockyhelmet: dex.items.get('rockyhelmet').effectType,
        brn: dex.conditions.get('brn').effectType, psn: dex.conditions.get('psn').effectType,
        sandstorm: dex.conditions.get('sandstorm').effectType,
    };
    expect('effect types of the damage that is no Move', types,
        {recoil: 'Condition', drain: 'Condition', lifeorb: 'Item', rockyhelmet: 'Item', brn: 'Status', psn: 'Status',
            sandstorm: 'Weather'});
    for (const name of Object.keys(types)) {
        expect('focussash ignores ' + name, fire({effectType: types[name]}, 100, 100, 900), {result: undefined, used: false});
    }
    // The confusion self-hit is a Move effect: the source says so (data/conditions.ts, confusion onBeforeMove).
    const source = readText(path.join(root, 'data', 'conditions.ts'));
    if (!/const activeMove = \{ id: this\.toID\('confused'\), effectType: 'Move', type: '\?\?\?' \};\s+this\.damage\(damage, pokemon, pokemon, activeMove as ActiveMove\);/.test(source)) {
        bad('the confusion self-hit is no longer damage with a Move effect in data/conditions.ts');
    }
}

// The four moves of step G10 against the pinned data: Low Kick's weight table is Grass Knot's (the engine shares
// one), First Impression has Fake Out's first-turn rule, Scald thaws its target and Recover heals half.
// Step G9, Encore: the pinned facts that the engine hard-codes (decision 0015, item 5e): the condition's duration and
// residual order, the failencore flag of the moves a gated member can have (the list in tests/test_pool_g9.c is the pin's
// whole list), and the behaviour of onStart (the Champions version, with the replacement of the queued action),
// onResidual and onDisableMove, called with stand-ins for the battle and the target.
function checkEncore(dex, repo) {
    const move = dex.moves.get('encore');
    const c = move.condition;
    expect('encore duration and residual order', [c.duration, c.onResidualOrder], [3, 16]);
    expect('encore flags, accuracy, target, pp', [move.flags.failencore, move.flags.bypasssub, move.flags.protect,
        move.accuracy, move.target, move.pp], [1, 1, 1, 100, 'normal', 5]);
    const text = readText(path.join(repo, 'tests', 'test_pool_g9.c'));
    const listed = (text.match(/failencore:begin \*\/([\s\S]*?)\/\* failencore:end/) || ['', ''])[1].match(/"[a-z]+"/g) || [];
    expect('failencore moves', dex.moves.all().filter((m) => m.flags.failencore).map((m) => m.id).sort(),
        listed.map((x) => x.slice(1, -1)));
    const slots = (pp) => ({icebeam: {id: 'icebeam', pp}, protect: {id: 'protect', pp: 5}});
    const run = (lastMove, ppOfLast, queued, extra) => {
        const state = {};
        const logs = [];
        const changes = [];
        const target = Object.assign({lastMove, volatiles: {}, getMoveData: (id) => slots(ppOfLast)[id],
            hasItem: () => false}, extra);
        const self = {effectState: state, add: (...a) => logs.push(a), dex,
            queue: {willMove: () => queued, changeAction: (t, a) => changes.push(a)}};
        state.duration = c.duration;
        const result = c.onStart.call(self, target);
        return {result, state, logs: logs.map((l) => l[0] + ':' + l[2]), changes, queued};
    };
    const mv = (id) => dex.moves.get(id);
    expect('onStart without a last move', run(null, 5, null).result, false);
    expect('onStart on struggle', run(mv('struggle'), 5, null).result, false);
    expect('onStart on encore', run(mv('encore'), 5, null).result, false);
    expect('onStart without PP', run(mv('icebeam'), 0, null).result, false);
    expect('onStart on a Dynamaxed target', run(mv('icebeam'), 5, null, {volatiles: {dynamax: {}}}).result, false);
    const plain = run(mv('icebeam'), 5, null);
    expect('onStart without a queued move', [plain.state.move, plain.state.duration, plain.logs, plain.changes.length],
        ['icebeam', 4, ['-start:Encore'], 0]);
    const queued = {moveid: 'protect', priority: 1, order: 200, choice: 'move'};
    const replaced = run(mv('icebeam'), 5, queued);
    expect('onStart with another move queued', [replaced.state.duration, replaced.changes,
        replaced.queued.priority], [3, [{choice: 'move', moveid: 'icebeam', order: 200}], 1 - 4 + 0]);
    const same = run(mv('icebeam'), 5, {moveid: 'icebeam', priority: 0, order: 200, choice: 'move'});
    expect('onStart with the same move queued', [same.state.duration, same.changes.length], [3, 0]);
    const herb = run(mv('icebeam'), 5, queued, {hasItem: (id) => id === 'mentalherb'});
    expect('onStart of a Mental Herb holder', [herb.state.duration, herb.changes.length], [3, 0]);
    // onResidual: it ends the volatile only when the Encored move has no PP; onDisableMove: every other slot.
    const removed = [];
    const ended = (pp) => {
        removed.length = 0;
        c.onResidual.call({effectState: {move: 'icebeam'}}, {getMoveData: () => ({pp}), removeVolatile: (v) => removed.push(v)});
        return removed.slice();
    };
    expect('onResidual with and without PP', [ended(1), ended(0)], [[], ['encore']]);
    const disabled = [];
    c.onDisableMove.call({effectState: {move: 'icebeam'}}, {hasMove: () => true, moveSlots: [{id: 'icebeam'}, {id: 'coil'},
        {id: 'protect'}], disableMove: (id) => disabled.push(id)});
    expect('onDisableMove', disabled, ['coil', 'protect']);
}

// Step G17, the recharge moves: the pinned facts that the engine hard-codes (decision 0015, item 5f): the ten moves with
// flags.recharge are exactly the ten with the mustrecharge self effect, the condition's duration, priority and lock, what
// its onBeforeMove and onStart show, and Sucker Punch's onTry reading the volatile.
function checkRecharge(dex) {
    const move = (id) => dex.moves.get(id);
    const flagged = dex.moves.all().filter((m) => m.flags.recharge).map((m) => m.id).sort();
    const selfs = dex.moves.all().filter((m) => m.self && m.self.volatileStatus === 'mustrecharge').map((m) => m.id).sort();
    expect('recharge flag and mustrecharge self effect', flagged, selfs);
    expect('recharge moves', flagged, ['blastburn', 'eternabeam', 'frenzyplant', 'gigaimpact', 'hydrocannon', 'hyperbeam',
        'meteorassault', 'prismaticlaser', 'roaroftime', 'rockwrecker']);
    expect('hyper beam', [move('hyperbeam').basePower, move('hyperbeam').accuracy, move('hyperbeam').priority], [150, 90, 0]);
    expect('meteor assault (Champions)', move('meteorassault').basePower, 170);
    const c = dex.conditions.get('mustrecharge');
    expect('mustrecharge duration, priority, lock', [c.duration, c.onBeforeMovePriority, c.onLockMove], [2, 11, 'recharge']);
    const logs = [];
    const removed = [];
    const self = {add: (...a) => logs.push(a.map((x) => (typeof x === 'string' ? x : 'POKEMON')).join(':'))};
    const pokemon = {removeVolatile: (v) => removed.push(v)};
    const result = c.onBeforeMove.call(self, pokemon);
    expect('mustrecharge onBeforeMove', [result, logs, removed], [null, ['cant:POKEMON:recharge'], ['mustrecharge', 'truant']]);
    logs.length = 0;
    c.onStart.call(self, pokemon);
    expect('mustrecharge onStart', logs, ['-mustrecharge:POKEMON']);
    // Sucker Punch fails against a Pokemon with the volatile, also when its queued action is a damaging move.
    const onTry = move('suckerpunch').onTry;
    const attack = {choice: 'move', move: {category: 'Physical', id: 'tackle'}};
    const sucker = (willMove, volatiles) => onTry.call({queue: {willMove: () => willMove}}, {}, {volatiles});
    expect('sucker punch', [sucker(attack, {}), sucker(attack, {mustrecharge: {}}), sucker(null, {})], [undefined, false, false]);
}

// Step G22, the weather Speed abilities, Inner Focus and Liquid Voice: the pinned facts that the engine hard-codes
// (decision 0015, item 5s), called on the pinned handlers. The Champions mod overrides none of the six abilities (it has
// no entry by their ids; the source of the generator hashes that file). `formes` are the rows of dfi_pool_forme_legal,
// `itemIds` and `abilityIds` the ids of the pool's headers.
function checkG22(dex, formes, itemIds, abilityIds) {
    const ability = (id) => dex.abilities.get(id);
    // Sand Rush, Swift Swim, Slush Rush, Chlorophyll: x2 Speed in their weather, and in no other, for every weather the
    // handlers name. The engine reads rain, sun, sand and snow of its state; Hail is not in the format (the weather the
    // handlers also accept is never up) and the Primal weathers are not states of the engine.
    const weathers = ['', 'raindance', 'sunnyday', 'sandstorm', 'snowscape', 'hail', 'primordialsea', 'desolateland'];
    const doubled = (id) => weathers.filter((w) => {
        const pokemon = {effectiveWeather: () => w, hasItem: () => false};
        const field = {isWeather: (names) => (Array.isArray(names) ? names : [names]).includes(w)};
        const r = call(ability(id).onModifySpe, battle(ability(id), {field}), [100, pokemon]);
        if (r !== undefined && r.chain !== 2) {
            bad(id + ': onModifySpe gives ' + JSON.stringify(r.chain) + ', not x2');
        }
        return r !== undefined;
    });
    expect('Sand Rush doubles Speed in', doubled('sandrush'), ['sandstorm']);
    expect('Swift Swim doubles Speed in', doubled('swiftswim'), ['raindance', 'primordialsea']);
    expect('Slush Rush doubles Speed in', doubled('slushrush'), ['snowscape', 'hail']);
    expect('Chlorophyll doubles Speed in', doubled('chlorophyll'), ['sunnyday', 'desolateland']);
    for (const id of ['sandrush', 'swiftswim', 'slushrush', 'chlorophyll']) {
        expect(id + ' has no other callback', Object.keys(dex.data.Abilities[id]).filter((k) => /^on/.test(k)).sort(),
            id === 'sandrush' ? ['onImmunity', 'onModifySpe'] : ['onModifySpe']);
    }
    // Utility Umbrella (which makes effectiveWeather ignore sun and rain) is not in the pool, and the only ability of the
    // pool that suppresses the weather (Cloud Nine; Air Lock has no row) stays unmarked (tests/test_pool_weather.c).
    expect('Utility Umbrella is an item of the pool', itemIds.has('utilityumbrella'), false);
    expect('abilities of the pool that suppress the weather',
        [...abilityIds].filter((id) => dex.data.Abilities[id] && dex.data.Abilities[id].suppressWeather).sort(), ['cloudnine']);
    // Sand Rush: immune to Sandstorm and to nothing else that runStatusImmunity asks.
    const immune = (type) => call(ability('sandrush').onImmunity, battle(ability('sandrush')), [type, {}]);
    expect('Sand Rush onImmunity', ['sandstorm', 'hail', 'brn', 'powder', 'trapped', 'psn'].map(immune),
        [false, undefined, undefined, undefined, undefined, undefined]);
    // Inner Focus: the flinch volatile is refused (null), no other; an Intimidate drop of Attack is deleted with
    // -fail|holder|unboost|atk|[from] ability: Inner Focus|[of] holder, a drop by another effect or of another stat is not.
    const focus = ability('innerfocus');
    expect('Inner Focus flinch', call(focus.onTryAddVolatile, battle(focus), [{id: 'flinch'}, {}]), null);
    expect('Inner Focus other volatiles', ['confusion', 'taunt', 'encore'].map(
        (id) => call(focus.onTryAddVolatile, battle(focus), [{id}, {}])), [undefined, undefined, undefined]);
    const boosted = (effectName, boost) => {
        const logs = [];
        const holder = {toString: () => 'HOLDER'};
        const self = battle(focus, {add: (...a) => logs.push(a.map((x) => (typeof x === 'string' ? x : 'POKEMON')).join('|'))});
        call(focus.onTryBoost, self, [boost, holder, {}, {name: effectName}]);
        return {boost, logs};
    };
    expect('Inner Focus vs Intimidate Attack', boosted('Intimidate', {atk: -1}),
        {boost: {}, logs: ['-fail|POKEMON|unboost|atk|[from] ability: Inner Focus|[of] HOLDER']});
    expect('Inner Focus vs Intimidate Attack and Defense', boosted('Intimidate', {atk: -1, def: -1}).boost, {def: -1});
    expect('Inner Focus vs Intimidate, Attack at the cap', boosted('Intimidate', {atk: 0}), {boost: {atk: 0}, logs: []});
    expect('Inner Focus vs another effect', boosted('Snarl', {atk: -1}), {boost: {atk: -1}, logs: []});
    expect('Inner Focus is breakable', focus.flags, {breakable: 1});
    // Intimidate itself (the engine's entry code): one -ability line, a Substitute is -immune, else a boost of Attack by -1
    // as a secondary effect of the ability.
    const intimidate = ability('intimidate').onStart.toString().replace(/\s+/g, ' ');
    expect('Intimidate onStart', /this\.boost\(\{ atk: -1 \}, target, pokemon, null, true\)/.test(intimidate), true);
    // The Flower Veil race: no Inner Focus holder of the pool is a Grass type, so a Grass type that both abilities
    // protect does not exist (the engine does not order the two TryBoost handlers).
    const holders = formes.filter((f) => f.abilities.includes('innerfocus'));
    expect('Grass types with Inner Focus', holders.filter((f) => dex.species.get(f.id).types.includes('Grass')).map((f) => f.id), []);
    expect('Inner Focus has holders', holders.length > 0, true);
    // Liquid Voice: a move with the sound flag becomes Water (not a Dynamaxed user's), nothing else changes; the
    // priority puts it after the other ModifyType handlers; the sound flag is what the tables' flags2 SOUND bit holds.
    const voice = ability('liquidvoice');
    const typeAfter = (type, flags, volatiles) => {
        const move = moveOf(type, {flags});
        call(voice.onModifyType, battle(voice), [move, {volatiles: volatiles || {}}]);
        return move.type;
    };
    expect('Liquid Voice', [typeAfter('Normal', {sound: 1}), typeAfter('Dark', {sound: 1}), typeAfter('Normal', {}),
        typeAfter('Normal', {sound: 1}, {dynamax: {}})], ['Water', 'Water', 'Normal', 'Normal']);
    expect('Liquid Voice onModifyTypePriority', voice.onModifyTypePriority, -1);
    return 1;
}

// Step G32: what the engine reads about the new rows (src/combat/turn.c), called on the pinned handlers. Eruption and Water
// Spout (power 150 x HP / maximum HP, then the engine floors it and clamps it to 1: sim/battle-actions.ts getDamage),
// Freeze-Dry (Water is super effective), Soundproof (a sound move aimed at the holder by another Pokemon is -immune), Unnerve
// (berries of the foes are not eaten while the holder stands) and Speed Boost (+1 Speed in the residual, not in the turn of
// the switch-in). Eject Button is a text fact of the generator (G32_ENTRY_FACTS).
// Step G41, Shadow Tag: the engine refuses the switch of a foe at the TURN boundary (turn.c dfi_switch_trapped). The pinned
// handlers are called on stubs: a foe that is not a Shadow Tag holder and is adjacent to the holder is trapped (hidden), and a
// holder, or a Pokemon that is not adjacent, is not; the maybe-flag follows the same test. Ghost is the one type that is immune
// to `trapped` (runStatusImmunity: typechart `trapped: 3`), so Soak and the forme's types decide it; no other type has the key.
// Shed Shell and Run Away would free the holder: the generator keeps them unmarked.
function checkG41(dex) {
    const tag = dex.abilities.get('shadowtag');
    const run = (fn, who, source, hasTag, adjacent) => {
        const calls = [];
        const pokemon = {hasAbility: (id) => id === 'shadowtag' && hasTag, isAdjacent: () => adjacent,
            tryTrap: (hidden) => calls.push(['tryTrap', hidden]), maybeTrapped: false};
        const b = battle(tag, {effectState: {target: {}}});
        call(fn, b, [pokemon, source]);
        return {calls, maybe: pokemon.maybeTrapped};
    };
    expect('Shadow Tag traps an adjacent foe', run(tag.onFoeTrapPokemon, 'p', undefined, false, true),
        {calls: [['tryTrap', true]], maybe: false});
    expect('Shadow Tag does not trap a holder', run(tag.onFoeTrapPokemon, 'p', undefined, true, true), {calls: [], maybe: false});
    expect('Shadow Tag does not trap a Pokemon that is not adjacent', run(tag.onFoeTrapPokemon, 'p', undefined, false, false),
        {calls: [], maybe: false});
    expect('Shadow Tag marks maybe-trapped', run(tag.onFoeMaybeTrapPokemon, 'p', {}, false, true), {calls: [], maybe: true});
    expect('Shadow Tag does not mark a holder', run(tag.onFoeMaybeTrapPokemon, 'p', {}, true, true), {calls: [], maybe: false});
    expect('the types immune to trapped', TYPES.filter((t) => dex.types.get(t).damageTaken.trapped === 3), ['Ghost']);
    return 1;
}

// Step G47, the status and volatile cures: the pinned handlers of Synchronize, Oblivious, Lum Berry and Mental Herb, called on
// stubs with their own arguments (the calls and log lines the engine reproduces: dfi_synchronize, dfi_lum_berry, dfi_mental_herb
// and the Oblivious branches of turn.c). Synchronize passes psn, tox, brn and par on, never slp or frz, never from Toxic Spikes,
// never to itself or with no source; Oblivious refuses Taunt and cuts Intimidate's Attack drop; Lum Berry eats a status or a
// confusion; Mental Herb is used when a volatile it cures is there and removes them in the list's order.
function checkG47(dex) {
    const sync = dex.abilities.get('synchronize');
    const target = {name: 'T', toString() { return 'T'; }};
    const syncRun = (status, source, effect) => {
        const log = [];
        const b = battle(sync, {add: (...a) => log.push(a)});
        const src = source === 'none' ? undefined : (source === 'self' ? target
            : {name: 'S', trySetStatus: (st, tg, eff) => log.push(['trySetStatus', st.id, tg.name, eff])});
        call(sync.onAfterSetStatus, b, [{id: status}, target, src, effect]);
        return log;
    };
    const activate = ['-activate', target, 'ability: Synchronize'];
    expect('Synchronize passes psn on to the source', syncRun('psn', 'S', undefined),
        [activate, ['trySetStatus', 'psn', 'T', {status: 'psn', id: 'synchronize'}]]);
    expect('Synchronize passes par on', syncRun('par', 'S', undefined)[1][1], 'par');
    expect('Synchronize passes tox on', syncRun('tox', 'S', undefined)[1][1], 'tox');
    expect('Synchronize passes brn on', syncRun('brn', 'S', undefined)[1][1], 'brn');
    expect('Synchronize does not pass slp on', syncRun('slp', 'S', undefined), []);
    expect('Synchronize does not pass frz on', syncRun('frz', 'S', undefined), []);
    expect('Synchronize is not passed back to a source with no source', syncRun('psn', 'none', undefined), []);
    expect('Synchronize does nothing for its own status', syncRun('psn', 'self', undefined), []);
    expect('Synchronize does not answer Toxic Spikes', syncRun('psn', 'S', {id: 'toxicspikes'}), []);
    const obl = dex.abilities.get('oblivious');
    const holder = {name: 'H', toString() { return 'H'; }};
    const oblLog = [];
    const b1 = battle(obl, {add: (...a) => oblLog.push(a)});
    const taunted = call(obl.onTryHit, b1, [holder, holder, {id: 'taunt'}]);
    expect('Oblivious refuses Taunt, with the -immune line', [taunted, oblLog],
        [null, [['-immune', holder, '[from] ability: Oblivious']]]);
    oblLog.length = 0;
    expect('Oblivious does not refuse a tackle', call(obl.onTryHit, b1, [holder, holder, {id: 'tackle'}]), undefined);
    const boost = {atk: -1, spe: -1};
    const intimidate = {name: 'Intimidate'};
    call(obl.onTryBoost, b1, [boost, holder, holder, intimidate]);
    expect('Oblivious cuts the Attack drop of Intimidate, with -fail', [boost, oblLog],
        [{spe: -1}, [['-fail', holder, 'unboost', 'atk', '[from] ability: Oblivious', '[of] H']]]);
    const herbLog = [];
    const holding = {status: '', volatiles: {taunt: {}}, useItem: () => { herbLog.push('useItem'); return true; },
        removeVolatile: (id) => herbLog.push('remove:' + id)};
    call(dex.items.get('mentalherb').onUpdate, battle(dex.items.get('mentalherb')), [holding]);
    expect('Mental Herb is used and removes its volatiles in the list order', herbLog,
        ['useItem', 'remove:attract', 'remove:taunt', 'remove:encore', 'remove:torment', 'remove:disable', 'remove:healblock']);
    const lumLog = [];
    const lum = dex.items.get('lumberry');
    call(lum.onUpdate, battle(lum), [{status: '', volatiles: {}, eatItem: () => lumLog.push('eat')}]);
    call(lum.onUpdate, battle(lum), [{status: 'par', volatiles: {}, eatItem: () => lumLog.push('eat')}]);
    call(lum.onUpdate, battle(lum), [{status: '', volatiles: {confusion: {}}, eatItem: () => lumLog.push('eat')}]);
    expect('Lum Berry is eaten for a status or a confusion, not otherwise', lumLog, ['eat', 'eat']);
    return 1;
}

// Step G33, the multi-hit batch and Mirror Armor: the pinned facts that the engine hard-codes (decision 0015, item 5y). The
// four moves' hit counts and Triple Axel's rising power; Mirror Armor's handler against stubs: it deletes every drop of
// another Pokemon that is still one (a stat at -6 has none), shows its ability line and gives the drop to a source that
// stands, and leaves a self change, a bounced drop, and a rise alone; no Grass-type forme has the ability.
function checkG33(dex) {
    expect('multihit', ['dualwingbeat', 'tripleaxel', 'twinbeam'].map((id) => dex.moves.get(id).multihit), [2, 3, 2]);
    expect('multiaccuracy', ['dualwingbeat', 'tripleaxel', 'twinbeam'].map((id) => !!dex.moves.get(id).multiaccuracy),
        [false, true, false]);
    // Population Bomb is not marked (its learners have no marked ability) but keeps its pinned fact for the follow-up.
    expect('Population Bomb', [dex.moves.get('populationbomb').multihit, !!dex.moves.get('populationbomb').multiaccuracy], [10, true]);
    const axe = dex.moves.get('tripleaxel');
    expect('Triple Axel power', [1, 2, 3].map((hit) => call(axe.basePowerCallback, battle(axe), [{}, {}, {hit}])), [20, 40, 60]);
    const armor = dex.abilities.get('mirrorarmor');
    const run = (boost, target, source, effect) => {
        const logs = [];
        const gave = [];
        const b = battle(armor, {add: (...a) => logs.push(a.map((x) => (typeof x === 'string' ? x : 'POKEMON')).join('|')),
            boost: (...a) => gave.push(a.map((x) => (x && x.hp !== undefined ? (x === source ? 'source' : 'target') : x)))});
        const left = Object.assign({}, boost);
        call(armor.onTryBoost, b, [left, target, source, effect]);
        return {left, logs, gave};
    };
    const target = {boosts: {atk: 0, spa: -6}, hp: 100};
    const source = {boosts: {}, hp: 100};
    expect('Mirror Armor bounces a drop', run({atk: -1, spa: 1}, target, source, {name: 'Intimidate'}),
        {left: {spa: 1}, logs: ['-ability|POKEMON|Mirror Armor'], gave: [[{atk: -1}, 'source', 'target', null, true]]});
    expect('Mirror Armor, a stat at -6 keeps its drop', run({spa: -1}, target, source, {name: 'Snarl'}),
        {left: {spa: -1}, logs: [], gave: []});
    expect('Mirror Armor, a source that has fainted', run({atk: -1}, target, {boosts: {}, hp: 0}, {name: 'Intimidate'}),
        {left: {}, logs: [], gave: []});
    expect('Mirror Armor, a self change', run({atk: -1}, target, target, {name: 'Close Combat'}), {left: {atk: -1}, logs: [], gave: []});
    expect('Mirror Armor, a drop that has bounced', run({atk: -1}, target, source, {name: 'Mirror Armor'}),
        {left: {atk: -1}, logs: [], gave: []});
    expect('Mirror Armor, no source', run({atk: -1}, target, null, {name: 'Spikes'}), {left: {atk: -1}, logs: [], gave: []});
    expect('Mirror Armor, a rise', run({atk: 1}, target, source, {name: 'Swords Dance'}), {left: {atk: 1}, logs: [], gave: []});
    const grass = [];
    for (const s of dex.species.all()) {
        if (Object.values(s.abilities).includes('Mirror Armor') && s.types.includes('Grass')) {
            grass.push(s.id);
        }
    }
    expect('no Grass-type forme has Mirror Armor', grass, []);
    // The accuracy of the later hits of a multiaccuracy move (src/combat/turn.c dfi_accuracy_check, later_hit). The Champions
    // loop (data/mods/champions/scripts.ts:481-510) scales `move.accuracy` by the two stages in floating point with no floor,
    // `accuracy /= boostTable[-boost]` and so on, then randomChance(accuracy, 100) = random(100) < accuracy. The engine has no
    // floating point, so it compares v * D < N for the exact rational N / D (accuracy x (3 + a) / 3 or x 3 / (3 - a), then x 3 /
    // (3 + e) or x (3 - e) / 3). Here both are computed for the accuracy of Triple Axel and every pair of stages; the number of
    // values v in 0..99 that hit must be equal (a double that lands next to an integer would make them differ).
    expect('Triple Axel accuracy', axe.accuracy, 90);
    const table = [1, 4 / 3, 5 / 3, 2, 7 / 3, 8 / 3, 3];
    let pairs = 0;
    for (let a = -6; a <= 6; a++) {
        for (let e = -6; e <= 6; e++) {
            let accuracy = axe.accuracy;
            if (a > 0) accuracy *= table[a]; else accuracy /= table[-a];
            if (e > 0) accuracy /= table[e]; else if (e < 0) accuracy *= table[-e];
            const numA = a > 0 ? 3 + a : 3, denA = a > 0 ? 3 : 3 - a;
            const numE = e > 0 ? 3 : 3 - e, denE = e > 0 ? 3 + e : 3;
            const numerator = axe.accuracy * numA * numE, denominator = denA * denE;
            let reference = 0, engine = 0;
            for (let v = 0; v < 100; v++) {
                reference += v < accuracy ? 1 : 0;
                engine += v * denominator < numerator ? 1 : 0;
            }
            expect('multiaccuracy a ' + a + ' e ' + e, engine, reference);
            pairs++;
        }
    }
    expect('multiaccuracy pairs', pairs, 169);
    return 1;
}

// Step G44 (simple moves): the four handlers' pinned rules, called with stubs as the probes above do. Power Trip adds 20 per
// positive stage (Pokemon.positiveBoosts, sim/pokemon.ts:1201-1208: a negative stage adds nothing); Thunder's onModifyMove is
// Hurricane's (true in rain, 50 under sun, the target's weather); Ice Fang's secondaries are the freeze and the flinch, in
// this order; Tri Attack's onHit draws sample(['brn', 'par', 'frz']) and sets that status.
function checkG44(dex) {
    const pt = dex.moves.get('powertrip');
    const positive = (boosts) => Object.values(boosts).reduce((n, b) => (b > 0 ? n + b : n), 0);
    const powerOf = (boosts) => call(pt.basePowerCallback, battle(pt), [{positiveBoosts: () => positive(boosts)}, {}, {basePower: 20}]);
    expect('Power Trip, no boost', powerOf({}), 20);
    expect('Power Trip, a negative stage adds nothing', powerOf({atk: -2}), 20);
    expect('Power Trip, two positive and one negative', powerOf({atk: 2, def: -1, spe: 1}), 80);
    expect('Power Trip, every stat at +6 and accuracy and evasion too', powerOf({atk: 6, def: 6, spa: 6, spd: 6, spe: 6, accuracy: 6, evasion: 6}), 860);
    const th = dex.moves.get('thunder');
    const thunderAccuracy = (weather) => {
        const move = {accuracy: 70};
        call(th.onModifyMove, battle(th), [move, {}, {effectiveWeather: () => weather}]);
        return move.accuracy;
    };
    expect('Thunder accuracy by weather', ['raindance', 'primordialsea', 'sunnyday', 'desolateland', ''].map(thunderAccuracy),
        [true, true, 50, 50, 70]);
    expect('Thunder secondary', th.secondary, {chance: 30, status: 'par'});
    const fang = dex.moves.get('icefang');
    expect('Ice Fang secondaries', fang.secondaries, [{chance: 10, status: 'frz'}, {chance: 10, volatileStatus: 'flinch'}]);
    const tri = dex.moves.get('triattack');
    expect('Tri Attack secondary chance', tri.secondary.chance, 20);
    const picks = [0, 1, 2].map((v) => {
        const sampled = [];
        const set = [];
        const b = battle(tri, {sample: (list) => { sampled.push(list.join(',')); return list[v]; }});
        call(tri.secondary.onHit, b, [{trySetStatus: (status) => set.push(status)}, {}]);
        return {sampled, set};
    });
    expect('Tri Attack draws one pick of three', picks, [
        {sampled: ['brn,par,frz'], set: ['brn']}, {sampled: ['brn,par,frz'], set: ['par']}, {sampled: ['brn,par,frz'], set: ['frz']}]);
    return 1;
}

// Step G54 (moves): the multi-hit rows and the side condition, read from the pinned data as the generator's facts read them.
// Scale Shot's self boost is after the last hit (its selfBoost), Icicle Spear and Scale Shot draw a count of 2 to 5 hits,
// Quick Guard is a priority 3 side condition, Upper Hand a priority 3 move whose flinch is its secondary, Heal Pulse never
// misses and Strength Sap has accuracy 100 (its -6 check is its onTryHit, before the accuracy check).
function checkG54(dex) {
    const ice = dex.moves.get('iciclespear');
    expect('Icicle Spear accuracy and multihit', [ice.accuracy, ice.multihit], [100, [2, 5]]);
    const sc = dex.moves.get('scaleshot');
    expect('Scale Shot accuracy and multihit', [sc.accuracy, sc.multihit], [90, [2, 5]]);
    expect('Scale Shot self boost', sc.selfBoost, {boosts: {def: -1, spe: 1}});
    const qg = dex.moves.get('quickguard');
    expect('Quick Guard side condition and priority', [qg.sideCondition, qg.priority], ['quickguard', 3]);
    const uh = dex.moves.get('upperhand');
    expect('Upper Hand priority', uh.priority, 3);
    expect('Upper Hand flinch', uh.secondary, {chance: 100, volatileStatus: 'flinch'});
    expect('Heal Pulse accuracy', dex.moves.get('healpulse').accuracy, true);
    expect('Strength Sap accuracy', dex.moves.get('strengthsap').accuracy, 100);
    return 1;
}

// Step G62 (Haze, decision 0031): accuracy true, a field target and no protect flag; onHitField clears the boosts of the
// standing actives (getAllActive, the default that skips a fainted Pokemon), checked by its text in gen_closure.py.
function checkG62(dex) {
    const haze = dex.moves.get('haze');
    expect('Haze accuracy and target', [haze.accuracy, haze.target], [true, 'all']);
    expect('Haze has no protect flag', haze.flags.protect === undefined, true);
    expect('Haze priority', haze.priority, 0);
    return 1;
}

function checkG32(dex) {
    for (const id of ['eruption', 'waterspout']) {
        const m = dex.moves.get(id);
        expect(id + ' power', [200, 400, 1, 100].map((hp) => call(m.basePowerCallback, battle(m), [{hp, maxhp: 400}, {}, {basePower: 150}])),
            [75, 150, 0.375, 37.5]);
    }
    const freeze = dex.moves.get('freezedry');
    expect('Freeze-Dry onEffectiveness', ['Water', 'Grass', 'Ice', 'Fire'].map((t) => call(freeze.onEffectiveness, battle(freeze), [0, {}, t])),
        [1, undefined, undefined, undefined]);
    expect('Freeze-Dry in the Champions mod has no secondary', freeze.secondary === undefined || freeze.secondary === null, true);
    const sound = dex.abilities.get('soundproof');
    const probe = (flags, same) => {
        const logs = [];
        const holder = {};
        const r = call(sound.onTryHit, battle(sound, {add: (...a) => logs.push(a.map((x) => (typeof x === 'string' ? x : 'POKEMON')).join('|'))}),
            [holder, same ? holder : {}, moveOf('Normal', {flags})]);
        return {r, logs};
    };
    expect('Soundproof vs a sound move', probe({sound: 1}, false), {r: null, logs: ['-immune|POKEMON|[from] ability: Soundproof']});
    expect('Soundproof vs another move', probe({}, false), {logs: []});
    expect('Soundproof vs its own sound move', probe({sound: 1}, true), {logs: []});
    const unnerve = dex.abilities.get('unnerve');
    expect('Unnerve', [true, false].map((unnerved) => call(unnerve.onFoeTryEatItem, battle(unnerve, {effectState: {unnerved}}), [])), [false, true]);
    const boost = dex.abilities.get('speedboost');
    expect('Speed Boost', [0, 1, 3].map((activeTurns) => {
        const boosts = [];
        call(boost.onResidual, battle(boost, {boost: (b) => boosts.push(b)}), [{activeTurns}]);
        return boosts;
    }), [[], [{spe: 1}], [{spe: 1}]]);
    expect('Speed Boost residual order', [boost.onResidualOrder, boost.onResidualSubOrder], [28, 2]);
    return 1;
}

// Step G19, Coaching and Glaive Rush: the pinned facts that the engine hard-codes (decision 0015, item 5i): Coaching's boosts,
// target and flags, and Glaive Rush's self effect and condition (never-miss, double damage, the removal before the next move).
function checkG19(dex) {
    const move = (id) => dex.moves.get(id);
    const c = move('coaching');
    expect('coaching', [c.boosts, c.target, c.accuracy, c.category, c.flags.protect, c.flags.bypasssub],
        [{atk: 1, def: 1}, 'adjacentAlly', true, 'Status', undefined, 1]);
    const g = move('glaiverush');
    expect('glaive rush', [g.basePower, g.accuracy, g.category, g.self, g.flags.protect], [120, 100, 'Physical',
        {volatileStatus: 'glaiverush'}, 1]);
    const cond = g.condition;
    expect('glaiverush condition', [cond.noCopy, cond.onBeforeMovePriority], [true, 100]);
    expect('glaiverush onAccuracy', cond.onAccuracy.call({}), true);
    expect('glaiverush onSourceModifyDamage', cond.onSourceModifyDamage.call({chainModify: (x) => ['chain', x]}), ['chain', 2]);
    const removed = [];
    cond.onBeforeMove.call({debug: () => {}}, {removeVolatile: (v) => removed.push(v)});
    expect('glaiverush onBeforeMove', removed, ['glaiverush']);
    const logs = [];
    cond.onStart.call({add: (...a) => logs.push(a.map((x) => (typeof x === 'string' ? x : 'POKEMON')).join(':'))}, {});
    expect('glaiverush onStart is silent', logs, ['-singlemove:POKEMON:Glaive Rush:[silent]']);
}

// Step G26, Perish Song: the pinned facts that the engine hard-codes (decision 0015, item 5w), called on the pinned
// handlers. The Champions mod has no entry of Perish Song (data/mods/champions/moves.ts is hashed by the generator).
function checkG26(dex) {
    const move = dex.moves.get('perishsong');
    expect('perish song', [move.basePower, move.accuracy, move.category, move.type, move.target, move.pp, move.priority],
        [0, true, 'Status', 'Normal', 'all', 5, 0]);
    // No protect flag: Protect and Wide Guard let it through (checkMoveBypassesProtect), and bypasssub: Substitute does not stop it.
    expect('perish song flags', Object.keys(move.flags).sort(), ['bypasssub', 'distance', 'metronome', 'sound']);
    const c = move.condition;
    expect('perishsong condition', [c.duration, c.onResidualOrder, c.onResidualPriority, c.onResidualSubOrder], [4, 24, undefined, undefined]);
    // The residual order 24 belongs to Perish Song alone among the entries that the engine's residual list has (the others
    // with an order at or above 23 are moves that no row models).
    const orders = [];
    for (const table of [dex.data.Moves, dex.data.Abilities, dex.data.Items, dex.data.Conditions]) {
        for (const [id, entry] of Object.entries(table)) {
            if (entry.condition && entry.condition.onResidualOrder === 24) orders.push(id);
            if (entry.onResidualOrder === 24) orders.push(id);
        }
    }
    expect('entries with onResidualOrder 24', orders, ['perishsong']);
    // The condition's callbacks: the count is the duration after the decrement of fieldEvent, the end shows perish0 and faints.
    const logs = [];
    const self = {add: (...a) => logs.push(a.map((x) => (typeof x === 'string' ? x : 'POKEMON')).join(':'))};
    let fainted = 0;
    c.onEnd.call(self, {faint() { fainted += 1; }});
    expect('perishsong onEnd', [logs, fainted], [['-start:POKEMON:perish0'], 1]);
    logs.length = 0;
    c.onResidual.call(self, {volatiles: {perishsong: {duration: 3}}});
    c.onResidual.call(self, {volatiles: {perishsong: {duration: 1}}});
    expect('perishsong onResidual', logs, ['-start:POKEMON:perish3', '-start:POKEMON:perish1']);
    // onHitField over the active Pokemon: what a Pokemon with and without the volatile, with a TryHit that stops it and
    // with none left to take it, gets.
    const run = (mons, tryHit) => {
        const out = [];
        const battle = {
            getAllActive: () => mons,
            runEvent: (name, pokemon) => (name === 'Invulnerability' ? true : tryHit(pokemon)),
            add: (...a) => out.push(a.map((x) => (typeof x === 'string' ? x : 'POKEMON')).join(':')),
        };
        const result = move.onHitField.call(battle, {}, {}, move);
        return {result, out, added: mons.map((m) => m.added || 0)};
    };
    const mon = (has) => {
        const m = {volatiles: has ? {perishsong: {}} : {}, added: 0, addVolatile(id) { m.added += 1; m.volatiles[id] = {}; }};
        return m;
    };
    expect('perish song on two fresh Pokemon', run([mon(false), mon(false)], () => true),
        {result: undefined, out: ['-start:POKEMON:perish3:[silent]', '-start:POKEMON:perish3:[silent]', '-fieldactivate:move: Perish Song'], added: [1, 1]});
    expect('perish song on a fresh and an infected Pokemon', run([mon(true), mon(false)], () => true),
        {result: undefined, out: ['-start:POKEMON:perish3:[silent]', '-fieldactivate:move: Perish Song'], added: [0, 1]});
    expect('perish song on infected Pokemon only', run([mon(true), mon(true)], () => true),
        {result: false, out: [], added: [0, 0]});
    const stopped = [mon(false), mon(false)];
    expect('perish song with a TryHit that stops the first', run(stopped, (p) => (p === stopped[0] ? null : true)),
        {result: undefined, out: ['-start:POKEMON:perish3:[silent]', '-fieldactivate:move: Perish Song'], added: [0, 1]});
    const all = [mon(false)];
    expect('perish song with every TryHit stopped is no failure', run(all, () => null),
        {result: undefined, out: [], added: [0]});
    // Good as Gold is the one marked ability that stops it (a status move of another Pokemon); the user's own does not.
    const gold = dex.abilities.get('goodasgold');
    const goldLogs = [];
    const goldSelf = {add: (...a) => goldLogs.push(a.map((x) => (typeof x === 'string' ? x : 'POKEMON')).join(':'))};
    const other = {}, user = {};
    expect('Good as Gold against a Perish Song of another', [gold.onTryHit.call(goldSelf, other, user, move), goldLogs],
        [null, ['-immune:POKEMON:[from] ability: Good as Gold']]);
    expect('Good as Gold against its own Perish Song', gold.onTryHit.call(goldSelf, user, user, move), undefined);
    // Soundproof stops it too (a sound move of another Pokemon): step G32 marked the ability, and the cast handles it.
    const proof = dex.abilities.get('soundproof');
    expect('Soundproof', [proof.onTryHit.call({add() {}}, other, user, move)], [null]);
    return 1;
}

// Step G27, Disable and Cursed Body: the pinned facts that the engine hard-codes (decision 0015, the G27 item), run on the
// pinned callbacks: Disable's onTryHit (no last move, Struggle, a Z or Max move fail), its condition (duration 5, one turn off
// when the target has not moved or when Cursed Body acts, the failures of onStart, the two -start lines, the order, the
// BeforeMove stop and its Champions form, the bar on the slot of its move) and Cursed Body's roll and conditions.
function checkG27(dex) {
    const move = (id) => dex.moves.get(id);
    const d = move('disable');
    expect('disable', [d.accuracy, d.priority, d.category, d.target, d.flags.protect, d.flags.bypasssub, d.pp],
        [100, 0, 'Status', 'normal', 1, 1, 20]);
    const tryHit = (lastMove) => d.onTryHit.call({}, {lastMove});
    expect('disable onTryHit', [tryHit(undefined), tryHit({id: 'struggle'}), tryHit({id: 'tackle'}),
        tryHit({id: 'tackle', isMax: true}), tryHit({id: 'tackle', isZOrMaxPowered: true})],
        [false, false, undefined, false, false]);
    const c = d.condition;
    expect('disable condition', [c.duration, c.noCopy, c.onResidualOrder, c.onBeforeMovePriority], [5, true, 17, 7]);
    // onStart: the target is queued (willMove), or acts now (the active Pokemon with its own move), or neither.
    const start = (opts) => {
        const logs = [];
        const effectState = {duration: 5};
        const self = {
            queue: {willMove: () => opts.queued}, activePokemon: opts.active, activeMove: opts.activeMove, effectState,
            add: (...a) => logs.push(a.map((x) => (typeof x === 'string' ? x : 'POKEMON')).join(':')),
            debug: () => {},
        };
        const pokemon = {lastMove: opts.lastMove, moveSlots: opts.slots || []};
        if (opts.active === true) self.activePokemon = pokemon;
        const result = c.onStart.call(self, pokemon, 'SOURCE', opts.effect || {effectType: 'Move', name: 'Disable'});
        return [result, effectState.duration, effectState.move, logs];
    };
    const tackle = {id: 'tackle', name: 'Tackle'};
    const slots = [{id: 'tackle', pp: 5}];
    expect('disable onStart: the target has not moved', start({queued: true, lastMove: tackle, slots}),
        [undefined, 4, 'tackle', ['-start:POKEMON:Disable:Tackle']]);
    expect('disable onStart: it has moved', start({queued: false, lastMove: tackle, slots}),
        [undefined, 5, 'tackle', ['-start:POKEMON:Disable:Tackle']]);
    expect('disable onStart: Cursed Body (the active Pokemon, a move of its own)',
        start({queued: false, active: true, activeMove: {isExternal: false}, lastMove: tackle, slots,
            effect: {effectType: 'Ability', name: 'Cursed Body'}}),
        [undefined, 4, 'tackle', ['-start:POKEMON:Disable:Tackle:[from] ability: Cursed Body:[of] SOURCE']]);
    expect('disable onStart: no last move', start({queued: false, lastMove: undefined, slots})[0], false);
    expect('disable onStart: the move has no PP', start({queued: false, lastMove: tackle, slots: [{id: 'tackle', pp: 0}]})[0], false);
    // onBeforeMove: only the barred move stops, with the cant line and no PP.
    const before = (condition, barred, moveId, flags) => {
        const logs = [];
        const self = {effectState: {move: barred}, add: (...a) => logs.push(a.map((x) => (typeof x === 'string' ? x : x.id || 'X')).join(':'))};
        return [condition.onBeforeMove.call(self, 'ATTACKER', 'DEFENDER', {id: moveId, flags: flags || {}}), logs];
    };
    expect('disable onBeforeMove', [before(c, 'tackle', 'tackle'), before(c, 'tackle', 'growl')],
        [[false, ['cant:ATTACKER:Disable:tackle']], [undefined, []]]);
    // The Champions mod: the same, except that a move with the cantusetwice flag is not stopped (no marked move has it).
    const champ = dex.moves.get('disable').condition;
    expect('disable Champions onBeforeMove', [before(champ, 'tackle', 'tackle'), before(champ, 'tackle', 'tackle', {cantusetwice: 1})],
        [[false, ['cant:ATTACKER:Disable:tackle']], [undefined, []]]);
    // onDisableMove bars the slot of its move only.
    const barred = [];
    c.onDisableMove.call({effectState: {move: 'tackle'}}, {moveSlots: [{id: 'tackle'}, {id: 'growl'}], disableMove: (id) => barred.push(id)});
    expect('disable onDisableMove', barred, ['tackle']);
    // Cursed Body: 3 in 10 on a damaging hit that is not Struggle's, never when the attacker is disabled already.
    const a = dex.abilities.get('cursedbody');
    const hit = (volatiles, moveOpts, roll) => {
        const added = [];
        const draws = [];
        const self = {randomChance: (n, m) => { draws.push([n, m]); return roll; }, effectState: {target: 'HOLDER'}};
        const source = {volatiles, addVolatile: (...args) => added.push(args)};
        a.onDamagingHit.call(self, 7, 'TARGET', source, moveOpts);
        return [added, draws];
    };
    expect('cursed body', [hit({}, {id: 'tackle', flags: {}}, true), hit({}, {id: 'tackle', flags: {}}, false),
        hit({disable: {}}, {id: 'tackle', flags: {}}, true), hit({}, {id: 'struggle', flags: {}}, true),
        hit({}, {id: 'tackle', isMax: true, flags: {}}, true), hit({}, {id: 'tackle', flags: {futuremove: 1}}, true)],
        [[[['disable', 'HOLDER']], [[3, 10]]], [[], [[3, 10]]], [[], []], [[], []], [[], []], [[], []]]);
}

function checkG10Moves(dex) {
    const move = (id) => dex.moves.get(id);
    const power = (m, weight) => call(m.basePowerCallback, battle(m), [{}, {getWeight() { return weight; }}]);
    const weights = [0, 99, 100, 101, 249, 250, 499, 500, 999, 1000, 1999, 2000, 5000];
    const table = [20, 20, 40, 40, 40, 60, 60, 80, 80, 100, 100, 120, 120];
    expect('lowkick power by weight', weights.map((w) => power(move('lowkick'), w)), table);
    expect('grassknot power by weight', weights.map((w) => power(move('grassknot'), w)), table);
    expect('lowkick type and category', [move('lowkick').type, move('lowkick').category], ['Fighting', 'Physical']);
    for (const id of ['firstimpression', 'fakeout']) {
        const m = move(id);
        const tried = (n) => call(m.onTry, battle(m, {hint() {}}), [{activeMoveActions: n}]);
        expect(id + ' onTry on the first and the second move action', [tried(1), tried(2)], [undefined, false]);
        const disabled = [];
        for (const n of [0, 1]) {
            call(m.onDisableMove, battle(m), [{activeMoveActions: n, disableMove(x) { disabled.push([n, x]); }}]);
        }
        expect(id + ' onDisableMove', disabled, [[1, id]]);
    }
    expect('firstimpression base power and priority (Champions)', [move('firstimpression').basePower,
        move('firstimpression').priority], [100, 2]);
    const scald = move('scald');
    expect('scald thawsTarget and defrost', [scald.thawsTarget, scald.flags.defrost], [true, 1]);
    expect('scald secondary', [scald.secondary.chance, scald.secondary.status], [30, 'brn']);
    expect('recover heal', move('recover').heal, [1, 2]);
    // The columns of the whole pool read every move: the moves with a heal field and with thawsTarget in the pin.
    const heals = [];
    const thaws = [];
    for (const m of dex.moves.all()) {
        if (m.isNonstandard === 'Future' || m.isNonstandard === 'Unobtainable' || m.isNonstandard === 'CAP') continue;
        if (m.heal) heals.push([m.id, m.heal]);
        if (m.thawsTarget) thaws.push(m.id);
    }
    expect('moves with thawsTarget in the pin', thaws.filter((id) => ['scald', 'matchagotcha', 'scorchingsands'].includes(id)),
        ['matchagotcha', 'scald', 'scorchingsands']);
    expect('recover and slackoff heal a half', heals.filter(([id]) => ['recover', 'slackoff'].includes(id)),
        [['recover', [1, 2]], ['slackoff', [1, 2]]]);
    // A Pokemon with Heal Block and Throat Chop has two BeforeMove handlers of equal priority; tools/reference/
    // trace_to_c.py drops their shuffle because no move is stopped by both: none has both the heal and the sound flag
    // (build_pool and tests/test_pool_tables.c check the pool's moves, this reads every move of the pin).
    expect('moves with both the heal and the sound flag in the pin',
        dex.moves.all().filter((m) => m.flags.heal && m.flags.sound).map((m) => m.id), []);
}

// The callbacks that change the priority of a move or the Speed of a Pokemon, on the entry or on its own condition
// (Unburden's volatile). The engine implements Prankster (+1 for a status move), Gale Wings (+1 for a Flying move at full HP, step G34), Unburden (x2 Speed without an item)
// and Choice Scarf (x1.5 Speed); every other modelled row has none.
const ORDER_CALLBACKS = ['onModifyPriority', 'onFractionalPriority', 'onModifySpe'];
const ENGINE_ORDER = {
    ability: {prankster: ['onModifyPriority'], galewings: ['onModifyPriority'], unburden: ['condition.onModifySpe'], sandrush: ['onModifySpe'],
        swiftswim: ['onModifySpe'], slushrush: ['onModifySpe'], chlorophyll: ['onModifySpe']},
    item: {choicescarf: ['onModifySpe']},
};
function orderCallbacks(raw) {
    return [...ORDER_CALLBACKS.filter((k) => raw[k] !== undefined),
        ...ORDER_CALLBACKS.filter((k) => raw.condition && raw.condition[k] !== undefined).map((k) => 'condition.' + k)];
}

function checkAbilities(dex, rows, moveIds, unmodeled, unmodeledMoves) {
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
            // A modelled row without a family does none of the family things. An UNMODELED row is refused whatever it
            // does: Dragonize (Mega Dragonite) is an "-ate" ability, Electric Surge a terrain setter, Huge Power doubles
            // Attack; a new family follows when the engine has the mechanic.
            if (!unmodeled.has(row.id)) {
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
            // The moves it does not change: the listed ones, and of the pool's moves only Weather Ball is among them.
            for (const id of NO_MODIFY_TYPE) {
                expect(row.id + ' leaves ' + id + ' alone', ateLeavesAlone(ability, id), true);
            }
            expect(row.id + ' changes a Normal move of another id', ateLeavesAlone(ability, 'probe'), false);
            // The engine skips two moves of the list, Weather Ball and Terrain Pulse (dfi_ate_excluded); no other move of
            // the list that the pool has is modelled.
            expect('the modelled pool moves that ' + row.id + ' leaves alone',
                [...moveIds.values()].filter((id) => NO_MODIFY_TYPE.includes(id) && !unmodeledMoves.has(id)),
                ['weatherball', 'terrainpulse']);
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
            // Sand Stream and Snow Warning have no guard: the Primal Pokemon of rain and sun are not special to them.
            const [species, orb] = PRIMAL[weather] || ['groudon', 'redorb'];
            const guarded = PRIMAL[weather] !== undefined;
            expect(row.id + ' with the Primal orb', setterEffect(ability, species, orb),
                {weather: guarded ? null : weather, terrain: null});
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
        // A holder is a species of its own, or a Mega forme (Fairy Aura is Floette-Mega's only: no species has it in
        // Champions). The Mega forme is legal through its base forme with its stone, which the validator accepts by
        // the Mega's name and rewrites; its moves are the base forme's.
        const holders = dex.species.all().filter((s) => s.exists && (!s.battleOnly || s.isMega) &&
            Object.values(s.abilities).some((a) => toId(a) === row.id));
        const name = dex.abilities.get(row.id).name;
        const legal = holders.some((s) => !validator.validateSet(set(s.name, name,
            s.isMega ? dex.items.get(s.requiredItem).name : '', [probeMove(s.isMega ? dex.species.get(s.battleOnly) : s)]), {}));
        if (!legal) {
            bad('ability ' + row.id + ' is not legal on any species of ' + FORMAT_ID + ' (' + holders.length + ' declare it)');
        }
    }
}

// The legal moves and abilities of the formes against the pinned validator.
function checkFormes(dex, validator, rows, moves, abilities) {
    const set = (species, ability, moveNames) => ({
        name: '', species, item: '', ability, moves: moveNames, nature: 'Adamant', gender: '',
        evs: {hp: 2, atk: 0, def: 0, spa: 0, spd: 0, spe: 0}, ivs: {hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31},
        level: 50,
    });
    const poolMoves = [...moves.entries()].sort((a, b) => a[0] - b[0]);
    const poolAbilities = [...abilities.entries()].sort((a, b) => a[0] - b[0]);
    let bases = 0;
    let probes = 0;
    for (const row of rows) {
        const species = dex.species.get(row.id);
        if (!species.exists) {
            bad('forme ' + row.id + ' does not exist');
            continue;
        }
        const learnBit = (number) => ((row.bytes[number >> 3] >> (number & 7)) & 1) === 1;
        if (species.isMega) {
            expect(row.id + ' (Mega) learnable bytes', row.bytes, row.bytes.map(() => 0));
            expect(row.id + ' (Mega) abilities', row.abilities, [Object.values(species.abilities).map((a) => dex.abilities.get(a).id)[0]]);
            expect(row.id + ' (Mega) declares one ability', Object.values(species.abilities).length, 1);
            continue;
        }
        bases += 1;
        if (row.abilities.length === 0) {
            bad(row.id + ' has no legal ability');
            continue;
        }
        const own = dex.abilities.get(row.abilities[0]).name;
        // The moves: a set of the forme with one move is accepted exactly when the bit is set.
        for (const [number, id] of poolMoves) {
            const move = dex.moves.get(id);
            const problems = validator.validateSet(set(species.name, own, [move.name]), {});
            probes += 1;
            if ((problems === null || problems === undefined || problems.length === 0) !== learnBit(number)) {
                bad(row.id + ' ' + id + ': the validator says ' + (problems ? 'illegal' : 'legal') + ', the bit says ' +
                    (learnBit(number) ? 'learnable' : 'not learnable'));
            }
        }
        for (let number = poolMoves.length; number < row.bytes.length * 8; ++number) {
            if (learnBit(number)) {
                bad(row.id + ': bit ' + number + ' is set beyond the last move');
            }
        }
        // The abilities: a set of the forme with a learnable move and the ability is accepted exactly when the ability is listed.
        const probe = poolMoves.find(([number]) => learnBit(number));
        if (probe === undefined) {
            bad(row.id + ' learns no pool move');
            continue;
        }
        for (const [, id] of poolAbilities) {
            const ability = dex.abilities.get(id);
            const problems = validator.validateSet(set(species.name, ability.name, [dex.moves.get(probe[1]).name]), {});
            probes += 1;
            const accepted = problems === null || problems === undefined || problems.length === 0;
            if (accepted !== row.abilities.includes(id)) {
                bad(row.id + ' ' + id + ': the validator says ' + (accepted ? 'legal' : 'illegal') + ', the list says ' +
                    (row.abilities.includes(id) ? 'legal' : 'not legal'));
            }
        }
        // The slot order of the list is the pokedex's.
        const declared = Object.values(species.abilities).map((a) => dex.abilities.get(a).id).filter((a) => row.abilities.includes(a));
        expect(row.id + ' ability order', row.abilities, declared);
    }
    return {bases, probes};
}

// ------------------------------------------- what the tables model (decision 0015 section 4.2)
// The UNMODELED markers of gen_closure.py --pool, re-derived from the pinned data in this file's own words: the
// special column of a move, the handler column of an item and of an ability, and the lists of unmodelled features.
// implemented in the turn code by id (G4: Focus Sash, Rock Head; G12: Floettite, Flower Veil, Fairy Aura)
const ENGINE_ROWS = {items: ['focussash', 'floettite', 'psychicseed', 'electricseed', 'mistyseed', 'expertbelt', 'ejectbutton', 'widelens', 'muscleband', 'wiseglasses', 'brightpowder', 'redcard', 'lumberry', 'mentalherb'],
    abilities: ['rockhead', 'flowerveil', 'fairyaura', 'roughskin', 'poisontouch', 'thermalexchange', 'stickyhold', 'trace',
        'levitate', 'sandrush', 'swiftswim', 'slushrush', 'chlorophyll', 'innerfocus', 'liquidvoice',
        'flamebody', 'clearbody', 'hospitality', 'overcoat', 'soundproof', 'unnerve', 'speedboost',
        'compoundeyes', 'ironfist', 'sharpness', 'solidrock', 'technician', 'multiscale', 'galewings', 'raindish', 'friendguard', 'cursedbody', 'mirrorarmor', 'auraguard', 'hypercutter', 'scrappy', 'infiltrator', 'queenlymajesty', 'damp', 'sturdy', 'snowcloak', 'sandveil', 'static', 'justified', 'limber', 'solarpower', 'regenerator', 'toxicdebris', 'shadowtag', 'suctioncups', 'guarddog',
        'steadfast', 'weakarmor', 'telepathy', 'voltabsorb', 'punkrock', 'moxie', 'synchronize', 'oblivious', 'keeneye', 'bigpecks']};
const ENGINE_TARGETS = new Set(['normal', 'any', 'adjacentAlly', 'adjacentFoe', 'self', 'allAdjacentFoes', 'allySide', 'all',
    'randomNormal', 'allAdjacent', 'allies', 'foeSide']); // foeSide: step G37 (the four hazards)
// The fields of a move that the tables model (gen_closure.py DATA_KEYS and IGNORED_KEYS), nothing else.
const MOVE_KEYS = new Set(['num', 'accuracy', 'basePower', 'category', 'name', 'pp', 'priority', 'flags', 'target', 'type',
    'critRatio', 'secondary', 'self', 'boosts', 'recoil', 'drain', 'status', 'volatileStatus', 'sideCondition',
    'pseudoWeather', 'selfSwitch', 'stallingMove', 'noPPBoosts', 'struggleRecoil', 'condition', 'contestType', 'zMove',
    'maxMove', 'isNonstandard', 'hasSheerForceBoost', 'inherit', 'thawsTarget', 'heal']);
const MODELLED_STATUS = new Set(['brn', 'frz', 'par', 'slp', 'psn', 'tox']);
const MODELLED_SIDE = new Set(['tailwind', 'reflect', 'lightscreen', 'stealthrock', 'spikes', 'toxicspikes', 'stickyweb']); // the last four: step G37
const STAT_NAMES = ['atk', 'def', 'spa', 'spd', 'spe', 'accuracy', 'evasion'];

function isBoostBlock(b) {
    return b !== null && typeof b === 'object' && Object.keys(b).length > 0 && Object.keys(b).every((k) => STAT_NAMES.includes(k));
}

// Whether the tables model a move of the whole pool: no callback, no field outside the modelled ones, a modelled
// target class, and its secondary, self block, boosts, status, volatile, side condition and pseudo weather one
// effect each. The move's handler id (G2) or its place in the prefix is decided by the caller.
// The pool rows that carry selfSwitch and that the turn code pivots with a flag of their own (dfi_pivot_moves): U-turn
// (a G2 row); Flip Turn is a row of the prefix.
const ENGINE_PIVOTS = ['uturn', 'voltswitch'];
// Step G13: the moves that are another move's handler under another name (gen_closure.py PROTECT_COPIES).
const PROTECT_COPIES = {detect: 'protect'};
// Step G46: the four forced-switch moves; their forceSwitch: true is modelled (gen_closure.py G46_FORCE_SWITCH_MOVES).
const G46_FORCE_SWITCH_MOVES = ['roar', 'whirlwind', 'dragontail', 'circlethrow'];
// Step G56: the three lock moves; their self volatileStatus 'lockedmove' is modelled (gen_closure.py G56_LOCKED_MOVES).
const G56_LOCKED_MOVES = ['outrage', 'thrash', 'petaldance'];

function moveIsModelled(raw, id) {
    if (raw.selfSwitch !== undefined && !ENGINE_PIVOTS.includes(id)) {
        return false;
    }
    for (const [key, value] of Object.entries(raw)) {
        // Step G13: Light of Ruin's tags (the Champions mod clears isNonstandard); no other tag value is read.
        if (key === 'tags' && JSON.stringify(value) === JSON.stringify(['Past Unobtainable'])) {
            continue;
        }
        // Step G46: forceSwitch: true of the four moves of G46_FORCE_SWITCH_MOVES, and nothing else of it.
        if (key === 'forceSwitch' && value === true && G46_FORCE_SWITCH_MOVES.includes(id)) {
            continue;
        }
        // Step G56: self: { volatileStatus: 'lockedmove' } of the three moves of G56_LOCKED_MOVES, and nothing else of it.
        if (key === 'self' && G56_LOCKED_MOVES.includes(id) && JSON.stringify(value) === JSON.stringify({ volatileStatus: 'lockedmove' })) {
            continue;
        }
        if (typeof value === 'function' || !MOVE_KEYS.has(key)) {
            return false;
        }
    }
    if (!ENGINE_TARGETS.has(raw.target)) {
        return false;
    }
    for (const key of ['stallingMove', 'selfSwitch', 'noPPBoosts', 'struggleRecoil', 'thawsTarget']) {
        if (key in raw && raw[key] !== true) {
            return false;
        }
    }
    // Step G10: heal is a fraction [a, b] with 0 < a <= b <= 255 (the heal column).
    if ('heal' in raw && !(Array.isArray(raw.heal) && raw.heal.length === 2 && raw.heal[0] > 0 &&
                           raw.heal[0] <= raw.heal[1] && raw.heal[1] <= 255)) {
        return false;
    }
    let vectors = 0;
    if (raw.secondary !== undefined) {
        const sec = raw.secondary;
        const keys = sec === null || typeof sec !== 'object' ? [] : Object.keys(sec);
        const effects = keys.filter((k) => k !== 'chance');
        if (!keys.includes('chance') || effects.length !== 1) {
            return false;
        }
        if (effects[0] === 'status') {
            if (!['brn', 'frz', 'par', 'slp', 'psn', 'tox'].includes(sec.status)) { // step G13: a poison secondary is modelled (status 5), step G36: a badly poisoning one (status 6)
                return false;
            }
        } else if (effects[0] === 'volatileStatus') {
            if (!['flinch', 'confusion'].includes(sec.volatileStatus)) {
                return false;
            }
        } else if (effects[0] === 'boosts') {
            if (!isBoostBlock(sec.boosts)) {
                return false;
            }
            vectors += 1;
        } else if (effects[0] === 'self') {
            // Step G28: a secondary whose own effect is a stat change of the user (Ancient Power).
            if (sec.self === null || typeof sec.self !== 'object' || Object.keys(sec.self).length !== 1 ||
                !isBoostBlock(sec.self.boosts)) {
                return false;
            }
            vectors += 1;
        } else {
            return false;
        }
    }
    // Step G17: the recharge moves: flags.recharge with exactly the mustrecharge self effect (the RECHARGE bit of the second
    // flags byte), one without the other is not modelled.
    const rechargeSelf = raw.self !== undefined && raw.self !== null && typeof raw.self === 'object' &&
        Object.keys(raw.self).length === 1 && raw.self.volatileStatus === 'mustrecharge';
    if (rechargeSelf !== !!(raw.flags && raw.flags.recharge)) {
        return false;
    }
    if (raw.self !== undefined && !rechargeSelf) {
        if (raw.self === null || typeof raw.self !== 'object' || !isBoostBlock(raw.self.boosts) || Object.keys(raw.self).length !== 1) {
            return false;
        }
        vectors += 1;
    }
    if (raw.boosts !== undefined) {
        // Step G19: Coaching, a status move whose primary boosts go to the adjacent ally, is modelled too.
        const toAlly = raw.target === 'adjacentAlly' && raw.category === 'Status';
        // Step G39: Charm and Fake Tears, a status move of one adjacent target whose primary boosts go to that target.
        const toTarget = raw.target === 'normal' && raw.category === 'Status';
        if ((raw.target !== 'self' && !toAlly && !toTarget) || !isBoostBlock(raw.boosts)) {
            return false;
        }
        vectors += 1;
    }
    if (vectors > 1) {
        return false;
    }
    if (raw.status !== undefined && !MODELLED_STATUS.has(raw.status)) {
        return false;
    }
    if (raw.volatileStatus !== undefined && raw.volatileStatus !== 'protect') {
        return false;
    }
    if (raw.sideCondition !== undefined && !MODELLED_SIDE.has(raw.sideCondition)) {
        return false;
    }
    if (raw.pseudoWeather !== undefined && raw.pseudoWeather !== 'trickroom') {
        return false;
    }
    if (raw.condition !== undefined && !(MODELLED_SIDE.has(raw.sideCondition) || raw.pseudoWeather === 'trickroom')) {
        return false;
    }
    return true;
}

// The callbacks and condition blocks of an item or ability entry (its own, or any field named onX).
function entryCallbacks(raw) {
    return Object.entries(raw).filter(([key, value]) => typeof value === 'function' || /^on[A-Z]/.test(key) ||
        key === 'condition').map(([key]) => key);
}

// The rows of the move table of the generated source: the numbers of every row, in id order.
function moveColumns(source, count) {
    const start = source.indexOf('const dfi_move_data dfi_pool_moves[');
    const end = source.indexOf('\n};', start);
    const rows = [];
    for (const m of source.slice(start, end).matchAll(/^    \{(.*)\},$/gm)) {
        rows.push(m[1].replace(/[{}]/g, '').split(',').map((x) => parseInt(x, 10)));
    }
    if (rows.length !== count || rows.some((r) => r.length !== 29)) {
        throw new Error('dfi_pool_moves: ' + rows.length + ' rows, expected ' + count + ' of 29 numbers');
    }
    return rows;
}

function handlerColumn(source, kind, array, count) {
    const start = source.indexOf('const uint8_t ' + array + '[');
    const end = source.indexOf('\n};', start);
    const re = new RegExp('^\\s*\\[DFI_' + kind + '_(\\w+)\\] = DFI_HANDLER_(\\w+),$', 'gm');
    const rows = [...source.slice(start, end).matchAll(re)].map((m) => ({id: m[1].toLowerCase(), handler: m[2]}));
    if (rows.length !== count) {
        throw new Error(array + ': ' + rows.length + ' rows, expected ' + count);
    }
    return rows;
}

function unmodeledList(source, kind, array) {
    const start = source.indexOf('const char *const ' + array + '[');
    const end = source.indexOf('\n};', start);
    const re = new RegExp('^\\s*\\[DFI_' + kind + '_(\\w+)\\] = "([^"]*)",$', 'gm');
    return new Map([...source.slice(start, end).matchAll(re)].map((m) => [m[1].toLowerCase(), m[2]]));
}

function checkHandlers(dex, source, header, extended) {
    const counts = {
        move: defineOf(header, 'DFI_POOL_MOVE_COUNT'), item: defineOf(header, 'DFI_POOL_ITEM_COUNT'),
        ability: defineOf(header, 'DFI_POOL_ABILITY_COUNT'),
    };
    const unmodeledSpecial = defineOf(header, 'DFI_SPECIAL_UNMODELED');
    const firstHandler = defineOf(header, 'DFI_SPECIAL_ENCORE');
    // Step G8: Throat Chop and Psychic Noise are rows of the G2 step that the generator reads strictly (their secondaries
    // are modelled kinds with a recorded engine and no handler id), so they have no UNMODELED marker to cross-check.
    const strictRows = new Set(['throatchop', 'psychicnoise']);
    const itemFamily = familyRows(source, 'ITEM', 'dfi_pool_item_family', counts.item);
    const abilityFamily = familyRows(source, 'ABILITY', 'dfi_pool_ability_family', counts.ability);
    const result = {moves: 0, items: 0, abilities: 0};
    // Moves: the special column is UNMODELED exactly where the pinned entry has something the tables do not model.
    const moveIds = [...definedIds([extended.closure, extended.ext, header], 'MOVE').entries()].sort((a, b) => a[0] - b[0]);
    const columns = moveColumns(source, counts.move);
    const unmodeledMoves = unmodeledList(source, 'MOVE', 'dfi_pool_move_unmodeled');
    for (const [number, id] of moveIds) {
        if (number >= columns.length) {
            continue;
        }
        const special = columns[number][28];
        if (special === unmodeledSpecial) {
            result.moves += 1;
        }
        if ((special === unmodeledSpecial) !== unmodeledMoves.has(id)) {
            bad('move ' + id + ': the UNMODELED special and its feature list disagree');
        }
        if (number < extended.moveCount || strictRows.has(id) || (special >= firstHandler && special < unmodeledSpecial)) {
            continue; // the closure, Team C and the G2 handler moves: code in the turn core, or a handler id of their own
        }
        const raw = dex.data.Moves[id];
        if (raw === undefined) {
            bad('move ' + id + ' has no pinned entry');
            continue;
        }
        if (PROTECT_COPIES[id] !== undefined) {
            // Step G13: Detect has Protect's handler and, field for field and callback for callback, Protect's text.
            const original = dex.data.Moves[PROTECT_COPIES[id]];
            for (const key of ['onPrepareHit', 'onHit', 'stallingMove', 'volatileStatus', 'priority', 'accuracy', 'target']) {
                expect('move ' + id + ' ' + key + ' is that of ' + PROTECT_COPIES[id], String(raw[key]), String(original[key]));
            }
            expect('move ' + id + ' has the special of ' + PROTECT_COPIES[id], special,
                   columns[moveIds.find((e) => e[1] === PROTECT_COPIES[id])[0]][28]);
            continue;
        }
        if (id === 'sacredsword') {
            // Step G39: Sacred Sword has Darkest Lariat's handler (the damage formula and the accuracy step that ignore the
            // target's Defense and evasion stages), with the same two fields and no callback.
            const original = dex.data.Moves.darkestlariat;
            for (const key of ['ignoreDefensive', 'ignoreEvasion', 'category', 'target', 'accuracy']) {
                expect('move ' + id + ' ' + key + ' is that of darkestlariat', raw[key], original[key]);
            }
            expect('move ' + id + ' has the special of darkestlariat', special,
                   columns[moveIds.find((e) => e[1] === 'darkestlariat')[0]][28]);
            continue;
        }
        if (moveIsModelled(raw, id) !== (special !== unmodeledSpecial)) {
            bad('move ' + id + ': the pinned entry is ' + (moveIsModelled(raw, id) ? 'modelled' : 'unmodelled') +
                ' but the special column says ' + (special === unmodeledSpecial ? 'UNMODELED' : 'modelled'));
        }
        if (special !== unmodeledSpecial) {
            expect('move ' + id + ' target class is one the turn code has', ENGINE_TARGETS.has(raw.target), true);
        }
    }
    // Step AC1: Trace may not copy an ability with the pin's notrace flag (data/abilities.ts:5118-5148). The turn code
    // excludes Trace alone, right while no other such ability is marked: tests/test_pool_tables.c names the nine
    // abilities of the pool that have the flag and requires every one but Trace to be unmarked, so the list is
    // pinned to the data here.
    {
        const poolAbilities = new Set([...definedIds([extended.closure, extended.ext, header], 'ABILITY').values()]);
        const flagged = [...poolAbilities].filter((id) => dex.data.Abilities[id] && dex.data.Abilities[id].flags &&
                                                          dex.data.Abilities[id].flags.notrace).sort();
        expect('the pool abilities with the notrace flag', flagged,
               ['disguise', 'forecast', 'hungerswitch', 'illusion', 'imposter', 'receiver', 'stancechange', 'trace',
                'zerotohero']);
    }
    // Items and abilities: a row without the UNMODELED handler is the closure's or Team C's, a family member, an
    // implemented row, or an entry with no callback of its own (a Mega Stone keeps its onTakeItem); a row with it
    // has a callback, a condition, another field, a second Mega forme or a reader elsewhere.
    for (const [what, kind, array, data, familyList, ext, engine] of [
        ['item', 'ITEM', 'dfi_pool_item_handler', dex.data.Items, itemFamily, extended.itemCount, ENGINE_ROWS.items],
        ['ability', 'ABILITY', 'dfi_pool_ability_handler', dex.data.Abilities, abilityFamily, extended.abilityCount, ENGINE_ROWS.abilities],
    ]) {
        const rows = handlerColumn(source, kind, array, counts[what]);
        const features = unmodeledList(source, kind, 'dfi_pool_' + what + '_unmodeled');
        rows.forEach((row, number) => {
            const unmodeled = row.handler === 'UNMODELED';
            if (unmodeled !== features.has(row.id)) {
                bad(what + ' ' + row.id + ': the UNMODELED handler and its feature list disagree');
            }
            result[what === 'ability' ? 'abilities' : 'items'] += unmodeled ? 1 : 0;
            const raw = data[row.id];
            if (raw === undefined) {
                bad(what + ' ' + row.id + ' has no pinned entry');
                return;
            }
            const callbacks = entryCallbacks(raw).filter((k) => !(raw.megaStone !== undefined && k === 'onTakeItem'));
            const exempt = number < ext || familyList[number].family !== 'NONE' || engine.includes(row.id);
            if (!unmodeled && !exempt && callbacks.length > 0) {
                bad(what + ' ' + row.id + ' is modelled but its pinned entry has ' + callbacks.join(', '));
            }
            // The queue sorts every action by a priority and a Speed that an ability or an item can change, and for a
            // fainted holder none of them counts (src/combat/turn.c, dfi_move_priority and dfi_speed_key). The engine
            // reads exactly two such effects, so a modelled row that has another is a mechanic nobody looked at.
            if (!unmodeled) {
                expect(what + ' ' + row.id + ' priority and Speed callbacks of a modelled row', orderCallbacks(raw),
                    (ENGINE_ORDER[what] || {})[row.id] || []);
            }
            if (unmodeled && exempt) {
                bad(what + ' ' + row.id + ' is UNMODELED but is a prefix row, a family member or implemented by id');
            }
            if (unmodeled && callbacks.length === 0 && !/read by id|second Mega|field /.test(features.get(row.id))) {
                bad(what + ' ' + row.id + ' is UNMODELED and no feature explains it: ' + features.get(row.id));
            }
        });
    }
    return result;
}

// The cosmetic formes that the validator treats as their base forme: a name for the base forme's row.
function checkAliases(dex, validator, source, header) {
    const start = source.indexOf('const dfi_pool_alias dfi_pool_forme_aliases[');
    const end = source.indexOf('\n};', start);
    const rows = [...source.slice(start, end).matchAll(/^\s*\{"([^"]+)", DFI_FORME_(\w+)\},$/gm)].map((m) => ({
        alias: m[1], base: m[2].toLowerCase()}));
    expect('alias count', rows.length, defineOf(header, 'DFI_POOL_ALIAS_COUNT'));
    const set = (name, moves, ability) => ({name: '', species: name, item: '', ability, moves, nature: 'Adamant', gender: '',
        evs: {hp: 2, atk: 0, def: 0, spa: 0, spd: 0, spe: 0}, ivs: {hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31}, level: 50});
    for (const {alias, base} of rows) {
        const a = dex.species.get(alias);
        const b = dex.species.get(base);
        if (!a.exists || a.id !== alias || !b.exists) {
            bad('alias ' + alias + ' (of ' + base + ') is not a pinned dex species');
            continue;
        }
        // Mechanically identical: the same dex number, types, base stats, weight and abilities, and the same base species.
        expect('alias ' + alias + ' is ' + base, [a.num, a.types, a.baseStats, a.weightkg, a.abilities, a.baseSpecies],
            [b.num, b.types, b.baseStats, b.weightkg, b.abilities, b.baseSpecies]);
        const first = Object.keys(dex.species.getLearnsetData(b.id).learnset || {})[0] || 'protect';
        const problems = validator.validateSet(set(a.name, [dex.moves.get(first).name], Object.values(a.abilities)[0]), {});
        if (problems && problems.length > 0) {
            bad('alias ' + alias + ' is not accepted by the validator: ' + problems[0]);
        }
    }
    return rows.length;
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
    const headers = ['closure_tables.h', 'extended_tables.h', 'pool_tables.h'].map((f) => readText(path.join(repo, 'src', 'data', f)));
    const moveIds = definedIds(headers, 'MOVE');
    const abilityIds = definedIds(headers, 'ABILITY');
    const formeRowsList = formeRows(source, defineOf(header, 'DFI_POOL_FORME_COUNT'), defineOf(header, 'DFI_POOL_LEARN_BYTES'));
    for (const row of abilityRows) {
        if (abilityIds.get(abilityRows.indexOf(row)) !== row.id) {
            bad('ability ' + row.id + ' is not the id ' + abilityRows.indexOf(row) + ' of the headers');
        }
    }

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
    const unmodeledOf = (kind, array, count) => new Set(handlerColumn(source, kind, array, count)
        .filter((r) => r.handler === 'UNMODELED').map((r) => r.id));
    const unmodeledItems = unmodeledOf('ITEM', 'dfi_pool_item_handler', itemCount);
    const unmodeledAbilities = unmodeledOf('ABILITY', 'dfi_pool_ability_handler', abilityCount);
    const specialUnmodeled = defineOf(header, 'DFI_SPECIAL_UNMODELED');
    const unmodeledMoves = new Set(moveColumns(source, defineOf(header, 'DFI_POOL_MOVE_COUNT'))
        .map((row, number) => (row[28] === specialUnmodeled ? moveIds.get(number) : undefined)).filter((id) => id !== undefined));
    const items = checkItems(dex, itemRows, unmodeledItems);
    checkFocusSash(dex, root);
    checkWeather(dex, source);
    checkTerrains(dex);
    checkG28(dex);
    checkG10Moves(dex);
    checkEncore(dex, repo);
    checkRecharge(dex);
    checkG19(dex);
    checkG26(dex);
    checkG27(dex);
    checkG32(dex);
    checkG33(dex);
    checkG41(dex);
    checkG47(dex);
    checkG44(dex);
    checkG54(dex);
    checkG62(dex);
    checkG22(dex, formeRowsList, new Set(definedIds(headers, 'ITEM').values()), new Set(abilityIds.values()));
    const abilities = checkAbilities(dex, abilityRows, moveIds, unmodeledAbilities, unmodeledMoves);
    // "All 18": a booster and a resist berry for each type, and nothing else in the families.
    expect('type boosters', items.TYPE_BOOSTER, 18);
    expect('resist berries', items.RESIST_BERRY, 18);
    expect('"-ate" abilities', abilities.ATE, 3);
    expect('pinch abilities', abilities.PINCH, 4);
    expect('weather setters', abilities.WEATHER_SETTER, 4);
    expect('terrain setters', abilities.TERRAIN_SETTER, 3);
    checkLegal(dex, TeamValidator.get(FORMAT_ID), itemRows, abilityRows, extendedAbilities);
    const legal = checkFormes(dex, TeamValidator.get(FORMAT_ID), formeRowsList, moveIds, abilityIds);
    const names = checkNames(dex, source, headers);
    const extendedHeader = readText(path.join(repo, 'src', 'data', 'extended_tables.h'));
    const unmodeled = checkHandlers(dex, source, header, {
        closure: headers[0], ext: headers[1], moveCount: defineOf(extendedHeader, 'DFI_EXT_MOVE_COUNT'),
        itemCount: defineOf(extendedHeader, 'DFI_EXT_ITEM_COUNT'), abilityCount: extendedAbilities,
    });
    const aliases = checkAliases(dex, TeamValidator.get(FORMAT_ID), source, header);

    if (failures > 0) {
        process.stderr.write('pool_families: ' + failures + ' mismatch(es)\n');
        process.exit(1);
    }
    process.stdout.write('pool_families: ' + itemRows.length + ' items and ' + abilityRows.length +
        ' abilities agree with the pinned handlers (' + JSON.stringify(items) + ', ' + JSON.stringify(abilities) +
        '); every pool item and the new abilities pass the validator; ' + legal.bases + ' base formes: ' + legal.probes +
        ' validator probes of their moves and abilities agree; ' + names + ' names are pinned dex ids; the UNMODELED markers agree with the pinned entries (' + JSON.stringify(unmodeled) + '); ' + aliases + ' cosmetic aliases are their base forme\n');
}

main();
