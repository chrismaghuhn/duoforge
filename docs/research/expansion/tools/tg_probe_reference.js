// Records short hand-made battles of the pinned Showdown with the repository's
// own harness (tools/reference/ps_trace.js, called as a library; nothing is
// written to the repository) and prints, per step, the protocol lines and the
// draws with their site and context. It is the evidence behind the "protocol
// lines" and "draws" rows of docs/research/expansion/team-gaps.md: each claim
// there about what a mechanic prints, or which random calls it makes, is one
// of these scenarios.
//
// usage: node tg_probe_reference.js [scenario ...]      (no argument: all)
//
// Scenarios are plain data below: two teams in paste text (gender always
// given, as the specs do) and the choices in request order. A choice that
// Showdown rejects throws, which is printed, never skipped.
'use strict';
const path = require('path');

const PS = process.env.DUOFORGE_PS_REFERENCE_DIR || 'C:/Dev/src/pokemon-showdown';
const REPO = path.resolve(__dirname, '..', '..', '..', '..');
const trace = require(path.join(REPO, 'tools', 'reference', 'ps_trace.js'));

const seed = n => 'sodium,' + n.toString(16).padStart(64, '0');
const set = (head, ability, nature, evs, moves) => [head, `Ability: ${ability}`, 'Level: 50', `EVs: ${evs}`, `${nature} Nature`,
	...moves.map(m => '- ' + m)].join('\n');
const team = (...sets) => sets.join('\n\n');

const T = {
	rillaboom: (moves, item = 'Miracle Seed') => set(`Rillaboom (M) @ ${item}`, 'Grassy Surge', 'Adamant', '32 HP / 32 Atk / 2 Spe', moves),
	raichu: (moves, item = 'Light Clay') => set(`Raichu (F) @ ${item}`, 'Lightning Rod', 'Timid', '2 HP / 32 SpA / 32 Spe', moves),
	gholdengo: (moves, item = 'Life Orb') => set(`Gholdengo @ ${item}`, 'Good as Gold', 'Modest', '2 HP / 32 SpA / 32 Spe', moves),
	milotic: (moves, item = 'Sitrus Berry') => set(`Milotic (F) @ ${item}`, 'Competitive', 'Calm', '32 HP / 32 SpD / 2 Def', moves),
	incineroar: (moves, item = 'Sitrus Berry') => set(`Incineroar (M) @ ${item}`, 'Intimidate', 'Careful', '32 HP / 2 Atk / 32 SpD', moves),
	salamence: (moves, item = 'Life Orb') => set(`Salamence (M) @ ${item}`, 'Intimidate', 'Timid', '2 HP / 32 SpA / 32 Spe', moves),
	kingambit: (moves, item = 'Leftovers') => set(`Kingambit (M) @ ${item}`, 'Defiant', 'Adamant', '32 HP / 32 Atk / 2 SpD', moves),
	pelipper: (moves, item = 'Sitrus Berry') => set(`Pelipper (M) @ ${item}`, 'Drizzle', 'Modest', '2 HP / 32 SpA / 32 Spe', moves),
	arcanine: (moves, item = 'Focus Sash') => set(`Arcanine-Hisui (M) @ ${item}`, 'Rock Head', 'Jolly', '2 HP / 32 Atk / 32 Spe', moves),
	floette: (moves, item = 'Floettite') => set(`Floette-Eternal (F) @ ${item}`, 'Flower Veil', 'Modest', '2 HP / 32 SpA / 32 Spe', moves),
	basculegion: (moves, item = 'Choice Scarf') => set(`Basculegion (M) @ ${item}`, 'Adaptability', 'Jolly', '2 HP / 32 Atk / 32 Spe', moves),
	farigiraf: (moves, item = 'Leftovers') => set(`Farigiraf (F) @ ${item}`, 'Armor Tail', 'Relaxed', '32 HP / 2 Def / 32 SpD', moves),
	golisopod: (moves, item = 'Sitrus Berry') => set(`Golisopod (M) @ ${item}`, 'Emergency Exit', 'Adamant', '32 HP / 32 Atk / 2 SpD', moves),
};
const slowSalamence = (moves, item = 'Leftovers') => set(`Salamence (M) @ ${item}`, 'Intimidate', 'Quiet', '32 HP / 32 SpA', moves);
const fastIncineroar = (moves, item = 'Sitrus Berry') => set(`Incineroar (M) @ ${item}`, 'Intimidate', 'Jolly', '2 HP / 32 Atk / 32 Spe', moves);
const teamStep = {p1: 'team 1234', p2: 'team 1234'};

