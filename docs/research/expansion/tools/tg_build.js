// Assembles docs/research/expansion/data/team_gaps.json and
// docs/research/expansion/team-gaps.md from the curated entries
// (tg_gaps_moves.js, tg_gaps_other.js, tg_plan.js) and from what can be
// computed: the verification of the 17 teams (tg_verify_teams.js), which teams
// a gap or a step concerns, the order under the cost-and-variety rule, the
// conflict matrix of the steps and a schedule for five builders. Read-only
// research tooling: it writes only the two output files.
//
// usage: node tg_build.js [--check]      (--check compares the committed files)
'use strict';
const fs = require('fs');
const path = require('path');
const verify = require('./tg_verify_teams.js');
const plan = require('./tg_plan.js');
const moveEntries = require('./tg_gaps_moves.js');
const otherEntries = require('./tg_gaps_other.js');

const {toID, dex} = verify;
const OUT_JSON = path.join(__dirname, '..', 'data', 'team_gaps.json');
const OUT_MD = path.join(__dirname, '..', 'team-gaps.md');
const BUILDERS = 5;
const SPECIES_ORDER = ['species:pelipper', 'species:arcaninehisui', 'species:annihilape', 'species:floetteeternal'];

// ---------------------------------------------------------------- data
const entries = [...otherEntries, ...moveEntries];
const byId = Object.fromEntries(entries.map(e => [e.id, e]));
if (Object.keys(byId).length !== entries.length) throw new Error('duplicate gap id');
const MAIN_SESSION_29 = ['species:pelipper', 'species:arcaninehisui', 'species:annihilape', 'ability:rockhead',
	'item:focusssash', 'item:expertbelt', 'item:colburberry', 'item:occaberry', 'item:blackglasses'].map(x => x.replace('focusssash', 'focussash'))
	.concat(['uturn', 'rockslide', 'throatchop', 'encore', 'doubleedge', 'thunderbolt', 'scald', 'wideguard', 'flashcannon', 'extremespeed',
		'headsmash', 'firstimpression', 'bulkup', 'liquidation', 'icepunch', 'shadowclaw', 'recover', 'soak', 'psychicnoise', 'drumbeating'].map(m => 'move:' + m));
const EXTRA = ['move:lowkick', 'move:dazzlinggleam', 'species:floetteeternal', 'item:floettite', 'ability:flowerveil', 'ability:fairyaura'];
for (const id of [...MAIN_SESSION_29, ...EXTRA]) if (!byId[id]) throw new Error('missing entry ' + id);
if (entries.length !== MAIN_SESSION_29.length + EXTRA.length) throw new Error('entry count ' + entries.length);

const a17 = verify.analyse(verify.CURVE);
const all = verify.analyse(null);
const gapId = (kind, name) => `${kind}:${toID(name)}`;

// ---------------------------------------------------------------- items and steps
const ITEM = Object.fromEntries(plan.ITEMS.map(i => [i.id, i]));
const STEP_OF_ITEM = {};
for (const s of plan.STEPS) for (const i of s.items) STEP_OF_ITEM[i] = s.id;
const itemOfGap = {};
for (const i of plan.ITEMS) for (const g of i.gaps) itemOfGap[g] = i.id;
for (const e of entries) {
	const item = itemOfGap[e.id];
	const step = item ? STEP_OF_ITEM[item] : (plan.DATA_ONLY.includes(e.id) ? 'G2' : null);
	if (step !== e.step) throw new Error(`${e.id}: entry says step ${e.step}, the plan says ${step}`);
}
const points = id => plan.POINTS[ITEM[id].effort];
const closure = ids => {
	const out = new Set();
	const visit = id => { if (out.has(id)) return; out.add(id); ITEM[id].requires.forEach(visit); };
	ids.forEach(visit);
	return out;
};

// ---------------------------------------------------------------- teams
const baseSpecies = forme => dex.species.get(forme).baseSpecies;
const teams = a17.results.map((r, i) => {
	const species = r.sets.map(s => baseSpecies(s.forme));
	const needsGaps = [];
	for (const [kind, names] of Object.entries(r.gaps)) for (const n of names) needsGaps.push(gapId(kind, n));
	const items = new Set();
	for (const g of needsGaps) if (itemOfGap[g]) items.add(itemOfGap[g]);
	const tags = Object.entries(plan.TAGS).filter(([, f]) => r.sets.some(f)).map(([k]) => k);
	return {
		id: r.id, curve_rank: i + 1, paste: r.paste, link: r.link, placing: r.rank, event: r.event,
		species, sets: r.sets.map(s => ({species: s.species, forme: s.forme, item: s.item, ability: s.ability, moves: s.moves})),
		validator_ok: !r.validator_problems, stat_points_ok: r.stat_points_ok,
		gaps: r.gaps, gap_ids: needsGaps.sort(), item_ids: [...items].sort(),
		member_rule: {inside_today: verify.insideToday(r), moves_outside_fixed_set: r.sets.flatMap(s => s.rule.moves_not_in_fixed_set_all.map(m => `${s.species}: ${m}`))},
		tags,
		is_reference: r.id === 'MC405' || r.id === 'MC408',
		reference_name: r.id === 'MC405' ? 'Team A' : r.id === 'MC408' ? 'Team B' : null,
		note_mega_name: r.sets.some(s => s.notes.length > 0),
	};
});
const TEAM = Object.fromEntries(teams.map(t => [t.id, t]));
const shared = (a, b) => a.filter(x => b.includes(x)).length;
const refSets = () => Object.entries(plan.REFERENCE_TEAMS).map(([name, species]) => ({name, species}));

