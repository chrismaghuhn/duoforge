// Mirrors tools/datagen/gen_closure.py parse_move (ext mode, Team C) and the
// paths of src/combat/turn.c for a move row, on the dex objects of the format.
'use strict';
const L = require('./lib.js');

const TARGET_CLASS = new Set(['normal', 'any', 'adjacentAlly', 'adjacentAllyOrSelf', 'adjacentFoe', 'self',
	'allAdjacentFoes', 'allySide', 'all', 'randomNormal']);
const ENGINE_TARGETS = new Set(['normal', 'any', 'adjacentFoe', 'self', 'allAdjacentFoes', 'allySide', 'all',
	'randomNormal']);
const STATUS = new Set(['brn', 'frz', 'par', 'slp']);          // closure STATUS (used for secondaries)
const STATUS_C = new Set(['brn', 'frz', 'par', 'slp', 'psn']); // ext STATUS_C (primary status)
const VOLATILE = new Set(['flinch', 'confusion']);
const SIDE_CONDITION = new Set(['tailwind', 'reflect', 'lightscreen']);
const PSEUDO_WEATHER = new Set(['trickroom']);
const FLAG_BITS = new Set(['contact', 'protect', 'charge', 'defrost']);
const IGNORED_FLAGS = new Set(['bullet', 'bypasssub', 'dance', 'distance', 'failcopycat', 'failencore', 'failinstruct',
	'failmefirst', 'failmimic', 'heal', 'metronome', 'mirror', 'noassist', 'nonsky', 'nosketch', 'nosleeptalk', 'pulse',
	'reflectable', 'slicing', 'snatch', 'sound', 'wind']);
const DATA_KEYS = new Set(['num', 'accuracy', 'basePower', 'category', 'name', 'pp', 'priority', 'flags', 'target', 'type',
	'critRatio', 'secondary', 'self', 'boosts', 'recoil', 'drain', 'status', 'volatileStatus', 'sideCondition',
	'pseudoWeather', 'selfSwitch', 'stallingMove', 'noPPBoosts', 'struggleRecoil', 'condition']);
const IGNORED_KEYS = new Set(['contestType', 'zMove', 'maxMove', 'isNonstandard', 'hasSheerForceBoost', 'inherit']);
// SPECIAL_C: move -> [handler id, callbacks it owns]
const SPECIAL_C = {
	grassknot: ['GRASS_KNOT', ['basePowerCallback', 'onTryHit']],
	weatherball: ['WEATHER_BALL', ['onModifyType', 'onModifyMove']],
	hurricane: ['HURRICANE', ['onModifyMove']],
	grassyglide: ['GRASSY_GLIDE', ['onModifyPriority']],
	electroshot: ['ELECTRO_SHOT', ['onTryMove']],
	fakeout: ['FAKE_OUT', ['onTry', 'onDisableMove']],
	partingshot: ['PARTING_SHOT', ['onHit']],
	protect: ['PROTECT', ['onPrepareHit', 'onHit']],
	struggle: ['STRUGGLE', ['onModifyMove']],
	darkestlariat: ['DARKEST_LARIAT', []],
	lastrespects: ['LAST_RESPECTS', ['basePowerCallback']],
	suckerpunch: ['SUCKER_PUNCH', ['onTry']],
	helpinghand: ['HELPING_HAND', ['onTryHit']],
	followme: ['FOLLOW_ME', ['onTry']],
};
const SPECIAL_FIELDS = {DARKEST_LARIAT: ['ignoreDefensive', 'ignoreEvasion']};
const SPECIAL_VOLATILE = {FOLLOW_ME: 'followme', HELPING_HAND: 'helpinghand'};
// Specials whose handler the engine does not run yet (turn.c returns E_INVARIANT).
const ENGINE_PENDING_SPECIAL = new Set(['SUCKER_PUNCH', 'HELPING_HAND', 'FOLLOW_ME']);
const DIRE_CLAW_ONHIT = "onHit(target, source) { const status = this.sample(['psn', 'par', 'slp']); target.trySetStatus(status, source); }";