const SCENARIOS = {
	// U-turn: the switch line of a damaging pivot, and the request after it.
	uturn: {
		seed: seed(0x6a01),
		teams: [
			team(T.rillaboom(['U-turn', 'Fake Out']), T.raichu(['Protect', 'Zap Cannon']), T.gholdengo(['Protect', 'Make It Rain']), T.milotic(['Protect', 'Muddy Water'])),
			team(T.incineroar(['Fake Out', 'Flare Blitz']), T.kingambit(['Protect', 'Iron Head']), T.salamence(['Protect', 'Hyper Voice']), T.pelipper(['Protect', 'Tailwind'])),
		],
		choices: [teamStep, {p1: 'move 1 1, move 1', p2: 'move 2 1, move 1'}, {p1: 'switch 3, pass'}, {p1: 'move 1, move 2 1', p2: 'move 2 1, move 2 1'}],
	},
	// Wide Guard: -singleturn, -activate per target, [spread], and the stall counter shared with Protect.
	wideguard: {
		seed: seed(0x6a02),
		teams: [
			team(T.pelipper(['Wide Guard', 'Protect']), T.milotic(['Protect', 'Muddy Water']), T.raichu(['Protect', 'Zap Cannon']), T.gholdengo(['Protect', 'Make It Rain'])),
			team(T.salamence(['Hyper Voice', 'Protect']), T.incineroar(['Fake Out', 'Snarl']), T.kingambit(['Protect', 'Iron Head']), T.rillaboom(['Fake Out', 'Protect'])),
		],
		choices: [teamStep, {p1: 'move 1, move 1', p2: 'move 1, move 2'}, {p1: 'move 2, move 2', p2: 'move 1, move 2'}, {p1: 'move 1, move 1', p2: 'move 1, move 2'}],
	},
	// Throat Chop against a slower Salamence that queued Hyper Voice: the cant line, then the disabled request.
	throatchop: {
		seed: seed(0x6a03),
		teams: [
			team(fastIncineroar(['Throat Chop', 'Fake Out']), T.rillaboom(['Fake Out', 'Protect']), T.raichu(['Protect', 'Zap Cannon']), T.gholdengo(['Protect', 'Make It Rain'])),
			team(slowSalamence(['Hyper Voice', 'Protect']), T.kingambit(['Protect', 'Iron Head']), T.pelipper(['Protect', 'Tailwind']), T.milotic(['Protect', 'Muddy Water'])),
		],
		choices: [teamStep, {p1: 'move 1 1, move 2', p2: 'move 1, move 1'}, {p1: 'move 1 1, move 2', p2: 'move 2, move 1'}, {p1: 'move 1 1, move 2', p2: 'move 1, move 1'}],
	},
	// Encore on a target that already chose another move; then Fake Out + Encore leaves Struggle.
	encore: {
		seed: seed(0x6a04),
		teams: [
			team(T.raichu(['Encore', 'Protect']), T.rillaboom(['Fake Out', 'Protect']), T.gholdengo(['Protect', 'Make It Rain']), T.milotic(['Protect', 'Muddy Water'])),
			team(T.incineroar(['Fake Out', 'Flare Blitz']), T.kingambit(['Protect', 'Iron Head']), T.salamence(['Protect', 'Hyper Voice']), T.pelipper(['Protect', 'Tailwind'])),
		],
		choices: [teamStep, {p1: 'move 2, move 2', p2: 'move 1 2, move 1'}, {p1: 'move 1 1, move 2', p2: 'move 2 1, move 2 1'}, {p1: 'move 2, move 2', p2: 'move 1, move 1'}, {p1: 'move 2, move 2', p2: 'move 1, move 1'}],
	},
	// Psychic Noise: Heal Block lines; Leech Life and Recover disabled; heals blocked.
	healblock: {
		seed: seed(0x6a05),
		teams: [
			team(T.farigiraf(['Psychic Noise', 'Protect']), T.rillaboom(['Fake Out', 'Protect']), T.raichu(['Protect', 'Zap Cannon']), T.gholdengo(['Protect', 'Make It Rain'])),
			team(T.milotic(['Recover', 'Protect'], 'Leftovers'), T.golisopod(['Leech Life', 'Protect']), T.salamence(['Protect', 'Hyper Voice']), T.pelipper(['Protect', 'Tailwind'])),
		],
		choices: [teamStep, {p1: 'move 1 1, move 2', p2: 'move 1, move 1 1'}, {p1: 'move 2, move 2', p2: 'move 2, move 2'}, {p1: 'move 2, move 2', p2: 'move 2, move 2'}, {p1: 'move 2, move 2', p2: 'move 1, move 1 1'}],
	},
	// Psychic Noise against a slower Milotic that queued Recover: the cant line with the move name.
	healblockcant: {
		seed: seed(0x6a0d),
		teams: [
			team(set('Farigiraf (F) @ Leftovers', 'Armor Tail', 'Timid', '32 HP / 32 Spe', ['Psychic Noise', 'Protect']), T.rillaboom(['Fake Out', 'Protect']), T.raichu(['Protect', 'Zap Cannon']), T.gholdengo(['Protect', 'Make It Rain'])),
			team(set('Milotic (F) @ Leftovers', 'Competitive', 'Quiet', '32 HP / 32 SpD', ['Recover', 'Protect']), T.golisopod(['Leech Life', 'Protect']), T.salamence(['Protect', 'Hyper Voice']), T.pelipper(['Protect', 'Tailwind'])),
		],
		choices: [teamStep, {p1: 'move 1 1, move 2', p2: 'move 1, move 2'}, {p1: 'move 2, move 2', p2: 'move 2, move 2'}],
	},
	// Soak: the typechange line, the fail line, and a Flying type that becomes grounded.
	soak: {
		seed: seed(0x6a06),
		teams: [
			team(T.basculegion(['Soak', 'Aqua Jet']), T.raichu(['Zap Cannon', 'Protect']), T.gholdengo(['Protect', 'Make It Rain']), T.milotic(['Protect', 'Muddy Water'])),
			team(T.pelipper(['Protect', 'Tailwind']), T.salamence(['Protect', 'Hyper Voice']), T.incineroar(['Fake Out', 'Flare Blitz']), T.kingambit(['Protect', 'Iron Head'])),
		],
		choices: [teamStep, {p1: 'move 1 1, move 1 1', p2: 'move 2, move 1'}, {p1: 'move 1 1, move 1 1', p2: 'move 2, move 1'}],
	},
	// Focus Sash against a KO from full HP, then against the next hit.
	focussash: {
		seed: seed(0x6a07),
		teams: [
			team(T.salamence(['Draco Meteor', 'Protect']), T.kingambit(['Kowtow Cleave', 'Protect']), T.raichu(['Protect', 'Zap Cannon']), T.gholdengo(['Protect', 'Make It Rain'])),
			team(T.pelipper(['Protect', 'Tailwind'], 'Focus Sash'), T.milotic(['Protect', 'Muddy Water']), T.incineroar(['Fake Out', 'Flare Blitz']), T.rillaboom(['Fake Out', 'Protect'])),
		],
		choices: [teamStep, {p1: 'move 1 1, move 2', p2: 'move 2, move 2'}, {p1: 'move 1 1, move 2', p2: 'move 2, move 2'}],
	},
	// Flower Veil: Intimidate on a Grass type next to the holder (the lead entries are in step 0).
	flowerveil: {
		seed: seed(0x6a08),
		teams: [
			team(T.floette(['Protect', 'Dazzling Gleam']), T.rillaboom(['Fake Out', 'Protect']), T.raichu(['Protect', 'Zap Cannon']), T.gholdengo(['Protect', 'Make It Rain'])),
			team(T.incineroar(['Fake Out', 'Flare Blitz']), T.salamence(['Protect', 'Hyper Voice']), T.kingambit(['Protect', 'Iron Head']), T.pelipper(['Protect', 'Tailwind'])),
		],
		choices: [teamStep, {p1: 'move 1, move 2', p2: 'move 2 1, move 2'}],
	},
	// Rock Head: Head Smash and Flare Blitz leave no recoil line.
	rockhead: {
		seed: seed(0x6a09),
		teams: [
			team(T.arcanine(['Head Smash', 'Flare Blitz']), T.raichu(['Protect', 'Zap Cannon']), T.gholdengo(['Protect', 'Make It Rain']), T.milotic(['Protect', 'Muddy Water'])),
			team(T.kingambit(['Protect', 'Iron Head']), T.milotic(['Protect', 'Muddy Water']), T.incineroar(['Fake Out', 'Flare Blitz']), T.rillaboom(['Fake Out', 'Protect'])),
		],
		choices: [teamStep, {p1: 'move 1 1, move 2 1', p2: 'move 2 1, move 2'}, {p1: 'move 2 2, move 2 1', p2: 'move 2 1, move 2'}],
	},
	// Recover at full and at half HP; Milotic hurt by Salamence first.
	recover: {
		seed: seed(0x6a0a),
		teams: [
			team(T.milotic(['Recover', 'Protect']), T.rillaboom(['Fake Out', 'Protect']), T.raichu(['Protect', 'Zap Cannon']), T.gholdengo(['Protect', 'Make It Rain'])),
			team(T.salamence(['Draco Meteor', 'Protect']), T.kingambit(['Kowtow Cleave', 'Protect']), T.pelipper(['Protect', 'Tailwind']), T.incineroar(['Fake Out', 'Flare Blitz'])),
		],
		choices: [teamStep, {p1: 'move 1, move 2', p2: 'move 1 1, move 2'}, {p1: 'move 1, move 2', p2: 'move 2, move 2'}],
	},
	// Mega Floette: Fairy Aura on the Mega Evolution, then Dazzling Gleam.
	fairyaura: {
		seed: seed(0x6a0b),
		teams: [
			team(T.floette(['Protect', 'Dazzling Gleam']), T.rillaboom(['Fake Out', 'Protect']), T.raichu(['Protect', 'Zap Cannon']), T.gholdengo(['Protect', 'Make It Rain'])),
			team(T.salamence(['Protect', 'Hyper Voice'], 'Leftovers'), T.kingambit(['Protect', 'Iron Head']), T.pelipper(['Protect', 'Tailwind']), T.milotic(['Protect', 'Muddy Water'])),
		],
		choices: [teamStep, {p1: 'move 2 mega, move 2', p2: 'move 1, move 2 1'}, {p1: 'move 2, move 2', p2: 'move 1, move 2 1'}],
	},
	// First Impression on turn 1, then it is disabled in the request.
	firstimpression: {
		seed: seed(0x6a0c),
		teams: [
			team(T.golisopod(['First Impression', 'Protect']), T.rillaboom(['Fake Out', 'Protect']), T.raichu(['Protect', 'Zap Cannon']), T.gholdengo(['Protect', 'Make It Rain'])),
			team(T.incineroar(['Fake Out', 'Flare Blitz']), T.kingambit(['Protect', 'Iron Head']), T.salamence(['Protect', 'Hyper Voice']), T.pelipper(['Protect', 'Tailwind'])),
		],
		choices: [teamStep, {p1: 'move 1 1, move 2', p2: 'move 2 1, move 1'}, {p1: 'move 2, move 2', p2: 'move 2 1, move 1'}],
	},
};