// ---------------------------------------------------------------- cost-and-variety order
function greedy(tolerance, p2Free, variety = true) {
	const built = new Set();
	const refs = refSets();
	const complete = [];
	const rounds = [];
	const sequence = [];
	let remaining = teams.filter(t => !t.is_reference);
	for (const t of teams.filter(t => t.is_reference)) {
		complete.push({team: t.id, round: 0, how: 'already playable (the reference team)'});
		refs.push({name: t.id, species: t.species});
	}
	const cost = ids => [...closure(ids)].filter(i => !built.has(i)).reduce((a, i) => a + (p2Free && i === 'G6a' ? 0 : points(i)), 0);
	let round = 0;
	while (remaining.length) {
		round += 1;
		// teams that need nothing more complete now
		const done = remaining.filter(t => cost(t.item_ids) === 0);
		for (const t of done) {
			complete.push({team: t.id, round: round - 1, how: 'its steps are built'});
			refs.push({name: t.id, species: t.species});
		}
		remaining = remaining.filter(t => !done.includes(t));
		if (!remaining.length) break;
		const withCost = remaining.map(t => ({t, cost: cost(t.item_ids)}));
		const min = Math.min(...withCost.map(x => x.cost));
		const cands = withCost.filter(x => x.cost <= min + tolerance).map(x => {
			const maxShared = Math.max(...refs.map(r => shared(x.t.species, r.species)));
			const nearest = refs.filter(r => shared(x.t.species, r.species) === maxShared).map(r => r.name);
			return {...x, maxShared, nearest, near_duplicate: maxShared >= plan.NEAR_DUPLICATE, distance: 6 - maxShared};
		});
		if (variety) {
			cands.sort((a, b) => (a.near_duplicate - b.near_duplicate) || (b.distance - a.distance) || (b.t.tags.length - a.t.tags.length) ||
				(a.cost - b.cost) || (a.t.curve_rank - b.t.curve_rank));
		} else {
			cands.sort((a, b) => (a.cost - b.cost) || (a.t.curve_rank - b.t.curve_rank));
		}
		const pick = cands[0];
		const missing = [...closure(pick.t.item_ids)].filter(i => !built.has(i));
		// dependencies first, then by effort
		missing.sort((a, b) => (ITEM[a].requires.length - ITEM[b].requires.length) || (points(a) - points(b)) || a.localeCompare(b));
		missing.forEach(i => { built.add(i); sequence.push(i); });
		rounds.push({
			round, minimum_cost: min, tolerance,
			candidates: cands.map(c => ({team: c.t.id, cost: c.cost, near_duplicate: c.near_duplicate, shared_max: c.maxShared, nearest: c.nearest, tags: c.t.tags})),
			chosen: pick.t.id, builds: missing,
			tie_break_used: cands.length > 1,
		});
	}
	return {complete, rounds, sequence, order: complete.map(c => c.team)};
}
const orderPlan = greedy(plan.TOLERANCE, false);
const orderPure = greedy(0, false, false);
const orderSunkP2 = greedy(plan.TOLERANCE, true);

// ---------------------------------------------------------------- conflicts and schedule
const itemRegions = id => (ITEM[id] ? ITEM[id].hard : plan.FOUNDATION[id].hard);
const sharedRegions = (a, b) => itemRegions(a).filter(r => itemRegions(b).includes(r));
const stepRegions = s => [...new Set(s.items.flatMap(i => ITEM[i].hard))].sort();
const stepConflicts = {};
for (const a of plan.STEPS) {
	stepConflicts[a.id] = {};
	for (const b of plan.STEPS) {
		if (a.id === b.id) continue;
		const ra = a.id === 'G1' || a.id === 'G2' ? plan.FOUNDATION[a.id].hard : stepRegions(a);
		const rb = b.id === 'G1' || b.id === 'G2' ? plan.FOUNDATION[b.id].hard : stepRegions(b);
		const common = ra.filter(r => rb.includes(r));
		if (common.length) stepConflicts[a.id][b.id] = common;
	}
}
const stepDeps = s => {
	if (s.id === 'G1') return [];
	if (s.id === 'G2') return ['G1'];
	const deps = new Set(['G2']);
	for (const i of s.items) for (const r of ITEM[i].requires) { const st = STEP_OF_ITEM[r]; if (st !== s.id) deps.add(st); }
	return [...deps].sort();
};
const reaches = (from, to, seen = new Set()) => {
	if (from === to) return true;
	if (seen.has(from)) return false;
	seen.add(from);
	return stepDeps(plan.STEPS.find(s => s.id === from)).some(d => reaches(d, to, seen));
};

function schedule(sequence) {
	const jobs = [
		{id: 'G1', dur: plan.POINTS[plan.FOUNDATION.G1.effort], deps: [], hard: plan.FOUNDATION.G1.hard},
		{id: 'G2', dur: plan.POINTS[plan.FOUNDATION.G2.effort], deps: ['G1'], hard: plan.FOUNDATION.G2.hard},
		...plan.ITEMS.map(i => ({id: i.id, dur: points(i.id), deps: ['G2', ...i.requires], hard: i.hard})),
	];
	jobs.find(j => j.id === 'G3').deps = []; // the state tail needs P1 only
	const priority = ['G1', 'G2', 'G3', ...sequence, ...plan.ITEMS.map(i => i.id)].filter((x, i, a) => a.indexOf(x) === i);
	const end = {};
	const start = {};
	const running = [];
	let t = 0;
	for (let guard = 0; guard < 1000 && Object.keys(start).length < jobs.length; guard++) {
		let started = true;
		while (started) {
			started = false;
			for (const id of priority) {
				if (start[id] !== undefined || running.length >= BUILDERS) continue;
				const j = jobs.find(x => x.id === id);
				if (!j.deps.every(d => end[d] !== undefined && end[d] <= t)) continue;
				if (running.some(r => r.hard.some(h => j.hard.includes(h)))) continue;
				start[id] = t;
				end[id] = t + j.dur;
				running.push(j);
				started = true;
			}
		}
		const next = Math.min(...running.map(r => end[r.id]));
		t = next;
		for (let i = running.length - 1; i >= 0; i--) if (end[running[i].id] <= t) running.splice(i, 1);
	}
	return {start, end, jobs};
}
const sched = schedule(orderPlan.sequence);
const stepEnd = {};
const stepStart = {};
for (const s of plan.STEPS) {
	const ids = s.items.length ? s.items : [s.id];
	stepStart[s.id] = Math.min(...ids.map(i => sched.start[i]));
	stepEnd[s.id] = Math.max(...ids.map(i => sched.end[i]));
}
const teamDone = {};
for (const t of teams) {
	if (t.is_reference) { teamDone[t.id] = {time: 0, last: null}; continue; }
	const needed = [...closure(t.item_ids), 'G1', 'G2'];
	const lastItem = needed.reduce((a, b) => (sched.end[b] > sched.end[a] ? b : a));
	teamDone[t.id] = {time: sched.end[lastItem], last: lastItem, last_step: STEP_OF_ITEM[lastItem] || lastItem, needs: [...closure(t.item_ids)].sort()};
}

