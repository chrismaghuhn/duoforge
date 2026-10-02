#!/usr/bin/env node
// Tests of ps_play.js, the random play of the differential loop.
//
// usage: node tools/reference/test_ps_play.js [<pinned checkout>]
//
// Without a checkout the policy generator and the way a choice is drawn,
// judged and enumerated run against stand-in sides. With one, real battles of
// the committed teams are played: the same policy gives the same choices, the
// choices of every battle replay in ps_trace.run with the same length and
// result, a cap stops a battle, and the request is refused when it is not
// exactly the documented one. CTest runs it as duoforge.reference.play_policy
// (label reference).
'use strict';

const fs = require('fs');
const path = require('path');
const {play, PolicyRng, chooseFor, enumerate, draw, domainHash, domainSampled, domainSample, MAX_REJECTIONS} =
    require('./ps_play.js');
const {run} = require('./ps_trace.js');

const REPO = path.resolve(__dirname, '..', '..');
const failures = [];

function check(name, cond, detail) {
    if (!cond) failures.push(detail ? `${name}: ${detail}` : name);
}

function same(name, have, want) {
    check(name, JSON.stringify(have) === JSON.stringify(want), `${JSON.stringify(have)} against ${JSON.stringify(want)}`);
}

function throwsWith(name, fn, part) {
    try {
        fn();
    } catch (e) {
        check(name, e.message.includes(part), `the error is "${e.message}", it should contain "${part}"`);
        return;
    }
    check(name, false, 'it did not throw');
}

// ---------------------------------------------------------------- the generator

// Known answers, from an independent Python implementation of the algorithm
// documented in ps_play.js (splitmix32 into sfc32, 12 outputs discarded).
const UINT32 = {
    0: [548183886, 1097162541, 2219297441, 1664216021, 3479288465, 3033988455],
    1: [1130556604, 2591592147, 3014952990, 960850752, 2734082507, 3058966613],
    42: [3825871779, 1851418855, 1383259262, 890322987, 2796912455, 4258306155],
    123456789: [3802896128, 80434582, 3894707069, 3900334430, 1534057038, 1158050898],
    4294967295: [2246433216, 2156899173, 2040853526, 3823104220, 1358629326, 3404600419],
};

function generator() {
    for (const [seed, want] of Object.entries(UINT32)) {
        const r = new PolicyRng(Number(seed));
        same(`uint32 of seed ${seed}`, Array.from({length: want.length}, () => r.uint32()), want);
    }
    let r = new PolicyRng(7);
    same('below(6) of seed 7', Array.from({length: 12}, () => r.below(6)), [1, 1, 5, 1, 4, 1, 1, 5, 4, 4, 3, 5]);
    r = new PolicyRng(11);
    same('shuffle of seed 11', r.shuffle([0, 1, 2, 3, 4, 5]).slice().sort(), [0, 1, 2, 3, 4, 5]);

    // below(n): every value, none out of range, n = 1 and n = 2^32.
    r = new PolicyRng(3);
    const seen = new Set();
    for (let i = 0; i < 600; i++) seen.add(r.below(6));
    same('below(6) reaches every value', [...seen].sort(), [0, 1, 2, 3, 4, 5]);
    check('below(1)', Array.from({length: 20}, () => r.below(1)).every((x) => x === 0));
    check('below(2^32) is a uint32', (() => { const x = r.below(4294967296); return x >= 0 && x < 4294967296; })());

    // The rejection: an output at or above floor(2^32 / 3) * 3 is not used.
    r = new PolicyRng(5);
    const feed = [4294967295, 4294967295, 7];
    r.uint32 = () => feed.shift();
    check('below(3) skips an output above the limit', r.below(3) === 1 && feed.length === 0);

    r = new PolicyRng(9);
    check('chance(0) never', Array.from({length: 200}, () => r.chance(0)).every((x) => !x));
    check('chance(1) always', Array.from({length: 200}, () => r.chance(1)).every((x) => x));
    const hits = Array.from({length: 4000}, () => r.chance(0.25)).filter(Boolean).length;
    check('chance(0.25) is about a quarter', hits > 800 && hits < 1200, `${hits} of 4000`);
    const a = new PolicyRng(77);
    const b = new PolicyRng(77);
    same('the same seed gives the same stream', [a.uint32(), a.uint32()], [b.uint32(), b.uint32()]);
    check('another seed another stream', new PolicyRng(78).uint32() !== new PolicyRng(77).uint32());
}

