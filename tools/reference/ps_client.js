#!/usr/bin/env node
// Client streams of committed battles from the pinned Pokemon Showdown: what a
// websocket client of each player receives (the Showdown live adapter's oracle,
// docs/superpowers/specs/2026-10-02-showdown-live-design.md section 8).
//
// usage: node tools/reference/ps_client.js <pinned checkout> <repo root> (--all | NAME...) [--check]
//        node tools/reference/ps_client.js <pinned checkout> --pack <team file>
//
// Each battle is replayed from its committed spec (format, seed, teams) with
// the choices its trace (tests/reference/traces/NAME.json) recorded, the way
// the server runs it: a Battle whose output goes through `send`, with
// sendUpdates() after every command as BattleStream._write does. After both
// players are set (team preview) the battle shows the open team sheets, as the
// server does when both players accept them (sim/battle.ts
// showOpenTeamSheets; it draws no random numbers). --all takes every committed
// closure battle (a spec without "data": "team_c").
//
// Output: one JSON object per message, in the order a client gets them:
//   {"battle": NAME, "to": "p1"|"p2", "lines": [...]}
// A sideupdate (a request, an error) goes to its side; an update goes to each
// player with the split lines resolved for that player
// (extractChannelMessages). Timestamps (|t:|) and empty messages are dropped.
//
// Each step's omniscient lines (filtered as ps_trace.js takeLog) must equal the
// trace's, and the start lines without the two |showteam| lines the trace's
// start: otherwise the battle is not the recorded one, and the tool exits 1.
// --check writes no stream and prints a summary.
//
// --pack prints Teams.pack(Teams.import(text)) of a team file.
'use strict';

const fs = require('fs');
const path = require('path');

function loadShowdown(checkout) {
    const dist = (...p) => require(path.join(checkout, 'dist', 'sim', ...p));
    return {
        Battle: dist('battle').Battle,
        extractChannelMessages: dist('battle').extractChannelMessages,
        PRNG: dist('prng').PRNG,
        Teams: dist('teams').Teams,
    };
}

function closureBattles(root) {
    const dir = path.join(root, 'tests', 'reference', 'specs');
    return fs.readdirSync(dir).filter((f) => f.endsWith('.json')).sort().map((f) => f.slice(0, -5))
        .filter((name) => {
            const data = JSON.parse(fs.readFileSync(path.join(dir, name + '.json'), 'utf8')).data;
            return data === undefined;
        });
}

function readJson(root, kind, name) {
    return JSON.parse(fs.readFileSync(path.join(root, 'tests', 'reference', kind, name + '.json'), 'utf8'));
}

// The client streams of one battle as an array of messages; throws when the
// replay differs from the trace.
function replay(sd, root, name) {
    const spec = readJson(root, 'specs', name);
    const trace = readJson(root, 'traces', name);
    const messages = [];
    const send = (type, data) => {
        if (Array.isArray(data)) data = data.join('\n');
        if (type === 'sideupdate') {
            const cut = data.indexOf('\n');
            const lines = data.slice(cut + 1).split('\n').filter((l) => l !== '');
            if (lines.length) messages.push({battle: name, to: data.slice(0, cut), lines});
        } else if (type === 'update') {
            const channels = sd.extractChannelMessages(data, [1, 2]);
            for (const [channel, to] of [[1, 'p1'], [2, 'p2']]) {
                const lines = channels[channel].filter((l) => l !== '' && !l.startsWith('|t:|'));
                if (lines.length) messages.push({battle: name, to, lines});
            }
        }
    };
    const battle = new sd.Battle({formatid: spec.format, prng: new sd.PRNG(spec.seed), send});
    let logPos = 0;
    const takeLog = () => {
        const lines = battle.log.slice(logPos).filter((l) => !l.startsWith('|t:|') && l !== '|');
        logPos = battle.log.length;
        return lines;
    };
    const same = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);
    for (const [i, id] of ['p1', 'p2'].entries()) {
        battle.setPlayer(id, {name: id, team: sd.Teams.pack(sd.Teams.import(spec.teams[i]))});
        battle.sendUpdates();
    }
    battle.showOpenTeamSheets();
    battle.sendUpdates();
    const start = takeLog();
    const sheets = start.filter((l) => l.startsWith('|showteam|'));
    if (sheets.length !== 2 || !same(start.filter((l) => !l.startsWith('|showteam|')), trace.start.log)) {
        throw new Error(`ps_client: ${name} start differs from the trace`);
    }
    trace.steps.forEach((step, k) => {
        for (const id of ['p1', 'p2']) {
            if (step.input[id] === undefined) continue;
            if (!battle.choose(id, step.input[id])) {
                throw new Error(`ps_client: ${name} step ${k}: ${id} choice rejected: ${step.input[id]}`);
            }
            battle.sendUpdates();
        }
        if (!same(takeLog(), step.log)) throw new Error(`ps_client: ${name} step ${k} differs from the trace`);
    });
    return messages;
}

function main() {
    const args = process.argv.slice(2);
    if (args.length === 3 && args[1] === '--pack') {
        const sd = loadShowdown(path.resolve(args[0]));
        process.stdout.write(sd.Teams.pack(sd.Teams.import(fs.readFileSync(args[2], 'utf8'))) + '\n');
        return;
    }
    const check = args.includes('--check');
    const rest = args.filter((a) => a !== '--check');
    if (rest.length < 3) {
        process.stderr.write('usage: ps_client.js <pinned checkout> <repo root> (--all | NAME...) [--check]\n' +
            '       ps_client.js <pinned checkout> --pack <team file>\n');
        process.exitCode = 2;
        return;
    }
    const sd = loadShowdown(path.resolve(rest[0]));
    const root = path.resolve(rest[1]);
    const names = rest[2] === '--all' && rest.length === 3 ? closureBattles(root) : rest.slice(2);
    try {
        for (const name of names) {
            const messages = replay(sd, root, name);
            if (!check) process.stdout.write(messages.map((m) => JSON.stringify(m)).join('\n') + '\n');
        }
    } catch (e) {
        process.stderr.write(e.message + '\n');
        process.exitCode = 1;
        return;
    }
    if (check) process.stdout.write(`ps_client: ${names.length} battles match their traces\n`);
}

if (require.main === module) main();
