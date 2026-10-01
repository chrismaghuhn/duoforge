#!/usr/bin/env node
// Executable evidence for docs/research/third-team/mechanics.md.
//
// Small, hand-built battles in the pinned Pokemon Showdown
// (b2cb775b0616115b775534eaeff50300e1fc81fc, champions mod, format
// gen9championsvgc2026regmc). Every scenario asserts what the reference does
// for one Team C mechanic; the exit code is 1 when an assertion fails. The
// teams here are ad-hoc (they are not validated and not reference teams).
//
// usage: node experiments.js            env PS_ROOT = pinned, built checkout
'use strict';
const cp = require('child_process');
const root = process.env.PS_ROOT || 'C:/Dev/src/pokemon-showdown';
const PIN = 'b2cb775b0616115b775534eaeff50300e1fc81fc';
const head = cp.execSync('git rev-parse HEAD', {cwd: root}).toString().trim();
if (head !== PIN) {
    console.error(`checkout ${root} is at ${head}, not at the pin ${PIN}`);
    process.exit(1);
}
const {Battle} = require(root + '/dist/sim/battle');
const {PRNG} = require(root + '/dist/sim/prng');
const {Teams} = require(root + '/dist/sim/teams');

let failures = 0;
function expect(cond, msg) {
    console.log((cond ? 'PASS ' : 'FAIL ') + msg);
    if (!cond) failures++;
}

function mon(name, gender, item, ability, evs, nature, moves) {
    return `${name} (${gender}) @ ${item}\nAbility: ${ability}\nLevel: 50\nEVs: ${evs}\n${nature} Nature\n` +
        moves.map((m) => '- ' + m).join('\n') + '\n';
}
const filler = (n) => mon(n, 'M', 'Leftovers', 'Pressure', '32 HP / 32 Def', 'Bold', ['Protect', 'Splash', 'Splash', 'Splash']);
const sneasler = () => mon('Sneasler', 'F', 'White Herb', 'Unburden', '2 HP / 32 Atk / 32 Spe', 'Adamant',
    ['Close Combat', 'Dire Claw', 'Protect', 'Fake Out']);
const kingambit = (item = 'Chople Berry') => mon('Kingambit', 'M', item, 'Defiant', '32 HP / 32 Atk / 2 SpD', 'Adamant',
    ['Kowtow Cleave', 'Sucker Punch', 'Iron Head', 'Protect']);
const indeedee = (ability) => mon('Indeedee-F', 'F', 'Colbur Berry', ability, '32 HP / 32 Def / 2 SpD', 'Relaxed',
    ['Follow Me', 'Trick Room', 'Helping Hand', 'Psychic']);
const basculegion = () => mon('Basculegion', 'M', 'Choice Scarf', 'Adaptability', '2 HP / 32 Atk / 32 Spe', 'Adamant',
    ['Last Respects', 'Wave Crash', 'Aqua Jet', 'Protect']);
const gholdengo = () => mon('Gholdengo', 'F', 'Leftovers', 'Good as Gold', '32 HP / 32 SpA', 'Modest',
    ['Make It Rain', 'Shadow Ball', 'Nasty Plot', 'Protect']);
const milotic = () => mon('Milotic', 'F', 'Leftovers', 'Competitive', '32 HP / 32 SpD', 'Calm',
    ['Muddy Water', 'Coil', 'Ice Beam', 'Hypnosis']);
const staraptor = (ability = 'Intimidate') => mon('Staraptor', 'F', 'Leftovers', ability, '32 HP / 32 Spe', 'Jolly',
    ['Close Combat', 'Brave Bird', 'Tailwind', 'Protect']);

class ForcedPRNG extends PRNG {
    // Answers random(lo, hi) from per-bounds queues while they last; records every draw.
    constructor(seed, forced = {}) {
        super(seed);
        this.forced = forced;
        this.draws = [];
    }
    random(from, to) {
        const lo = to === undefined || to === null ? 0 : from;
        const hi = to === undefined || to === null ? from : to;
        const q = this.forced[lo + ',' + hi];
        const value = q && q.length ? q.shift() : super.random(from, to);
        this.draws.push([lo, hi, value]);
        return value;
    }
}

