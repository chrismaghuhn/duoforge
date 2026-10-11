// Validates a team pool with the pinned Showdown server's own team validator (the live-path arena, issue #362): a team
// the server refuses can never be challenged with, so the arena draws its pairs from the valid teams only and reports
// the others with the validator's reasons.
//
//   node tools/live/validate_pool.js <showdown dir> <format> <ids file> <teams dir> > valid.txt 2> refused.txt
//
// stdout: the valid ids, one per line, in the ids file's order; stderr: "<id>\t<problems joined by ' | '>" per refused
// team. A team file that is missing is refused too.
'use strict';
const fs = require('fs');
const path = require('path');

const [showdownDir, format, idsFile, teamsDir] = process.argv.slice(2);
if (!showdownDir || !format || !idsFile || !teamsDir) {
	console.error('usage: node tools/live/validate_pool.js <showdown dir> <format> <ids file> <teams dir>');
	process.exit(2);
}
const sim = require(path.resolve(showdownDir, 'dist', 'sim'));
const validator = sim.TeamValidator.get(format);
const ids = fs.readFileSync(idsFile, 'utf8').split(/\r?\n/).map(s => s.trim()).filter(Boolean);
let valid = 0;
for (const id of ids) {
	const file = path.join(teamsDir, `${id}.txt`);
	let problems;
	if (!fs.existsSync(file)) {
		problems = ['no team file'];
	} else {
		const team = sim.Teams.import(fs.readFileSync(file, 'utf8'));
		problems = team ? validator.validateTeam(team) : ['the paste does not import'];
	}
	if (problems && problems.length) {
		process.stderr.write(`${id}\t${problems.join(' | ')}\n`);
	} else {
		process.stdout.write(`${id}\n`);
		valid++;
	}
}
process.stderr.write(`validate_pool: ${valid} of ${ids.length} teams valid under ${format}\n`);
