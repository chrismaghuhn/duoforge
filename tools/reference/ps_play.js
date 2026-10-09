// Random play judged by the pinned Pokemon Showdown (differential loop A3,
// docs/research/expansion/differential-testing.md component 4): both sides of
// a battle answer every request with a random choice, Showdown says whether
// the choice is allowed, and the answers are returned as the "choices" of a
// spec. The worker serves it as the command "play" (ps_worker.js).
//
// play(root, battle, policy) -> {choices, ended, steps, domain}
//   battle  {format, seed, teams: [p1 paste, p2 paste]}, as in a spec
//   policy  {seed: uint32, max_steps: n >= 1, switch_weight: 0..1, mega_weight: 0..1,
//            domain_rate: 0..1 (optional, default 0)}
//   choices [{p1: "...", p2: "..."}, ...]: one entry per step, with the sides
//           that had a request at the start of the step (p1 first), as plan
//           mode of ps_trace.js answers them; ended: the battle is over;
//           steps: choices.length. The battle stops after max_steps steps.
//   domain  {samples: [{step, side, accepted}, ...], request_changed: n}: see
//           "The domain of a request" below.
//
// Nothing here is evidence. The battle that is played is a plain Battle, and
// Showdown's own choice validation runs on it with side.choose(text) and
// side.clearChoice() as trials; a rejected trial may change the request
// (Showdown marks a move disabled or a Pokemon trapped when it is told so by
// an "Unavailable choice"). The authoritative trace is always the recording
// of the returned choices as a spec (ps_trace.run), made from a fresh battle
// that sees only the final choices, so a trial never leaks into it.
//
// A choice for one side is drawn like this, with the policy's own generator:
//   team preview  4 distinct Pokemon of the team (side.pickedTeamSize()), in
//                 random order: "team 3512";
//   switch        (a replacement or a pivot) each slot that must switch takes
//                 a random standing reserve not taken by the other slot, else
//                 "pass"; the slots take their turn in random order, so with
//                 one reserve either slot may get it; the other slots "pass";
//   move          per slot: "pass" for an empty or fainted slot; else with
//                 probability switch_weight a switch to a random standing
//                 reserve (not when the request says the Pokemon is trapped,
//                 nor when the Pokemon's own `trapped` flag is set: a hidden trap,
//                 and not one the other slot takes); else a random enabled
//                 move of the request, with a random target among
//                 [1, 2, -1, -2] that battle.validTargetLoc allows for the
//                 move's target type when battle.actions.targetTypeChoices
//                 says the move takes one (a move without a target type, as a
//                 locked move, takes none); "mega" is appended with
//                 probability mega_weight when the request says canMegaEvo
//                 and the other slot did not take it.
// Showdown judges the text with side.choose(text). A rejected text is cleared
// with side.clearChoice() and a new one is drawn. After 200 rejections every
// joint option of the side is enumerated in a fixed order (team: permutations
// in lexicographic order; switch and move: the options of slot 0 times those
// of slot 1, a slot's options in the order pass, switches by position, moves
// by index with their targets 1, 2, -1, -2 and then with mega) and a random
// one of those Showdown accepts is taken; if it accepts none the error is
// "no accepted choice". The accepted text is committed with battle.choose(id,
// text), exactly as ps_trace.js does for a recorded choice.
//
// The policy generator is its own: sfc32 (Chris Doty-Humphrey's small fast
// counter, a, b, c, d) seeded by four outputs of splitmix32 of the policy
// seed, 12 outputs discarded. It never touches the battle's PRNG, and it is
// defined here in 32-bit integer arithmetic only, so its stream is the same on
// every platform:
//   splitmix32(s):  s = s + 0x9e3779b9 (mod 2^32); t = s ^ (s >> 16);
//                   t = t * 0x21f0aaad (mod 2^32); t = t ^ (t >> 15);
//                   t = t * 0x735a2d97 (mod 2^32); return t ^ (t >> 15)
//   sfc32:          t = a + b + d; d = d + 1; a = b ^ (b >> 9);
//                   b = c + (c << 3); c = rotl(c, 21) + t; return t
//                   (all mod 2^32)
//   below(n):       the first output below floor(2^32 / n) * n, mod n (no bias)
//   chance(p):      an output < floor(p * 2^32)
//   shuffle:        Fisher-Yates from the end, j = below(i + 1)
//
// The domain of a request (differential loop A4, the domain check of the
// runner): for a sampled request the whole set of choices that Showdown
// accepts is asked for. Every joint option of the side, the options that
// enumerate() lists, is judged with side.choose(text) and side.clearChoice(),
// as the trials of chooseFor are, and the accepted texts are returned in the
// order of enumerate() as {step, side, accepted}: step is the index of the step
// the request is answered in (the index of its entry in choices), side 0 for p1
// and 1 for p2. Team preview is a request like any other.
//
// Which requests are sampled is not decided by the policy's generator but by
// a hash of (policy seed, step, side), so that sampling never changes the
// choices of the battle; a request is sampled when
//   hash < floor(domain_rate * 2^32),
//   hash = h(h(h(0x243f6a88, seed), step), side)   with h(a, w) = the first
//          output of splitmix32 of a ^ w
// (domain_rate 0 samples nothing, 1 everything).
//
// Judging a request can change it: Showdown marks a move disabled or a Pokemon
// trapped when a choice is rejected as an "Unavailable choice", in the request
// and in the maybe-flags of the Pokemon. The request and the flags are put back
// as they were, so the battle goes on as if there had been no sample, and a
// sample whose request changed while it was taken is dropped: it is no set of
// choices of one request. Such samples are counted, in request_changed.
// The one exception is a hidden trap: the refusal of a switch of the last active Pokemon turns its `maybeTrapped` into `trapped`
// (Shadow Tag, step G41); that change alone keeps the sample.
'use strict';