// within a round the teams are ordered by the time the schedule completes them
orderPlan.order = orderPlan.complete.slice().sort((a, b) => (a.round - b.round) || (teamDone[a.team].time - teamDone[b.team].time) ||
	(TEAM[a.team].curve_rank - TEAM[b.team].curve_rank)).map(c => c.team);
const tieEvents = orderPlan.rounds.filter(r => r.tie_break_used).map(r => {
	const chosen = r.candidates.find(c => c.team === r.chosen);
	const cheapest = r.candidates.filter(c => c.cost === r.minimum_cost);
	const skipped = r.candidates.filter(c => c.team !== r.chosen && c.near_duplicate);
	const dearer = chosen.cost > r.minimum_cost;
	return {round: r.round, chosen_near_duplicate: chosen.near_duplicate, chosen: r.chosen, chosen_cost: chosen.cost, chosen_shared: chosen.shared_max, minimum_cost: r.minimum_cost,
		cheapest: cheapest.map(c => c.team), skipped_near_duplicates: skipped.map(c => `${c.team} (${c.cost}, shares ${c.shared_max} with ${c.nearest.join('/')})`), took_more_than_cheapest: dearer};
}).filter(e => e.skipped_near_duplicates.length || e.took_more_than_cheapest);

const firstBuilds = o => o.rounds.slice(0, 4).map(r => r.builds.join('+')).join(' | ');
const QUESTIONS = plan.QUESTIONS.map(q => q.id !== 'Q3' ? q : {...q, text: q.text.replace('the step order changes only at the start, see below.',
	`the same steps get built either way and only the first rounds differ. Builds of the first four rounds without the rule: ${firstBuilds(orderPure)}; with it: ${firstBuilds(orderPlan)}.`)});
const peak = (() => {
	let m = 0;
	for (const j of sched.jobs) { const t = sched.start[j.id]; m = Math.max(m, sched.jobs.filter(k => sched.start[k.id] <= t && sched.end[k.id] > t).length); }
	return m;
})();

// ---------------------------------------------------------------- usage
function usageIn(set, kind, name) {
	const id = toID(name);
	if (kind === 'move') return set.moves.some(m => toID(m) === id);
	if (kind === 'item') return toID(set.item) === id;
	if (kind === 'ability') return toID(set.ability) === id;
	return set.forme === id;
}
const gaps = entries.map(e => {
	const [kind, ident] = e.id.split(':');
	const nameForUsage = e.id === 'species:floetteeternal' ? 'floetteeternal' : ident;
	const in17 = teams.filter(t => t.gap_ids.includes(e.id)).map(t => t.id);
	const pastes = all.results.filter(r => r.sets.some(s => usageIn(s, kind, nameForUsage))).length;
	const prio = in17.length ? 'in the 17 teams' : 'next ring';
	return {
		...e, teams_of_17: in17, pastes_of_227: pastes, scope: prio,
		in_main_session_29: MAIN_SESSION_29.includes(e.id), item: itemOfGap[e.id] || null,
	};
});

// ---------------------------------------------------------------- JSON
const poolRows = {
	formes: ['pelipper', 'arcaninehisui', 'annihilape', 'floetteeternal', 'floettemega'],
	moves: gaps.filter(g => g.kind === 'move').map(g => g.id.slice(5)),
	abilities: ['rockhead', 'flowerveil', 'fairyaura'],
	items: ['focussash', 'expertbelt', 'floettite'],
	items_from_p1_section_3: ['colburberry', 'occaberry', 'blackglasses'],
	columns: [
		'legal moves per forme (bitset over the pool\'s 510 moves) and, optionally, the legal abilities per forme (G1)',
		'flags2: sound, heal, thaws_target (and the guarded ignorable flags punch, slicing, allyanim) for every id, the prefix included (finding F4)',
		'moves: a first-turn-only parameter (Fake Out, First Impression), a weight-power special shared by Grass Knot and Low Kick, a heal fraction, a lockout predicate (sound / heal), a type-set parameter, a side-guard parameter, a primary volatile (Encore), secondary kinds for the lockout and Heal Block, a side condition value for Wide Guard',
		'pivot moves: the generated table of damaging self-switch moves (Flip Turn, U-turn, Volt Switch) that maps a switch flag to its move id (G5)',
		'formes: weights 280 / 1680 / 560 / 9 / 1008 hg and gender rules (Floette-Eternal FEMALE) from the pinned pokedex',
	],
};
const mainCounts = {species: a17.union.species.length, items: a17.union.item.length, abilities: a17.union.ability.length, moves: a17.union.move.length};

