// Classifies every move, ability and item of gen9championsvgc2026regmc for
// DuoForge. Read-only on the Showdown checkout; writes classification.json
// next to this script.
'use strict';
const fs = require('fs');
const path = require('path');
const L = require('./lib.js');
const MC = require('./moves_check.js');
const F = require('./families.js');

const dex = L.dex;
const PS = 'C:/Dev/src/pokemon-showdown';

// ------------------------------------------------------------------ helpers
const handlerSrc = d => L.handlers(d).map(([p, v]) => p + ':' + (typeof v === 'function' ? v.toString() : JSON.stringify(v))).join('\n');
const codeChars = d => L.handlers(d).reduce((n, [, v]) => n + L.looseNorm(v).length, 0);

function clusterIds(entries, sigFn) {
	const by = new Map();
	for (const [id, d] of entries) {
		if (!L.handlers(d).length) continue;
		const s = sigFn(d);
		if (!by.has(s)) by.set(s, []);
		by.get(s).push(id);
	}
	const out = {};
	let n = 0;
	for (const ids of [...by.values()].sort((a, b) => b.length - a.length)) {
		n += 1;
		for (const id of ids) out[id] = {id: n, size: ids.length};
	}
	return out;
}

// ------------------------------------------------------------- flag consumers
// Which live entries (and the conditions they use) read a move flag.
function flagConsumers() {
	const sources = [];
	for (const m of L.live(dex.moves.all())) sources.push(['move:' + m.id, handlerSrc(dex.data.Moves[m.id])]);
	for (const a of L.live(dex.abilities.all())) sources.push(['ability:' + a.id, handlerSrc(dex.data.Abilities[a.id])]);
	for (const i of L.live(dex.items.all())) sources.push(['item:' + i.id, handlerSrc(dex.data.Items[i.id])]);
	// Volatiles a live move applies whose condition block lives on a past move.
	const used = new Set();
	for (const m of L.live(dex.moves.all())) {
		const d = dex.data.Moves[m.id];
		for (const v of [d.volatileStatus, d.secondary && d.secondary.volatileStatus, d.self && d.self.volatileStatus]) {
			if (v) used.add(v);
		}
	}
	for (const v of used) {
		const pm = dex.data.Moves[v];
		if (pm && pm.condition && dex.moves.get(v).isNonstandard) sources.push(['condition:' + v, handlerSrc(pm)]);
	}
	for (const [cid, c] of Object.entries(dex.data.Conditions)) sources.push(['condition:' + cid, handlerSrc(c)]);
	const core = {dance: ['core:Dancer (sim/battle-actions.ts)'], powder: ['core:powder immunity (sim/battle-actions.ts)'],
		mustpressure: ['core:Pressure (sim/pokemon.ts)'], futuremove: ['core (sim)'], cantusetwice: ['core (sim)']};
	const flags = new Set();
	for (const m of L.live(dex.moves.all())) for (const f of Object.keys(dex.data.Moves[m.id].flags || {})) flags.add(f);
	const out = {};
	for (const f of flags) {
		const re = new RegExp(`flags\\[["']${f}["']\\]|flags\\.${f}\\b`);
		out[f] = sources.filter(([, s]) => re.test(s)).map(([k]) => k).concat(core[f] || []);
	}
	return out;
}