const path = require('path');

const MAX_REJECTIONS = 200;
const WARM_UP = 12;
const TARGET_LOCS = [1, 2, -1, -2]; // foes, then the own side; validTargetLoc keeps the ones a move allows

// ---------------------------------------------------------------- policy generator

function splitmix32(seed) {
    let s = seed >>> 0;
    return () => {
        s = (s + 0x9e3779b9) >>> 0;
        let t = (s ^ (s >>> 16)) >>> 0;
        t = Math.imul(t, 0x21f0aaad) >>> 0;
        t = (t ^ (t >>> 15)) >>> 0;
        t = Math.imul(t, 0x735a2d97) >>> 0;
        return (t ^ (t >>> 15)) >>> 0;
    };
}

class PolicyRng {
    constructor(seed) {
        const mix = splitmix32(seed);
        this.a = mix();
        this.b = mix();
        this.c = mix();
        this.d = mix();
        for (let i = 0; i < WARM_UP; i++) this.uint32();
    }

    uint32() {
        const t = (((this.a + this.b) >>> 0) + this.d) >>> 0;
        this.d = (this.d + 1) >>> 0;
        this.a = (this.b ^ (this.b >>> 9)) >>> 0;
        this.b = (this.c + ((this.c << 3) >>> 0)) >>> 0;
        this.c = (((this.c << 21) | (this.c >>> 11)) >>> 0);
        this.c = (this.c + t) >>> 0;
        return t;
    }

    // An integer from 0 to n - 1, n from 1 to 2^32.
    below(n) {
        const limit = Math.floor(4294967296 / n) * n;
        for (;;) {
            const x = this.uint32();
            if (x < limit) return x % n;
        }
    }

    chance(p) {
        return this.uint32() < Math.floor(p * 4294967296);
    }

    pick(items) {
        return items[this.below(items.length)];
    }

    shuffle(items) {
        const out = items.slice();
        for (let i = out.length - 1; i > 0; i--) {
            const j = this.below(i + 1);
            [out[i], out[j]] = [out[j], out[i]];
        }
        return out;
    }
}