// The moves marked in src/data/support_manifest.c.
const MANIFEST = new Set(['highhorsepower', 'protect', 'muddywater', 'coil', 'shadowsneak', 'swordsdance', 'focusblast',
	'shadowball', 'nastyplot', 'drillrun', 'dragonpulse', 'snarl', 'psychic', 'spiritbreak', 'icebeam', 'hypnosis',
	'zapcannon', 'ironhead', 'heatwave', 'hurricane', 'tailwind', 'reflect', 'lightscreen', 'trickroom', 'woodhammer',
	'bravebird', 'bitterblade', 'leechlife', 'closecombat', 'makeitrain', 'weatherball', 'grassknot', 'grassyglide',
	'fakeout', 'electroshot', 'partingshot', 'kowtowcleave', 'hypervoice', 'dracometeor', 'wavecrash', 'aquajet',
	'flareblitz', 'darkestlariat', 'lastrespects', 'flipturn', 'struggle']);
// In the extended tables (generated) but not marked yet.
const TABLED_PENDING = new Set(['direclaw', 'followme', 'helpinghand', 'suckerpunch']);

function boostVec(o) {
	return o && typeof o === 'object' && Object.keys(o).length > 0;
}

// Returns {gen: [...issues], engine: [...issues], callbacks: [...paths], special}
function check(id) {
	const d = L.dex.data.Moves[id];
	const keys = L.ownKeys(d);
	const special = SPECIAL_C[id] ? SPECIAL_C[id][0] : 'NONE';
	const owned = new Set(SPECIAL_C[id] ? SPECIAL_C[id][1] : []);
	const ownedFields = new Set(SPECIAL_FIELDS[special] || []);
	const gen = [];
	const engine = [];
	const cbs = L.handlers(d).map(h => h[0]);
	for (const k of keys) {
		const v = d[k];
		if (typeof v === 'function') {
			if (!owned.has(k)) gen.push('callback:' + k);
		} else if (!DATA_KEYS.has(k) && !IGNORED_KEYS.has(k) && !ownedFields.has(k)) {
			gen.push('field:' + k);
		}
	}
	for (const f of Object.keys(d.flags || {})) {
		if (!FLAG_BITS.has(f) && !IGNORED_FLAGS.has(f)) gen.push('flag:' + f);
	}
	if (!TARGET_CLASS.has(d.target)) gen.push('target:' + d.target);
	else if (!ENGINE_TARGETS.has(d.target)) engine.push('target:' + d.target);
	let vectors = 0;
	if (d.secondary) {
		const s = d.secondary;
		const sk = L.ownKeys(s);
		if (!('chance' in s)) gen.push('secondary:nochance');
		if (s.status) {
			if (!STATUS.has(s.status)) gen.push('secondary.status:' + s.status);
		} else if (s.volatileStatus) {
			if (!VOLATILE.has(s.volatileStatus)) gen.push('secondary.volatile:' + s.volatileStatus);
		} else if (s.boosts) {
			vectors += 1;
		} else if (s.self) {
			// gen_closure.py tests `'boosts' in text` before anything else: a
			// self-boost secondary would be encoded as a target boost.
			gen.push('secondary.self' + (s.self.boosts ? ':boosts(MISENCODED as target boost)' : ':' + L.ownKeys(s.self).join('+')));
		} else if (typeof s.onHit === 'function') {
			// gen_closure.py compares the TS source (single quotes); the built
			// dist prints double quotes.
			const body = s.onHit.toString().replace(/\s+/g, ' ').trim().replace(/"/g, "'");
			if (body !== DIRE_CLAW_ONHIT) gen.push('secondary.onHit');
		} else {
			gen.push('secondary:unknown(' + sk.join('+') + ')');
		}
		for (const k of sk) {
			if (!['chance', 'status', 'volatileStatus', 'boosts', 'self', 'onHit', 'dustproof', 'kingsrock'].includes(k)) {
				gen.push('secondary.' + k);
			}
		}
	}
	if (d.self) {
		const sk = L.ownKeys(d.self);
		if (d.self.boosts) vectors += 1;
		for (const k of sk) if (k !== 'boosts') gen.push('self.' + k + (typeof d.self[k] === 'string' ? ':' + d.self[k] : ''));
		if (!d.self.boosts && !sk.length) gen.push('self:empty');
	}
	if (boostVec(d.boosts)) {
		if (d.target !== 'self') gen.push('boosts:target-' + d.target);
		vectors += 1;
	}
	if (vectors > 1) gen.push('boosts:more-than-one-vector');
	if (d.status && !STATUS_C.has(d.status)) gen.push('status:' + d.status);
	const ownedVol = SPECIAL_VOLATILE[special];
	if (d.volatileStatus && d.volatileStatus !== 'protect' && d.volatileStatus !== ownedVol) {
		gen.push('volatileStatus:' + d.volatileStatus);
	}
	if (d.sideCondition && !SIDE_CONDITION.has(d.sideCondition)) gen.push('sideCondition:' + d.sideCondition);
	if (d.pseudoWeather && !PSEUDO_WEATHER.has(d.pseudoWeather)) gen.push('pseudoWeather:' + d.pseudoWeather);
	if (d.condition && !(SIDE_CONDITION.has(d.sideCondition) || PSEUDO_WEATHER.has(d.pseudoWeather) || id === 'protect' ||
		ownedVol)) {
		gen.push('condition:no-known-owner');
	}
	if (typeof d.selfSwitch === 'string') gen.push('selfSwitch:' + d.selfSwitch + '(MISENCODED as plain switch)');
	const ppCapped = Math.min(d.pp, 20);
	if (!d.noPPBoosts && ppCapped % 5 !== 0) gen.push('pp:not-multiple-of-5');
	const acc = d.accuracy === true ? 0 : d.accuracy;
	for (const [k, v] of [['basePower', d.basePower], ['accuracy', acc], ['pp', d.pp], ['priority', d.priority + 8],
		['critRatio', d.critRatio || 1]]) {
		if (!(v >= 0 && v <= 255)) gen.push('range:' + k);
	}
	// Engine paths (turn.c), meaningful once the row is generated.
	const status = d.category === 'Status';
	if (status) {
		const ok = special === 'PROTECT' || SIDE_CONDITION.has(d.sideCondition) || PSEUDO_WEATHER.has(d.pseudoWeather) ||
			(d.status && STATUS_C.has(d.status)) || special === 'PARTING_SHOT' ||
			(boostVec(d.boosts) && d.target === 'self');
		if (!ok) engine.push('status-move-shape');
		if (d.selfSwitch && special !== 'PARTING_SHOT') engine.push('status-selfSwitch');
	} else {
		if (d.secondary && d.self && d.self.boosts) engine.push('secondary+self-boost');
	}
	if (ENGINE_PENDING_SPECIAL.has(special)) engine.push('special-pending:' + special);
	return {gen, engine, callbacks: cbs, special, implemented: MANIFEST.has(id), tabled: MANIFEST.has(id) ||
		TABLED_PENDING.has(id)};
}

module.exports = {check, MANIFEST, TABLED_PENDING, SPECIAL_C};

if (require.main === module) {
	const ms = L.live(L.dex.moves.all());
	const counts = {};
	for (const m of ms) {
		const r = check(m.id);
		if (r.callbacks.length) continue;
		const all = r.gen.concat(r.engine.map(e => 'engine:' + e));
		const k = all.length ? all.join(' ; ') : 'A';
		(counts[k] = counts[k] || []).push(m.id);
	}
	for (const [k, v] of Object.entries(counts).sort((a, b) => b[1].length - a[1].length)) {
		console.log(`${v.length}\t${k}\t${v.join(' ')}`);
	}
}
