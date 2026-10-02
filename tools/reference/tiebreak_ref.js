#!/usr/bin/env node
// Reference values of Battle.tiebreak() from the pinned Pokemon Showdown
// (the engine's duoforge_battle_tiebreak, tests/test_tiebreak.c).
//
// usage: node tools/reference/tiebreak_ref.js <pinned checkout> <repo root> [--check <file>]
//
// The committed battles (tests/reference/specs, with the choices actually
// made in tests/reference/traces) are replayed on a fresh Battle up to
// several prefixes of their choice entries, and at each stop the pinned
// Battle.tiebreak() is called (sim/battle.ts:1467-1508). It ends the battle,
// so every stop is its own replay; a battle that had already ended at its
// stop is recorded with its own winner, which is what the engine returns
// for a terminal battle.
//
// For every stop the fixture holds the winner and the three quantities the
// tiebreak compares, taken from the battle's state immediately before the
// call with the pin's own expressions: the Pokemon not fainted, the HP
// percentage (the sum of hp / maxhp over side.pokemon in its array order,
// times 100, divided by 6, as the 64 bits of the double) and the total HP.
// They are cross-checked against what tiebreak() prints (the counts, the
// rounded percentages and the totals of the sides it compared), and the
// winner against this script's own copy of the three steps, so a drift of
// either is an error of the script, not a silent fixture.
//
// Without --check it prints tests/reference/tiebreak_ref.h to stdout. With
// --check it compares the output to the given file byte for byte and exits
// non-zero on a difference. CTest never needs Node: the header is committed,
// and the check runs only when DUOFORGE_PS_REFERENCE_DIR is set.
'use strict';

const fs = require('fs');
const path = require('path');

const PIN = 'b2cb775b0616115b775534eaeff50300e1fc81fc';
const HARNESS_VERSION = 1;

// The stops of a battle with `n` choice entries: the first prefixes, every
// third one after them, and the last two. Prefix 0 is the state asking for
// the team (side.pokemon is the whole roster), the last one is usually the
// ended battle. (Every prefix would be a replay each: about 80 s for the
// committed battles, with 3000 stops.)
function stopsOf(n) {
    const stops = [];
    for (let k = 0; k <= n; k++) {
        if (k <= 2 || k % 3 === 0 || k >= n - 1) stops.push(k);
    }
    return stops;
}

function bitsOf(x) {
    const view = new DataView(new ArrayBuffer(8));
    view.setFloat64(0, x);
    const hex = (v) => v.toString(16).padStart(8, '0');
    return '0x' + hex(view.getUint32(0)) + hex(view.getUint32(4)) + 'ull';
}

// The three steps of Battle.tiebreak on the quantities, with the pin's
// comparison (===) and its order; returns [winner, stage] with the winner
// 'p1', 'p2' or '' for a tie and the stage 1 (count), 2 (HP percentage),
// 3 (total HP) or 4 (tie).
function decide(notFainted, pct, total) {
    const ids = ['p1', 'p2'];
    const maxNotFainted = Math.max(...notFainted);
    let tied = [0, 1].filter((i) => notFainted[i] === maxNotFainted);
    if (tied.length <= 1) return [ids[tied[0]], 1];
    const maxPct = Math.max(...tied.map((i) => pct[i]));
    tied = tied.filter((i) => pct[i] === maxPct);
    if (tied.length <= 1) return [ids[tied[0]], 2];
    const maxTotal = Math.max(...tied.map((i) => total[i]));
    tied = tied.filter((i) => total[i] === maxTotal);
    if (tied.length <= 1) return [ids[tied[0]], 3];
    return ['', 4];
}

// What tiebreak() printed: side id -> {left, pct, total} for the sides each
// message named.
function printed(lines) {
    const seen = {p1: {}, p2: {}};
    for (const line of lines) {
        const m = /^\|-message\|(.*)$/.exec(line);
        if (!m) continue;
        for (const part of m[1].split('; ')) {
            let r = /^(p[12]): (\d+) Pokemon left$/.exec(part);
            if (r) seen[r[1]].left = Number(r[2]);
            r = /^(p[12]): (-?\d+)% total HP left$/.exec(part);
            if (r) seen[r[1]].pct = Number(r[2]);
            r = /^(p[12]): (-?\d+) total HP left$/.exec(part);
            if (r) seen[r[1]].total = Number(r[2]);
        }
    }
    return seen;
}