// ---------------------------------------------------------------- what a side can do

// Positions (0-based, in side.pokemon) of the Pokemon that can come in: not active, not fainted.
function standingReserves(side) {
    const out = [];
    for (let i = side.active.length; i < side.pokemon.length; i++) {
        if (!side.pokemon[i].fainted) out.push(i);
    }
    return out;
}

function teamText(side, positions) {
    return 'team ' + positions.map((i) => i + 1).join(side.pokemon.length >= 10 ? ',' : '');
}

// The targets (locations) a move of this target type allows, in a fixed order; [] when it takes none.
function targetsOf(side, pokemon, targetType) {
    const battle = side.battle;
    if (targetType === undefined || !battle.actions.targetTypeChoices(targetType)) return [];
    return TARGET_LOCS.filter((loc) => battle.validTargetLoc(loc, pokemon, targetType));
}

// The moves a move request offers for a slot that can be chosen: [index, entry].
function enabledMoves(request) {
    return request.moves.map((entry, i) => [i, entry]).filter(([, entry]) => !entry.disabled);
}

function drawTeam(side, rng) {
    const order = rng.shuffle([...side.pokemon.keys()]);
    return teamText(side, order.slice(0, side.pickedTeamSize()));
}

// A slot flagged by Revival Blessing (sim/side.ts chooseSwitch): its switch names a fainted Pokemon, not a standing one.
function revivalSlot(side, slot) {
    const pokemon = side.active[slot];
    return !!(pokemon && side.slotConditions && side.slotConditions[pokemon.position] &&
        side.slotConditions[pokemon.position].revivalblessing);
}

function faintedReserves(side) {
    const out = [];
    for (let i = side.active.length; i < side.pokemon.length; i++) {
        if (side.pokemon[i].fainted) out.push(i);
    }
    return out;
}

function drawSwitch(side, rng) {
    const flags = side.activeRequest.forceSwitch;
    const free = standingReserves(side);
    const fainted = faintedReserves(side);
    const chosen = new Map();
    // sim/side.ts clearChoice: exactly min(flagged, standing reserves) switches; a revive is one of them and names a fainted
    // Pokemon, a normal switch takes a standing reserve. The rest pass.
    const flagged = rng.shuffle([...flags.keys()].filter((i) => flags[i]));
    let budget = Math.min(flagged.length, free.length);
    for (const slot of flagged) {
        if (budget <= 0) break;
        if (revivalSlot(side, slot)) {
            if (!fainted.length) continue;
            chosen.set(slot, fainted.splice(rng.below(fainted.length), 1)[0]);
        } else {
            chosen.set(slot, free.splice(rng.below(free.length), 1)[0]);
        }
        budget -= 1;
    }
    return side.active.map((_, slot) => (chosen.has(slot) ? `switch ${chosen.get(slot) + 1}` : 'pass')).join(', ');
}

function drawMove(side, rng, policy) {
    const request = side.activeRequest;
    const free = standingReserves(side);
    let megaTaken = false;
    const parts = side.active.map((pokemon, slot) => {
        if (!pokemon || pokemon.fainted) return 'pass';
        const req = request.active[slot];
        const wantSwitch = rng.chance(policy.switch_weight);
        // The request tells a Pokemon that is trapped for sure, not one that Shadow Tag holds in secret: the request of the
        // last active Pokemon has only `maybeTrapped` then (sim/pokemon.ts getMoveRequestData), and the server refuses the
        // switch. The Pokemon's own flag is read as well (`true` or 'hidden'), so that such a switch is never drawn.
        if (wantSwitch && free.length && !req.trapped && !pokemon.trapped) {
            return `switch ${free.splice(rng.below(free.length), 1)[0] + 1}`;
        }
        const moves = enabledMoves(req);
        if (!moves.length) return 'move 1';
        const [index, entry] = rng.pick(moves);
        let text = `move ${index + 1}`;
        const targets = targetsOf(side, pokemon, entry.target);
        if (targets.length) text += ' ' + rng.pick(targets);
        const wantMega = rng.chance(policy.mega_weight);
        if (wantMega && req.canMegaEvo && !megaTaken) {
            text += ' mega';
            megaTaken = true;
        }
        return text;
    });
    return parts.join(', ');
}