// ---------------------------------------------------------------- stand-in sides

const TARGET_TYPES = new Set(['normal', 'any', 'adjacentAlly', 'adjacentAllyOrSelf', 'adjacentFoe']);

// battle.validTargetLoc of the pinned Showdown for two slots a side.
function validTargetLoc(loc, source, targetType) {
    if (loc === 0) return true;
    const numSlots = 2;
    const sourceLoc = -(source.position + 1);
    if (Math.abs(loc) > numSlots) return false;
    const isSelf = sourceLoc === loc;
    const isFoe = loc > 0;
    const across = -(numSlots + 1 - loc);
    const isAdjacent = loc > 0 ? Math.abs(across - sourceLoc) <= 1 : Math.abs(loc - sourceLoc) === 1;
    switch (targetType) {
        case 'normal': return isAdjacent;
        case 'adjacentAlly': return isAdjacent && !isFoe;
        case 'adjacentAllyOrSelf': return isAdjacent && !isFoe || isSelf;
        case 'adjacentFoe': return isAdjacent && isFoe;
        case 'any': return !isSelf;
    }
    return false;
}

// A side that accepts the texts for which accept(text) is true; log has every call in order.
function standIn(state, request, parts, accept) {
    const log = [];
    const side = {
        requestState: state,
        activeRequest: request,
        pokemon: parts.pokemon,
        active: parts.pokemon.slice(0, 2),
        battle: {actions: {targetTypeChoices: (t) => TARGET_TYPES.has(t)}, validTargetLoc},
        pickedTeamSize: () => 4,
        choose(text) {
            log.push(['choose', text]);
            return accept(text);
        },
        clearChoice() {
            log.push(['clear']);
        },
    };
    return {side, log};
}

function mons(fainted) {
    return Array.from({length: 6}, (_, i) => ({position: i, fainted: !!fainted[i]}));
}

const POLICY = {seed: 1, max_steps: 10, switch_weight: 0.1, mega_weight: 0.5};

