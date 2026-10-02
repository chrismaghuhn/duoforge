#!/usr/bin/env node
// Stats of the pinned Pokemon Showdown for the M11 replay pipeline (python/duoforge_replay): the own side's stats in a
// replay come from a stat point prior, and Python never computes a stat.
//
// usage: node tools/reference/ps_stats.js <pinned checkout> [--serve]
//        node tools/reference/ps_stats.js <pinned checkout> --choice-items
//
// Reads a JSON array of {"species": NAME, "nature": NAME, "sp": [hp, atk, def, spa, spd, spe]} from stdin and writes a
// JSON array of [hp, atk, def, spa, spd, spe]: Battle.spreadModify of the format gen9championsvgc2026regmc (the
// Champions statModify: Stat Points in the EV field, level 50). With --serve it answers one such array per input line
// until stdin closes (one persistent process per worker). An unknown species or nature exits 2 (one-shot) or answers
// {"error": ...} (--serve). --choice-items prints the sorted ids of the format's items with isChoice.
'use strict';

const fs = require('fs');
const path = require('path');
const readline = require('readline');

const FORMAT = 'gen9championsvgc2026regmc';
const STATS = ['hp', 'atk', 'def', 'spa', 'spd', 'spe'];

const args = process.argv.slice(2);
if (args.length < 1 || args.length > 2 || (args.length === 2 && !['--serve', '--choice-items'].includes(args[1]))) {
    process.stderr.write('usage: ps_stats.js <pinned checkout> [--serve | --choice-items]\n');
    process.exit(2);
}
const root = path.resolve(args[0]);
if (!fs.existsSync(path.join(root, 'dist', 'sim', 'battle.js'))) {
    process.stderr.write(`ps_stats: ${root}/dist/sim/battle.js not found (npm ci --ignore-scripts --omit=dev; node build)\n`);
    process.exit(2);
}
const {Battle} = require(path.join(root, 'dist', 'sim', 'battle'));
const battle = new Battle({formatid: FORMAT});
const dex = battle.dex;

function stats(query) {
    const species = dex.species.get(query.species);
    if (!species.exists) throw new Error(`unknown species ${JSON.stringify(query.species)}`);
    const nature = dex.natures.get(query.nature);
    if (!nature.exists) throw new Error(`unknown nature ${JSON.stringify(query.nature)}`);
    if (!Array.isArray(query.sp) || query.sp.length !== 6 || !query.sp.every((v) => Number.isInteger(v) && v >= 0)) {
        throw new Error(`stat points must be six non-negative integers: ${JSON.stringify(query.sp)}`);
    }
    const set = {
        species: species.name, nature: nature.name, level: 50,
        evs: Object.fromEntries(STATS.map((s, i) => [s, query.sp[i]])),
        ivs: Object.fromEntries(STATS.map((s) => [s, 31])),
    };
    const out = battle.spreadModify(species.baseStats, set);
    return STATS.map((s) => out[s]);
}

if (args[1] === '--choice-items') {
    const ids = dex.items.all().filter((i) => i.isChoice).map((i) => i.id).sort();
    process.stdout.write(JSON.stringify(ids) + '\n');
} else if (args[1] === '--serve') {
    const rl = readline.createInterface({input: process.stdin});
    rl.on('line', (line) => {
        let answer;
        try {
            answer = JSON.parse(line).map(stats);
        } catch (err) {
            answer = {error: err.message};
        }
        process.stdout.write(JSON.stringify(answer) + '\n');
    });
} else {
    try {
        const queries = JSON.parse(fs.readFileSync(0, 'utf8'));
        process.stdout.write(JSON.stringify(queries.map(stats)) + '\n');
    } catch (err) {
        process.stderr.write(`ps_stats: ${err.message}\n`);
        process.exit(2);
    }
}
