// Curated plan data of docs/research/expansion/data/team_gaps.json: the
// cross-cutting findings, the work items and steps with their files, the
// regions of src/combat/turn.c they touch, the team reference sets for the
// variety rule and the open questions. tg_build.js computes everything that
// can be computed (which teams a step completes, the order under the cost and
// variety rule, the conflict matrix, the schedule) from this data and from the
// verification of the 17 teams; nothing here is a count that a script could
// derive. Line numbers are of origin/main cfe18c0.
'use strict';

// ---------------------------------------------------------------- regions
// Pieces of the shared files that a step edits. Two steps that name one
// region conflict (a hard conflict: the same lines or the same function);
// steps that only share a SOFT resource merge mechanically.
const REGIONS = {
	'turn.types': {file: 'src/combat/turn.c', lines: '104-114, 720-757', what: 'dfi_has_type, dfi_grounded, dfi_type_immune, dfi_type_mod: the only three reads of a forme\'s types'},
	'turn.boost': {file: 'src/combat/turn.c', lines: '504-579', what: 'dfi_boost: Contrary, the cap, the Competitive and Defiant reactions'},
	'turn.status': {file: 'src/combat/turn.c', lines: '1028-1110', what: 'dfi_try_status and dfi_add_volatile'},
	'turn.heal': {file: 'src/combat/turn.c', lines: '1330-1340, 1413-1438, 3125-3135', what: 'dfi_heal, the Update (Sitrus Berry) and Grassy Terrain\'s inline residual heal'},
	'turn.before': {file: 'src/combat/turn.c', lines: '1553-1624', what: 'dfi_before_move: sleep/freeze, flinch, confusion, paralysis'},
	'turn.run_front': {file: 'src/combat/turn.c', lines: '1755-2028', what: 'dfi_run_move up to TryMove: support check, targets, PP, lock, move line, redirects'},
	'turn.run_status': {file: 'src/combat/turn.c', lines: '2029-2073', what: 'the status-move branches: side conditions, Trick Room, primary self boosts'},
	'turn.ontry': {file: 'src/combat/turn.c', lines: '2076-2101', what: 'the special-handler guard and the Fake Out / Sucker Punch onTry checks'},
	'turn.hit_steps': {file: 'src/combat/turn.c', lines: '2127-2242', what: 'Psychic Terrain, Protect, TryHit abilities, immunity, accuracy'},
	'turn.power_bp': {file: 'src/combat/turn.c', lines: '824-866', what: 'base power by weight or fainted count, and the BasePower chain'},
	'turn.moddmg': {file: 'src/combat/turn.c', lines: '765-769, 941-976', what: 'the ModifyDamage chain and its compile-time order asserts'},
	'turn.damage_loop': {file: 'src/combat/turn.c', lines: '2283-2313', what: 'spread damage and dfi_deal per target'},
	'turn.self_switch': {file: 'src/combat/turn.c', lines: '2314-2329', what: 'the switch flag of a damaging pivot move'},
	'turn.secondaries': {file: 'src/combat/turn.c', lines: '2347-2391', what: 'secondary effects per hit target'},
	'turn.thaw_after': {file: 'src/combat/turn.c', lines: '2409-2429, 2466-2476', what: 'the Fire thaw and the place after the second Update'},
	'turn.recoil': {file: 'src/combat/turn.c', lines: '2446-2477', what: 'recoil, the user\'s Emergency Exit check, the Update after it'},
	'turn.switch': {file: 'src/combat/turn.c', lines: '2559-2618', what: 'dfi_run_switch: the [switch] event and its cause'},
	'turn.entry_mega': {file: 'src/combat/turn.c', lines: '2666-2726, 2827-2855', what: 'entry abilities and the Mega Evolution'},
	'turn.residual': {file: 'src/combat/turn.c', lines: '2859-3242', what: 'the residual list and its handlers'},
	'turn.use_item': {file: 'src/combat/turn.c', lines: '1177-1193', what: 'dfi_use_item: the berry test and Unburden'},
	'request.candidates': {file: 'src/state/request.c', lines: '106-175', what: 'dfi_slot_candidates: what a slot may choose'},
	'state.layout': {file: 'src/state/battle_internal.h, src/codec/state_codec.{h,c}, src/state/invariants.c, tools/state_model/state_v3_model.py', lines: '-', what: 'the state\'s canonical layout, its checks and the oracle'},
	'state.limits': {file: 'src/state/closure_member.c', lines: '8-22', what: 'dfi_kind_limits: per data kind, the highest valid flag, status, terrain, switch-flag values'},
	'state.member': {file: 'src/state/closure_member.c', lines: '41-109, 285-363', what: 'the member rules: moves, ability, gender, item and their invariants'},
	'public.view': {file: 'include/duoforge/duoforge.h, src/state/observation.c, python/duoforge/_layout.py', lines: '427-461', what: 'the position and side views'},
	'public.events': {file: 'include/duoforge/duoforge.h, src/combat/events.c, tests/support/conformance_compare.c', lines: '494-571', what: 'event kinds, causes, flags'},
	'gen': {file: 'tools/datagen/gen_closure.py', lines: '83-112, 219-333', what: 'the generator\'s encodings and its parse_move'},
	'tables': {file: 'src/data/pool_tables.{h,c} (decision 0015) and the pins in tests/CMakeLists.txt', lines: '-', what: 'the generated POOL tables, their hashes and fingerprint'},
	'harness': {file: 'tools/reference/ps_trace.js', lines: '77-107', what: 'the draw classification'},
	'converter.rules': {file: 'tools/reference/trace_to_c.py', lines: '233-327', what: 'the draw drop rules'},
	'converter.lines': {file: 'tools/reference/trace_to_c.py', lines: '546-777', what: 'ev_cause and step_events: the protocol lines it knows'},
};
const SOFT = ['support manifest (src/data/support_manifest.c)', 'tests/CMakeLists.txt pins and test counts', 'library version (duoforge.h, python/duoforge/_lib.py, tests/test_api_atomicity.c)', 'docs/support/README.md'];