function drawing() {
    // Team preview: four distinct of six, "team 3512".
    let {side} = standIn('teampreview', {teamPreview: true}, {pokemon: mons([])}, () => true);
    const rng = new PolicyRng(1);
    for (let i = 0; i < 30; i++) {
        const text = draw(side, rng, POLICY);
        const m = /^team (\d{4})$/.exec(text);
        check('team preview text', m !== null && new Set(m[1]).size === 4 && [...m[1]].every((c) => c >= '1' && c <= '6'), text);
    }

    // A replacement: two slots must switch, one reserve: either slot may get it, the other passes.
    ({side} = standIn('switch', {forceSwitch: [true, true]}, {pokemon: mons([true, true, false, true, true, true])}, () => true));
    const seen = new Set();
    for (let seed = 0; seed < 40; seed++) seen.add(draw(side, new PolicyRng(seed), POLICY));
    same('one reserve for two slots', [...seen].sort(), ['pass, switch 3', 'switch 3, pass']);
    // One slot must switch: the other passes; a standing reserve is chosen, never a fainted one.
    ({side} = standIn('switch', {forceSwitch: [false, true]}, {pokemon: mons([false, true, false, true, false, true])}, () => true));
    same('only the flagged slot switches', draw(side, new PolicyRng(2), POLICY).replace(/\d$/, 'N'), 'pass, switch N');
    for (let seed = 0; seed < 20; seed++) {
        const n = /switch (\d)$/.exec(draw(side, new PolicyRng(seed), POLICY));
        check('a standing reserve', n !== null && ['3', '5'].includes(n[1]), n && n[1]);
    }

    // A move request.
    const req = (extra) => ({moves: [{move: 'Tackle', id: 'tackle', target: 'normal', disabled: false},
        {move: 'Protect', id: 'protect', target: 'self', disabled: false},
        {move: 'Fake Out', id: 'fakeout', target: 'normal', disabled: true},
        {move: 'Helping Hand', id: 'helpinghand', target: 'adjacentAlly', disabled: false}], ...extra});
    ({side} = standIn('move', {active: [req({canMegaEvo: true}), req({canMegaEvo: true})]}, {pokemon: mons([])}, () => true));
    const all = new Set();
    for (let seed = 0; seed < 300; seed++) {
        const text = draw(side, new PolicyRng(seed), {...POLICY, mega_weight: 1, switch_weight: 0});
        all.add(text);
        const parts = text.split(', ');
        check('one text per slot', parts.length === 2, text);
        check('mega at most once', (text.match(/mega/g) || []).length === 1, text); // weight 1: the first slot takes it
        for (const part of parts) {
            check('a move that is enabled', /^move [124]/.test(part), part); // move 3 is disabled
            if (/^move 1/.test(part)) check('a target for a move that takes one', /^move 1 (-1|-2|1|2)( mega)?$/.test(part), part);
            if (/^move 2/.test(part)) check('no target for a self move', /^move 2( mega)?$/.test(part), part);
        }
    }
    check('both foes and the ally are targeted', [...all].some((t) => / 1[ ,]/.test(t)) && [...all].some((t) => / 2[ ,]/.test(t)) &&
        [...all].some((t) => / -\d/.test(t)));
    // The ally is the other position; nobody targets self with a normal move.
    check('a slot never targets itself', [...all].every((t) => {
        const [a, b] = t.split(', ');
        return !/^move 1 -1/.test(a) && !/^move 1 -2/.test(b);
    }), 'slot a is -1 and slot b -2');

    // switch_weight 1: both slots want to switch; two reserves, then none left; a trapped slot stays.
    ({side} = standIn('move', {active: [req({}), req({})]}, {pokemon: mons([])}, () => true));
    const text = draw(side, new PolicyRng(4), {...POLICY, switch_weight: 1});
    check('both slots switch to different reserves', /^switch [3-6], switch [3-6]$/.test(text) && text.split(', ')[0] !== text.split(', ')[1], text);
    ({side} = standIn('move', {active: [req({trapped: true}), req({})]}, {pokemon: mons([])}, () => true));
    check('a trapped Pokemon does not switch', /^move /.test(draw(side, new PolicyRng(4), {...POLICY, switch_weight: 1}).split(', ')[0]));
    ({side} = standIn('move', {active: [req({}), req({})]}, {pokemon: mons([false, false, true, true, true, true])}, () => true));
    check('no reserve, no switch', draw(side, new PolicyRng(4), {...POLICY, switch_weight: 1}).split(', ').every((p) => p.startsWith('move ')));

    // A fainted slot passes; a locked move is "move 1" without a target.
    ({side} = standIn('move', {active: [req({}), {moves: [{move: 'Electro Shot', id: 'electroshot'}], trapped: true}]},
        {pokemon: mons([true, false, false, false, false, false])}, () => true));
    const t = draw(side, new PolicyRng(6), {...POLICY, switch_weight: 0, mega_weight: 1});
    check('fainted slot passes and a locked move has no target', t.startsWith('pass, move 1') && t === 'pass, move 1', t);
}

function judging() {
    // Rejections: a new text is drawn after each, the choice is cleared after every trial.
    let calls = 0;
    let {side, log} = standIn('teampreview', {teamPreview: true}, {pokemon: mons([])}, () => ++calls > 3);
    const text = chooseFor(side, new PolicyRng(1), POLICY);
    check('the fourth text is the one accepted', log.filter((e) => e[0] === 'choose').length === 4 && log.filter((e) => e[0] === 'choose')[3][1] === text);
    check('every trial is cleared', log.length === 8 && log.every((e, i) => e[0] === (i % 2 ? 'clear' : 'choose')));

    // 200 rejections, then every option is tried in a fixed order and one that is accepted is taken. Nothing is
    // accepted among the first 200 trials (the random texts), whatever they are.
    const wanted = 'team 6543';
    let trials = 0;
    ({side, log} = standIn('teampreview', {teamPreview: true}, {pokemon: mons([])}, (t) => ++trials > MAX_REJECTIONS && t === wanted));
    check('only the one accepted text is found', chooseFor(side, new PolicyRng(2), POLICY) === wanted);
    const chooses = log.filter((e) => e[0] === 'choose').map((e) => e[1]);
    check('200 random texts, then the 360 options', chooses.length === MAX_REJECTIONS + 360, String(chooses.length));
    same('the options come in lexicographic order', chooses.slice(MAX_REJECTIONS, MAX_REJECTIONS + 3), ['team 1234', 'team 1235', 'team 1236']);
    check('the last option', chooses[chooses.length - 1] === 'team 6543');

    // Nothing accepted.
    ({side} = standIn('teampreview', {teamPreview: true}, {pokemon: mons([])}, () => false));
    throwsWith('no accepted choice', () => chooseFor(side, new PolicyRng(3), POLICY), 'no accepted choice');

    // Several are accepted: the pick is the policy's, and the same for the same seed.
    ({side} = standIn('teampreview', {teamPreview: true}, {pokemon: mons([])}, (t) => t.startsWith('team 1') && !t.endsWith('6')));
    const picked = chooseFor(side, new PolicyRng(4), POLICY);
    check('one of the accepted', picked.startsWith('team 1') && !picked.endsWith('6'), picked);
    check('the same seed picks the same', chooseFor(side, new PolicyRng(4), POLICY) === picked);
}

