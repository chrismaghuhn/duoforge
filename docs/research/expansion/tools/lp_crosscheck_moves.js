// Independent cross-check of legal_pool.json (read-only). Recomputes every
// (selectable species, move) pair with checkMove + checkCanLearn directly and
// compares it with the pairs build_legal_pool.js got from validateSet.
// Expected output: equal pair counts and 0 diffs.
const {Dex, TeamValidator} = require('C:/Dev/src/pokemon-showdown/dist/sim');
const j = require('./legal_pool.json');
const format = Dex.formats.get('gen9championsvgc2026regmc');
const dex = Dex.forFormat(format);
const v = TeamValidator.get(format.id);
let diff = 0, pairs = 0, total = 0;
const sel = j.species.filter(s => s.kind === 'selectable');
for (const s of sel) {
  const sp = dex.species.get(s.id);
  const mine = new Set(s.moves);
  for (const mv of dex.moves.all()) {
    total++;
    const ok = !v.checkMove({name: 'x'}, mv, {}) && !v.checkCanLearn(mv, sp, v.allSources(sp), {level: 100, ability: dex.abilities.get(s.abilities_legal[0]).name});
    if (ok) pairs++;
    if (ok !== mine.has(mv.id)) { diff++; if (diff < 10) console.log('DIFF', s.id, mv.id, 'direct', ok, 'validateSet', mine.has(mv.id)); }
  }
}
console.log('pairs (species,move) legal by checkMove+checkCanLearn:', pairs, 'validateSet pairs:', sel.reduce((a, s) => a + s.moves.length, 0), 'diffs', diff, 'of', total);