function start(t1, t2, forced) {
    const prng = new ForcedPRNG('sodium,' + '1'.padStart(64, '0'), forced);
    const battle = new Battle({formatid: 'gen9championsvgc2026regmc', prng});
    battle.setPlayer('p1', {name: 'p1', team: Teams.pack(Teams.import(t1.join('\n')))});
    battle.setPlayer('p2', {name: 'p2', team: Teams.pack(Teams.import(t2.join('\n')))});
    battle.choose('p1', 'team 1234');
    battle.choose('p2', 'team 1234');
    return battle;
}
function turn(battle, c1, c2) {
    const from = battle.log.length;
    if (!battle.choose('p1', c1)) throw new Error(`p1 "${c1}": ${battle.p1.choice.error}`);
    if (!battle.choose('p2', c2)) throw new Error(`p2 "${c2}": ${battle.p2.choice.error}`);
    return battle.log.slice(from);
}
const has = (log, re) => log.some((l) => re.test(l));
const speed = (b, side, slot) => b.sides[side].active[slot].getStat('spe');

console.log('== X1 opening: Intimidate -> White Herb -> Unburden; Defiant');
{
    const b = start([sneasler(), kingambit(), filler('Pelipper'), filler('Gengar')],
        [staraptor(), gholdengo(), filler('Pelipper'), filler('Gengar')]);
    const open = b.log.join('\n');
    expect(/-ability\|p2a: Staraptor\|Intimidate\|boost/.test(open) && /-unboost\|p1a: Sneasler\|atk\|1/.test(open),
        'foe Intimidate lowers Sneasler Atk at the opening');
    expect(/-boost\|p1b: Kingambit\|atk\|2/.test(open), 'Defiant: Kingambit gains +2 Atk after the same Intimidate');
    expect(/-enditem\|p1a: Sneasler\|White Herb/.test(open) && b.sides[0].active[0].item === '',
        'White Herb is consumed during the opening switch-in sequence');
    expect(speed(b, 0, 0) === 2 * (120 + 32 + 20), 'Unburden doubles Sneasler Speed (172 -> 344) before turn 1');
}

console.log('== X2 Unburden after a mid-turn White Herb (Close Combat self-drop)');
{
    const b = start([sneasler(), filler('Pelipper'), filler('Gengar'), filler('Gyarados')],
        [milotic(), gholdengo(), filler('Pelipper'), filler('Gengar')]);
    expect(speed(b, 0, 0) === 172 && b.sides[0].active[0].item === 'whiteherb', 'before: Speed 172 and the herb is held');
    const log = turn(b, 'move 1 1, move 2', 'move 2, move 4');
    const iDrop = log.findIndex((l) => /-unboost\|p1a: Sneasler\|def\|1/.test(l));
    const iHerb = log.findIndex((l) => /-enditem\|p1a: Sneasler\|White Herb/.test(l));
    expect(iDrop >= 0 && iHerb > iDrop, 'White Herb is used after the Close Combat self-drops (AnyAfterMove)');
    expect(speed(b, 0, 0) === 344, 'after: Unburden gives Speed 344');
}

console.log('== X3 Follow Me beats Lightning Rod (RedirectTarget priority 1 versus 0)');
{
    const team1 = () => [indeedee('Own Tempo'),
        mon('Raichu', 'F', 'Leftovers', 'Lightning Rod', '32 HP / 32 Spe', 'Timid', ['Protect', 'Thunderbolt', 'Fake Out', 'Splash']),
        filler('Pelipper'), filler('Gengar')];
    const team2 = () => [mon('Archaludon', 'M', 'Leftovers', 'Stamina', '32 HP / 32 SpA', 'Modest', ['Thunderbolt', 'Dragon Pulse', 'Snarl', 'Protect']),
        gholdengo(), filler('Pelipper'), filler('Gengar')];
    let b = start(team1(), team2());
    let log = turn(b, 'move 1, move 4', 'move 1 2, move 4');
    expect(has(log, /\|move\|p2a: Archaludon\|Thunderbolt\|p1a: Indeedee/) && !has(log, /Lightning Rod/),
        'Follow Me: Thunderbolt aimed at the Lightning Rod user lands on the Follow Me user');
    b = start(team1(), team2());
    log = turn(b, 'move 4 1, move 4', 'move 1 2, move 4');
    expect(has(log, /-ability\|p1b: Raichu\|Lightning Rod\|boost/), 'without Follow Me, Lightning Rod absorbs it');
}