function enumerating() {
    // A replacement of two slots with two reserves: each flagged slot a reserve or a pass, slot 0 slowest.
    let {side} = standIn('switch', {forceSwitch: [true, true]}, {pokemon: mons([true, true, false, false, true, true])}, () => true);
    same('replacements', enumerate(side), ['pass, pass', 'pass, switch 3', 'pass, switch 4', 'switch 3, pass', 'switch 3, switch 3',
        'switch 3, switch 4', 'switch 4, pass', 'switch 4, switch 3', 'switch 4, switch 4']);
    ({side} = standIn('switch', {forceSwitch: [false, true]}, {pokemon: mons([false, true, false, true, true, true])}, () => true));
    same('one slot flagged', enumerate(side), ['pass, pass', 'pass, switch 3']);

    // A move request: pass, switches by position, moves by index with targets 1, 2, -1, -2 (slot 0: the ally is -2), mega after each.
    const req = (mega) => ({moves: [{move: 'Tackle', id: 'tackle', target: 'adjacentFoe', disabled: false},
        {move: 'Protect', id: 'protect', target: 'self', disabled: false},
        {move: 'Fake Out', id: 'fakeout', target: 'normal', disabled: true}], canMegaEvo: mega});
    ({side} = standIn('move', {active: [req(true), req(false)]}, {pokemon: mons([false, false, false, true, true, true])}, () => true));
    const options = enumerate(side);
    const first = ['pass', 'switch 3', 'move 1 1', 'move 1 1 mega', 'move 1 2', 'move 1 2 mega', 'move 2', 'move 2 mega'];
    const second = ['pass', 'switch 3', 'move 1 1', 'move 1 2', 'move 2'];
    check('slot 0 options times slot 1 options', options.length === first.length * second.length, String(options.length));
    same('the first options (slot 1 varies fastest)', options.slice(0, 6), second.slice(0, 5).map((x) => `pass, ${x}`).concat(['switch 3, pass']));
    same('the last option', options[options.length - 1], 'move 2 mega, move 2');
    check('no disabled move is offered', options.every((o) => !/move 3/.test(o)));
    check('mega only for the slot that can', options.every((o) => !/, .*mega/.test(o)));

    // A fainted slot only passes.
    ({side} = standIn('move', {active: [req(false), req(false)]}, {pokemon: mons([true, false, false, false, false, false])}, () => true));
    check('a fainted slot passes', enumerate(side).every((o) => o.startsWith('pass, ')));

    // A locked move: one option and no target.
    ({side} = standIn('move', {active: [{moves: [{move: 'Electro Shot', id: 'electroshot'}], trapped: true}, req(false)]},
        {pokemon: mons([false, true, false, false, false, false])}, () => true));
    same('a locked move: move 1, no target; slot 1 is fainted', enumerate(side),
        ['pass, pass', 'switch 3, pass', 'switch 4, pass', 'switch 5, pass', 'switch 6, pass', 'move 1, pass']);
}

// ---------------------------------------------------------------- the domain of a request

// Known answers, from an independent Python implementation of the hash that ps_play.js documents.
const DOMAIN_HASH = [
    [0, 0, 0, 3341786526], [0, 0, 1, 2503378128], [1, 0, 0, 574037688], [1, 3, 1, 1098631492],
    [42, 17, 0, 3998770238], [123456789, 5, 1, 1726878130], [4294967295, 99, 1, 743359916],
    [7000, 0, 0, 197846074], [7000, 1, 1, 2249556593],
];