function draw(side, rng, policy) {
    switch (side.requestState) {
        case 'teampreview': return drawTeam(side, rng);
        case 'switch': return drawSwitch(side, rng);
        case 'move': return drawMove(side, rng, policy);
        default: throw new Error(`no choice to draw for a ${side.requestState} request`);
    }
}

// ---------------------------------------------------------------- every option, in a fixed order

function permutations(n, k) {
    const out = [];
    const rec = (prefix) => {
        if (prefix.length === k) {
            out.push(prefix);
            return;
        }
        for (let i = 0; i < n; i++) if (!prefix.includes(i)) rec([...prefix, i]);
    };
    rec([]);
    return out;
}

// The joint options of the slots, slot 0 varying slowest: each slot's options are texts.
function joint(slotOptions) {
    let out = [''];
    for (const options of slotOptions) {
        const next = [];
        for (const prefix of out) for (const option of options) next.push(prefix === '' ? option : `${prefix}, ${option}`);
        out = next;
    }
    return out;
}

function enumerate(side) {
    if (side.requestState === 'teampreview') {
        return permutations(side.pokemon.length, side.pickedTeamSize()).map((positions) => teamText(side, positions));
    }
    const reserves = standingReserves(side);
    if (side.requestState === 'switch') {
        const flags = side.activeRequest.forceSwitch;
        const fainted = faintedReserves(side);
        return joint(side.active.map((_, slot) => {
            if (!flags[slot]) return ['pass'];
            const targets = revivalSlot(side, slot) ? fainted : reserves;
            return ['pass', ...targets.map((r) => `switch ${r + 1}`)];
        }));
    }
    if (side.requestState !== 'move') throw new Error(`no choice to enumerate for a ${side.requestState} request`);
    return joint(side.active.map((pokemon, slot) => {
        if (!pokemon || pokemon.fainted) return ['pass'];
        const req = side.activeRequest.active[slot];
        const options = ['pass', ...reserves.map((r) => `switch ${r + 1}`)];
        for (const [index, entry] of enabledMoves(req)) {
            const targets = targetsOf(side, pokemon, entry.target);
            for (const target of targets.length ? targets : [null]) {
                const text = `move ${index + 1}` + (target === null ? '' : ` ${target}`);
                options.push(text);
                if (req.canMegaEvo) options.push(`${text} mega`);
            }
        }
        return options;
    }));
}

// ---------------------------------------------------------------- the side's answer

// Showdown's verdict on a text, with the choice cleared again: the trial changes nothing that stays.
function trial(side, text) {
    const accepted = side.choose(text);
    side.clearChoice();
    return accepted;
}

// A text for the side that Showdown accepts.
function chooseFor(side, rng, policy) {
    for (let attempt = 0; attempt < MAX_REJECTIONS; attempt++) {
        const text = draw(side, rng, policy);
        if (trial(side, text)) return text;
    }
    const accepted = enumerate(side).filter((text) => trial(side, text));
    if (!accepted.length) throw new Error('no accepted choice');
    return rng.pick(accepted);
}

// ps_trace.js's choose(): the commit.
function commit(battle, id, text) {
    if (!battle[id].requestState) throw new Error(`${id} has no request for "${text}"`);
    if (!battle.choose(id, text)) throw new Error(`${id} choice rejected: "${text}": ${battle[id].choice.error}`);
}

// ---------------------------------------------------------------- the domain of a request

// h(a, w): the first output of splitmix32 of a ^ w.
function mixWord(a, w) {
    return splitmix32((a ^ w) >>> 0)();
}

