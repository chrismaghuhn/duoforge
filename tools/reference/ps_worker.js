#!/usr/bin/env node
// Persistent reference worker: one Node process that records many battles
// with the pinned Pokemon Showdown (differential loop, docs/research/expansion/
// differential-testing.md component 1).
//
// usage: node tools/reference/ps_worker.js <pinned checkout>
//
// The protocol is JSON lines: one request per stdin line, one response per
// stdout line, in request order. Nothing else goes to stdout; diagnostics go
// to stderr. The worker exits at EOF of stdin.
//
//   {"id": n, "cmd": "version"}
//     -> {"id": n, "ok": true, "node": process.version, "pin": PIN, "harness": HARNESS_VERSION}
//   {"id": n, "cmd": "record", "spec": <spec object>, "spec_file": "<basename.json>"}
//     -> {"id": n, "ok": true, "trace": "<the trace text of ps_trace.run>"}
//   anything that throws, an unknown command or a malformed line
//     -> {"id": n, "ok": false, "error": "<message>", "stack": "<first lines>"}
//
// `id` is an integer chosen by the client and echoed back; a line that is not
// a JSON object with an integer id is answered with id null. The worker keeps
// serving after an error. It has no recording logic of its own: `record` is
// ps_trace.run(), whose result is the exact text the command line prints.
'use strict';

const fs = require('fs');
const path = require('path');
const readline = require('readline');

const {run, PIN, HARNESS_VERSION} = require('./ps_trace.js');

const args = process.argv.slice(2);
if (args.length !== 1) {
    process.stderr.write('usage: ps_worker.js <pinned checkout>\n');
    process.exit(2);
}
const root = path.resolve(args[0]);
// Fail at the start, not at the first request, when the checkout is not built.
if (!fs.existsSync(path.join(root, 'dist', 'sim', 'battle.js'))) {
    process.stderr.write(`ps_worker: ${root}/dist/sim/battle.js not found (npm ci --ignore-scripts --omit=dev; node build)\n`);
    process.exit(2);
}

// stdout carries the protocol and nothing else: what the reference or the
// harness prints through console.log or process.stdout goes to stderr.
const writeResponse = process.stdout.write.bind(process.stdout);
process.stdout.write = (...rest) => process.stderr.write(...rest);
// A client that went away is the end of the work, not an error to report.
process.stdout.on('error', () => process.exit(1));

const STACK_LINES = 6;

// Commands: each takes the parsed request and returns the fields that follow
// "ok": true, or throws.
const COMMANDS = {
    version() {
        return {node: process.version, pin: PIN, harness: HARNESS_VERSION};
    },
    record(req) {
        if (req.spec === null || typeof req.spec !== 'object' || Array.isArray(req.spec)) {
            throw new Error('record: spec must be an object');
        }
        // The trace stores the file name only: a path would be cut silently.
        if (typeof req.spec_file !== 'string' || !/^[^/\\]+$/.test(req.spec_file)) {
            throw new Error('record: spec_file must be a file name, without a directory');
        }
        return {trace: run(root, req.spec, req.spec_file)};
    },
    // A3: "play" goes here: the worker draws random choices and Showdown
    // judges each one (side.choose, isChoiceDone, clearChoice); the battle is
    // saved as a normal "choices" spec. It is not built yet, so a request for
    // it fails like any unknown command.
};

function describe(err) {
    return err && typeof err.message === 'string' ? err.message : String(err);
}

function failure(id, message, err) {
    const stack = err && typeof err.stack === 'string' ? err.stack.split('\n').slice(0, STACK_LINES).join('\n') : '';
    return {id, ok: false, error: message, stack};
}

// The response to one request line: always exactly one object.
function handle(line) {
    let req;
    try {
        req = JSON.parse(line);
    } catch (err) {
        return failure(null, 'malformed request: ' + describe(err), err);
    }
    if (req === null || typeof req !== 'object' || Array.isArray(req)) {
        return failure(null, 'malformed request: not a JSON object', null);
    }
    if (!Number.isInteger(req.id)) {
        return failure(null, 'malformed request: id must be an integer', null);
    }
    if (typeof req.cmd !== 'string' || !Object.prototype.hasOwnProperty.call(COMMANDS, req.cmd)) {
        return failure(req.id, 'unknown command: ' + JSON.stringify(req.cmd), null);
    }
    try {
        return Object.assign({id: req.id, ok: true}, COMMANDS[req.cmd](req));
    } catch (err) {
        return failure(req.id, describe(err), err);
    }
}

const lines = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
lines.on('line', (line) => {
    writeResponse(JSON.stringify(handle(line)) + '\n');
});
// EOF: nothing keeps the event loop alive, so the process ends by itself once
// the responses are written (an explicit exit could cut them off).
