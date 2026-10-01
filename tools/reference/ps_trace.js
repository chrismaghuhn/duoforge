#!/usr/bin/env node
// Reference traces of complete battles from the pinned Pokemon Showdown
// (decision 0006 section 7).
//
// usage: node tools/reference/ps_trace.js <pinned checkout> <spec.json> [--check <trace.json>]
//
// A spec names the format, a PRNG seed, both teams (Showdown paste text,
// gender always given) and the choices in request order. The harness runs
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
'use strict';

const fs = require('fs');
const path = require('path');

const PIN = 'b2cb775b0616115b775534eaeff50300e1fc81fc';
const HARNESS_VERSION = 1;

// Stack frame name -> site. The first match in stack order wins.
const SITE_RULES = [
    ['BattleActions.hitStepAccuracy', 'ACCURACY'],
    ['Battle.randomizer', 'DAMAGE_ROLL'],
    ['BattleActions.secondaries', 'SECONDARY'],
    ['BattleActions.getDamage', 'CRIT'],
    ['Battle.onStallMove', 'STALL'],
];

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
        return ['RANDOM_TARGET', 'execute'];
    }
    for (const [frame, site] of SITE_RULES) {
        if (frames.includes(frame)) return [site, ev];
    }
    return ['UNKNOWN', frames.slice(0, 6).join('<')];
}

function wrapEvents(battle) {
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

function main() {
    const args = process.argv.slice(2);
    if (args.length !== 2 && !(args.length === 4 && args[2] === '--check')) {
        process.stderr.write('usage: ps_trace.js <pinned checkout> <spec.json> [--check <trace.json>]\n');
        process.exit(2);
    }
    const root = path.resolve(args[0]);
    const {Battle} = require(path.join(root, 'dist', 'sim', 'battle'));
    const {PRNG} = require(path.join(root, 'dist', 'sim', 'prng'));
    const {Teams} = require(path.join(root, 'dist', 'sim', 'teams'));
    const spec = JSON.parse(fs.readFileSync(args[1], 'utf8'));

    let battle = null;
    let draws = [];
    class RecordingPRNG extends PRNG {
        random(from, to) {
            const value = super.random(from, to);
            const lo = to === undefined || to === null ? 0 : from;
            const hi = to === undefined || to === null ? from : to;
            const [site, context] = classify(new Error().stack, battle);
            draws.push({site, context, lo, hi, value});
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
        terrain: battle.field.terrain || '',
        sides: battle.sides.map((side) => ({
            request: side.requestState || '',
            active: side.active.map((p) => (p ? side.pokemon.indexOf(p) : -1)),
            pokemon: side.pokemon.map((p) => ({
                species: p.species.name,
                hp: p.hp,
                maxhp: p.maxhp,
                status: p.status || '',
                fainted: p.fainted,
                boosts: ['atk', 'def', 'spa', 'spd', 'spe', 'accuracy', 'evasion'].map((b) => p.boosts[b]),
                pp: p.moveSlots.map((m) => m.pp),
                volatiles: Object.keys(p.volatiles).sort(),
            })),
        })),
    });

    const trace = {
        harness: HARNESS_VERSION,
        pin: PIN,
        spec: path.basename(args[1]),
        format: spec.format,
        seed: spec.seed,
        start: {log: takeLog(), state: snapshot()},
        steps: [],
    };
    for (const entry of spec.choices) {
        draws = [];
        for (const id of ['p1', 'p2']) {
            if (entry[id] === undefined) continue;
            if (!battle[id].requestState) throw new Error(`${id} has no request for "${entry[id]}"`);
            if (!battle.choose(id, entry[id])) throw new Error(`${id} choice rejected: "${entry[id]}"`);
        }
        trace.steps.push({input: entry, draws, log: takeLog(), state: snapshot()});
        if (battle.ended) break;
    }
    const text = JSON.stringify(trace, null, 1) + '\n';
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

main();