const json = {
	meta: {
		note: 'Research draft, agent-generated 2026-10-02 (Builder C). Not a contract and not a support claim. Generated by docs/research/expansion/tools/tg_build.js from tg_gaps_moves.js, tg_gaps_other.js, tg_plan.js and tg_verify_teams.js.',
		showdown_pin: 'b2cb775b0616115b775534eaeff50300e1fc81fc', duoforge_base: 'origin/main cfe18c0 (library 0.19.0); decision 0015 from origin/chris/expansion-p1-pool 1aab4c2',
		format: 'gen9championsvgc2026regmc', survey: 'VGCPastes Reg M-C survey of 2026-10-02 (outside git; ids and links only)',
		effort_points: plan.POINTS, tolerance_points: plan.TOLERANCE, near_duplicate_shared_species: plan.NEAR_DUPLICATE, builders: BUILDERS,
	},
	verification: {
		method: 'tg_verify_teams.js: Teams.import of each paste, TeamValidator.validateTeam of a copy, names looked up in src/data/*.h and *.c, sets compared with the fixed set of their forme.',
		teams: teams.map(t => ({
			id: t.id, curve_rank: t.curve_rank, paste: t.paste, link: t.link, placing: t.placing, event: t.event, species: t.species,
			validator_ok: t.validator_ok, stat_points_ok: t.stat_points_ok, gaps: t.gaps,
			inside_member_rule_today: t.member_rule.inside_today, moves_outside_fixed_set: t.member_rule.moves_outside_fixed_set,
			names_a_mega_forme: t.note_mega_name, sets: t.sets,
		})),
		union: a17.union, union_counts: mainCounts, disagreements_with_main_session: a17.disagreements,
		inside_member_rule_today: teams.filter(t => t.member_rule.inside_today).map(t => t.id),
		forme_move_pairs_outside_fixed_sets: new Set(a17.results.flatMap(r => r.sets.flatMap(s => s.rule.moves_not_in_fixed_set_all.map(m => `${s.forme}:${toID(m)}`)))).size,
		all_227: {
			pastes: all.results.length, validator_invalid: all.results.filter(r => r.validator_problems).map(r => r.id),
			stat_points_outside_rule: all.results.filter(r => !r.stat_points_ok).map(r => r.id),
			inside_member_rule_today: all.results.filter(verify.insideToday).map(r => r.id),
			disagreements_by_name_are_mega_names: all.disagreements.every(d => /mega|^(floetteeternal|absol|glimmora|tyranitar|baxcalibur|froslass|blastoise|gardevoir)$/.test(d.only_mine || d.only_main_session)),
		},
	},
	findings: plan.FINDINGS,
	gaps: gaps.map(g => ({
		id: g.id, kind: g.kind, name: g.name, scope: g.scope, in_main_session_29: g.in_main_session_29,
		teams_of_17: g.teams_of_17, pastes_of_227: g.pastes_of_227, step: g.step, item: g.item, effort: g.effort,
		pinned: g.pinned, draws: g.draws, protocol: g.protocol, duoforge: g.duoforge, state: g.state, interactions: g.interactions,
		evidence: g.evidence, cites: g.cites,
	})),
	pool_rows: poolRows,
	foundation: {P1: plan.FOUNDATION.P1.title, G1: plan.FOUNDATION.G1.title, G2: plan.FOUNDATION.G2.title, data_only_in_G2: plan.DATA_ONLY},
	regions: plan.REGIONS,
	soft_shared_resources: plan.SOFT,
	work_items: plan.ITEMS.map(i => ({id: i.id, title: i.title, effort: i.effort, points: points(i.id), requires: i.requires, hard_regions: i.hard, gaps: i.gaps, step: STEP_OF_ITEM[i.id], start: sched.start[i.id], end: sched.end[i.id]})),
	steps: plan.STEPS.map(s => {
		const foundation = s.id === 'G1' || s.id === 'G2';
		const done = teams.filter(t => !t.is_reference && teamDone[t.id].last_step === s.id).map(t => t.id);
		const conflicts = stepConflicts[s.id];
		const parallel = plan.STEPS.filter(o => o.id !== s.id && !conflicts[o.id] && !reaches(o.id, s.id) && !reaches(s.id, o.id)).map(o => o.id);
		return {
			id: s.id, title: s.title, prs: s.prs, items: s.items, depends_on: stepDeps(s),
			effort_points: foundation ? plan.POINTS[plan.FOUNDATION[s.id].effort] : s.items.reduce((a, i) => a + points(i), 0),
			regions: foundation ? plan.FOUNDATION[s.id].hard : stepRegions(s),
			public_changes: s.public || [], gaps: foundation ? (s.id === 'G2' ? plan.DATA_ONLY : []) : s.items.flatMap(i => ITEM[i].gaps),
			teams_completed_last: done, hard_conflicts: conflicts, parallel_safe_with: parallel,
			start: stepStart[s.id], end: stepEnd[s.id],
		};
	}),
	schedule: {
		builders: BUILDERS, unit: 'effort points; P1 is taken as merged at 0',
		waves: Object.entries(Object.entries(sched.start).reduce((m, [id, t]) => { (m[t] = m[t] || []).push(id); return m; }, {}))
			.map(([t, ids]) => ({start: Number(t), items: ids.sort(), ends: Object.fromEntries(ids.map(i => [i, sched.end[i]]))})).sort((a, b) => a.start - b.start),
	},
	team_order: {
		rule: `cost = effort points of the steps a team still needs (shared steps once; G3 counted when first needed; P1, G1, G2 common). Cheapest team first; teams within ${plan.TOLERANCE} points of the cheapest tie; ties are broken by (1) not a near-duplicate (sharing ${plan.NEAR_DUPLICATE} or more species with Team A, B, C or a team completed earlier), (2) more species away from the nearest of those, (3) more archetype tags (rain or sun, Trick Room, Wide Guard), (4) lower cost, (5) the order of curve.txt.`,
		curve_txt: verify.CURVE,
		plan: orderPlan.order, effort_only_no_tie_break: orderPure.order, p2_treated_as_already_scheduled: orderSunkP2.order,
		rounds: orderPlan.rounds, tie_events: tieEvents, rounds_without_tie_break: orderPure.rounds.map(r => ({round: r.round, chosen: r.chosen, builds: r.builds})),
		completion: Object.fromEntries(teams.map(t => [t.id, teamDone[t.id]])),
	},
	teams: teams.map(t => ({id: t.id, curve_rank: t.curve_rank, species: t.species, tags: t.tags, steps_needed: teamDone[t.id].needs || [], completes_at: teamDone[t.id].time, last_step: teamDone[t.id].last_step || null, gap_ids: t.gap_ids})),
	open_questions: QUESTIONS,
};

