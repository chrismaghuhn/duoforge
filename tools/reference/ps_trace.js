#!/usr/bin/env node
// Reference traces of complete battles from the pinned Pokemon Showdown
// (decision 0006 section 7).
//
// usage: node tools/reference/ps_trace.js <pinned checkout> <spec.json> [--check <trace.json>]
//
// A spec names the format, a PRNG seed, both teams (Showdown paste text,
// gender always given) and either the choices in request order ("choices")
// or a plan ("plan": per side the choices for its move requests in order,
// with "max_steps"): then a replacement request is answered with the first
// standing reserves in team order, a move choice for a fainted slot becomes
// "pass", a move without PP falls back to the first with PP, a target is
// dropped for a move that takes none (and is 1 for one that needs it, or the
// ally's slot for an ally-only move such as Helping Hand), a switch to a
// Pokemon that cannot come in goes to the first standing
// reserve (or becomes "move 1 1", as does a switch of a trapped Pokemon),
// and an exhausted plan repeats its last
// entry. The trace records the choices
// actually made. The harness runs
// the battle with a recording PRNG and prints a normalized trace: for every
// choice entry the draws it caused (site, bounds, value), the protocol
// lines, and the state at the next boundary (exact HP, status, stages, PP,
// active slots, requests).
//
// Draw sites are read from the call stack of each draw and named as in
// src/rng/draw.h; the context says which sort or event a draw belongs to
// (queue: the action order; each:<event>: all actives by speed;
// field:<event> or event:<event>: the handlers of that event). Draws that
// sort the team-preview actions are recorded as TEAM_ORDER: they order the
// independent per-side team actions and change nothing, so DuoForge does not
// make them (docs/OPEN_DECISIONS.md). Draws the harness cannot classify are
// recorded as UNKNOWN; a trace with an UNKNOWN draw must not be used as a
// fixture.
//
// CTest never needs Node: traces are committed under tests/reference/traces
// and checked by duoforge.reference.traces when the checkout and Node are
// present.
//
// As a module, require('./ps_trace.js') gives run(root, spec, specFile), which
// records one battle and returns the trace text, and PIN and HARNESS_VERSION.
// One process can record many battles: the Showdown modules stay cached, and
// the state of this module is reset at the start of every run.
'use strict';

const fs = require('fs');
const path = require('path');

const PIN = 'b2cb775b0616115b775534eaeff50300e1fc81fc';
const HARNESS_VERSION = 14;

// Stack frame name -> site. The first match in stack order wins.
const SITE_RULES = [
    ['BattleActions.hitStepAccuracy', 'ACCURACY'],
    ['Battle.randomizer', 'DAMAGE_ROLL'],
    ['BattleActions.secondaries', 'SECONDARY'],
    ['BattleActions.selfDrops', 'SECONDARY'], // its random(100) passes without a chance
    ['BattleActions.getDamage', 'CRIT'],
    ['Battle.onStallMove', 'STALL'],
];

// Draws inside a condition's own handler, named by the effect and event the
// reference is running (battle.effect, battle.event); the confusion self-hit
// roll stays a DAMAGE_ROLL.
const CONDITION_SITES = {
    'slp:Start': 'SLEEP_TURNS',
    'frz:BeforeMove': 'FREEZE_THAW',
    'par:BeforeMove': 'FULL_PARALYSIS',
    'confusion:Start': 'CONFUSION_TURNS',
    'confusion:BeforeMove': 'CONFUSION_HIT',
    // Poison Touch (step G14): its randomChance(3, 10) in onSourceDamagingHit. No committed trace had one before, so
    // the harness version stays 14 (it was an UNKNOWN draw, which the converter refuses).
    'poisontouch:DamagingHit': 'POISON_TOUCH',
};

// The event a draw happens in (innermost last), tracked by wrapping the
// reference's event entry points; it tells which sort a SPEED_TIE draw
// belongs to.
const eventStack = [];