// The hash that decides whether the request of `side` (0 or 1) at `step` is sampled.
function domainHash(seed, step, side) {
    return mixWord(mixWord(mixWord(0x243f6a88, seed), step), side);
}

function domainSampled(seed, step, side, rate) {
    return domainHash(seed, step, side) < Math.floor(rate * 4294967296);
}

// What judging can change in a request: the request itself and the maybe-flags of the Pokemon.
function snapshotRequest(side) {
    return {
        json: JSON.stringify(side.activeRequest),
        flags: side.pokemon.map((p) => [p.maybeTrapped, p.maybeDisabled, p.maybeLocked]),
    };
}

// The request as it was, in place (nothing else holds on to it) and the flags.
function restoreRequest(side, snapshot) {
    const request = side.activeRequest;
    for (const key of Object.keys(request)) delete request[key];
    Object.assign(request, JSON.parse(snapshot.json));
    side.pokemon.forEach((p, i) => {
        [p.maybeTrapped, p.maybeDisabled, p.maybeLocked] = snapshot.flags[i];
    });
}

// The one change of a request that is no change of the set of choices (step G41, Shadow Tag): a switch of the last active
// Pokemon that a hidden trap refuses is answered with [Unavailable choice] and an updated request (sim/side.ts:527-534,
// 984-1000), where that Pokemon's `maybeTrapped` has become `trapped: true` (sim/pokemon.ts:1112-1134) and the request carries
// `update: true` (sim/side.ts:521-523). Exactly that and nothing else: the same keys and values elsewhere, an `rqid` aside (the
// pin keeps it, a new one would do), and the maybe-flags of the Pokemon unchanged or `maybeTrapped` going from true to false.
// Every other change stays a changed request.
function onlyMaybeTrappedResolved(snapshot, after) {
    const a = JSON.parse(snapshot.json);
    const b = JSON.parse(after.json);
    if (!Array.isArray(a.active) || !Array.isArray(b.active) || a.active.length !== b.active.length) return false;
    let resolved = 0;
    for (let i = 0; i < a.active.length; i++) {
        const x = a.active[i];
        const y = b.active[i];
        if (x && y && x.maybeTrapped === true && x.trapped === undefined && y.trapped === true && y.maybeTrapped === undefined) {
            const x2 = {...x};
            const y2 = {...y};
            delete x2.maybeTrapped;
            delete y2.trapped;
            if (JSON.stringify(x2) !== JSON.stringify(y2)) return false;
            a.active[i] = x2;
            b.active[i] = y2;
            resolved++;
        }
    }
    if (resolved === 0) return false;
    if (a.update !== undefined || b.update !== true) return false;
    delete a.rqid;
    delete b.rqid;
    delete b.update;
    if (JSON.stringify(a) !== JSON.stringify(b)) return false;
    for (let i = 0; i < snapshot.flags.length; i++) {
        const [mt0, md0, ml0] = snapshot.flags[i];
        const [mt1, md1, ml1] = after.flags[i];
        if (md0 !== md1 || ml0 !== ml1 || (mt0 !== mt1 && !(mt0 === true && mt1 === false))) return false;
    }
    return true;
}

// The texts that Showdown accepts for the request of `side`, in the order of enumerate(side); null when the request
// changed while they were judged (it is put back either way). The change of onlyMaybeTrappedResolved does not make a
// sample null: the refused switches are refused with or without it.
function domainSample(side) {
    const snapshot = snapshotRequest(side);
    const accepted = enumerate(side).filter((text) => trial(side, text));
    const after = snapshotRequest(side);
    if (after.json === snapshot.json && JSON.stringify(after.flags) === JSON.stringify(snapshot.flags)) return accepted;
    const resolved = onlyMaybeTrappedResolved(snapshot, after);
    restoreRequest(side, snapshot);
    return resolved ? accepted : null;
}

// ---------------------------------------------------------------- the request

function isObject(x) {
    return x !== null && typeof x === 'object' && !Array.isArray(x);
}

