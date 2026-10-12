#!/usr/bin/env node
// run() of ps_trace.js in ONE process, the way a persistent worker uses it.
//
// 1. Every committed spec is recorded; each result must equal its committed
//    trace byte for byte (CRLF read as LF, as --check does).
// 2. A run that throws (a choice the reference rejects) must be followed by a
//    normal run that is identical again.
// 3. Five specs run again in reverse order, closure and Team C battles, one
//    of them ending the battle: no state may leak from one run to the next.
//
// usage: node tools/reference/test_ps_trace_run.js <pinned checkout>
//
// CTest runs it as duoforge.reference.trace_run when the checkout and Node are
// present (the checkout is not needed otherwise: the traces are committed).
'use strict';

const fs = require('fs');
const path = require('path');
const {run, PIN, HARNESS_VERSION} = require('./ps_trace.js');

const REPO = path.resolve(__dirname, '..', '..');
const SPECS = path.join(REPO, 'tests', 'reference', 'specs');
const TRACES = path.join(REPO, 'tests', 'reference', 'traces');

// The second pass, in the order of the first (reversed when run): a Team C
// battle that ends with a win, Team C with a choice lock, the switch-in order
// tie of the closure, a short choices spec, a long plan spec that ends the
// battle.
const AGAIN = ['c05_helmet_endgame', 'c07_scarf_paralysis', 's13_lightning_rod_switch_in_order',
    's2_turn_core_1', 's3_struggle_end'];

function readSpec(name) {
    return JSON.parse(fs.readFileSync(path.join(SPECS, name + '.json'), 'utf8'));
}

function committed(name) {
    return fs.readFileSync(path.join(TRACES, name + '.json'), 'utf8').replace(/\r\n/g, '\n');
}

function firstDifference(have, want) {
    const a = have.split('\n');
    const b = want.split('\n');
    let i = 0;
    while (i < a.length && i < b.length && a[i] === b[i]) i += 1;
    return `line ${i + 1}: ${JSON.stringify(a[i])} against ${JSON.stringify(b[i])}`;
}

function main() {
    const args = process.argv.slice(2);
    if (args.length !== 1) {
        process.stderr.write('usage: test_ps_trace_run.js <pinned checkout>\n');
        process.exit(2);
    }
    const root = path.resolve(args[0]);
    const failures = [];

    if (typeof run !== 'function' || typeof PIN !== 'string' || typeof HARNESS_VERSION !== 'number') {
        failures.push('ps_trace.js must export run, PIN and HARNESS_VERSION');
    }

    // Records spec `name` with run() and compares it with the committed trace.
    const check = (pass, name) => {
        let text;
        try {
            const file = path.join(SPECS, name + '.json');
            text = run(root, JSON.parse(fs.readFileSync(file, 'utf8')), file);
        } catch (e) {
            failures.push(`${pass}: ${name}: run() threw: ${e.message}`);
            return;
        }
        const want = committed(name);
        if (text !== want) failures.push(`${pass}: ${name}: differs from its trace, at ${firstDifference(text, want)}`);
    };

    const names = fs.readdirSync(SPECS).filter((f) => f.endsWith('.json')).map((f) => f.slice(0, -5)).sort();
    for (const name of names) check('first pass', name);

    // A battle that fails: Showdown rejects the choice, run() throws and does not exit.
    const broken = readSpec('s2_turn_core_1');
    broken.choices[1].p1 = 'move 9';
    let threw = null;
    try {
        run(root, broken, path.join(SPECS, 'broken.json'));
    } catch (e) {
        threw = e;
    }
    if (threw === null || !/choice rejected/.test(threw.message)) {
        failures.push(`a rejected choice must throw "choice rejected", got ${threw === null ? 'no error' : threw.message}`);
    }
    check('after a failed run', 's2_turn_core_1');

    // The second pass needs the mix it claims: closure and Team C, one battle that ends.
    for (const name of AGAIN) {
        if (!names.includes(name)) failures.push(`second pass: ${name} is not a committed spec`);
    }
    const kinds = AGAIN.filter((n) => names.includes(n)).map((n) => ({
        teamC: readSpec(n).data === 'team_c',
        ended: JSON.parse(committed(n)).steps.slice(-1)[0].state.ended,
    }));
    if (!kinds.some((k) => k.teamC) || !kinds.some((k) => !k.teamC) || !kinds.some((k) => k.ended)) {
        failures.push('second pass: it must hold a Team C battle, a closure battle and one that ends');
    }
    for (const name of AGAIN.filter((n) => names.includes(n)).reverse()) check('second pass', name);

    if (failures.length) {
        process.stderr.write('test_ps_trace_run: FAILED\n' + failures.map((f) => '  ' + f + '\n').join(''));
        process.exit(1);
    }
    process.stdout.write(`test_ps_trace_run: ${names.length} specs identical to their traces in one process, ` +
        `${AGAIN.length} again in reverse order, and after a failed run\n`);
}

main();