function domainHashes() {
    for (const [seed, step, side, want] of DOMAIN_HASH) {
        check(`domain hash of (${seed}, ${step}, ${side})`, domainHash(seed, step, side) === want, String(domainHash(seed, step, side)));
    }
    // The rate: 0 samples nothing, 1 everything, 0.25 about a quarter, and the same triple always gives the same answer.
    let quarter = 0;
    for (let seed = 0; seed < 100; seed++) {
        for (let step = 0; step < 100; step++) {
            for (const side of [0, 1]) {
                check('rate 0 samples nothing', !domainSampled(seed, step, side, 0));
                check('rate 1 samples everything', domainSampled(seed, step, side, 1));
                if (domainSampled(seed, step, side, 0.25)) quarter++;
            }
        }
    }
    check('rate 0.25 samples about a quarter of 20000 triples', quarter === 5062, String(quarter));
    check('the same triple, the same answer', [0.1, 0.5].every((r) => domainSampled(5, 6, 1, r) === domainSampled(5, 6, 1, r)));
    // Monotone in the rate: what is sampled at a rate is sampled at a higher one.
    let monotone = true;
    for (let step = 0; step < 300; step++) {
        if (domainSampled(9, step, 0, 0.2) && !domainSampled(9, step, 0, 0.6)) monotone = false;
    }
    check('a request sampled at 0.2 is sampled at 0.6', monotone);
    // Step, side and seed all count: the answers are not all one.
    const kinds = new Set([0, 1, 2, 3, 4, 5].map((step) => domainHash(3, step, 0)));
    check('another step, another hash', kinds.size === 6);
    check('another side, another hash', domainHash(3, 2, 0) !== domainHash(3, 2, 1));
    check('another seed, another hash', domainHash(3, 2, 0) !== domainHash(4, 2, 0));
}

// A side that remembers what was judged, whose request is what the test says: `mutate(request, text)` may change it
// when a text is judged, as Showdown does for an "Unavailable choice".
function sampledSide(request, accept, mutate) {
    const {side, log} = standIn('move', request, {pokemon: mons([])}, accept);
    side.pokemon.forEach((p) => {
        p.maybeTrapped = false;
        p.maybeDisabled = true;
        p.maybeLocked = true;
    });
    const judged = side.choose;
    side.choose = (text) => {
        if (mutate) mutate(side, text);
        return judged(text);
    };
    return {side, log};
}

function sampling() {
    const req = (extra) => ({moves: [{move: 'Tackle', id: 'tackle', target: 'adjacentFoe', disabled: false},
        {move: 'Protect', id: 'protect', target: 'self', disabled: false}], canMegaEvo: false, ...extra});
    // The accepted texts, in the order of enumerate(), every one judged and cleared; nothing is left changed.
    let {side, log} = sampledSide({active: [req({}), req({})]}, (t) => !/switch/.test(t) && !/pass/.test(t.split(', ')[1]));
    const before = JSON.stringify(side.activeRequest);
    const all = enumerate(side);
    const accepted = domainSample(side);
    same('the accepted texts are the enumerated ones that were accepted, in order', accepted,
        all.filter((t) => !/switch/.test(t) && !/pass/.test(t.split(', ')[1])));
    check('every option was judged once, and the choice cleared after each', log.length === 2 * all.length &&
        log.every((e, i) => e[0] === (i % 2 ? 'clear' : 'choose')) && log.filter((e) => e[0] === 'choose').every((e, i) => e[1] === all[i]));
    check('the request is as it was', JSON.stringify(side.activeRequest) === before);
    check('and so are the flags of the Pokemon', side.pokemon.every((p) => !p.maybeTrapped && p.maybeDisabled && p.maybeLocked));

    // A request that changes while it is judged (a move found to be disabled, the lock known): the sample is dropped,
    // and the request and the flags are put back, in place.
    const requestObject = {active: [req({}), req({})]};
    ({side} = sampledSide(requestObject, () => true, (s, text) => {
        if (text.startsWith('move 2')) {
            s.activeRequest.active[0].moves[1].disabled = true; // found out by the choice
            s.activeRequest.update = true; // what emitRequest adds
            s.pokemon[0].maybeLocked = false; // updateDisabledRequest
        }
    }));
    const original = JSON.stringify(requestObject);
    check('a request that changed gives no sample', domainSample(side) === null);
    check('and is put back as it was', JSON.stringify(side.activeRequest) === original && side.activeRequest === requestObject);
    check('with the flags', side.pokemon[0].maybeLocked === true && side.pokemon[0].maybeDisabled === true);
    // Only the flags changed: the same.
    ({side} = sampledSide({active: [req({}), req({})]}, () => true, (s) => { s.pokemon[1].maybeTrapped = true; }));
    check('flags that changed alone give no sample either', domainSample(side) === null && side.pokemon[1].maybeTrapped === false);
    // Team preview is a request like the others.
    ({side} = standIn('teampreview', {teamPreview: true}, {pokemon: mons([])}, (t) => t.startsWith('team 1')));
    const picks = domainSample(side);
    check('team preview: the picks that start with 1', picks.length === 60 && picks.every((t) => /^team 1\d{3}$/.test(t)), String(picks.length));
}

