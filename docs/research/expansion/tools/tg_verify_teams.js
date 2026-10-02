// Independent re-check of the missing list of the cheapest-team curve of the
// VGCPastes survey (read-only research tooling for
// docs/research/expansion/team-gaps.md).
//
// The main session compared real Reg M-C pastes with DuoForge's tables by
// name (names in `mc_full_coverage.json`, order in `curve.txt`, both outside
// git). This script redoes it from the paste text with the pinned Showdown:
//
//   - every paste is parsed with `Teams.import` and every set is checked with
//     the pinned `TeamValidator` (the format's own legality, Stat Points
//     included: 66 in total, 32 per stat);
//   - species (as the forme the engine would need: a Mega name becomes its
//     base forme with the stone), item, ability, moves and nature are looked
//     up in DuoForge's extended tables (read from src/data/*.h and *.c, so
//     the answer is what the engine has today, not what a list says);
//   - what a name match cannot show is checked too: the engine's member rule
//     (src/state/closure_member.c) accepts only the moves of the forme's one
//     fixed set and only the forme's one ability, so each set is compared
//     with the table's set of its forme.
//
// usage: node tg_verify_teams.js [--all] [--json <out.json>]
// As a module: require('./tg_verify_teams.js').analyse(ids) -> {results, union, disagreements}.
//
// Paths: the pinned checkout and the survey directory are hard-coded like the
// other scripts of this directory (DUOFORGE_PS_REFERENCE_DIR and
// DUOFORGE_SURVEY_DIR override them). The pastes are not copied into the
// repository: ids and links only.
'use strict';
const fs = require('fs');
const path = require('path');

const PS = process.env.DUOFORGE_PS_REFERENCE_DIR || 'C:/Dev/src/pokemon-showdown';
const SURVEY = process.env.DUOFORGE_SURVEY_DIR || 'C:/Dev/src/duoforge-data/vgcpastes-mc-2026-10-02';
const REPO = path.resolve(__dirname, '..', '..', '..', '..');
const {Dex, Teams, TeamValidator} = require(PS + '/dist/sim');

// The 17 teams of curve.txt, in its order (cheapest team first, by gap count).
const CURVE = ['MC405', 'MC408', 'MC246', 'MC371', 'MC373', 'MC177', 'MC22', 'MC97', 'MC167', 'MC264', 'MC392', 'MC36',
	'MC56', 'MC215', 'MC196', 'MC172', 'MC385'];

const format = Dex.formats.get('gen9championsvgc2026regmc');
const dex = Dex.forFormat(format);
const validator = TeamValidator.get(format.id);
const toID = s => String(s).toLowerCase().replace(/[^a-z0-9]/g, '');

// ---------------------------------------------------------------- tables
function read(rel) {
	return fs.readFileSync(path.join(REPO, rel), 'utf8').replace(/\r\n/g, '\n');
}
function defines(text, prefix) {
	const out = {};
	const re = new RegExp('#define DFI_' + prefix + '_([A-Z0-9]+) (\\d+)u', 'g');
	let m;
	while ((m = re.exec(text))) if (m[1] !== 'COUNT') out[m[1].toLowerCase()] = Number(m[2]);
	return out;
}
const hdr = read('src/data/closure_tables.h') + read('src/data/extended_tables.h');
const T = {
	forme: defines(hdr, 'FORME'), move: defines(hdr, 'MOVE'), item: defines(hdr, 'ITEM'),
	ability: defines(hdr, 'ABILITY'), nature: defines(hdr, 'NATURE'),
};
const byId = o => Object.fromEntries(Object.entries(o).map(([k, v]) => [v, k]));
const NAME = {forme: byId(T.forme), move: byId(T.move), item: byId(T.item), ability: byId(T.ability)};

// The forme rows of the extended tables: ability, gender rule, Mega links and the one fixed set.
const ext = read('src/data/extended_tables.c');
const rows = [];
{
	const start = ext.indexOf('dfi_ext_formes[DFI_EXT_FORME_COUNT] = {');
	const end = ext.indexOf('};', start);
	const re = /^\s*\{(\d+)u, (\d+)u, \{(\d+)u, (\d+)u\}, \{(\d+)u, (\d+)u, (\d+)u, (\d+)u, (\d+)u, (\d+)u\}, (\d+)u, (\d+)u, (\d+)u, (\d+)u, (\d+)u, (\d+)u, (\d+)u, (\d+)u, \{(\d+)u, (\d+)u, (\d+)u, (\d+)u\}\},/;
	for (const line of ext.slice(start, end).split('\n')) {
		const m = re.exec(line);
		if (!m) continue;
		const n = m.slice(1).map(Number);
		rows.push({dex: n[0], weight_hg: n[1], ability: n[10], gender_rule: n[11], is_mega: n[12], base_forme: n[13],
			mega_forme: n[14], mega_item: n[15], set_item: n[16], set_moves: n.slice(18, 18 + n[17])});
	}
}
if (rows.length !== Object.keys(T.forme).length) throw new Error('forme rows and ids disagree');
const FORME_ROW = Object.fromEntries(Object.entries(T.forme).map(([k, v]) => [k, rows[v]]));