// ---------------------------------------------------------------- work items
// An item is the smallest unit that a team can need; a step (PR) is one item
// or a few that share their files. Effort points: XS 1, S 2, M 4, L 8.
const POINTS = {XS: 1, S: 2, M: 4, L: 8};
const ITEMS = [
	{id: 'G3', title: 'POOL state tail', effort: 'M', requires: [], hard: ['state.layout', 'state.limits', 'public.view'], gaps: []},
	{id: 'G4a', title: 'Focus Sash', effort: 'S', requires: [], hard: ['turn.damage_loop', 'turn.use_item'], gaps: ['item:focussash']},
	{id: 'G4b', title: 'Rock Head', effort: 'S', requires: [], hard: ['turn.recoil'], gaps: ['ability:rockhead']},
	{id: 'G5', title: 'U-turn: pivot cause by move', effort: 'S', requires: [], hard: ['turn.self_switch', 'turn.switch', 'state.limits', 'converter.lines'], gaps: ['move:uturn']},
	{id: 'G6a', title: 'P2 (0015): type boosters and resist berries', effort: 'M', requires: [], hard: ['turn.power_bp', 'turn.moddmg', 'turn.use_item', 'converter.rules'], gaps: ['item:colburberry', 'item:occaberry', 'item:blackglasses']},
	{id: 'G6b', title: 'Expert Belt', effort: 'S', requires: ['G6a'], hard: ['turn.moddmg', 'converter.rules'], gaps: ['item:expertbelt']},
	{id: 'G7', title: 'Wide Guard (side guards)', effort: 'M', requires: ['G3'], hard: ['turn.run_status', 'turn.hit_steps', 'turn.residual', 'public.events', 'public.view', 'converter.lines'], gaps: ['move:wideguard']},
	{id: 'G8a', title: 'Lockout volatiles: Throat Chop', effort: 'M', requires: ['G3'], hard: ['turn.before', 'turn.secondaries', 'turn.status', 'turn.residual', 'request.candidates', 'gen', 'public.events', 'converter.lines'], gaps: ['move:throatchop']},
	{id: 'G8b', title: 'Psychic Noise: Heal Block', effort: 'S', requires: ['G8a'], hard: ['turn.heal', 'turn.before', 'turn.residual', 'request.candidates', 'public.view', 'converter.lines'], gaps: ['move:psychicnoise']},
	{id: 'G9', title: 'Encore', effort: 'L', requires: ['G3'], hard: ['turn.run_front', 'turn.status', 'turn.residual', 'request.candidates', 'harness', 'converter.rules', 'converter.lines', 'public.events', 'public.view'], gaps: ['move:encore']},
	{id: 'G10a', title: 'First Impression (first-turn family)', effort: 'S', requires: [], hard: ['request.candidates', 'turn.ontry', 'gen'], gaps: ['move:firstimpression']},
	{id: 'G10b', title: 'Scald: thawsTarget', effort: 'S', requires: [], hard: ['turn.thaw_after', 'gen'], gaps: ['move:scald']},
	{id: 'G10c', title: 'Recover: heal fraction', effort: 'S', requires: [], hard: ['turn.run_status', 'turn.heal', 'gen', 'converter.lines'], gaps: ['move:recover']},
	{id: 'G10d', title: 'Low Kick: weight power', effort: 'S', requires: [], hard: ['turn.power_bp', 'gen'], gaps: ['move:lowkick']},
	{id: 'G11', title: 'Soak: type override', effort: 'M', requires: ['G3'], hard: ['turn.types', 'turn.entry_mega', 'public.view', 'public.events', 'converter.lines', 'gen'], gaps: ['move:soak']},
	{id: 'G12a', title: 'Flower Veil', effort: 'M', requires: [], hard: ['turn.boost', 'turn.status', 'public.events', 'converter.lines'], gaps: ['ability:flowerveil']},
	{id: 'G12b', title: 'Fairy Aura, Floettite and Floette-Eternal marked', effort: 'S', requires: ['G6a'], hard: ['turn.power_bp', 'turn.entry_mega', 'converter.lines'], gaps: ['ability:fairyaura', 'item:floettite', 'species:floetteeternal']},
];
// Everything the data steps G1 and G2 deliver: the rows and the 12 data-only moves.
const FOUNDATION = {
	P1: {title: 'P1 (decision 0015, in progress): the POOL kinds, tables, family columns', effort: null},
	G1: {title: 'Member legality for POOL: legal moves per forme instead of the fixed set', effort: 'M', hard: ['gen', 'tables', 'state.member', 'state.limits']},
	G2: {title: 'Gap rows, move columns, generator mappings; the 12 data-only moves and the new formes marked', effort: 'M', hard: ['gen', 'tables']},
};
const DATA_ONLY = ['move:rockslide', 'move:doubleedge', 'move:thunderbolt', 'move:flashcannon', 'move:extremespeed', 'move:headsmash',
	'move:bulkup', 'move:liquidation', 'move:icepunch', 'move:shadowclaw', 'move:drumbeating', 'move:dazzlinggleam',
	'species:pelipper', 'species:arcaninehisui', 'species:annihilape'];

