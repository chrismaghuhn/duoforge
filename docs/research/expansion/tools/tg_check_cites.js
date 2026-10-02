// Checks every structured citation in data/team_gaps.json: the file exists at
// the stated place, the line exists and contains the stated text. Files with the
// prefix `ps:` are read from the pinned Showdown checkout; all others from the
// DuoForge commit named by --ref (default HEAD). Also recomputes the chain
// order claim of the Expert Belt entry (modifiers 4915, 2048 and 2732 chain to
// 1639 in every order with Showdown's chainModify rounding) and checks that
// every `file.ext:N` or `file.ext N-M` mention in the texts names an existing
// line. Read-only research tooling; exits 1 on any failure.
//
// usage: node tg_check_cites.js [--ref <git ref>]
'use strict';
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');

const PS = process.env.DUOFORGE_PS_REFERENCE_DIR || 'C:/Dev/src/pokemon-showdown';
const ref = process.argv.includes('--ref') ? process.argv[process.argv.indexOf('--ref') + 1] : 'HEAD';
const json = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'data', 'team_gaps.json'), 'utf8'));

const cache = new Map();
function lines(file) {
	if (cache.has(file)) return cache.get(file);
	let text = null;
	try {
		if (file.startsWith('ps:')) text = fs.readFileSync(path.join(PS, file.slice(3)), 'utf8');
		else text = execFileSync('git', ['show', `${ref}:${file}`], {encoding: 'utf8', maxBuffer: 64 << 20, stdio: ['ignore', 'pipe', 'ignore']});
	} catch (e) { text = null; }
	const l = text === null ? null : text.split(/\r?\n/);
	cache.set(file, l);
	return l;
}

let bad = 0;
let n = 0;
for (const g of json.gaps) {
	for (const c of g.cites) {
		n++;
		const l = lines(c.file);
		if (!l) { console.log(`MISSING FILE  ${g.id}: ${c.file}`); bad++; continue; }
		const line = l[c.line - 1];
		if (line === undefined) { console.log(`NO LINE       ${g.id}: ${c.file}:${c.line} (file has ${l.length})`); bad++; continue; }
		if (!line.includes(c.contains)) { console.log(`MISMATCH      ${g.id}: ${c.file}:${c.line} lacks "${c.contains}" -> ${line.trim().slice(0, 100)}`); bad++; }
	}
}
console.log(`${n} structured citations checked, ${bad} failed`);

// mentions in the free texts: `turn.c:1234`, `turn.c:1234-1300`, `turn.c 1234-1300`
const KNOWN = {
	'turn.c': 'src/combat/turn.c', 'request.c': 'src/state/request.c', 'closure_member.c': 'src/state/closure_member.c',
	'gen_closure.py': 'tools/datagen/gen_closure.py', 'trace_to_c.py': 'tools/reference/trace_to_c.py', 'ps_trace.js': 'tools/reference/ps_trace.js',
	'battle_internal.h': 'src/state/battle_internal.h', 'state_codec.h': 'src/codec/state_codec.h', 'duoforge.h': 'include/duoforge/duoforge.h',
};
const strings = [];
(function walk(v) { if (typeof v === 'string') strings.push(v); else if (Array.isArray(v)) v.forEach(walk); else if (v && typeof v === 'object') Object.values(v).forEach(walk); })(
	[json.gaps.map(g => [g.pinned, g.draws, g.protocol, g.duoforge, g.state, g.interactions, g.evidence]), json.findings, json.regions, json.soft_shared_resources, json.open_questions]);
let mentions = 0;
let badMentions = 0;
const re = /\b(turn\.c|request\.c|closure_member\.c|gen_closure\.py|trace_to_c\.py|ps_trace\.js|battle_internal\.h|state_codec\.h|duoforge\.h)[: ](\d+)(?:-(\d+))?/g;
for (const s of strings) {
	for (const m of s.matchAll(re)) {
		mentions++;
		const l = lines(KNOWN[m[1]]);
		const last = Number(m[3] || m[2]);
		if (!l || last > l.length || Number(m[2]) < 1) { console.log(`BAD MENTION   ${m[0]} (file has ${l ? l.length : '?'} lines)`); badMentions++; }
	}
}
console.log(`${mentions} file:line mentions in the texts checked for existing lines, ${badMentions} failed`);

// chainModify rounding of the pinned battle.ts: ((prev * next + 2048) >> 12)
const chain = (prev, next) => (prev * next + 2048) >> 12;
const orders = [[4915, 2048, 2732], [4915, 2732, 2048], [2048, 4915, 2732], [2048, 2732, 4915], [2732, 4915, 2048], [2732, 2048, 4915]];
const results = orders.map(o => o.reduce((a, m) => chain(a, m), 4096));
const same = results.every(r => r === results[0]);
console.log(`chain order check: ${results.join(' ')} -> ${same ? 'identical' : 'DIFFERENT'}`);
const expected = Number(process.env.EXPECT_CHAIN || results[0]);
if (!same) bad++;
console.log(`final chained modifier: ${results[0]}${results[0] === expected ? '' : ' (unexpected)'}`);

process.exit(bad || badMentions ? 1 : 0);
