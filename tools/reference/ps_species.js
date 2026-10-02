#!/usr/bin/env node
// Species data of the pinned Pokemon Showdown for the paste importer (tools/reference/import_paste.py).
//
// usage: node tools/reference/ps_species.js <pinned checkout> [format id]   (default gen9championsvgc2026regmc)
//
// Reads a JSON array of species names from stdin and writes one JSON object to stdout: for each name the facts of the
// pinned pokedex of that format that the importer reads, nothing else:
//
//   {"<name as given>": {"exists": bool, "name": "<canonical name>", "baseSpecies": "...", "forme": "...",
//                        "gender": "" | "M" | "F" | "N", "genderRatio": {"M": x, "F": y}, "isMega": bool,
//                        "requiredItem": "<the Mega Stone>" | null, "battleOnly": "<the species it changes from>" | null}}
//
// "gender" is the species' fixed gender ("M", "F"), "N" for no gender, and "" for a species that can be either. The
// script decides nothing: it only reads the pokedex.
'use strict';

const fs = require('fs');
const path = require('path');

const args = process.argv.slice(2);
if (args.length < 1 || args.length > 2) {
    process.stderr.write('usage: ps_species.js <pinned checkout> [format id]\n');
    process.exit(2);
}
const root = path.resolve(args[0]);
const format = args[1] || 'gen9championsvgc2026regmc';
if (!fs.existsSync(path.join(root, 'dist', 'sim', 'dex.js'))) {
    process.stderr.write(`ps_species: ${root}/dist/sim/dex.js not found (npm ci --ignore-scripts --omit=dev; node build)\n`);
    process.exit(2);
}
const {Dex} = require(path.join(root, 'dist', 'sim', 'dex'));
const dex = Dex.forFormat(format);

let names;
try {
    names = JSON.parse(fs.readFileSync(0, 'utf8'));
} catch (err) {
    process.stderr.write(`ps_species: stdin is not JSON: ${err.message}\n`);
    process.exit(2);
}
if (!Array.isArray(names) || !names.every((n) => typeof n === 'string')) {
    process.stderr.write('ps_species: stdin must be a JSON array of species names\n');
    process.exit(2);
}

const out = {};
for (const name of names) {
    const s = dex.species.get(name);
    out[name] = {
        exists: !!s.exists,
        name: s.name,
        baseSpecies: s.baseSpecies,
        forme: s.forme || '',
        gender: s.gender || '',
        genderRatio: {M: s.genderRatio.M, F: s.genderRatio.F},
        isMega: !!s.isMega,
        requiredItem: s.requiredItem || null,
        battleOnly: typeof s.battleOnly === 'string' ? s.battleOnly : null,
    };
}
process.stdout.write(JSON.stringify(out) + '\n');
