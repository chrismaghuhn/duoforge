// Which random calls does Encore's queue replacement make? Patches PRNG.sample
// and PRNG.random of the pinned Showdown to print their stacks while
// BattleQueue.changeAction is running, then records the `encore` scenario of
// tg_probe_reference.js. Read-only research tooling for
// docs/research/expansion/team-gaps.md (finding F5 and the Encore entry).
//
// Expected output, from the pinned checkout: one `SAMPLE in changeAction` with
// two items (side.randomFoe, called from getRandomTarget, called from
// resolveAction) and no `RANDOM in insertChoice`: the draw that tools/reference/
// ps_trace.js records as INSERT_TIE/queue is a random-target draw, not an
// insertion tie.
'use strict';
const path = require('path');

const PS = process.env.DUOFORGE_PS_REFERENCE_DIR || 'C:/Dev/src/pokemon-showdown';
const {PRNG} = require(PS + '/dist/sim/prng');

const frames = n => new Error().stack.split('\n').slice(2, 2 + n).map(s => s.trim().split(' ')[1]).join(' < ');
const sample = PRNG.prototype.sample;
PRNG.prototype.sample = function (items) {
	const st = frames(8);
	if (st.includes('changeAction')) console.log(`SAMPLE in changeAction, ${items.length} items | ${st}`);
	return sample.call(this, items);
};
const random = PRNG.prototype.random;
PRNG.prototype.random = function (a, b) {
	const st = frames(6);
	if (st.includes('insertChoice') && !st.includes('sample')) console.log(`RANDOM in insertChoice (a tie): ${a}, ${b} | ${st}`);
	return random.call(this, a, b);
};
process.argv.push('encore');
require(path.join(__dirname, 'tg_probe_reference.js'));
