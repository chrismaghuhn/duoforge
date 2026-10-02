// Prints the source entries of a move, ability, item or species at the pinned
// Showdown checkout, with file:line, for the base data and the Champions mod
// (read-only research tooling for docs/research/expansion/team-gaps.md).
//
// usage: node tg_show.js <moves|abilities|items|pokedex|formats-data|learnsets|conditions> <id> [<id> ...]
//
// An entry is the top-level `\tid: {` block of data/<file>.ts and of
// data/mods/champions/<file>.ts; the Champions entry overrides the base one
// (`inherit: true`). Lines are printed as `file:line| text`.
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = process.env.DUOFORGE_PS_REFERENCE_DIR || 'C:/Dev/src/pokemon-showdown';

function entry(file, id) {
	const full = path.join(ROOT, file);
	if (!fs.existsSync(full)) return null;
	const lines = fs.readFileSync(full, 'utf8').replace(/\r\n/g, '\n').split('\n');
	const re = new RegExp('^\\t' + id + ': \\{');
	for (let i = 0; i < lines.length; i++) {
		if (!re.test(lines[i])) continue;
		if (/\},\s*$/.test(lines[i]) && (lines[i].match(/\{/g) || []).length === (lines[i].match(/\}/g) || []).length) {
			return {file, first: i + 1, last: i + 1, text: [lines[i]]};
		}
		let depth = 0;
		for (let j = i; j < lines.length; j++) {
			depth += (lines[j].match(/\{/g) || []).length - (lines[j].match(/\}/g) || []).length;
			if (depth <= 0) return {file, first: i + 1, last: j + 1, text: lines.slice(i, j + 1)};
		}
	}
	return null;
}

function show(kind, id) {
	for (const file of [`data/${kind}.ts`, `data/mods/champions/${kind}.ts`]) {
		const e = entry(file, id);
		if (!e) {
			console.log(`-- ${file}: no entry ${id}`);
			continue;
		}
		console.log(`-- ${file}:${e.first}-${e.last}`);
		e.text.forEach((t, k) => console.log(`${e.first + k}| ${t}`));
	}
}

const [kind, ...ids] = process.argv.slice(2);
if (!kind || !ids.length) {
	console.error('usage: node tg_show.js <moves|abilities|items|pokedex|formats-data|learnsets|conditions> <id> ...');
	process.exit(2);
}
for (const id of ids) {
	console.log(`===== ${kind} ${id}`);
	show(kind, id);
}