function classify(stack, battle) {
    const frames = stack.split('\n').slice(2).map((s) => s.trim().split(' ')[1] || '');
    const ev = eventStack.length ? eventStack[eventStack.length - 1] : '';
    if (frames.some((f) => f.endsWith('.shuffle')) && frames.some((f) => f.endsWith('speedSort'))) {
        if (frames.includes('BattleQueue.sort')) {
            const team = battle.turn === 0 && battle.queue.list.some((a) => a.choice === 'team');
            return [team ? 'TEAM_ORDER' : 'SPEED_TIE', 'queue'];
        }
        if (frames.includes('Battle.eachEvent')) return ['SPEED_TIE', 'each:' + ev];
        if (frames.includes('Battle.fieldEvent')) return ['SPEED_TIE', 'field:' + ev];
        if (frames.includes('BattleActions.runSwitch')) return ['SPEED_TIE', 'switch-order'];
        return ['SPEED_TIE', 'event:' + ev];
    }
    if (frames.includes('BattleQueue.insertChoice')) return ['INSERT_TIE', 'queue'];
    if (frames.includes('Battle.getRandomTarget')) {
        // Where the target is needed: computing an action's priority and
        // speed (the result only feeds ModifyPriority), resolving a queued
        // choice, or executing the move.
        if (frames.includes('Battle.getActionSpeed')) return ['RANDOM_TARGET', 'action-speed'];
        if (frames.includes('BattleQueue.resolveAction')) return ['RANDOM_TARGET', 'resolve'];
        return ['RANDOM_TARGET', 'execute:' + randomTargetClass];
    }
    if (!frames.includes('Battle.randomizer')) {
        const site = CONDITION_SITES[`${battle.effect && battle.effect.id}:${battle.event && battle.event.id}`];
        if (site) return [site, ev];
    }
    for (const [frame, site] of SITE_RULES) {
        if (frames.includes(frame)) return [site, ev];
    }
    return ['UNKNOWN', frames.slice(0, 6).join('<')];
}

// What a tie draw shuffles or inserts among, so the trace converter can
// check the precondition of a drop rule. Entries: actions
// "A:<choice>:<slot>:<move>", handlers "H:<effect>:<holder>:<cb|end>",
// Pokemon "P:<slot>:<handlers for the current event>".
function slotOf(p) {
    return p && p.side ? p.side.id + 'abc'[p.position] : '-';
}

function holderOf(h) {
    const x = h.effectHolder;
    if (!x) return '-';
    if (x.side && x.species) return slotOf(x);
    if (x.sideConditions) return x.id;
    return 'field';
}

function describe(item, battle) {
    if (item && item.choice) {
        // A runSwitch action carries the number of SwitchIn handlers of its
        // Pokemon: the entry effects whose order a tie decides.
        const extra = item.choice === 'runSwitch' && item.pokemon ?
            ':' + battle.findEventHandlers(item.pokemon, 'SwitchIn').length : '';
        return `A:${item.choice}:${slotOf(item.pokemon)}:${item.move ? item.move.id : ''}${extra}`;
    }
    if (item && item.effect) {
        return `H:${item.effect.id || item.effect.name}:${holderOf(item)}:${item.callback ? 'cb' : 'end'}`;
    }
    if (item && item.species) {
        if (inRunSwitch) {
            // runSwitch sorts every active Pokemon; the order matters only
            // between Pokemon that are entering (S: not started, standing)
            // and have SwitchIn handlers (abilities' onStart included), and
            // between standing Pokemon with onAnySwitchIn handlers (White
            // Herb), which run for every Pokemon on the field: their effects
            // follow, only when there are any.
            const n = battle.findPokemonEventHandlers(item, 'onSwitchIn').length;
            const any = item.hp ? battle.findPokemonEventHandlers(item, 'onAnySwitchIn').map((h) => h.effect.id) : [];
            return `P:${slotOf(item)}:${n}:${!item.isStarted && !item.fainted ? 'S' : '-'}` +
                (any.length ? ':' + any.join('+') : '');
        }
        // The handlers the Pokemon has for the current event, by effect.
        const ev = eventStack.length ? eventStack[eventStack.length - 1] : '';
        const hs = ev ? battle.findEventHandlers(item, ev) : [];
        return `P:${slotOf(item)}:${hs.length}:${hs.map((h) => h.effect.id).join('+')}`;
    }
    return '?';
}