// ----------------------------------------------------- core references (sim)
function coreRefs() {
	const files = fs.readdirSync(path.join(PS, 'sim')).filter(f => f.endsWith('.ts')).map(f => path.join(PS, 'sim', f));
	files.push(path.join(PS, 'data/mods/champions/scripts.ts'));
	const text = files.map(f => fs.readFileSync(f, 'utf8')).join('\n');
	const refs = {};
	const add = (id, what) => {
		(refs[id] = refs[id] || new Set()).add(what);
	};
	for (const m of text.matchAll(/has(Ability|Item)\(\s*(\[[^\]]*\]|['"][^'"]+['"])/g)) {
		for (const q of m[2].matchAll(/['"]([^'"]+)['"]/g)) add(q[1].toLowerCase().replace(/[^a-z0-9]/g, ''), 'sim:has' + m[1]);
	}
	for (const m of text.matchAll(/\b(ability|item) === ['"]([a-z0-9]+)['"]/g)) add(m[2], 'sim:' + m[1] + '===');
	return refs;
}

// --------------------------------------------------------------- extensions
let CONSUMERS = {};
// The generic extension a generator/engine issue stands for (B).
function extensionOf(issue, d, id) {
	const [kind, rest] = [issue.split(':')[0], issue.slice(issue.indexOf(':') + 1)];
	if (issue.startsWith('engine:')) {
		const e = issue.slice(7);
		if (e.startsWith('target:')) return 'ally target classes (adjacentAlly, adjacentAllyOrSelf) in the engine';
		if (e === 'status-move-shape') return null; // a consequence of another extension
		if (e === 'status-selfSwitch') return 'status-move pivot';
		if (e === 'secondary+self-boost') return 'secondary and self-drop on one move';
		if (e.startsWith('special-pending:')) return null; // planned Team C handler, not a generic extension
		return 'engine:' + e;
	}
	switch (kind) {
	case 'target':
		return {allAdjacent: 'target class allAdjacent (spread that also hits the ally)', foeSide: 'target class foeSide',
			allies: 'target class allies', allyTeam: 'target class allyTeam', scripted: 'target class scripted'}[rest] ||
			'target class ' + rest;
	case 'field': {
		const map = {
			multihit: 'multihit', multiaccuracy: 'multihit: per-hit accuracy (multiaccuracy)', heal: 'heal fraction (heal)',
			weather: 'weather-setting move (weather)', terrain: 'terrain-setting move (terrain)', ohko: 'OHKO (ohko)',
			damage: 'fixed damage (damage)', forceSwitch: 'phazing (forceSwitch)', selfdestruct: 'user faints (selfdestruct)',
			breaksProtect: 'breaksProtect', ignoreDefensive: 'ignoreDefensive/ignoreEvasion as data (today only the DARKEST_LARIAT special)',
			ignoreEvasion: 'ignoreDefensive/ignoreEvasion as data (today only the DARKEST_LARIAT special)',
			overrideOffensiveStat: 'stat-source override (Body Press, Foul Play, Psyshock)',
			overrideOffensivePokemon: 'stat-source override (Body Press, Foul Play, Psyshock)',
			overrideDefensiveStat: 'stat-source override (Body Press, Foul Play, Psyshock)',
			thawsTarget: 'thawsTarget', willCrit: 'always crits (willCrit)', secondaries: 'several secondaries (secondaries)',
			tracksTarget: 'ignores redirection (tracksTarget)', smartTarget: 'smartTarget (Dragon Darts)',
			selfBoost: 'self stat change after the whole move (selfBoost)', tags: 'bookkeeping field tags (ignore)',
			ignoreImmunity: 'ignoreImmunity field (Thunder Wave: Ground immune)', slotCondition: 'slot condition',
			sleepUsable: 'sleepUsable', callsMove: 'callsMove', hasCrashDamage: 'crash damage',
			mindBlownRecoil: 'HP cost (mindBlownRecoil)',
		};
		return map[rest] || 'field ' + rest;
	}
	case 'flag': {
		if (rest === 'recharge') return null; // comes with mustrecharge
		if (rest === 'powder') return 'flag powder: Grass/Overcoat immunity (needs a bit; the flags byte is full)';
		if (rest === 'cantusetwice') return 'flag cantusetwice: not twice in a row (needs a bit; the flags byte is full)';
		const readers = (CONSUMERS[rest] || []).filter(c => c !== 'move:' + id);
		if (!readers.length) return `flag ${rest}: nothing in the format reads it (add to IGNORED_FLAGS)`;
		const names = readers.map(c => (c.startsWith('core') ? c.replace(/^core:?\s*/, '') || 'core' : c.split(':')[1]));
		return `flag ${rest}: read by ${names.join(', ')} (needs a bit; the flags byte is full)`;
	}
	case 'secondary.self':
		return 'self-boost secondary (gen_closure.py would encode it as a target boost today)';
	case 'secondary.status':
		return rest === 'psn' ? 'poison secondary (Team C step 6 poison; gen_closure.py maps secondary statuses with the closure STATUS)' : 'toxic (tox) status';
	case 'secondary.volatile':
		return 'secondary volatile ' + rest;
	case 'boosts':
		if (rest === 'more-than-one-vector') return 'two boost vectors on one move';
		return 'stat change on the target of a status move';
	case 'self.volatileStatus':
		if (rest === 'mustrecharge') return 'recharge turn (mustrecharge)';
		if (rest === 'lockedmove') return 'rampage lock (lockedmove)';
		return 'self volatile ' + rest;
	case 'status':
		return rest === 'tox' ? 'toxic (tox) status' : 'primary status ' + rest;
	case 'volatileStatus':
		if (rest === 'confusion') return 'primary confusion (volatileStatus)';
		if (rest === 'partiallytrapped') return 'partial trapping (partiallytrapped, residual 1/8)';
		return 'primary volatile ' + rest;
	case 'sideCondition':
		return 'side condition ' + rest;
	case 'pseudoWeather':
		return 'pseudo-weather ' + rest;
	case 'selfSwitch':
		return 'selfSwitch variant ' + rest.split('(')[0] + ' (gen_closure.py would encode a plain switch)';
	case 'pp':
		return 'PP rule';
	case 'callback':
	case 'condition':
	case 'secondary.onHit': // the callback is the family's or bespoke code
	case 'self.onHit':
	case 'secondary': // secondary: {} only marks Sheer Force (Ceaseless Edge, Stone Axe)
		return null;
	default:
		return issue;
	}
}

// Engine checks beyond the row: poison, and the damaging pivot attribution.
function engineExtras(id, d) {
	const out = [];
	if (d.status === 'psn') out.push('poison status (Team C step 6)');
	if (d.selfSwitch === true && d.category !== 'Status' && id !== 'flipturn') {
		out.push('damaging pivot names its move (the switch event hard-codes Flip Turn, turn.c:2168)');
	}
	return out;
}

// ------------------------------------------------------------------- moves
function classifyMoves(consumers) {
	const fam = {};
	for (const [fid, f] of Object.entries(F.MOVE_FAMILIES)) for (const m of f.members) fam[m] = fid;
	const size = {};
	for (const [s, ids] of Object.entries(F.MOVE_SIZE)) for (const id of ids) size[id] = s;
	const live = L.live(dex.moves.all());
	const entries = live.map(m => [m.id, dex.data.Moves[m.id]]);
	const exact = clusterIds(entries, L.signature);
	const out = {};
	const IGN = new Set(['allyanim', 'distance', 'nosketch', 'metronome', 'mirror']);
	for (const m of live) {
		const id = m.id;
		const d = dex.data.Moves[id];
		const r = MC.check(id);
		const issues = r.gen.concat(r.engine.map(e => 'engine:' + e));
		const exts = new Set();
		for (const is of issues) {
			const e = extensionOf(is, d, id);
			if (e) exts.add(e);
		}
		for (const e of engineExtras(id, d)) exts.add(e);
		if (exts.size === 0 && issues.includes('engine:status-move-shape')) exts.add('status-move path');
		// For a move with callbacks, the conditions it owns and the data its
		// own callbacks read are part of that code, not a generic extension.
		if (r.callbacks.length) {
			const own = /^(primary volatile|side condition|pseudo-weather|secondary volatile|self volatile|slot condition|callsMove|sleepUsable|crash damage|HP cost|status-move path)/;
			for (const e of [...exts]) if (own.test(e)) exts.delete(e);
		}
		// flags the generator ignores today but a live entry reads
		const latent = Object.keys(d.flags || {}).filter(f => !['contact', 'protect', 'charge', 'defrost'].includes(f) &&
			!IGN.has(f) && (consumers[f] || []).some(c => c !== 'move:' + id)).sort();
		const rec = {
			name: d.name, class: null, family: null, reason: '',
			callbacks: r.callbacks, extensions: [...exts].sort(), latent_flags: latent,
			implemented: r.implemented, in_extended_tables: r.tabled, special: r.special,
			auto_cluster: exact[id] || null, code_chars: codeChars(d),
		};
		if (!r.callbacks.length) {
			if (!exts.size) {
				rec.class = 'A';
				rec.reason = 'pure data; gen_closure.py encodes every field and turn.c runs it';
			} else {
				rec.class = 'B';
				rec.reason = 'pure data, needs: ' + rec.extensions.join('; ');
			}
		} else if (fam[id]) {
			const f = F.MOVE_FAMILIES[fam[id]];
			rec.class = 'C';
			rec.family = fam[id];
			rec.family_strength = f.strength;
			rec.reason = `${f.group}: ${f.rule}` + (rec.extensions.length ? '; also needs: ' + rec.extensions.join('; ') : '');
		} else {
			rec.class = 'D';
			rec.size = size[id] || 'S';
			rec.reason = 'bespoke callbacks (' + r.callbacks.join(', ') + ')' +
				(rec.extensions.length ? '; also needs: ' + rec.extensions.join('; ') : '');
		}
		if (r.special !== 'NONE') rec.reason += `; named handler DFI_SPECIAL_${r.special}` + (r.implemented ? '' : ' (not run yet)');
		out[id] = rec;
	}
	// sanity: every curated member is live and classified C
	for (const [fid, f] of Object.entries(F.MOVE_FAMILIES)) {
		for (const mm of f.members) {
			if (!out[mm]) throw new Error(`family ${fid}: ${mm} is not a live move`);
			if (out[mm].class !== 'C') throw new Error(`family ${fid}: ${mm} has no callbacks (class ${out[mm].class})`);
		}
	}
	return out;
}

// ------------------------------------------------------ abilities and items
const ABILITY_MANIFEST = new Set(['drizzle', 'grassysurge', 'intimidate', 'stamina', 'competitive', 'flashfire',
	'lightningrod', 'goodasgold', 'armortail', 'prankster', 'blaze', 'drought', 'contrary', 'noguard', 'toughclaws',
	'emergencyexit', 'defiant', 'adaptability', 'aerilate']);
const ABILITY_TABLED = new Set(['unburden', 'psychicsurge']);
const ITEM_MANIFEST = new Set(['leftovers', 'sitrusberry', 'grassyseed', 'lifeorb', 'mysticwater', 'lightclay',
	'miracleseed', 'staraptite', 'raichunitey', 'golisopite', 'charizarditey', 'salamencite', 'rockyhelmet',
	'chopleberry']);
const ITEM_TABLED = new Set(['whiteherb', 'choicescarf']);

function classifyEffects(kind, refs) {
	const isItem = kind === 'items';
	const table = isItem ? dex.data.Items : dex.data.Abilities;
	const live = L.live(isItem ? dex.items.all() : dex.abilities.all());
	const FAM = isItem ? F.ITEM_FAMILIES : F.ABILITY_FAMILIES;
	const CORE = isItem ? F.ITEM_CORE : F.ABILITY_CORE;
	const SIZE = isItem ? F.ITEM_SIZE : F.ABILITY_SIZE;
	const manifest = isItem ? ITEM_MANIFEST : ABILITY_MANIFEST;
	const tabled = isItem ? ITEM_TABLED : ABILITY_TABLED;
	const fam = {};
	for (const [fid, f] of Object.entries(FAM)) for (const m of f.members || []) fam[m] = fid;
	const size = {};
	for (const [s, ids] of Object.entries(SIZE)) for (const id of ids) size[id] = s;
	const entries = live.map(x => [x.id, table[x.id]]);
	const exact = clusterIds(entries, L.signature);
	const loose = clusterIds(entries, L.looseSignature);
	const out = {};
	for (const x of live) {
		const id = x.id;
		const d = table[id];
		const hs = L.handlers(d).map(h => h[0]);
		const rec = {
			name: d.name, class: null, family: null, reason: '', callbacks: hs,
			implemented: manifest.has(id), in_extended_tables: manifest.has(id) || tabled.has(id),
			auto_cluster: exact[id] || null, loose_cluster: loose[id] || null, code_chars: codeChars(d),
			core_refs: refs[id] ? [...refs[id]].sort() : [],
		};
		const fid = isItem && d.megaStone ? 'mega_stone' : fam[id];
		if (fid) {
			const f = FAM[fid];
			rec.family = fid;
			rec.family_strength = f.strength;
			rec.class = fid === 'mega_stone' ? 'A' : 'C';
			rec.reason = `${f.group}: ${f.rule}`;
			if (fid === 'mega_stone') {
				const forme = Object.values(d.megaStone).join(', ');
				rec.reason = `data only for the existing Mega Evolution (stone -> ${forme}); onTakeItem matters once item-removal moves exist`;
			}
		} else if (!hs.length) {
			rec.class = CORE[id] === 'no battle effect' ? 'A' : 'D';
			rec.size = rec.class === 'D' ? (size[id] || 'S') : undefined;
			rec.reason = CORE[id] ? 'no handler: ' + CORE[id] : 'no handler and no known effect';
			rec.core_hook = rec.class === 'D';
		} else {
			rec.class = 'D';
			rec.size = size[id] || 'S';
			rec.reason = 'bespoke handlers (' + hs.join(', ') + ')';
		}
		if (CORE[id] && hs.length) rec.reason += '; also core: ' + CORE[id];
		if (rec.core_refs.length && !rec.core_hook) rec.reason += '; referenced in the simulator core';
		out[id] = rec;
	}
	for (const [fid, f] of Object.entries(FAM)) {
		for (const mm of f.members || []) if (!out[mm]) throw new Error(`${kind} family ${fid}: ${mm} is not live`);
	}
	return out;
}

// -------------------------------------------------------------------- main
function main() {
	const consumers = flagConsumers();
	CONSUMERS = consumers;
	const refs = coreRefs();
	const moves = classifyMoves(consumers);
	const abilities = classifyEffects('abilities', refs);
	const items = classifyEffects('items', refs);
	const skipped = {moves: {}, abilities: {}, items: {}};
	// The 17 Hidden Power variants share the id hiddenpower; key them by name.
	const toID = s => s.toLowerCase().replace(/[^a-z0-9]/g, '');
	for (const m of dex.moves.all()) if (m.isNonstandard) skipped.moves[toID(m.name)] = m.isNonstandard;
	for (const a of dex.abilities.all()) if (a.isNonstandard) skipped.abilities[a.id] = a.isNonstandard;
	for (const i of dex.items.all()) if (i.isNonstandard) skipped.items[i.id] = i.isNonstandard;
	const count = (o, k) => Object.values(o).reduce((a, r) => ((a[r[k]] = (a[r[k]] || 0) + 1), a), {});
	const doc = {
		meta: {
			format: L.FORMAT, mod: 'champions', showdown_pin: 'b2cb775b0616115b775534eaeff50300e1fc81fc',
			duoforge_head: 'f756c8e (chris/m5-team-c-step5-items)',
			scope: 'every entry of Dex.forFormat(format) with isNonstandard unset; legality (species, bans) is not applied',
			classes: {
				A: 'pure data that gen_closure.py (ext mode) and turn.c already handle (still needs a manifest flag and evidence); for items: data for an existing generic mechanism',
				B: 'pure data (no callbacks) that needs generic extensions, named in `extensions`',
				C: 'member of a family: one C rule for all members (family_strength param) or one hook structure with a small per-member effect (shape)',
				D: 'bespoke; size S/M/L is a judgement (S: one predicate in an existing hook, M: new volatile/condition/hook, L: cross-cutting)',
			},
			fields: 'callbacks: handler paths found on the entry (on*, *Callback, and inside condition/secondary/self); auto_cluster: id and size of the cluster of identical normalised handlers (literals stripped); loose_cluster: same with protocol messages stripped; code_chars: size of the normalised handlers; latent_flags: move flags the generator ignores today that a live entry reads',
			counts: {moves: count(moves, 'class'), abilities: count(abilities, 'class'), items: count(items, 'class')},
			flag_consumers: consumers,
		},
		moves, abilities, items, skipped_nonstandard: skipped,
	};
	fs.writeFileSync(path.join(__dirname, 'classification.json'), JSON.stringify(doc, null, 1));
	console.log(JSON.stringify(doc.meta.counts));
}

main();