// ---------------------------------------------------------------- the request

function request() {
    const battle = {format: 'gen9championsvgc2026regmc', seed: 'sodium,' + '0'.repeat(63) + '1', teams: ['a', 'b']};
    const bad = [
        ['no policy', battle, undefined, 'play: policy must be an object'],
        ['a missing key', battle, {seed: 1, max_steps: 5, switch_weight: 0.1}, 'play: policy has the keys'],
        ['an extra key', battle, {...POLICY, extra: 1}, 'play: policy has the keys'],
        ['a seed above 2^32 - 1', battle, {...POLICY, seed: 4294967296}, 'play: policy.seed'],
        ['a negative seed', battle, {...POLICY, seed: -1}, 'play: policy.seed'],
        ['a seed that is not an integer', battle, {...POLICY, seed: 1.5}, 'play: policy.seed'],
        ['no steps', battle, {...POLICY, max_steps: 0}, 'play: policy.max_steps'],
        ['a weight above 1', battle, {...POLICY, switch_weight: 1.5}, 'play: policy.switch_weight'],
        ['a weight that is not a number', battle, {...POLICY, mega_weight: '0.5'}, 'play: policy.mega_weight'],
        ['a NaN weight', battle, {...POLICY, mega_weight: NaN}, 'play: policy.mega_weight'],
        ['a domain rate above 1', battle, {...POLICY, domain_rate: 1.5}, 'play: policy.domain_rate'],
        ['a negative domain rate', battle, {...POLICY, domain_rate: -0.1}, 'play: policy.domain_rate'],
        ['a domain rate that is not a number', battle, {...POLICY, domain_rate: '0.1'}, 'play: policy.domain_rate'],
        ['a NaN domain rate', battle, {...POLICY, domain_rate: NaN}, 'play: policy.domain_rate'],
        ['a domain rate of null', battle, {...POLICY, domain_rate: null}, 'play: policy.domain_rate'],
        ['no battle', undefined, POLICY, 'play: battle must be an object'],
        ['a battle with a missing key', {format: battle.format, seed: battle.seed}, POLICY, 'play: battle has the keys'],
        ['one team', {...battle, teams: ['a']}, POLICY, 'play: battle.teams'],
        ['a team that is not text', {...battle, teams: ['a', 5]}, POLICY, 'play: battle.teams'],
        ['a format that is not text', {...battle, format: 5}, POLICY, 'play: battle.format'],
    ];
    for (const [name, b, p, part] of bad) throwsWith(name, () => play('.', b, p), part);
}

// ---------------------------------------------------------------- real battles

