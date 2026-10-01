'use strict';
// Confirms the built dist/ data of the champions mod equals the TypeScript
// sources at the pinned checkout, for the fields that decide legality:
//   isNonstandard overrides in items/moves/abilities/formats-data, and the
//   learnset keys + source strings of every top-level entry in learnsets.ts.
// Read-only.
const fs = require('fs');
const SD = 'C:/Dev/src/pokemon-showdown';
const { Dex } = require(SD + '/dist/sim');
const dex = Dex.forFormat(Dex.formats.get('gen9championsvgc2026regmc'));
const data = dex.data;
const read = f => fs.readFileSync(`${SD}/data/mods/champions/${f}.ts`, 'utf8').replace(/\r\n/g, '\n');

function parseNonstandard(txt) {
  const out = new Map();
  // top-level entries are indented by exactly one tab
  const re = /^\t([a-z0-9]+): \{\n([\s\S]*?)^\t\},?\n/gm;
  let m;
  while ((m = re.exec(txt))) {
    const ns = /^\t\tisNonstandard: (null|"[A-Za-z]+"),/m.exec(m[2]);
    out.set(m[1], ns ? (ns[1] === 'null' ? null : JSON.parse(ns[1])) : undefined);
  }
  return out;
}

let bad = 0;
for (const [file, table] of [['items', 'Items'], ['moves', 'Moves'], ['abilities', 'Abilities'], ['formats-data', 'FormatsData']]) {
  const parsed = parseNonstandard(read(file));
  let checked = 0, diff = 0;
  for (const [id, want] of parsed) {
    if (want === undefined) continue; // override does not touch isNonstandard
    checked++;
    const got = data[table][id] ? data[table][id].isNonstandard : '<missing>';
    if ((got ?? null) !== want) { diff++; if (diff <= 5) console.log('  DIFF', file, id, 'ts', want, 'dist', got); }
  }
  console.log(`${file}: ${parsed.size} entries parsed, ${checked} isNonstandard overrides compared, ${diff} differences`);
  bad += diff;
}

// learnsets: every top-level entry, not only those whose first key is "learnset"
{
  const entries = new Map();
  let cur = null, inLearnset = false;
  for (const line of read('learnsets').split('\n')) {
    let m;
    if ((m = /^\t([a-z0-9]+): \{$/.exec(line))) { cur = m[1]; entries.set(cur, {}); inLearnset = false; continue; }
    if (!cur) continue;
    if (/^\t\tlearnset: \{$/.test(line)) { inLearnset = true; continue; }
    if (inLearnset && /^\t\t\},$/.test(line)) { inLearnset = false; continue; }
    if (inLearnset && (m = /^\t\t\t([a-z0-9]+): \[(.*)\],$/.exec(line))) {
      entries.get(cur)[m[1]] = m[2].split(',').map(x => x.trim().replace(/"/g, '')).filter(Boolean);
    }
  }
  let diff = 0, moveTotal = 0;
  for (const [id, moves] of entries) {
    moveTotal += Object.keys(moves).length;
    const ld = data.Learnsets[id] && data.Learnsets[id].learnset;
    const a = JSON.stringify(Object.keys(moves).sort().map(k => [k, moves[k]]));
    const c = JSON.stringify(Object.keys(ld || {}).sort().map(k => [k, ld[k]]));
    if (a !== c) { diff++; if (diff <= 5) console.log('  LEARNSET DIFF', id, Object.keys(moves).length, Object.keys(ld || {}).length); }
  }
  console.log(`learnsets: ${entries.size} top-level entries parsed, ${moveTotal} learnset entries, ${diff} differences`);
  bad += diff;
}
console.log(bad === 0 ? 'dist matches sources' : 'MISMATCH: ' + bad);