// ---------------------------------------------------------------- steps (PRs)
// Steps group items by builder and PR. `public` lists additive public
// changes (each is a minor version step, to be numbered with the other
// sessions before it is taken, decision 0015 section 4).
const STEPS = [
	{id: 'G1', items: [], title: 'Member legality for POOL', prs: 1},
	{id: 'G2', items: [], title: 'Gap rows, columns, 12 data-only moves marked', prs: 1},
	{id: 'G3', items: ['G3'], title: 'POOL state tail', prs: 1, public: ['position-view bits for Encore and Heal Block (reserved byte bits 8 and 16) and, for Soak, bit 32 or one more byte; a side-view bit for Wide Guard (the side view\'s reserved byte)']},
	{id: 'G4', items: ['G4a', 'G4b'], title: 'Focus Sash and Rock Head', prs: 2, public: []},
	{id: 'G5', items: ['G5'], title: 'U-turn', prs: 1, public: []},
	{id: 'G6', items: ['G6a', 'G6b'], title: 'P2 (0015) and Expert Belt', prs: 2, public: []},
	{id: 'G7', items: ['G7'], title: 'Wide Guard', prs: 1, public: ['BLOCKED detail for Wide Guard', 'side-view bit']},
	{id: 'G8', items: ['G8a', 'G8b'], title: 'Throat Chop and Psychic Noise (Heal Block)', prs: 2, public: ['position-view bit 16 (Heal Block)', 'CANT with cause MOVE and the stopped move']},
	{id: 'G9', items: ['G9'], title: 'Encore', prs: 1, public: ['position-view bit 8 (Encore)', 'a volatile start/end event kind or detail']},
	{id: 'G10', items: ['G10a', 'G10b', 'G10c', 'G10d'], title: 'First Impression, Scald, Recover, Low Kick', prs: 4, public: []},
	{id: 'G11', items: ['G11'], title: 'Soak', prs: 1, public: ['the changed type (view bit 32 or a byte)', 'a type-change event']},
	{id: 'G12', items: ['G12a', 'G12b'], title: 'Floette-Eternal: Flower Veil, Fairy Aura, Floettite', prs: 2, public: ['a BLOCK event kind']},
];