function realBattles(checkout) {
    const read = (file) => fs.readFileSync(path.join(REPO, file), 'utf8').trim();
    const TEAMS = {A: read('tests/reference/teams/team_a.txt'), B: read('tests/reference/teams/team_b.txt'),
        C: read('docs/research/third-team/team-c.txt')};
    const FORMAT = 'gen9championsvgc2026regmc';
    const make = (pairing, n) => ({format: FORMAT, seed: 'sodium,' + n.toString(16).padStart(64, '0'),
        teams: [TEAMS[pairing[0]], TEAMS[pairing[1]]]});
    const specOf = (pairing, battle, choices) => {
        const spec = {name: 'play_policy', purpose: 'test', format: battle.format, seed: battle.seed, teams: battle.teams, choices};
        if (pairing.includes('C')) spec.data = 'team_c';
        return spec;
    };
    const pairings = ['AB', 'BA', 'AA', 'BB', 'CA', 'AC', 'CC', 'BC'];
    const seen = {pass: 0, switchInMove: 0, mega: 0, ally: 0, preview: 0};
    for (const [i, pairing] of pairings.entries()) {
        const battle = make(pairing, 100 + i);
        const policy = {seed: 7000 + i, max_steps: 300, switch_weight: 0.1, mega_weight: 0.5};
        const result = play(checkout, battle, policy);
        same(`${pairing}: the same policy plays the same battle`, play(checkout, battle, policy), result);
        check(`${pairing}: the result has the documented shape`, Object.keys(result).join() === 'choices,ended,steps,domain' &&
            result.steps === result.choices.length && result.choices.every((e) => Object.keys(e).every((k) => k === 'p1' || k === 'p2')) &&
            Object.keys(result.domain).join() === 'samples,request_changed');
        same(`${pairing}: no domain_rate, no sample`, result.domain, {samples: [], request_changed: 0});
        check(`${pairing}: team preview first, both sides`, /^team \d{4}$/.test(result.choices[0].p1) && /^team \d{4}$/.test(result.choices[0].p2));
        // The authoritative recording of the choices agrees with the play.
        const trace = JSON.parse(run(checkout, specOf(pairing, battle, result.choices), 'play_policy.json'));
        check(`${pairing}: the choices replay with the same length`, trace.steps.length === result.steps, `${trace.steps.length} against ${result.steps}`);
        check(`${pairing}: and the same end`, trace.steps[trace.steps.length - 1].state.ended === result.ended);
        check(`${pairing}: the trace holds what was chosen`, trace.steps.every((s, k) => JSON.stringify(s.input) === JSON.stringify(result.choices[k])));
        for (const entry of result.choices) {
            for (const text of Object.values(entry)) {
                if (/pass/.test(text)) seen.pass++;
                if (/mega/.test(text)) seen.mega++;
                if (/move \d -\d/.test(text)) seen.ally++;
                if (/^team/.test(text)) seen.preview++;
                if (/switch/.test(text) && /move/.test(text)) seen.switchInMove++;
            }
        }
    }
    check('over the battles: passes, mega, ally targets and switches in a move request all occur',
        seen.pass > 0 && seen.mega > 0 && seen.ally > 0 && seen.switchInMove > 0, JSON.stringify(seen));

    // Another policy seed: other choices; the same battle seed.
    const battle = make('AB', 500);
    const a = play(checkout, battle, {seed: 1, max_steps: 300, switch_weight: 0.1, mega_weight: 0.5});
    const b = play(checkout, battle, {seed: 2, max_steps: 300, switch_weight: 0.1, mega_weight: 0.5});
    check('another policy seed gives other choices', JSON.stringify(a.choices) !== JSON.stringify(b.choices));

    // The cap: the battle stops after max_steps and is not over.
    for (const cap of [1, 2, 3]) {
        const capped = play(checkout, battle, {seed: 1, max_steps: cap, switch_weight: 0.1, mega_weight: 0.5});
        same(`max_steps ${cap}`, [capped.steps, capped.ended, capped.choices.length], [cap, false, cap]);
        same(`the first ${cap} choices are those of the longer battle`, capped.choices, a.choices.slice(0, cap));
    }

    // The weights: switch_weight 0 never switches in a move request, 1 switches whenever it can.
    const none = play(checkout, battle, {seed: 3, max_steps: 300, switch_weight: 0, mega_weight: 0});
    check('switch_weight 0 and mega_weight 0: no mega, and no switch in a move request',
        none.choices.slice(1).every((e) => Object.values(e).every((t) => !/mega/.test(t) && !(/move/.test(t) && /switch/.test(t)))));
    domains(checkout, make, pairings);
}