function checkKeys(what, x, keys, optional = []) {
    if (!isObject(x)) throw new Error(`play: ${what} must be an object`);
    const extra = Object.keys(x).filter((k) => !keys.includes(k) && !optional.includes(k));
    const missing = keys.filter((k) => !(k in x));
    if (extra.length || missing.length) {
        throw new Error(`play: ${what} has the keys ${JSON.stringify(Object.keys(x))}, ` +
            `it needs ${JSON.stringify(keys)}` + (optional.length ? ` and may have ${JSON.stringify(optional)}` : ''));
    }
}

function validate(battle, policy) {
    checkKeys('battle', battle, ['format', 'seed', 'teams']);
    if (typeof battle.format !== 'string') throw new Error('play: battle.format must be a string');
    if (typeof battle.seed !== 'string' && !Array.isArray(battle.seed)) throw new Error('play: battle.seed must be a string');
    if (!Array.isArray(battle.teams) || battle.teams.length !== 2 || battle.teams.some((t) => typeof t !== 'string')) {
        throw new Error('play: battle.teams must be two strings');
    }
    checkKeys('policy', policy, ['seed', 'max_steps', 'switch_weight', 'mega_weight'], ['domain_rate']);
    if (!Number.isInteger(policy.seed) || policy.seed < 0 || policy.seed > 0xFFFFFFFF) {
        throw new Error('play: policy.seed must be an integer from 0 to 4294967295');
    }
    if (!Number.isInteger(policy.max_steps) || policy.max_steps < 1) {
        throw new Error('play: policy.max_steps must be a positive integer');
    }
    for (const key of ['switch_weight', 'mega_weight', ...('domain_rate' in policy ? ['domain_rate'] : [])]) {
        if (typeof policy[key] !== 'number' || !(policy[key] >= 0 && policy[key] <= 1)) {
            throw new Error(`play: policy.${key} must be a number from 0 to 1`);
        }
    }
}

function play(root, battleSpec, policy) {
    validate(battleSpec, policy);
    root = path.resolve(root);
    const {Battle} = require(path.join(root, 'dist', 'sim', 'battle'));
    const {PRNG} = require(path.join(root, 'dist', 'sim', 'prng'));
    const {Teams} = require(path.join(root, 'dist', 'sim', 'teams'));

    const battle = new Battle({formatid: battleSpec.format, prng: new PRNG(battleSpec.seed)});
    for (const [i, id] of ['p1', 'p2'].entries()) {
        battle.setPlayer(id, {name: id, team: Teams.pack(Teams.import(battleSpec.teams[i]))});
    }
    const rng = new PolicyRng(policy.seed);
    const rate = policy.domain_rate ?? 0;
    const choices = [];
    const domain = {samples: [], request_changed: 0};
    while (choices.length < policy.max_steps && !battle.ended) {
        // The sides asked at the start of the step: answering one can finish the step and ask both again.
        const asked = ['p1', 'p2'].filter((id) => battle[id].requestState);
        if (!asked.length) throw new Error('no side has a request and the battle has not ended');
        const entry = {};
        const step = choices.length;
        for (const id of asked) {
            const side = id === 'p1' ? 0 : 1;
            // The sample is taken before the policy draws: it leaves the request as it was, and the hash, not the
            // generator, says whether to take it.
            if (domainSampled(policy.seed, step, side, rate)) {
                const accepted = domainSample(battle[id]);
                if (accepted === null) domain.request_changed++;
                else domain.samples.push({step, side, accepted});
            }
            const text = chooseFor(battle[id], rng, policy);
            commit(battle, id, text);
            entry[id] = text;
        }
        choices.push(entry);
    }
    return {choices, ended: !!battle.ended, steps: choices.length, domain};
}

module.exports = {play, PolicyRng, splitmix32, chooseFor, enumerate, draw, domainHash, domainSampled, domainSample,
    MAX_REJECTIONS};