// ---------------------------------------------------------------- teams
// The reference teams the learner trains on: base species only.
const REFERENCE_TEAMS = {
	A: ['Rillaboom', 'Staraptor', 'Milotic', 'Ceruledge', 'Raichu', 'Gholdengo'],
	B: ['Politoed', 'Golisopod', 'Archaludon', 'Farigiraf', 'Charizard', 'Grimmsnarl'],
	C: ['Sneasler', 'Incineroar', 'Salamence', 'Indeedee', 'Kingambit', 'Basculegion'],
};
// Archetype tags from sets (moves and abilities): the variety rule counts these.
const TAGS = {
	rain: s => s.ability === 'Drizzle',
	sun: s => s.item === 'Charizardite Y',
	trickroom: s => s.moves.includes('Trick Room'),
	wideguard: s => s.moves.includes('Wide Guard'),
};
// The rule (stated in the note): a team is a near-duplicate when it shares this many species with one reference team.
const NEAR_DUPLICATE = 5;
const TOLERANCE = 2; // "about the same cost": within one S step of the cheapest

// ---------------------------------------------------------------- findings
const FINDINGS = [
	{
		id: 'F1', title: 'Name coverage is not playability: the member rule accepts one fixed set per forme',
		evidence: 'src/state/closure_member.c:41-49 (dfi_in_set), :86 (setup), :353 (invariant), :102 and :316 (the one ability). Decision 0006 section 2.1 and 0009 section 3.4 define a member as "1 to 4 moves of the forme\'s set"; 0015 keeps the CLOSURE rules for POOL. tg_verify_teams.js over the 17 teams: only MC405 and MC408 (Teams A and B) are inside; 15 teams carry 42 (forme, move) pairs outside the fixed sets (Protect on Milotic, Swords Dance on Kingambit, Sucker Punch on Golisopod, ...), the gap moves included. The abilities are not the problem here: every set of the 17 uses the one ability the new formes would get.',
		consequence: 'Closing all 29 gaps as table rows would still leave 15 teams unplayable: every real team beyond A and B needs moves that its forme\'s fixed set lacks.',
		proposal: 'A step G1 before any team: the legal moves per forme (a bitset over the pool\'s moves, derived from the pinned learnsets and cross-checked with legal_pool.json) replace the fixed set under POOL; the ability list per forme can follow (14 of 68 formes in the 227 pastes use more than one ability). Best taken into P1 now, because it is a column of the POOL tables and the POOL fingerprint covers it.',
	},
	{
		id: 'F2', title: 'The gap count overstates the cost of data and understates the mechanics',
		evidence: 'tg_probe_generator.py: 12 of the 22 moves are encoded by the generator today (U-turn, Rock Slide, Double-Edge, Thunderbolt, Flash Cannon, Extreme Speed, Head Smash, Bulk Up, Liquidation, Shadow Claw, Drum Beating, Dazzling Gleam); Ice Punch needs only an ignored flag. The three species are rows. What costs engine work: Encore (L), Wide Guard, Throat Chop with Psychic Noise, Soak, Flower Veil (M), the pivot cause, Focus Sash, Rock Head, First Impression, Scald, Recover, Low Kick, Fairy Aura, and the P2 items (S each).',
		consequence: 'Teams that look expensive by gap count are cheap by mechanics (MC172 and MC385 need Focus Sash and Rock Head, two S steps) and one-gap teams can be the dearest (MC373: Encore).',
		proposal: 'Order by effort of the missing mechanics, not by gap count (section 5.4).',
	},
	{
		id: 'F3', title: 'The state has no room for the new volatiles',
		evidence: 'The position\'s volatile byte is full: eight bits in use (battle_internal.h:62-70). The position block is 21 bytes with no spare byte (src/codec/state_codec.h:10-50, :93). Needed: Encore (last move, slot and turns), Throat Chop and Heal Block (two-turn timers), a Soak type override, and a Wide Guard flag per side. The position view\'s `reserved` byte has bits 8 to 128 free (duoforge.h:439-446).',
		consequence: 'Five of the 35 entries need new state; the first of them cannot be built without a layout decision. Decision 0009 stayed inside the v3 layout; this cannot.',
		proposal: 'One step G3 that adds a POOL-only tail to the state (about 18 bytes: four bytes per position and one per side), valid only under the POOL kinds like 0009\'s Team C values, so every CLOSURE and TEAM_C state keeps its bytes. Alternatives: schema 4 for every kind (all goldens change) or bit-sharing in spare bits of existing bytes (no size change, obscure). Owner decision (section 6).',
	},
	{
		id: 'F4', title: 'The move row\'s flags byte is full, and three flags gain readers',
		evidence: 'gen_closure.py:83-84 uses all eight bits. `sound` is read by Throat Chop and held by Snarl (26), Parting Shot (35) and Hyper Voice (40) in the tables today; `heal` is read by Heal Block and is set on drain moves too (the pool has 23, Bitter Blade 12 and Leech Life 21 among the table\'s); `thawsTarget` is a property of Scald. IGNORED_FLAGS lists sound and heal (gen_closure.py:89-91). `punch`, `slicing` and `allyanim` have no reader in the tables.',
		consequence: 'Marking Throat Chop or Psychic Noise without the bits would be a silent misbehaviour for existing moves.',
		proposal: 'A second flags column in the POOL tables (G2/P1) filled for every id, prefix included, with sound, heal, thaws_target; `punch`, `slicing`, `allyanim` go to IGNORED_FLAGS with a generator test that fails when their reader (Iron Fist, Sharpness) enters the tables. The closure and TEAM_C canonical bytes keep only the first byte, like the psn immunity bit of 0009.',
	},
	{
		id: 'F5', title: 'Harness and converter gaps found by running the mechanics',
		evidence: 'tg_probe_reference.js: (a) Encore\'s changeAction draws a random target inside insertChoice, and ps_trace.js:90-91 tests `insertChoice` before `getRandomTarget`, so the draw is recorded as INSERT_TIE/queue (a probe patch of PRNG.sample confirms one target draw and no tie draw). (b) The converter drops RANDOM_TARGET `resolve` (trace_to_c.py:321-322) although this one decides the target. (c) An unknown `cant` reason is a bare KeyError (trace_to_c.py:667-676), as is `-fail|X|heal` (:686-687). (d) The protocol name of Arcanine-Hisui and Floette-Eternal is the base species; only Indeedee-F is mapped (:356). (e) Unknown lines: `[from] U-turn`, `-singleturn|..|Wide Guard`, `-start|..|Encore` and `|move: Heal Block`, `-start|..|typechange`, `-block`. (f) The ModifyDamage tie rule knows screens and {Life Orb, Chople Berry} only.',
		consequence: 'Each of these stops a trace loudly or, for (a) and (b), would put a wrong draw in the tape; none is silent, but each step needs its converter change.',
		proposal: 'Each step lists its converter and harness change (section 5.2). (a) and (b) belong to Encore and are the only ones that change the harness; its version stays 14 because no committed trace has a changeAction.',
	},
	{
		id: 'F6', title: 'Row-adding PRs in parallel would fight over generated files',
		evidence: 'Decision 0015 section 2: the POOL fingerprint changes with every PR that changes the pool data; the generated tables and their sha256 pins in tests/CMakeLists.txt are single files. Decision 0009 section 3.2 generated all Team C data in step 1 for this reason.',
		consequence: 'Five builders adding their own rows would conflict on the generated file, the pins and the id order, and every recorded trace would need regeneration after each merge.',
		proposal: 'G2 adds every gap row and every column once (unmarked); the mechanic steps only mark and implement and do not touch the tables. The 35 ids and their columns are in team_gaps.json (`pool_rows`).',
	},
	{
		id: 'F7', title: 'Class re-check against classification.json',
		evidence: 'Five entries change: Ice Punch B to A (the generator needs an ignored flag, no bit; Iron Fist is not in the tables), Rock Head D/M to S, Expert Belt D/M to S, Psychic Noise B to M (Heal Block is a mechanic of its own), Wide Guard C/param with new side state. U-turn stays B (the data is A, the engine\'s cause is the extension).',
		consequence: 'Efforts in section 5 follow the re-check.',
		proposal: 'None.',
	},
	{
		id: 'F8', title: 'Verification caveats that are not disagreements',
		evidence: 'A paste that names a Mega forme (Salamence-Mega in MC172; Floette-Mega in five survey teams) is the base forme holding its stone: the setup refuses a Mega forme, and the ability is the base\'s (Intimidate, Flower Veil). Indeedee (M) is a different forme from Indeedee-F (Speed 95 against 85) and is not in the tables; the survey name `Indeedee` must not be read as Indeedee-F. Most pastes omit the gender; the engine requires one (decision 0009: male for every 50/50 species), and Showdown draws a random gender for a missing one (sim/pokemon.ts:340), so a spec must state it. Two of the 227 pastes (MC213, MC214) name a move that does not exist (Precipice Blades) and fail the validator; neither is among the 17.',
		consequence: 'The team converter (not part of this note) normalises all four.',
		proposal: 'None.',
	},
];