// ---------------------------------------------------------------- narrative computed from the data
const newTeams = teams.filter(t => !t.is_reference);
const lastTeam = (() => { const t = newTeams.reduce((a, b) => (teamDone[b.id].time > teamDone[a.id].time ? b : a)); return {team: t.id, time: teamDone[t.id].time, last: teamDone[t.id].last}; })();
const firstNewTime = Math.min(...newTeams.map(t => teamDone[t.id].time));
const firstNew = newTeams.filter(t => teamDone[t.id].time === firstNewTime).map(t => t.id);
const posOf = (o, id) => o.order.indexOf(id) + 1;
const nearDup = newTeams.map(t => ({t, shared: refSets().map(r => ({r: r.name, n: shared(t.species, r.species)})).sort((a, b) => b.n - a.n)[0]}))
	.filter(x => x.shared.n >= plan.NEAR_DUPLICATE);
function varietySummary() {
	const d = nearDup.map(x => `${x.t.id} (${x.shared.n} species shared with ${x.shared.r}, plan position ${posOf(orderPlan, x.t.id)} against curve.txt ${x.t.curve_rank})`).join(', ');
	return `near-duplicates of Team A, B or C by the ${plan.NEAR_DUPLICATE}-species test: ${d}. The tie-break demotes them only when another team costs within ${plan.TOLERANCE} points; the tie events are listed in section 5.4.`;
}
function tieNarrative() {
	const out = [];
	const vsPure = newTeams.filter(t => posOf(orderPlan, t.id) !== posOf(orderPure, t.id));
	out.push(vsPure.length ? 'Against the same greedy with no tie-break (cost only, ties by curve.txt): ' + vsPure.map(t => `${t.id} ${posOf(orderPure, t.id)} to ${posOf(orderPlan, t.id)}`).join(', ') + '.' : 'The rule did not change any position of the greedy.');
	const vsCurve = newTeams.filter(t => posOf(orderPlan, t.id) !== t.curve_rank);
	out.push('Against curve.txt: ' + vsCurve.map(t => `${t.id} ${t.curve_rank} to ${posOf(orderPlan, t.id)}`).join(', ') + '.');
	for (const e of tieEvents) {
		out.push(`Round ${e.round}: ${e.chosen} (cost ${e.chosen_cost}, ${e.chosen_shared} species shared with the nearest reference) is taken` +
			(e.took_more_than_cheapest ? ` although the cheapest, ${e.cheapest.join(' and ')} (${e.minimum_cost}), is cheaper` : '') +
			(e.chosen_near_duplicate ? '; every candidate was a near-duplicate, so more archetype tags decided' : (e.skipped_near_duplicates.length ? `; passed over as near-duplicates: ${e.skipped_near_duplicates.join('; ')}` : '')) + '.');
	}
	const mc246 = TEAM.MC246;
	if (mc246 && nearDup.some(x => x.t.id === 'MC246')) {
		out.push(`MC246 is Team A with Salamence for Staraptor (5 of 6 species shared). Its only gap is P2 (${points('G6a')} points) and its steps are built anyway for MC392; with the variety rule it completes at t=${teamDone.MC246.time}, in the same round as MC392 (t=${teamDone.MC392.time}), but the first two builds go to ${orderPlan.rounds[0].chosen} and ${orderPlan.complete.find(c => c.round === 1 && c.team !== orderPlan.rounds[0].chosen)?.team || '-'} (Arcanine-Hisui, Focus Sash, Rock Head) instead of the Team A near-duplicate. The rule costs the curve nothing: P2 is built in round 2.`);
	}
	return out.join(' ');
}

// ---------------------------------------------------------------- markdown
const esc = s => String(s).replace(/\|/g, '\\|');
const cell = v => (Array.isArray(v) ? v.map(esc).join('<br>') : esc(v));
const table = (head, rows) => ['| ' + head.join(' | ') + ' |', '|' + head.map(() => '---').join('|') + '|', ...rows.map(r => '| ' + r.map(cell).join(' | ') + ' |')].join('\n');
const gapOrder = [...SPECIES_ORDER, 'ability:rockhead', 'ability:flowerveil', 'ability:fairyaura', 'item:focussash', 'item:expertbelt', 'item:colburberry', 'item:occaberry', 'item:blackglasses', 'item:floettite'];
const sections = [
	['4.1 Species and formes', g => g.kind === 'species'],
	['4.2 Abilities', g => g.kind === 'ability'],
	['4.3 Items', g => g.kind === 'item'],
	['4.4 Moves', g => g.kind === 'move'],
];
const idsOf = g => g.teams_of_17.length ? `${g.teams_of_17.join(', ')} (${g.teams_of_17.length} of 17; ${g.pastes_of_227} of 227 pastes)` : `none of the 17 (${g.pastes_of_227} of 227 pastes); ${g.scope}`;
const fmtDup = c => c.near_duplicate ? 'near-duplicate' : '';