function show(arg) {
	// "name" runs every choice; "name:N" only the first N (to look at the state before a rejected choice).
	const [name, count] = arg.split(':');
	const sc = {...SCENARIOS[name]};
	if (process.env.TG_SEED) sc.seed = seed(parseInt(process.env.TG_SEED, 16)); // another roll of the same scenario
	let n = count ? Number(count) : sc.choices.length;
	let text = null;
	let failure = '';
	for (; n >= 1 && text === null; n--) {
		const spec = {name, purpose: 'probe', format: 'gen9championsvgc2026regmc', seed: sc.seed, teams: sc.teams,
			choices: sc.choices.slice(0, n)};
		try {
			text = trace.run(PS, spec, name + '.json');
		} catch (e) {
			failure = `step ${n - 1}: ${e.message}`; // the last choice that Showdown rejected (the one before it ran)
		}
	}
	if (text === null) {
		console.log(`### ${name}: ${failure}`);
		return;
	}
	if (failure) console.log(`(the scenario's choice ${failure})`);
	const t = JSON.parse(text);
	console.log(`### ${name} (seed ...${sc.seed.slice(-4)})`);
	t.steps.forEach((st, i) => {
		console.log(`-- step ${i} input ${JSON.stringify(st.input)}`);
		const lines = st.log.filter(l => !l.startsWith('|t:|') && l !== '|' && !l.startsWith('|split|'));
		for (const l of lines) console.log('   ' + l);
		const kinds = st.draws.map(d => `${d.site}${d.context ? '/' + d.context : ''}[${d.lo},${d.hi})=${d.value}`);
		if (kinds.length) console.log('   draws: ' + kinds.join(' '));
		const enabled = st.state.sides.map(s => JSON.stringify(s.enabled)).join(' ');
		console.log(`   requests: ${st.state.sides.map(s => s.request || '-').join('/')} enabled ${enabled}`);
	});
}

const wanted = process.argv.slice(2);
for (const name of wanted.length ? wanted : Object.keys(SCENARIOS)) show(name);
