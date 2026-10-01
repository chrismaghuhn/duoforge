// Shared helpers for the DuoForge dex inventory (read-only analysis of the
// pinned Showdown checkout; writes nothing outside this directory).
'use strict';
const {Dex} = require('C:/Dev/src/pokemon-showdown/dist/sim');

const FORMAT = 'gen9championsvgc2026regmc';
const dex = Dex.forFormat(Dex.formats.get(FORMAT));

// Own, defined keys of a raw data entry (a mod's `key: undefined` removes it).
function ownKeys(o) {
	return Object.keys(o).filter(k => o[k] !== undefined);
}

// Normalise a handler: drop its name, string and number literals, stat keys
// and whitespace, so handlers that differ only in such literals compare equal.
function norm(v) {
	if (typeof v !== 'function') return 'CONST:' + JSON.stringify(normConst(v));
	let s = v.toString();
	s = s.replace(/^\s*(async\s+)?[A-Za-z_$][\w$]*\s*\(/, 'fn(');
	s = s.replace(/^\s*function\s*[\w$]*\s*\(/, 'fn(');
	s = s.replace(/`(?:\\[\s\S]|[^`\\])*`/g, 'S');
	s = s.replace(/'(?:\\.|[^'\\\n])*'/g, 'S');
	s = s.replace(/"(?:\\.|[^"\\\n])*"/g, 'S');
	s = s.replace(/\b\d+(\.\d+)?\b/g, 'N');
	s = s.replace(/\b(atk|def|spa|spd|spe|accuracy|evasion)\b(?=\s*:)/g, 'STAT');
	s = s.replace(/\.(atk|def|spa|spd|spe|accuracy|evasion)\b/g, '.STAT');
	s = s.replace(/\/\/[^\n]*\n/g, '\n');
	s = s.replace(/\/\*[\s\S]*?\*\//g, '');
	s = s.replace(/\s+/g, ' ').trim();
	return s;
}
function normConst(v) {
	if (typeof v === 'number') return 'N';
	if (typeof v === 'string') return 'S';
	return v;
}

// A looser form: also drops protocol-only statements (add, debug, hint,
// attrLastMove), optional chaining and `x && ` guards on move/effect, so
// handlers that differ only in their messages compare equal.
function looseNorm(v) {
	let s = norm(v);
	if (s.startsWith('CONST:')) return s;
	s = s.replace(/this\.(add|debug|hint|attrLastMove|addMove)\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\);?/g, '');
	s = s.replace(/\?\./g, '.');
	s = s.replace(/\b(move|effect|target|source|pokemon) && /g, '');
	s = s.replace(/\s+/g, ' ').replace(/\{ \}/g, '{}').trim();
	return s;
}

// Every handler of an effect object: [path, value]. `on*` keys (functions or
// constants such as onCriticalHit: false), *Callback keys, and the handlers
// of nested effect objects (condition, secondary, secondaries, self).
// onModifyPriority and onFractionalPriority are events, not orderings.
const PRIO_RE_RAW = /^on\w+(Priority|Order|SubOrder)$/;
const PRIO_RE = {test: k => PRIO_RE_RAW.test(k) && k !== 'onModifyPriority' && k !== 'onFractionalPriority'};
function handlers(o, prefix = '') {
	const out = [];
	if (!o || typeof o !== 'object') return out;
	for (const k of ownKeys(o)) {
		const v = o[k];
		const p = prefix + k;
		if (typeof v === 'function') {
			out.push([p, v]);
		} else if (/^on[A-Z]/.test(k) && !PRIO_RE.test(k)) {
			out.push([p, v]); // constant handler
		} else if (k === 'condition' || k === 'self' || k === 'secondary' || k === 'fling') {
			if (v && typeof v === 'object') out.push(...handlers(v, p + '.'));
		} else if (k === 'secondaries' && Array.isArray(v)) {
			v.forEach((s, i) => out.push(...handlers(s, `${p}[${i}].`)));
		}
	}
	return out;
}
// Priority/order parameters of handlers, as part of the shape.
function prioKeys(o, prefix = '') {
	const out = [];
	if (!o || typeof o !== 'object') return out;
	for (const k of ownKeys(o)) {
		if (PRIO_RE.test(k)) out.push(prefix + k);
		else if (k === 'condition' && o[k] && typeof o[k] === 'object') out.push(...prioKeys(o[k], 'condition.'));
	}
	return out.sort();
}

function signature(o) {
	const hs = handlers(o).map(([p, v]) => p + '=' + norm(v)).sort();
	return hs.concat(prioKeys(o)).join(' || ');
}
function looseSignature(o) {
	const hs = handlers(o).map(([p, v]) => p + '=' + looseNorm(v)).sort();
	return hs.join(' || ');
}
function shape(o) {
	return handlers(o).map(([p]) => p).concat(prioKeys(o)).sort().join(',');
}

const live = arr => arr.filter(x => !x.isNonstandard);
module.exports = {dex, FORMAT, ownKeys, norm, looseNorm, handlers, prioKeys, signature, looseSignature, shape, live};