function card(g) {
	const gen = g.duoforge;
	const rows = [
		['Used by', idsOf(g)],
		['Pinned', g.pinned],
		['Draws', g.draws],
		['Protocol lines', [...g.protocol.lines, ...g.protocol.unknown.map(u => '**Unknown to the converter:** ' + u)]],
		['DuoForge today', [`Tables: ${gen.tables}. Generator: ${gen.generator}.`, `Class: ${gen.classification}. Re-check: ${gen.recheck}`, `Engine: ${gen.engine}`]],
		['State, public, request', g.state],
		['Interactions', g.interactions],
		['Evidence', [...g.evidence.specs.map(s => 'Spec ' + s), ...g.evidence.tests.map(s => 'Test: ' + s)]],
		['Step', `${g.step}${g.item ? ' (item ' + g.item + ')' : ''}, effort ${g.effort} (${plan.POINTS[g.effort]} point${plan.POINTS[g.effort] === 1 ? '' : 's'})`],
	];
	return `#### ${g.name}\n\n${table(['Aspect', 'Entry'], rows)}\n`;
}

const t17 = teams;
const teamRows = t17.map(t => [
	t.curve_rank, t.id, t.reference_name || t.placing || '-', t.species.join(', '),
	t.gaps.species.concat(t.gaps.item, t.gaps.ability, t.gaps.move).join(', ') || 'none',
	t.validator_ok ? 'yes' : 'NO', t.member_rule.inside_today ? 'yes' : `no (${t.member_rule.moves_outside_fixed_set.length})`,
]);

const stepRows = json.steps.map(s => [
	s.id, s.title, s.gaps.map(g => g.split(':')[1]).join(', ') || '-', s.teams_completed_last.join(', ') || '-',
	`${s.effort_points} (${s.prs} PR${s.prs > 1 ? 's' : ''})`, s.depends_on.join(', ') || '-', s.parallel_safe_with.join(', ') || '-',
]);

const orderRows = teams.map(t => {
	const pos = orderPlan.order.indexOf(t.id) + 1;
	const pure = orderPure.order.indexOf(t.id) + 1;
	const sunk = orderSunkP2.order.indexOf(t.id) + 1;
	const comp = teamDone[t.id];
	const maxShared = Math.max(...Object.values(plan.REFERENCE_TEAMS).map(r => shared(t.species, r)));
	return [t.curve_rank, t.id, pos, pure, sunk, t.is_reference ? 'built' : [...closure(t.item_ids)].sort().join(' '),
		t.is_reference ? 0 : `t=${comp.time}`, `${maxShared} (A/B/C)`, t.tags.join(', ') || '-',
		pos !== t.curve_rank ? (pos < t.curve_rank ? `up ${t.curve_rank - pos}` : `down ${pos - t.curve_rank}`) : 'same'];
});

const tieRounds = orderPlan.rounds.map(r => [r.round, r.minimum_cost, r.candidates.map(c => `${c.team} (${c.cost}${c.near_duplicate ? ', near-duplicate of ' + c.nearest.join('/') : ''}; ${c.tags.join('+') || 'no tag'})`).join('; '), r.chosen, r.builds.join(', '), r.tie_break_used ? 'yes' : 'no']);

const conflictRows = [];
for (const a of plan.STEPS) for (const b of plan.STEPS) if (a.id < b.id && stepConflicts[a.id][b.id]) conflictRows.push([`${a.id} - ${b.id}`, stepConflicts[a.id][b.id].join(', ')]);

const waveRows = json.schedule.waves.map(w => [`t=${w.start}`, w.items.map(i => `${i} (to ${w.ends[i]})`).join(', ')]);

const regionRows = Object.entries(plan.REGIONS).map(([id, r]) => [id, r.file + (r.lines !== '-' ? ' ' + r.lines : ''), r.what]);

const stepFileRows = json.steps.map(s => {
	const regs = s.regions;
	const tc = regs.filter(r => r.startsWith('turn.')).join(', ') || '-';
	const other = regs.filter(r => !r.startsWith('turn.')).join(', ') || '-';
	return [s.id, tc, other, s.public_changes.join('; ') || '-'];
});

