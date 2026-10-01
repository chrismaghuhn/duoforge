#!/usr/bin/env node
// Validates a Showdown team paste against the pinned Pokemon Showdown checkout
// (b2cb775b0616115b775534eaeff50300e1fc81fc) for gen9championsvgc2026regmc.
//
// usage: node validate-team.js [team.txt] [format]
//   env PS_ROOT   pinned checkout (default C:/Dev/src/pokemon-showdown, must be built: dist/sim exists)
//
// Prints the validator problems (none = legal), the pinned commit check and a
// per-set summary (species, gender, item, ability, nature, stat points with
// their total). Exit code 1 when the validator reports problems or when the
// checkout is not at the pin.
'use strict';
const fs = require('fs');
const path = require('path');
const cp = require('child_process');

const PIN = 'b2cb775b0616115b775534eaeff50300e1fc81fc';
const root = process.env.PS_ROOT || 'C:/Dev/src/pokemon-showdown';
const file = process.argv[2] || path.join(__dirname, 'team-c.txt');
const format = process.argv[3] || 'gen9championsvgc2026regmc';

const head = cp.execSync('git rev-parse HEAD', {cwd: root}).toString().trim();
if (head !== PIN) {
	console.error(`checkout ${root} is at ${head}, not at the pin ${PIN}`);
	process.exit(1);
}
const {TeamValidator} = require(root + '/dist/sim/team-validator');
const {Teams} = require(root + '/dist/sim/teams');

const text = fs.readFileSync(file, 'utf8');
const team = Teams.import(text);
if (!team) {
	console.error('Teams.import returned null');
	process.exit(1);
}
const problems = TeamValidator.get(format).validateTeam(team);

console.log(`format ${format}, pin ${head}, file ${path.basename(file)}, ${team.length} sets`);
for (const set of team) {
	const evs = set.evs || {};
	const total = Object.values(evs).reduce((a, b) => a + b, 0);
	const spread = ['hp', 'atk', 'def', 'spa', 'spd', 'spe'].map(s => `${evs[s] || 0}`).join('/');
	console.log(`  ${set.species} (${set.gender || '-'}) @ ${set.item}, ${set.ability}, ${set.nature}, ` +
		`sp ${spread} = ${total}, level ${set.level}: ${set.moves.join(', ')}`);
}
if (problems) {
	console.log('PROBLEMS:');
	for (const p of problems) console.log('  - ' + p);
	process.exit(1);
}
console.log('validator: no problems (team is legal)');
