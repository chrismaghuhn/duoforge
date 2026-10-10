'use strict';
// Random teams of the pinned Showdown's "[Gen 9 Champions] Random Doubles Battle" generator, one JSON line per team.
//
// usage: node tools/reference/ps_random_teams.js <checkout> <seed: 16 hex digits> <first index> <count>
//
// Team i uses the PRNG seed "sodium,<seed><i as 16 hex digits>", so a team depends only on the pin, the seed and its
// index. Each line is {"index": i, "seed": "...", "team": [...]} with Showdown's own sets, names resolved through the
// champions dex (species, item, ability and move names, not ids). Nothing is changed here: the level, the stat points,
// the missing nature and the items are Showdown's (random_teams.py turns them into registry pastes and says how).
const path = require('path');

const [checkout, seed, first, count] = process.argv.slice(2);
if (!checkout || !/^[0-9a-f]{16}$/.test(seed || '') || !/^\d+$/.test(first || '') || !/^\d+$/.test(count || '')) {
	process.stderr.write('usage: node ps_random_teams.js <checkout> <seed: 16 hex digits> <first index> <count>\n');
	process.exit(2);
}
const {Teams, Dex} = require(path.join(checkout, 'dist', 'sim'));
const FORMAT = 'gen9championsrandomdoublesbattle';
const format = Dex.formats.get(FORMAT);
if (!format.exists || format.mod !== 'champions' || format.gameType !== 'doubles') {
	process.stderr.write(`the checkout has no ${FORMAT} (champions, doubles)\n`);
	process.exit(1);
}
const dex = Dex.mod('champions');
const name = (table, id) => {
	const entry = dex[table].get(id);
	if (!entry.exists) throw new Error(`${table} ${id} is not in the champions dex`);
	return entry.name;
};
for (let i = Number(first); i < Number(first) + Number(count); i++) {
	const s = `sodium,${seed}${i.toString(16).padStart(16, '0')}`;
	const team = Teams.generate(FORMAT, {seed: s}).map(set => ({
		species: name('species', set.species),
		gender: set.gender || '',
		shiny: !!set.shiny,
		level: set.level,
		item: set.item ? name('items', set.item) : '',
		ability: name('abilities', set.ability),
		nature: set.nature || '',
		evs: set.evs,
		ivs: set.ivs,
		moves: set.moves.map(m => name('moves', m)),
	}));
	process.stdout.write(JSON.stringify({index: i, seed: s, team}) + '\n');
}