const md = `# Gaps of the cheapest complete teams (expansion order)

Status: **research draft**, agent-generated on 2026-10-02 (Builder C of the expansion track). It is not a contract, not evidence and not a support claim (see \`../README.md\`). Showdown pin \`b2cb775b0616115b775534eaeff50300e1fc81fc\`. The DuoForge state analysed is \`origin/main\` \`cfe18c0\` (library 0.19.0, Team C complete, differential loop merged); decision 0015 is read from \`origin/chris/expansion-p1-pool\`. Machine-readable twin: \`data/team_gaps.json\`; every table below is generated from the same data by \`tools/tg_build.js\`.

## 1. Summary

- **The survey list is right, and incomplete as a plan.** An independent check from the paste text and the pinned validator reproduces the 29 gaps of the 17 cheapest teams exactly (3 species, 1 ability, 5 items, 20 moves), with no disagreement, no invalid set and every Stat Point spread inside 32 per stat and 66 in total.
- **Name coverage is not playability (F1).** The engine accepts one fixed four-move set per forme (\`closure_member.c:41-49\`). Only Teams A and B (MC405, MC408) are inside it; the other 15 teams need ${json.verification.forme_move_pairs_outside_fixed_sets} (forme, move) pairs it lacks. Without a legal-move rule per forme (step G1) no team beyond A and B can be set up, however many rows are added.
- **Gaps are cheaper than they look (F2).** 12 of the 22 moves are encoded by the generator today (Ice Punch needs one ignored flag) and need evidence only; the three species are rows. The real mechanics are Encore (L); Wide Guard, Throat Chop, Soak, Flower Veil and P2 (M); and S items (the pivot cause of U-turn, Focus Sash, Rock Head, Expert Belt, Psychic Noise, First Impression, Scald, Recover, Low Kick, Fairy Aura with Floettite).
- **Three shared resources are full (F3, F4):** the volatile byte, the move flags byte and the position block. Five entries (Throat Chop, Encore, Psychic Noise, Soak, Wide Guard) need state; a POOL-only state tail (step G3) and a second flags column are the way to avoid touching any CLOSURE or TEAM_C byte.
- **Two harness findings (F5):** \`ps_trace.js\` records Encore's random-target draw as INSERT_TIE, and the converter drops RANDOM_TARGET draws although this one decides the target; the converter also lacks the lines of U-turn, Wide Guard, Encore, Heal Block and Soak.
- **The plan:** G1 to G3 first (one builder for G1 then G2, the state tail beside G2), then the mechanic steps, whose files are disjoint in most pairs (section 5.3). With five builders all 17 teams are playable at t=${lastTeam.time} effort points after P1 (${lastTeam.team}, last step ${lastTeam.last}); the first new teams after A and B (${firstNew.join(', ')}) arrive at t=${firstNewTime} with the Focus Sash and Rock Head steps.
- **Variety rule (section 5.4):** ${varietySummary()}
- **Owner questions:** ${plan.QUESTIONS.length}, the first two block the plan (section 6).

## 2. Verification of the gap list

**Method** (\`tools/tg_verify_teams.js\`): each paste is read with Showdown's own \`Teams.import\` and validated with the pinned \`TeamValidator\` (on a copy: the validator rewrites Mega names); each set's forme (a Mega name becomes its base forme with the stone), item, ability, moves and nature are looked up in \`src/data/*.h\` and \`*.c\` of the working tree, not in a list; each set is compared with the fixed set of its forme in the tables.

${table(['Curve', 'Team', 'Placing / role', 'Species', 'Gaps (by name)', 'Valid', 'Inside the member rule today'], teamRows)}

**Result.** Union of the gaps: ${a17.union.species.length} species (${a17.union.species.join(', ')}), ${a17.union.ability.length} ability (${a17.union.ability.join(', ')}), ${a17.union.item.length} items (${a17.union.item.join(', ')}), ${a17.union.move.length} moves (${a17.union.move.join(', ')}); natures none (all 25 are in the table). Disagreements with the main session's list by name: **${a17.disagreements.length}**. Validator: all 17 teams valid; Stat Points: every set at most 32 per stat and 66 in total. Over all 227 pastes: ${json.verification.all_227.validator_invalid.join(' and ')} are invalid (the nonexistent move Precipice Blades), none of them among the 17; only MC405 and MC408 are inside the tables and the member rule.

**Where a name match is not enough** (finding F8 and F1):

${table(['Item', 'Check', 'Result'], [
	['Forme names', 'Floette-Eternal vs Floette-Mega, Indeedee-F vs Indeedee (M), Arcanine-Hisui, a Mega name in a paste', 'MC172 names Salamence-Mega: the setup needs Salamence with Salamencite and its own ability. Five survey teams (MC210, MC221, MC222, MC296, MC354) name Floette-Mega: the base is Floette-Eternal holding Floettite. None of them is among the 17. Indeedee (M) is another forme (Speed 95 against 85) and is not in the tables.'],
	['Items and stones', 'does every Mega stone fit its holder', 'yes in all 17 teams (the validator does not check it: README section 2)'],
	['Abilities', 'is the set ability the one the table row would carry', 'yes in all 17: Pelipper Drizzle, Arcanine-Hisui Rock Head, Annihilape Defiant; in the 227 pastes 14 of 68 formes use more than one ability (Arcanine-Hisui: 28 Rock Head, 5 Intimidate)'],
	['Natures', 'all in the 25 of the table', 'yes'],
	['Genders', 'explicit in the paste?', 'rarely (Grimmsnarl, Basculegion); Showdown draws a random gender for a missing one on a 50/50 species (sim/pokemon.ts:340), the engine requires one (male for every 50/50 species, decision 0009); Floette-Eternal is female only'],
	['Stat Points', '66 in total, 32 per stat (the Champions rule)', 'yes in all 227 pastes'],
	['Moves', "in the table AND in the forme's fixed set", 'no for 15 of the 17 teams (finding F1)'],
])}

## 3. Cross-cutting findings

${table(['Id', 'Finding', 'Evidence', 'Consequence', 'Proposal'], plan.FINDINGS.map(f => [f.id, f.title, f.evidence, f.consequence, f.proposal]))}

## 4. The gaps

The 35 entries are the 29 of the survey, Low Kick, Dazzling Gleam, Floette-Eternal with Floettite and Flower Veil, and Fairy Aura (Floette-Mega's only ability, which the survey list does not name but the setup gate requires). Each card answers the questions of the task: the pinned implementation (\`moves.ts:N\` is \`data/moves.ts\`, \`champions/...\` is \`data/mods/champions/...\`, \`sim/...\` the pinned sim directory, \`turn.c\` and \`request.c\` of \`origin/main\`), the draws, the protocol lines (the converter's gaps in bold), DuoForge today, new state, interactions and evidence. Every claim about a printed line or a draw is a run of \`tools/tg_probe_reference.js\`; every file:line is checked by \`tools/tg_check_cites.js\`.

${sections.map(([title, f]) => `### ${title}\n\n${gaps.filter(f).sort((a, b) => (gapOrder.indexOf(a.id) < 0 ? 99 : gapOrder.indexOf(a.id)) - (gapOrder.indexOf(b.id) < 0 ? 99 : gapOrder.indexOf(b.id)) || a.name.localeCompare(b.name)).map(card).join('\n')}`).join('\n')}

## 5. Step plan

### 5.1 Steps

P1 (decision 0015, in progress) comes first. Effort points: XS 1, S 2, M 4, L 8. "Teams completed" are those whose last missing step this is in the schedule of section 5.3. "Parallel-safe with" lists steps with no hard conflict (section 5.2) and no dependency between them.

${table(['Step', 'Mechanics', 'Gaps', 'Teams completed', 'Effort', 'Depends on', 'Parallel-safe with'], stepRows)}