// ---------------------------------------------------------------- open questions
const QUESTIONS = [
	{id: 'Q1', text: 'Is the learnset gate (G1) part of P1? Under decision 0015 as written, POOL keeps the fixed set per forme, so no team beyond A and B can be set up. Folding it into P1 now saves a second regeneration of the POOL tables and fingerprint.'},
	{id: 'Q2', text: 'How may the state grow (finding F3)? A POOL-only tail (recommended), schema 4 for every kind, or bit-sharing in the existing bytes. The same question for the observation: Soak\'s type needs bit 32 of the view\'s reserved byte (enough for Soak alone) or one more byte, which changes the 736-byte observation and the Python feature layout.'},
	{id: 'Q3', text: 'Does the variety rule use Team C as a reference (this note does) and does it count teams completed earlier in the plan? It decides which team gets evidence first when two cost about the same (section 5.4); the step order changes only at the start, see below.'},
	{id: 'Q4', text: 'May G2 add all 35 rows at once, unmarked, so the POOL fingerprint is fixed for the whole track (finding F6)? The alternative is each step adding its own rows and regenerating the tables after every merge.'},
	{id: 'Q5', text: 'Is P2 (0015) kept where 0015 puts it, right after P1, or may it wait behind the Focus Sash and Rock Head steps that complete two teams sooner? The order table shows both costs.'},
];

module.exports = {REGIONS, SOFT, POINTS, ITEMS, FOUNDATION, DATA_ONLY, STEPS, REFERENCE_TEAMS, TAGS, NEAR_DUPLICATE, TOLERANCE, FINDINGS, QUESTIONS};