console.log('== X4 Sucker Punch reads the target\'s queued action; Helping Hand');
{
    const mk = () => start([kingambit(), indeedee('Own Tempo'), filler('Pelipper'), filler('Gengar')],
        [gholdengo(), mon('Farigiraf', 'F', 'Leftovers', 'Own Tempo', '32 HP / 32 SpA', 'Modest', ['Psychic', 'Grass Knot', 'Trick Room', 'Protect']),
            filler('Pelipper'), filler('Gengar')]);
    let b = mk();
    let log = turn(b, 'move 2 1, move 3 -1', 'move 3, move 4');
    expect(has(log, /\|move\|p1a: Kingambit\|Sucker Punch\|\|\[still\]/) && has(log, /-fail\|p1a: Kingambit/),
        'Sucker Punch fails against a target that queued a status move (Nasty Plot)');
    expect(has(log, /\|move\|p1b: Indeedee\|Helping Hand\|p1a: Kingambit/) &&
        log.findIndex((l) => /Helping Hand/.test(l)) < log.findIndex((l) => /Sucker Punch/.test(l)),
        'Helping Hand (+5) resolves before Sucker Punch (+1)');
    b = mk();
    log = turn(b, 'switch 3, move 3 -1', 'move 4, move 4');
    expect(has(log, /\|move\|p1b: Indeedee\|Helping Hand\|p1a: Pelipper/) && !has(log, /-fail\|p1b: Indeedee/),
        'Helping Hand works on a partner that switched in this turn (newlySwitched), although its action is a switch');
    b = mk();
    log = turn(b, 'move 2 1, move 4 2', 'move 1, move 4');
    expect(has(log, /\|move\|p1a: Kingambit\|Sucker Punch\|p2a: Gholdengo/) && !has(log, /-fail\|p1a: Kingambit/),
        'Sucker Punch hits a target that queued an attacking move (Make It Rain)');
}

console.log('== X5 Psychic Terrain: Psychic Surge at the opening, priority blocking');
{
    const b = start([indeedee('Psychic Surge'), basculegion(), filler('Pelipper'), filler('Gengar')],
        [mon('Rillaboom', 'M', 'Miracle Seed', 'Overgrow', '18 HP / 32 Atk', 'Adamant', ['Wood Hammer', 'Grassy Glide', 'Fake Out', 'High Horsepower']),
            staraptor('Reckless'), filler('Pelipper'), filler('Gengar')]);
    expect(b.field.terrain === 'psychicterrain' && b.field.terrainState.duration === 5, 'Psychic Surge sets a 5-turn Psychic Terrain');
    const log = turn(b, 'move 4 1, move 3 1', 'move 3 -2, move 2 1');
    expect(has(log, /-activate\|p2a: Rillaboom\|move: Psychic Terrain/),
        'Aqua Jet (+1) of the terrain setter\'s own side is blocked against a grounded foe');
    expect(has(log, /\|move\|p2a: Rillaboom\|Fake Out\|p2b: Staraptor/) && has(log, /cant\|p2b: Staraptor\|flinch/),
        'an ally-targeted Fake Out (+3) is not blocked');
}

console.log('== X6 Last Respects power and the Choice lock');
{
    const b = start([basculegion(), kingambit(), filler('Pelipper'), filler('Gengar')],
        [gholdengo(), filler('Farigiraf'), filler('Pelipper'), filler('Gengar')]);
    const lr = b.dex.moves.get('lastrespects');
    const bp = () => lr.basePowerCallback.call(b, b.sides[0].active[0], b.sides[1].active[0], lr);
    expect(b.sides[0].totalFainted === 0 && bp() === 50, 'Last Respects has 50 base power with no fainted ally');
    b.sides[0].active[1].faint();
    b.faintMessages();
    expect(b.sides[0].totalFainted === 1 && bp() === 100, 'one fainted ally: side.totalFainted 1, base power 100');
    const c = start([basculegion(), kingambit(), filler('Pelipper'), filler('Gengar')],
        [gholdengo(), filler('Farigiraf'), filler('Pelipper'), filler('Gengar')]);
    turn(c, 'move 2 1, move 1 1', 'move 4, move 4');
    const moves = c.sides[0].activeRequest.active[0].moves.map((m) => [m.id, !!m.disabled]);
    expect(JSON.stringify(moves) === JSON.stringify([['lastrespects', true], ['wavecrash', false], ['aquajet', true], ['protect', true]]),
        'after Wave Crash the request disables the other three moves (Choice Scarf lock)');
    expect(!c.choose('p1', 'move 1 1, move 1 1'), 'choosing a locked-out move is rejected: ' + c.p1.choice.error);
}