// Real battles with their domains sampled: the samples are what Showdown accepts, and they change nothing else.
function domains(checkout, make, pairings) {
    const base = (i) => ({seed: 7000 + i, max_steps: 300, switch_weight: 0.1, mega_weight: 0.5});
    let sampled = 0;
    let withMega = 0;
    let changedTotal = 0;
    let moveRequests = 0;
    for (const [i, pairing] of pairings.entries()) {
        const battle = make(pairing, 100 + i);
        const plain = play(checkout, battle, base(i));
        const all = play(checkout, battle, {...base(i), domain_rate: 1});
        same(`${pairing}: sampling every request leaves the choices, the end and the length as they were`,
            [all.choices, all.ended, all.steps], [plain.choices, plain.ended, plain.steps]);
        // Every request has a sample (or is counted as changed), in the order of steps, p1 before p2.
        const asked = plain.choices.reduce((n, e) => n + Object.keys(e).length, 0);
        check(`${pairing}: every request is sampled or counted`, all.domain.samples.length + all.domain.request_changed === asked,
            `${all.domain.samples.length} + ${all.domain.request_changed} against ${asked}`);
        const order = all.domain.samples.map((s) => s.step * 2 + s.side);
        check(`${pairing}: the samples come in the order of step and side`, order.every((x, k) => k === 0 || order[k - 1] < x));
        for (const sample of all.domain.samples) {
            check(`${pairing}: a sample has step, side and accepted`, Object.keys(sample).join() === 'step,side,accepted' &&
                Number.isInteger(sample.step) && (sample.side === 0 || sample.side === 1) && Array.isArray(sample.accepted));
            const text = plain.choices[sample.step][sample.side === 0 ? 'p1' : 'p2'];
            check(`${pairing}: the side answered the step it is sampled at`, text !== undefined);
            check(`${pairing}: what was chosen is among the accepted (step ${sample.step} side ${sample.side}: ${text})`,
                sample.accepted.includes(text));
            check(`${pairing}: the accepted texts are distinct`, new Set(sample.accepted).size === sample.accepted.length);
            if (sample.step === 0) {
                check(`${pairing}: team preview accepts the 360 ordered picks of four of six`,
                    sample.accepted.length === 360 && sample.accepted[0] === 'team 1234' && sample.accepted[359] === 'team 6543');
            } else if (sample.accepted.some((t) => /^(move|switch|pass)/.test(t))) {
                moveRequests++;
            }
            if (sample.accepted.some((t) => /mega/.test(t))) withMega++;
        }
        sampled += all.domain.samples.length;
        changedTotal += all.domain.request_changed;
        // A lower rate samples some of the same requests, with the same sets: the decision is the hash's alone.
        const some = play(checkout, battle, {...base(i), domain_rate: 0.25});
        same(`${pairing}: a rate of 0.25 changes no choice either`, some.choices, plain.choices);
        const byKey = new Map(all.domain.samples.map((s) => [`${s.step}:${s.side}`, s]));
        check(`${pairing}: what a rate of 0.25 samples, a rate of 1 samples too, with the same set`,
            some.domain.samples.every((s) => JSON.stringify(byKey.get(`${s.step}:${s.side}`)) === JSON.stringify(s)));
        check(`${pairing}: and it samples fewer`, some.domain.samples.length < all.domain.samples.length ||
            all.domain.samples.length < 4, `${some.domain.samples.length} of ${all.domain.samples.length}`);
        same(`${pairing}: the same request and rate give the same samples`, play(checkout, battle, {...base(i), domain_rate: 0.25}), some);
    }
    check('over the battles: many requests are sampled, including move requests and Mega options', sampled > 100 &&
        moveRequests > 50 && withMega > 0, `${sampled} samples, ${moveRequests} move or switch requests, ${withMega} with Mega`);
    check('a request that changed while it was judged is rare (it is counted, not an error)', changedTotal <= sampled / 4,
        String(changedTotal));
    // domain_rate is optional and checked when given.
    const battle = make('AB', 500);
    same('no domain_rate is a rate of 0', play(checkout, battle, {seed: 1, max_steps: 3, switch_weight: 0.1, mega_weight: 0.5}).domain,
        {samples: [], request_changed: 0});
    same('a rate of 0 samples nothing', play(checkout, battle, {seed: 1, max_steps: 3, switch_weight: 0.1, mega_weight: 0.5, domain_rate: 0}).domain,
        {samples: [], request_changed: 0});
}

function main() {
    const args = process.argv.slice(2);
    if (args.length > 1) {
        process.stderr.write('usage: test_ps_play.js [<pinned checkout>]\n');
        process.exit(2);
    }
    generator();
    drawing();
    judging();
    enumerating();
    domainHashes();
    sampling();
    request();
    if (args.length === 1) realBattles(path.resolve(args[0]));
    if (failures.length) {
        process.stderr.write('test_ps_play: FAILED\n' + failures.map((f) => '  ' + f + '\n').join(''));
        process.exit(1);
    }
    process.stdout.write(`test_ps_play: the generator, the draws, the judging and the enumeration${args.length ?
        ', and real battles of the committed teams' : ''} are as documented\n`);
}

main();