function main() {
    const args = process.argv.slice(2);
    if (args.length !== 2 && !(args.length === 4 && args[2] === '--check')) {
        process.stderr.write('usage: tiebreak_ref.js <pinned checkout> <repo root> [--check <file>]\n');
        process.exit(2);
    }
    const root = path.resolve(args[0]);
    const repo = path.resolve(args[1]);
    const {Battle} = require(path.join(root, 'dist', 'sim', 'battle'));
    const {PRNG} = require(path.join(root, 'dist', 'sim', 'prng'));
    const {Teams} = require(path.join(root, 'dist', 'sim', 'teams'));
    const specDir = path.join(repo, 'tests', 'reference', 'specs');
    const traceDir = path.join(repo, 'tests', 'reference', 'traces');

    // A fresh battle with the first `prefix` choice entries of the trace made.
    const replay = (spec, trace, prefix) => {
        const battle = new Battle({formatid: spec.format, prng: new PRNG(spec.seed)});
        for (const [i, id] of ['p1', 'p2'].entries()) {
            battle.setPlayer(id, {name: id, team: Teams.pack(Teams.import(spec.teams[i]))});
        }
        for (let k = 0; k < prefix; k++) {
            const entry = trace.steps[k].input;
            for (const id of ['p1', 'p2']) {
                if (entry[id] === undefined) continue;
                if (!battle[id].requestState) throw new Error(`${spec.name}: ${id} has no request for "${entry[id]}"`);
                if (!battle.choose(id, entry[id])) {
                    throw new Error(`${spec.name}: ${id} choice rejected: "${entry[id]}": ${battle[id].choice.error}`);
                }
            }
        }
        return battle;
    };

    const out = [];
    const line = (s) => out.push(s);
    line('/*');
    line(' * GENERATED by tools/reference/tiebreak_ref.js (harness version ' + HARNESS_VERSION + ') from Pokemon');
    line(' * Showdown at ' + PIN + ',');
    line(' * Battle.tiebreak() (sim/battle.ts:1467-1508) called on fresh replays of the committed battles');
    line(' * (tests/reference/specs, with the choices of tests/reference/traces). Do not edit by hand.');
    line(' */');
    line('#ifndef DUOFORGE_TESTS_REFERENCE_TIEBREAK_REF_H');
    line('#define DUOFORGE_TESTS_REFERENCE_TIEBREAK_REF_H');
    line('#include <stdint.h>');
    line('');
    line('/* choice entries made before the stop (0: before the team is picked), the battle had already ended');
    line(' * (result is its own), the result (DUOFORGE_RESULT_*), the stage that decided (1 Pokemon left, 2 HP');
    line(' * percentage, 3 total HP, 4 a tie; 0 for an ended battle), per side the Pokemon not fainted and the');
    line(' * total HP and the HP percentage as the bits of the double (the sum of hp / maxhp over side.pokemon');
    line(' * in its array order, times 100, divided by 6) */');
    line('typedef struct df_tb_stop {');
    line('    uint16_t prefix;');
    line('    uint8_t ended, result, stage, not_fainted[2];');
    line('    uint32_t hp_total[2];');
    line('    uint64_t pct_bits[2];');
    line('} df_tb_stop;');
    line('typedef struct df_tb_battle {');
    line('    const char *name;');
    line('    uint32_t choice_entries; /* the battle\'s choice entries in the trace */');
    line('    const df_tb_stop *stops;');
    line('    uint32_t stop_count;');
    line('} df_tb_battle;');
    line('');

    const names = fs.readdirSync(specDir).filter((f) => f.endsWith('.json')).sort().map((f) => f.slice(0, -5));
    const tables = [];
    const stats = {stops: 0, ended: 0, byStage: [0, 0, 0, 0, 0], winners: {p1: 0, p2: 0, '': 0}};
    for (const name of names) {
        const specFile = path.join(specDir, name + '.json');
        const spec = JSON.parse(fs.readFileSync(specFile, 'utf8'));
        spec.name = name;
        const trace = JSON.parse(fs.readFileSync(path.join(traceDir, name + '.json'), 'utf8'));
        if (trace.pin !== PIN || trace.spec !== name + '.json') {
            throw new Error(`${name}: the trace is not of this spec and pin`);
        }
        const rows = [];
        for (const prefix of stopsOf(trace.steps.length)) {
            const battle = replay(spec, trace, prefix);
            // The quantities of sim/battle.ts:1475-1504, before the call.
            const notFainted = battle.sides.map((side) => side.pokemon.filter((p) => !p.fainted).length);
            const pct = battle.sides.map((side) =>
                side.pokemon.map((p) => p.hp / p.maxhp).reduce((a, b) => a + b) * 100 / 6);
            const total = battle.sides.map((side) => side.pokemon.map((p) => p.hp).reduce((a, b) => a + b));
            let ended = 0;
            let winner;
            let stage = 0;
            if (battle.ended) {
                ended = 1;
                winner = battle.winner;
                stats.ended++;
            } else {
                const logStart = battle.log.length;
                if (battle.tiebreak() === false || !battle.ended) throw new Error(`${name}@${prefix}: tiebreak did nothing`);
                winner = battle.winner;
                const [mine, myStage] = decide(notFainted, pct, total);
                if (mine !== winner) {
                    throw new Error(`${name}@${prefix}: the pin says "${winner}", this script "${mine}"`);
                }
                stage = myStage;
                const seen = printed(battle.log.slice(logStart));
                for (const [i, id] of ['p1', 'p2'].entries()) {
                    if (seen[id].left !== notFainted[i]) throw new Error(`${name}@${prefix}: ${id} left`);
                    if (seen[id].pct !== undefined && seen[id].pct !== Math.round(pct[i])) {
                        throw new Error(`${name}@${prefix}: ${id} percentage ${seen[id].pct} vs ${pct[i]}`);
                    }
                    if (seen[id].total !== undefined && seen[id].total !== total[i]) {
                        throw new Error(`${name}@${prefix}: ${id} total ${seen[id].total} vs ${total[i]}`);
                    }
                }
                // The messages of the stages reached are exactly those the decision implies.
                const reachedPct = stage >= 2;
                const reachedTotal = stage >= 3;
                for (const id of ['p1', 'p2']) {
                    if ((seen[id].pct !== undefined) !== reachedPct || (seen[id].total !== undefined) !== reachedTotal) {
                        throw new Error(`${name}@${prefix}: the printed stages disagree with the decision`);
                    }
                }
            }
            if (winner !== 'p1' && winner !== 'p2' && winner !== '') throw new Error(`${name}@${prefix}: winner "${winner}"`);
            const result = winner === 'p1' ? 1 : winner === 'p2' ? 2 : 3;
            stats.stops++;
            stats.byStage[stage]++;
            stats.winners[winner]++;
            rows.push(`    {${prefix}u, ${ended}u, ${result}u, ${stage}u, {${notFainted.map((x) => x + 'u').join(', ')}}, ` +
                `{${total.map((x) => x + 'u').join(', ')}}, {${pct.map(bitsOf).join(', ')}}},`);
        }
        tables.push({name, entries: trace.steps.length, rows});
    }

    for (const t of tables) {
        line(`static const df_tb_stop tb_${t.name}[] = {`);
        for (const r of t.rows) line(r);
        line('};');
    }
    line('');
    line('static const df_tb_battle tb_battles[] = {');
    for (const t of tables) {
        line(`    {"${t.name}", ${t.entries}u, tb_${t.name}, sizeof tb_${t.name} / sizeof tb_${t.name}[0]},`);
    }
    line('};');
    line('');
    line(`/* ${stats.stops} stops: ${stats.ended} of an ended battle; decided by the count ${stats.byStage[1]},`);
    line(` * the HP percentage ${stats.byStage[2]}, the total HP ${stats.byStage[3]}, a tie ${stats.byStage[4]};`);
    line(` * winners: side 0 ${stats.winners.p1}, side 1 ${stats.winners.p2}, tie ${stats.winners['']} */`);
    line('#endif');
    const text = out.join('\n') + '\n';

    if (args.length === 4) {
        const have = fs.readFileSync(args[3], 'utf8').replace(/\r\n/g, '\n');
        if (have !== text) {
            process.stderr.write('tiebreak_ref: ' + args[3] + ' differs from the reference run\n');
            process.exit(1);
        }
        process.stdout.write('tiebreak_ref: ' + args[3] + ' matches the reference run\n');
        return;
    }
    process.stdout.write(text);
}

main();