console.log('== X7 Chople Berry: halves a super-effective Fighting hit and is eaten');
{
    const mk = (item) => start([kingambit(item), filler('Pelipper'), filler('Gengar'), filler('Gyarados')],
        [staraptor(), gholdengo(), filler('Pelipper'), filler('Gengar')]);
    const withBerry = mk('Chople Berry');
    const log = turn(withBerry, 'move 3 1, move 4', 'move 1 1, move 4');
    const noBerry = mk('Light Ball');
    turn(noBerry, 'move 3 1, move 4', 'move 1 1, move 4');
    const lost = (bat, hp0) => hp0 - bat.sides[0].active[0].hp;
    const hp0 = 207;
    const iSE = log.findIndex((l) => /-supereffective\|p1a: Kingambit\|2/.test(l));
    const iEat = log.findIndex((l) => /-enditem\|p1a: Kingambit\|Chople Berry\|\[eat\]/.test(l));
    const iWeaken = log.findIndex((l) => /-enditem\|p1a: Kingambit\|Chople Berry\|\[weaken\]/.test(l));
    expect(iSE >= 0 && iEat > iSE && iWeaken > iEat, 'log order: -supereffective, -enditem [eat], -enditem [weaken]');
    expect(withBerry.sides[0].active[0].item === '' && Math.abs(lost(withBerry, hp0) * 2 - lost(noBerry, hp0)) <= 2,
        `damage with the berry (${lost(withBerry, hp0)}) is half of the damage without it (${lost(noBerry, hp0)})`);
}

console.log('== X8 Mega Salamence: Aerilate turns Hyper Voice into a Flying move');
{
    const mk = () => start([mon('Salamence', 'M', 'Salamencite', 'Intimidate', '2 HP / 32 SpA / 32 Spe', 'Timid',
        ['Protect', 'Hyper Voice', 'Draco Meteor', 'Tailwind']), kingambit(), filler('Pelipper'), filler('Gengar')],
    [mon('Ceruledge', 'M', 'Leftovers', 'Flash Fire', '32 HP / 32 Atk', 'Adamant', ['Bitter Blade', 'Shadow Sneak', 'Swords Dance', 'Protect']),
        milotic(), filler('Pelipper'), filler('Gengar')]);
    let b = mk();
    let log = turn(b, 'move 2, move 4', 'move 3, move 2');
    expect(has(log, /-immune\|p2a: Ceruledge/), 'before Mega: Normal-type Hyper Voice does not affect the Ghost-type Ceruledge');
    b = mk();
    log = turn(b, 'move 2 mega, move 4', 'move 3, move 2');
    expect(has(log, /-mega\|p1a: Salamence\|Salamence\|Salamencite/) && b.sides[0].active[0].species.name === 'Salamence-Mega' &&
        b.sides[0].active[0].ability === 'aerilate', 'Mega Evolution: Salamence-Mega with Aerilate');
    expect(!has(log, /-immune\|p2a: Ceruledge/) && has(log, /\|-damage\|p2a: Ceruledge\|/), 'after Mega: Hyper Voice (now Flying) damages Ceruledge');
}

console.log('== X9 Dire Claw: draw order (Champions override: 30% secondary, then sample of psn/par/slp)');
{
    // random(100): accuracy 0 (hits), secondary 0 (< 30); random(24) no crit; random(16) roll; random(3): pick 2 = slp, then sleep sample 0 -> 2 turns
    const forced = {'0,100': [0, 0], '0,24': [5], '0,16': [3], '0,3': [2, 0]};
    const b = start([sneasler(), filler('Pelipper'), filler('Gengar'), filler('Gyarados')],
        [milotic(), gholdengo(), filler('Pelipper'), filler('Gengar')], forced);
    const from = b.prng.draws.length;
    const log = turn(b, 'move 2 1, move 2', 'move 2, move 4');
    const draws = b.prng.draws.slice(from);
    const fmt = (list) => list.map((d) => `[${d[0]},${d[1]})`).join(' ');
    expect(has(log, /-status\|p2a: Milotic\|slp/), 'forced pick index 2 puts the target to sleep');
    expect(fmt(draws.slice(0, 6)) === '[0,100) [0,24) [0,16) [0,100) [0,3) [0,3)',
        'draws in order: accuracy, crit, damage roll, secondary chance, status pick, sleep length (got ' + fmt(draws.slice(0, 6)) + ')');
    console.log('     later draws of the turn (not Dire Claw; residual speed-tie shuffles): ' + (fmt(draws.slice(6)) || 'none'));
}

console.log(failures ? `\n${failures} assertion(s) failed` : '\nall assertions passed');
process.exit(failures ? 1 : 0);