// True while BattleActions.runSwitch sorts the active Pokemon.
let inRunSwitch = false;

// The target class of the move a random target is drawn for (set while
// Battle.getRandomTarget runs).
let randomTargetClass = '';

function wrapEvents(battle) {
    const originalRandomTarget = battle.getRandomTarget;
    battle.getRandomTarget = function (pokemon, move) {
        randomTargetClass = this.dex.moves.get(move).target;
        try {
            return originalRandomTarget.call(this, pokemon, move);
        } finally {
            randomTargetClass = '';
        }
    };
    for (const name of ['runEvent', 'fieldEvent', 'eachEvent', 'singleEvent', 'priorityEvent']) {
        const original = battle[name];
        battle[name] = function (eventid, ...rest) {
            eventStack.push(eventid);
            try {
                return original.call(this, eventid, ...rest);
            } finally {
                eventStack.pop();
            }
        };
    }
}

// Records one battle and returns the trace text. `root` is the pinned
// checkout, `spec` the parsed spec and `specFile` its path (the trace stores
// the file name). It never exits the process: errors throw. The Showdown
// modules stay cached by require, so one process can record many battles; the
// state of this module is reset first, also after a run that threw.
function run(root, spec, specFile) {
    eventStack.length = 0;
    inRunSwitch = false;
    randomTargetClass = '';
    root = path.resolve(root);
    const {Battle} = require(path.join(root, 'dist', 'sim', 'battle'));
    const {PRNG} = require(path.join(root, 'dist', 'sim', 'prng'));
    const {Teams} = require(path.join(root, 'dist', 'sim', 'teams'));

    let battle = null;
    let draws = [];
    let group = null;
    let groupStart = 0;
    class RecordingPRNG extends PRNG {
        shuffle(items, start = 0, end = items.length) {
            inRunSwitch = new Error().stack.includes('BattleActions.runSwitch');
            group = items.slice(start, end).map((x) => describe(x, battle));
            inRunSwitch = false;
            groupStart = start;
            try {
                return super.shuffle(items, start, end);
            } finally {
                group = null;
            }
        }
        random(from, to) {
            const value = super.random(from, to);
            const lo = to === undefined || to === null ? 0 : from;
            const hi = to === undefined || to === null ? from : to;
            const [site, context] = classify(new Error().stack, battle);
            const draw = {site, context, lo, hi, value};
            if (site === 'SPEED_TIE' || site === 'TEAM_ORDER') {
                draw.group = group;
                draw.start = groupStart; // the shuffle's first index; draws are random(i, start + n)
            }
            if (site === 'INSERT_TIE') draw.group = battle.queue.list.map((x) => describe(x, battle));
            draws.push(draw);
            return value;
        }
    }
    const prng = new RecordingPRNG(spec.seed);
    battle = new Battle({formatid: spec.format, prng});
    wrapEvents(battle);
    for (const [i, id] of ['p1', 'p2'].entries()) {
        battle.setPlayer(id, {name: id, team: Teams.pack(Teams.import(spec.teams[i]))});
    }
    let logPos = 0;
    const takeLog = () => {
        const lines = battle.log.slice(logPos).filter((l) => !l.startsWith('|t:|') && l !== '|');
        logPos = battle.log.length;
        return lines;
    };
    const snapshot = () => ({
        turn: battle.turn,
        ended: battle.ended,
        winner: battle.winner || '',
        weather: battle.field.weather || '',
        weather_turns: battle.field.weatherState.duration || 0,
        terrain: battle.field.terrain || '',
        terrain_turns: battle.field.terrainState.duration || 0,
        trick_room: battle.field.pseudoWeather.trickroom ? battle.field.pseudoWeather.trickroom.duration || 0 : 0,
        sides: battle.sides.map((side) => ({
            request: side.requestState || '',
            // Remaining duration of Tailwind, Reflect and Light Screen (0 when absent).
            conditions: ['tailwind', 'reflect', 'lightscreen'].map((id) =>
                (side.sideConditions[id] ? side.sideConditions[id].duration || 0 : 0)),
            // Per active slot of a move request: 1 a selectable move, 0 a
            // disabled one (no PP, Fake Out), 2 Struggle.
            enabled: side.requestState === 'move' && side.activeRequest && side.activeRequest.active ?
                side.activeRequest.active.map((a) => (a.moves || []).map((mv) =>
                    (mv.id === 'struggle' ? 2 : (mv.disabled ? 0 : 1)))) : [],
            active: side.active.map((p) => (p ? side.pokemon.indexOf(p) : -1)),
            pokemon: side.pokemon.map((p) => ({
                species: p.species.name,
                set_species: p.set.species,
                mega: p.species.isMega ? 1 : 0,
                switch_flag: p.switchFlag ? 1 : 0, // a pivot (self-switch move, Emergency Exit) when standing
                hp: p.hp,
                maxhp: p.maxhp,
                item: p.item || '',
                status: p.status || '',
                status_time: p.statusState.time || 0,
                confusion: p.volatiles.confusion ? p.volatiles.confusion.time : 0,
                fainted: p.fainted,
                boosts: ['atk', 'def', 'spa', 'spd', 'spe', 'accuracy', 'evasion'].map((b) => p.boosts[b]),
                pp: p.moveSlots.map((m) => m.pp),
                volatiles: Object.keys(p.volatiles).sort(),
                // A two-turn move's lock: its move slot and the stored target location.
                locked: p.volatiles.twoturnmove && p.volatiles[p.volatiles.twoturnmove.move] ?
                    [p.moveSlots.findIndex((s) => s.id === p.volatiles.twoturnmove.move),
                        p.volatiles[p.volatiles.twoturnmove.move].targetLoc] : null,
                // A Choice item's lock (Team C): the slot of its move; absent without one,
                // so traces without a choice lock stay as they were.
                choice: p.volatiles.choicelock ?
                    p.moveSlots.findIndex((s) => s.id === p.volatiles.choicelock.move) : undefined,
            })),
        })),
    });

    const trace = {
        harness: HARNESS_VERSION,
        pin: PIN,
        spec: path.basename(specFile),
        format: spec.format,
        seed: spec.seed,
        start: {log: takeLog(), state: snapshot()},
        steps: [],
    };
    // A planned "move N [T]": a move without PP falls back to the first move
    // that has PP (Struggle when none has), a target is kept only for a move
    // that takes one, and a move that takes one without a target aims at 1.
    // An ally-only move (adjacentAlly, Helping Hand) aims at the ally's slot,
    // -2 from the left position and -1 from the right one, unless the plan
    // names an own-side target.
    let megaTaken = false;
    const planMove = (p, part) => {
        const w = part.split(' ');
        if (w[0] !== 'move') return part;
        if (p.getLockedMove()) return 'move 1'; // the only move, no target: the stored one is used
        // "mega" is kept while the Pokemon can still Mega Evolve and no other
        // slot of this choice declared it.
        const mega = w[w.length - 1] === 'mega' && p.canMegaEvo && !megaTaken ? ' mega' : '';
        if (w[w.length - 1] === 'mega') w.pop();
        if (mega) megaTaken = true;
        const usable = p.moveSlots.map((m, i) => (m.pp > 0 && !m.disabled ? i : -1)).filter((i) => i >= 0);
        if (!usable.length) return 'move 1';
        let n = Number(w[1]) - 1;
        if (!usable.includes(n)) n = usable[0];
        const target = battle.dex.moves.get(p.moveSlots[n].id).target;
        const takes = battle.actions.targetTypeChoices(target);
        let loc = w[2] || '1';
        if (target === 'adjacentAlly' && !(Number(loc) < 0)) loc = String(p.position - 2);
        return `move ${n + 1}` + (takes ? ' ' + loc : '') + mega;
    };
    const choose = (id, text) => {
        if (!battle[id].requestState) throw new Error(`${id} has no request for "${text}"`);
        if (!battle.choose(id, text)) throw new Error(`${id} choice rejected: "${text}": ${battle[id].choice.error}`);
    };
    if (spec.choices) {
        for (const entry of spec.choices) {
            draws = [];
            for (const id of ['p1', 'p2']) {
                if (entry[id] !== undefined) choose(id, entry[id]);
            }
            trace.steps.push({input: entry, draws, log: takeLog(), state: snapshot()});
            if (battle.ended) break;
        }
    } else {
        const next = {p1: 0, p2: 0};
        for (let step = 0; step < spec.plan.max_steps && !battle.ended; step++) {
            draws = [];
            const entry = {};
            // The sides asked at the start of the step: answering one side can
            // finish the step and ask both again.
            const asked = ['p1', 'p2'].filter((id) => battle[id].requestState);
            for (const id of asked) {
                const side = battle[id];
                let text;
                if (side.requestState === 'teampreview') {
                    text = 'team ' + side.pokemon.slice(0, 4).map((_, i) => i + 1).join('');
                } else if (side.requestState === 'switch') {
                    const used = new Set();
                    text = side.active.map((p) => {
                        if (!p || !p.switchFlag) return 'pass';
                        const i = side.pokemon.findIndex((q, k) => k >= side.active.length && !q.fainted && !used.has(k));
                        if (i < 0) return 'pass';
                        used.add(i);
                        return 'switch ' + (i + 1);
                    }).join(', ');
                } else {
                    const plan = spec.plan[id];
                    const raw = plan[Math.min(next[id], plan.length - 1)].split(', ');
                    next[id] += 1;
                    // A planned switch to a fainted or active Pokemon (or one
                    // the other slot already takes) goes to the first standing
                    // reserve, or becomes "move 1 1" when none is left; so does
                    // a planned switch of a trapped Pokemon (for example one
                    // charging a two-turn move).
                    const taken = new Set();
                    megaTaken = false;
                    text = side.active.map((p, k) => {
                        if (!p || p.fainted) return 'pass';
                        const w = raw[k].split(' ');
                        if (w[0] !== 'switch') return planMove(p, raw[k]);
                        if (p.trapped) return planMove(p, 'move 1 1');
                        let n = Number(w[1]) - 1;
                        const ok = (i) => i >= side.active.length && side.pokemon[i] && !side.pokemon[i].fainted &&
                            !taken.has(i);
                        if (!ok(n)) n = side.pokemon.findIndex((q, i) => ok(i));
                        if (n < 0) return planMove(p, 'move 1 1');
                        taken.add(n);
                        return 'switch ' + (n + 1);
                    }).join(', ');
                }
                choose(id, text);
                entry[id] = text;
            }
            trace.steps.push({input: entry, draws, log: takeLog(), state: snapshot()});
        }
    }
    return JSON.stringify(trace, null, 1) + '\n';
}

function main() {
    const args = process.argv.slice(2);
    if (args.length !== 2 && !(args.length === 4 && args[2] === '--check')) {
        process.stderr.write('usage: ps_trace.js <pinned checkout> <spec.json> [--check <trace.json>]\n');
        process.exit(2);
    }
    const root = path.resolve(args[0]);
    const spec = JSON.parse(fs.readFileSync(args[1], 'utf8'));
    const text = run(root, spec, args[1]);
    if (text.includes('"UNKNOWN"')) process.stderr.write('ps_trace: warning: unclassified draws\n');

    if (args.length === 4) {
        const have = fs.readFileSync(args[3], 'utf8').replace(/\r\n/g, '\n');
        if (have !== text) {
            process.stderr.write('ps_trace: ' + args[3] + ' differs from the reference run\n');
            process.exit(1);
        }
        process.stdout.write('ps_trace: ' + args[3] + ' matches the reference run\n');
        return;
    }
    process.stdout.write(text);
}

module.exports = {run, PIN, HARNESS_VERSION};

if (require.main === module) main();