// ---------------------------------------------------------------- one set
function analyseSet(set) {
	const sp = dex.species.get(set.species);
	const out = {species: sp.name, notes: []};
	// A Mega name in a paste is the base forme holding its stone.
	let baseId = sp.id;
	if (sp.isMega) {
		const battleOnly = Array.isArray(sp.battleOnly) ? sp.battleOnly[0] : sp.battleOnly;
		baseId = toID(battleOnly || sp.baseSpecies);
		out.notes.push(`paste names the Mega forme ${sp.name}; the setup needs ${battleOnly} with ${set.item}`);
	}
	out.forme = baseId;
	out.item = set.item;
	out.ability = set.ability;
	out.nature = set.nature;
	out.moves = set.moves;
	out.gender_given = set.gender || '';
	const sd = dex.species.get(baseId);
	out.gender_species = sd.gender || 'M/F';
	const row = FORME_ROW[baseId];
	const gaps = {species: [], item: [], ability: [], move: [], nature: []};
	if (!row) gaps.species.push(sd.name);
	if (set.item && !(toID(set.item) in T.item)) gaps.item.push(set.item);
	if (set.ability && !(toID(set.ability) in T.ability)) gaps.ability.push(set.ability);
	if (set.nature && !(toID(set.nature) in T.nature)) gaps.nature.push(set.nature);
	for (const mv of set.moves) if (!(toID(mv) in T.move)) gaps.move.push(mv);
	// What a name match does not show: the engine's member rule.
	// moves_outside_set: table moves outside the forme's fixed set; moves_not_in_fixed_set_all: every move
	// the set carries that the forme's fixed set lacks, gap moves included (the validator accepts them all).
	const rule = {moves_outside_set: [], moves_not_in_fixed_set_all: [], ability_outside_forme: null, stone_mismatch: null};
	const itm = dex.items.get(set.item);
	if (itm.megaStone && !(sd.name in itm.megaStone)) rule.stone_mismatch = `${set.item} is not the stone of ${sd.name}`;
	if (row) {
		const setMoves = new Set(row.set_moves.map(i => NAME.move[i]));
		for (const mv of set.moves) {
			if (!setMoves.has(toID(mv))) rule.moves_not_in_fixed_set_all.push(mv);
			if (toID(mv) in T.move && !setMoves.has(toID(mv))) rule.moves_outside_set.push(mv);
		}
		const abilityIfSetUp = NAME.ability[row.ability];
		const shown = sp.isMega ? null : toID(set.ability);
		if (shown && shown !== abilityIfSetUp) rule.ability_outside_forme = `${set.ability} (the table's ${sd.name} has ${abilityIfSetUp})`;
	} else {
		rule.moves_not_in_fixed_set_all.push(...set.moves);
	}
	const ev = Object.values(set.evs || {}).reduce((a, b) => a + b, 0);
	const evMax = Math.max(...Object.values(set.evs || {}));
	out.stat_points = {total: ev, max: evMax, ok: ev <= 66 && evMax <= 32};
	out.gaps = gaps;
	out.rule = rule;
	return out;
}

function analyseTeam(entry) {
	const pid = entry.paste.split('/').pop();
	const text = fs.readFileSync(path.join(SURVEY, 'pastes', pid + '.txt'), 'utf8');
	// validateTeam rewrites the sets it is given (a Mega name becomes its base forme), so it gets its own copy.
	const sets = Teams.import(text).map(analyseSet);
	const problems = validator.validateTeam(Teams.import(text));
	const gaps = {species: new Set(), item: new Set(), ability: new Set(), move: new Set(), nature: new Set()};
	let deviations = 0;
	for (const s of sets) {
		for (const k of Object.keys(gaps)) s.gaps[k].forEach(x => gaps[k].add(x));
		deviations += s.rule.moves_outside_set.length + (s.rule.ability_outside_forme ? 1 : 0);
	}
	return {
		id: entry.id, paste: pid, link: entry.paste, rank: entry.rank || '', event: entry.event || '',
		validator_problems: problems, sets,
		gaps: Object.fromEntries(Object.entries(gaps).map(([k, v]) => [k, [...v].sort()])),
		member_rule_deviations: deviations,
		stat_points_ok: sets.every(s => s.stat_points.ok),
	};
}