The foundation steps in words. **G1** replaces the fixed set by a legal-move rule per forme under POOL (finding F1). **G2** adds all rows and columns once, unmarked, and marks the 12 data-only moves and the three species with four recorded battles (finding F6). **G3** adds the POOL state tail and the view bits (finding F3). P2 is step **G6a** and keeps decision 0015's scope; Expert Belt rides with it (same chain, same compile-time asserts). A step marks only what it tested (decision 0015 section 2).

### 5.2 What each step touches

Regions of the shared files (hard conflict = two steps naming one region):

${table(['Region', 'File and lines', 'What'], regionRows)}

${table(['Step', 'turn.c regions', 'Other regions', 'Additive public changes'], stepFileRows)}

Soft overlaps (mechanical merges, every mechanic step): ${plan.SOFT.join('; ')}. The version number of each public change is taken with the other sessions before the PR (decision 0015 section 4).

Hard conflicts between steps (the regions they share):

${table(['Pair', 'Shared regions'], conflictRows)}

### 5.3 Schedule for five builders

The simulation starts at P1 merged (t=0), uses effort points as durations, never runs two steps with a hard conflict together and starts items in the order of section 5.4.

${table(['Start', 'Items that start (end time)'], waveRows)}

At most ${peak} items run at the same time: the hard conflicts of section 5.2, not the number of builders, limit the schedule. Reading it: one builder owns G1 and then G2 (generator, tables, member rules); the state tail G3 runs beside G2. After G2 and G3 the mechanic steps are spread over five builders; Encore (G9) waits for the lockout step (G8a) because both edit the residual list, the request builder and the converter's \`cant\` and \`-start\` handling.

### 5.4 Team order: curve.txt against the plan

**Rule.** Cost is the effort of the steps a team still needs (shared steps once, G3 when first needed; P1, G1, G2 common to all teams beyond A and B). The cheapest team goes first. Teams within ${plan.TOLERANCE} points of the cheapest cost about the same (one S step); among them the variety rule decides: (1) a team that shares ${plan.NEAR_DUPLICATE} or more species with Team A, B, C or a team completed earlier is a near-duplicate and goes last; (2) the more species away from the nearest of those, the better; (3) then more archetype tags (rain or sun, Trick Room, Wide Guard); (4) then the cheaper; (5) then the order of \`curve.txt\`. "Plan" counts P2 as work (4 points); "no tie-break" is the same greedy with tolerance 0; "P2 scheduled" treats P2 as already decided (cost 0).

${table(['Curve', 'Team', 'Plan', 'No tie-break', 'P2 scheduled', 'Steps needed', 'Done', 'Most species shared', 'Tags', 'Move'], orderRows)}

**Where the tie-break changed the curve order.** ${tieNarrative()}

Why each round chose its team (candidates within the tolerance, with the variety facts):

${table(['Round', 'Cheapest', 'Candidates', 'Chosen', 'Builds', 'Tie-break used'], tieRounds)}

## 6. Open questions for the owner

${QUESTIONS.map(q => `${q.id}. ${q.text}`).join('\n\n')}

## 7. Files

- \`data/team_gaps.json\`: this note as data (entries, steps, schedule, order), from \`tools/tg_build.js\`.
- \`tools/tg_verify_teams.js\`: the independent check of the 17 teams (also \`--all\` for the 227 pastes); \`tools/tg_probe_generator.py\`: what \`gen_closure.py\` encodes or rejects for each move; \`tools/tg_probe_reference.js\` and \`tools/tg_probe_encore_draws.js\`: short Showdown battles that show the lines and draws of the mechanics; \`tools/tg_show.js\`: prints a Showdown entry with file:line; \`tools/tg_check_cites.js\`: checks every citation in the data against the files.
- \`tools/tg_gaps_moves.js\`, \`tools/tg_gaps_other.js\`, \`tools/tg_plan.js\`: the curated entries; \`tools/tg_build.js\` writes both outputs (\`--check\` compares them).
- The survey data (pastes, \`mc_full_coverage.json\`, \`curve.txt\`) stays outside git in \`C:\\Dev\\src\\duoforge-data\\vgcpastes-mc-2026-10-02\\\`; the pastes are cited by id and link only (the id of a team is its survey id, the link is in the JSON).
- Like the other scripts here, these are research tooling, not part of the build or CI; they hard-code \`C:/Dev/src/pokemon-showdown\` (override: \`DUOFORGE_PS_REFERENCE_DIR\`) and the survey directory (\`DUOFORGE_SURVEY_DIR\`).
`;

// ---------------------------------------------------------------- write or check
const jsonText = JSON.stringify(json, null, 1) + '\n';
if (process.argv.includes('--check')) {
	const same = fs.readFileSync(OUT_JSON, 'utf8').replace(/\r\n/g, '\n') === jsonText && fs.readFileSync(OUT_MD, 'utf8').replace(/\r\n/g, '\n') === md;
	console.log(same ? 'team_gaps.json and team-gaps.md match the data' : 'team_gaps.json or team-gaps.md differ from the data');
	process.exit(same ? 0 : 1);
}
fs.writeFileSync(OUT_JSON, jsonText);
fs.writeFileSync(OUT_MD, md);
console.log(`wrote ${path.relative(process.cwd(), OUT_JSON)} (${jsonText.length} bytes) and ${path.relative(process.cwd(), OUT_MD)} (${md.length} bytes)`);
console.log('plan order:', orderPlan.order.join(' '));
console.log('no tie-break:', orderPure.order.join(' '));
console.log('P2 scheduled:', orderSunkP2.order.join(' '));
console.log('completion:', teams.map(t => `${t.id}@${teamDone[t.id].time}`).join(' '));
console.log('waves:', json.schedule.waves.map(w => `t${w.start}[${w.items.join(',')}]`).join(' '));