// ---------------------------------------------------------------- run
function analyse(ids) {
	const survey = JSON.parse(fs.readFileSync(path.join(SURVEY, 'mc_full_coverage.json'), 'utf8'));
	const wanted = ids || survey.map(t => t.id);
	const results = wanted.map(id => analyseTeam(survey.find(t => t.id === id)));
	// The main session's list, for the diff (names, by kind).
	const disagreements = [];
	for (const r of results) {
		const m = survey.find(x => x.id === r.id).missing || {};
		for (const kind of ['species', 'item', 'ability', 'move', 'nature']) {
			const mine = new Set(r.gaps[kind].map(x => toID(x)));
			const theirs = new Set((m[kind] || []).map(x => toID(x)));
			for (const x of mine) if (!theirs.has(x)) disagreements.push({team: r.id, kind, only_mine: x});
			for (const x of theirs) if (!mine.has(x)) disagreements.push({team: r.id, kind, only_main_session: x});
		}
	}
	const union = {species: new Set(), item: new Set(), ability: new Set(), move: new Set(), nature: new Set()};
	for (const r of results) for (const k of Object.keys(union)) r.gaps[k].forEach(x => union[k].add(x));
	return {results, union: Object.fromEntries(Object.entries(union).map(([k, v]) => [k, [...v].sort()])), disagreements};
}

function insideToday(r) {
	return !Object.values(r.gaps).some(a => a.length) && r.member_rule_deviations === 0 &&
		r.sets.every(s => s.rule.moves_not_in_fixed_set_all.length === 0);
}

function report(a, all) {
	const {results, union, disagreements} = a;
	console.log(`teams: ${results.length}; validator-invalid: ${results.filter(r => r.validator_problems).length}; ` +
		`Stat Points outside the Champions rule: ${results.filter(r => !r.stat_points_ok).length}`);
	console.log('id      missing(species | item | ability | move)                                   member-rule deviations');
	for (const r of results) {
		const g = r.gaps;
		console.log(`${r.id.padEnd(7)} ${[g.species.join(','), g.item.join(','), g.ability.join(','), g.move.join(',')].join(' | ').padEnd(70)} ${r.member_rule_deviations}`);
	}
	console.log('member-rule deviations (a move of the table that is not in its forme\'s fixed set, or another ability):');
	for (const r of results) {
		const parts = [];
		for (const s of r.sets) {
			const d = [...s.rule.moves_outside_set];
			if (s.rule.ability_outside_forme) d.push('ability ' + s.rule.ability_outside_forme);
			if (d.length) parts.push(`${s.species}: ${d.join(', ')}`);
		}
		if (parts.length) console.log(`  ${r.id.padEnd(6)} ${parts.join('; ')}`);
	}
	const inside = results.filter(insideToday);
	const pairs = new Set();
	for (const r of results) for (const s of r.sets) for (const mv of s.rule.moves_not_in_fixed_set_all) pairs.add(`${s.forme}:${toID(mv)}`);
	const stone = results.flatMap(r => r.sets.filter(s => s.rule.stone_mismatch).map(s => `${r.id} ${s.rule.stone_mismatch}`));
	const wrongAbility = results.flatMap(r => r.sets.filter(s => s.rule.ability_outside_forme).map(s => `${r.id} ${s.species}`));
	console.log(`inside the tables AND the fixed sets today (the member rule of closure_member.c): ${inside.map(r => r.id).join(', ') || 'none'}`);
	console.log(`(forme, move) pairs outside the fixed sets, gap moves included: ${pairs.size}`);
	console.log(`Mega stone on a forme that is not its holder: ${stone.length ? stone.join('; ') : 'none'}; set ability other than the table's one for its forme: ${wrongAbility.length ? wrongAbility.join('; ') : 'none'}`);
	console.log('notes:');
	for (const r of results) for (const s of r.sets) for (const n of s.notes) console.log(`  ${r.id}: ${n}`);
	console.log('union of the gaps:');
	for (const [k, v] of Object.entries(union)) console.log(`  ${k}: ${v.length} ${v.join(', ')}`);
	console.log('disagreements with the main session (by name):', disagreements.length ? JSON.stringify(disagreements) : 'none');
	if (all) {
		console.log(`of all ${results.length} pastes, fully inside the tables AND the member rule: ${inside.map(r => r.id).join(', ') || 'none'}`);
	}
}

module.exports = {CURVE, analyse, insideToday, dex, toID, T, NAME, FORME_ROW, SURVEY};

if (require.main === module) {
	const args = process.argv.slice(2);
	const all = args.includes('--all');
	const jsonOut = args.includes('--json') ? args[args.indexOf('--json') + 1] : null;
	const a = analyse(all ? null : CURVE);
	report(a, all);
	if (jsonOut) {
		const dump = {
			meta: {pin: 'b2cb775b0616115b775534eaeff50300e1fc81fc', format: format.id, teams: a.results.length},
			union: a.union, disagreements: a.disagreements, teams: a.results,
		};
		fs.writeFileSync(jsonOut, JSON.stringify(dump, null, 1) + '\n');
		console.log('wrote', jsonOut);
	}
}
