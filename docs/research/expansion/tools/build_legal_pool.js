'use strict';
/*
 * build_legal_pool.js -- read-only inventory of what is LEGAL in
 *   gen9championsvgc2026regmc
 * at the pinned Showdown checkout, using Showdown's own TeamValidator.
 *
 * Writes (next to this script):
 *   legal_pool.json
 *
 * Nothing under C:/Dev/src/pokemon-showdown or the DuoForge worktree is
 * modified; both are only read.
 *
 * Method (see "method" in the output):
 *   - a species/forme is legal iff TeamValidator.validateSet accepts a
 *     complete, otherwise-valid set naming it;
 *   - a move is legal for a species iff validateSet accepts that species with
 *     that move as its only move (so checkMove, the Obtainable Moves learnset
 *     check and every ruleset hook run);
 *   - an ability is legal for a species iff validateSet accepts it;
 *   - an item is legal iff validateSet accepts it on two probe species;
 *   - a Mega forme is legal iff validateSet accepts <base species> holding
 *     <stone> (the validator resolves the stone to the Mega forme, tierSpecies,
 *     and runs checkSpecies on it).
 */
const fs = require('fs');
const path = require('path');
const SD = 'C:/Dev/src/pokemon-showdown';
const { Dex, TeamValidator } = require(SD + '/dist/sim');

const OUT_DIR = __dirname;
const FORMAT_ID = 'gen9championsvgc2026regmc';
const PIN = 'b2cb775b0616115b775534eaeff50300e1fc81fc';
const DUOFORGE = 'C:/Dev/src/duoforge/.claude/worktrees/epic-yalow-463a67';

const format = Dex.formats.get(FORMAT_ID);
if (!format.exists) throw new Error('format missing');
const dex = Dex.forFormat(format);
const validator = TeamValidator.get(FORMAT_ID);
const ruleTable = Dex.formats.getRuleTable(format);

function mkSet(species, ability, item, moves, extra) {
  return Object.assign({
    name: '', species, item: item || '', ability, moves,
    nature: 'Adamant', gender: '',
    evs: { hp: 2, atk: 0, def: 0, spa: 0, spd: 0, spe: 0 },
    ivs: { hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31 },
    level: 50,
  }, extra || {});
}
const validate = set => validator.validateSet(set, {});
const toID = s => String(s).toLowerCase().replace(/[^a-z0-9]+/g, '');
const uniq = a => [...new Set(a)];
const sortIds = a => [...a].sort();

// ---------------------------------------------------------------- rules block
const rules = {
  format_id: format.id,
  format_name: format.name,
  mod: format.mod,
  game_type: format.gameType,
  ruleset_as_declared: format.ruleset,
  rule_table_keys: [...ruleTable.keys()],
  banlist_effective: [...ruleTable.keys()].filter(k => k.startsWith('-')),
  team_size: { min: ruleTable.minTeamSize, max: ruleTable.maxTeamSize, picked: ruleTable.pickedTeamSize },
  level: { adjust_level_to: ruleTable.adjustLevel, validator_max_level: ruleTable.maxLevel },
  moves_per_set: ruleTable.maxMoveCount,
  stat_points: {
    note: 'champions mod: set.evs holds Stat Points (validator: useStatPoints = mod startsWith champions)',
    total_limit: ruleTable.evLimit, per_stat_max: 32, ivs: 'all 31 required',
  },
  min_source_gen: ruleTable.minSourceGen,
  clauses_team_level: ['Species Clause', 'Item Clause = 1', 'Nickname Clause'],
  terastallization: 'disabled (mod scripts.ts actions.canTerastallize returns null; validator drops teraType for champions mods)',
  dynamax_zmoves: 'none: all 87 Z/Max moves in the dex are tagged nonexistent (Past/Gmax), no Z-crystal item is legal, sim/side.ts canDynamaxNow() requires gen 8',
};

// ---------------------------------------------------------- species scanning
const allSpecies = dex.species.all().filter(s => s.exists);
const allMoves = dex.moves.all().filter(m => m.exists);
const allItems = dex.items.all().filter(i => i.exists);
const allAbilities = dex.abilities.all().filter(a => a.exists);

/** First move of the species' learnset chain that the validator accepts alone. */
function learnsetMoveIds(sp) {
  const out = new Set();
  for (const { learnset } of dex.species.getFullLearnset(sp.id)) for (const m of Object.keys(learnset)) out.add(m);
  return [...out];
}

const declaredAbilityNames = sp => uniq(Object.values(sp.abilities));

const speciesScan = new Map(); // id -> { legalAbilities, probeMove, problems }
for (const sp of allSpecies) {
  if (/-Gmax$/.test(sp.name)) continue; // validator alias for base + gigantamax flag; handled below
  const mvs = learnsetMoveIds(sp);
  let probe = null;
  for (const m of mvs) {
    const mv = dex.moves.get(m);
    if (mv.exists && !validator.checkMove({ name: 'x' }, mv, {})) { probe = m; break; }
  }
  if (!probe) probe = 'protect';
  const legalAbilities = [];
  const problems = {};
  for (const a of declaredAbilityNames(sp)) {
    const p = validate(mkSet(sp.name, a, '', [probe]));
    if (p) problems[a] = p; else legalAbilities.push(a);
  }
  speciesScan.set(sp.id, { legalAbilities, probeMove: probe, problems });
}

// selectable = not a battle-only forme and validator accepts it with >= 1 ability
const selectable = allSpecies.filter(sp => !/-Gmax$/.test(sp.name) && !sp.battleOnly &&
  speciesScan.get(sp.id).legalAbilities.length > 0);

// ---------------------------------------------------------------- items
const itemLegal = new Map();
for (const it of allItems) {
  const p1 = validate(mkSet('Garchomp', 'Rough Skin', it.name, ['protect']));
  const p2 = validate(mkSet('Charizard', 'Blaze', it.name, ['protect']));
  itemLegal.set(it.id, { ok: !p1 && !p2, p1, p2 });
}
const legalItems = allItems.filter(i => itemLegal.get(i.id).ok);
const itemProbeDisagree = allItems.filter(i => !!itemLegal.get(i.id).p1 !== !!itemLegal.get(i.id).p2).map(i => i.id);

// ----------------------------------------------------------- Mega formes
const megaRecords = new Map(); // mega id -> { megaSpecies, holders: [{base, item}] }
for (const it of allItems) {
  if (!it.megaStone) continue;
  for (const [baseName, megaName] of Object.entries(it.megaStone)) {
    const bs = dex.species.get(baseName);
    const ms = dex.species.get(megaName);
    let okAbility = null;
    let firstProblem = null;
    for (const a of declaredAbilityNames(bs)) {
      const p = validate(mkSet(bs.name, a, it.name, ['protect']));
      if (!p) { okAbility = a; break; }
      if (!firstProblem) firstProblem = p;
    }
    // also: the validator accepts the Mega forme named directly (it rewrites to base) -- cross-check
    let okDirect = false;
    if (okAbility) okDirect = !validate(mkSet(ms.name, okAbility, it.name, ['protect']));
    const rec = megaRecords.get(ms.id) || { megaSpecies: ms, holders: [] };
    rec.holders.push({ base: bs, item: it, ok: !!okAbility, okDirect, problem: okAbility ? null : firstProblem });
    megaRecords.set(ms.id, rec);
  }
}
const legalMegas = [...megaRecords.values()].filter(r => r.holders.some(h => h.ok));
const illegalMegaPairs = [];
for (const r of megaRecords.values()) for (const h of r.holders) if (!h.ok) illegalMegaPairs.push({ item: h.item.id, base: h.base.id, mega: r.megaSpecies.id, first_problem: (h.problem || [])[0] || null });

// ----------------------------------------------- battle-only (non-Mega) formes
const battleOnly = [];
const battleOnlyExcluded = [];
for (const sp of allSpecies) {
  if (!sp.battleOnly || sp.isMega || sp.isPrimal) continue;
  if (/-Gmax$/.test(sp.name)) continue;
  if (sp.isNonstandard) continue; // nonexistent in this mod (Past etc.); listed below only if their base is legal
  const baseName = Array.isArray(sp.battleOnly) ? sp.battleOnly[0] : sp.battleOnly;
  const bs = dex.species.get(baseName);
  const baseLegal = selectable.some(s => s.id === bs.id);
  // try the in-battle forme named directly with its required ability / item / move
  const ab = sp.requiredAbility || Object.values(sp.abilities)[0];
  const item = sp.requiredItem || '';
  const mv = sp.requiredMove ? [sp.requiredMove] : ['protect'];
  const p = validate(mkSet(sp.name, ab, item, mv));
  const rec = { sp, base: bs, baseLegal, validatorProblems: p };
  if (baseLegal && !p) battleOnly.push(rec); else battleOnlyExcluded.push(rec);
}
// battle-only formes that are tagged nonexistent but whose base is legal would be reachable in theory:
const battleOnlyNonexistentWithLegalBase = allSpecies
  .filter(sp => sp.battleOnly && !sp.isMega && !sp.isPrimal && sp.isNonstandard && !/-Gmax$/.test(sp.name))
  .filter(sp => {
    const baseName = Array.isArray(sp.battleOnly) ? sp.battleOnly[0] : sp.battleOnly;
    return selectable.some(s => s.id === dex.species.get(baseName).id);
  }).map(sp => sp.id);

// ----------------------------------------------------------- moves x species
const t0 = Date.now();
const movesBySpecies = new Map();
const legalMoveSet = new Set();
for (const sp of selectable) {
  const ab = speciesScan.get(sp.id).legalAbilities[0];
  const list = [];
  for (const mv of allMoves) {
    const p = validate(mkSet(sp.name, ab, '', [mv.name]));
    if (!p) { list.push(mv.id); legalMoveSet.add(mv.id); }
  }
  movesBySpecies.set(sp.id, list);
}
const crossProductMs = Date.now() - t0;

// cross-check: learnset keys (own chain) intersect not-nonexistent moves, vs validator result
const learnsetMismatch = [];
for (const sp of selectable) {
  const fromValidator = new Set(movesBySpecies.get(sp.id));
  const fromLearnset = new Set(learnsetMoveIds(sp).filter(m => {
    const mv = dex.moves.get(m);
    return mv.exists && !validator.checkMove({ name: 'x' }, mv, {});
  }));
  const onlyV = [...fromValidator].filter(m => !fromLearnset.has(m));
  const onlyL = [...fromLearnset].filter(m => !fromValidator.has(m));
  if (onlyV.length || onlyL.length) learnsetMismatch.push({ species: sp.id, onlyValidator: onlyV, onlyLearnset: onlyL });
}

// ------------------------------------------------------------- abilities
const abilityInfo = new Map(); // id -> { onSelectable: Set, onMega: Set, onBattleOnly: Set }
const ab = id => { if (!abilityInfo.has(id)) abilityInfo.set(id, { onSelectable: new Set(), onMega: new Set(), onBattleOnly: new Set() }); return abilityInfo.get(id); };
for (const sp of selectable) for (const a of speciesScan.get(sp.id).legalAbilities) ab(toID(a)).onSelectable.add(sp.id);
for (const r of legalMegas) for (const a of declaredAbilityNames(r.megaSpecies)) ab(toID(a)).onMega.add(r.megaSpecies.id);
for (const r of battleOnly) for (const a of declaredAbilityNames(r.sp)) ab(toID(a)).onBattleOnly.add(r.sp.id);

// ---------------------------------------------------------- DuoForge ids
function parseDefines(file) {
  const txt = fs.readFileSync(file, 'utf8');
  const out = { FORME: [], MOVE: [], ITEM: [], ABILITY: [] };
  const re = /^#define DFI_(FORME|MOVE|ITEM|ABILITY)_([A-Z0-9_]+)\s+(\d+)u/gm;
  let m;
  while ((m = re.exec(txt))) {
    const [, kind, name, num] = m;
    if (name === 'COUNT' || name === 'EXT_COUNT') continue;
    if (kind === 'MOVE' && name.startsWith('FLAG_')) continue; // flag bits, not move ids
    out[kind].push({ name: 'DFI_' + kind + '_' + name, id: name.toLowerCase().replace(/_/g, ''), num: Number(num) });
  }
  return out;
}
const dfClosure = parseDefines(DUOFORGE + '/src/data/closure_tables.h');
const dfExt = parseDefines(DUOFORGE + '/src/data/extended_tables.h');
const dfi = {};
for (const k of ['FORME', 'MOVE', 'ITEM', 'ABILITY']) {
  const m = new Map();
  for (const e of [...dfClosure[k], ...dfExt[k]]) m.set(e.num, e);
  dfi[k] = [...m.values()].sort((a, b) => a.num - b.num);
}
const dfiSets = {
  forme: new Set(dfi.FORME.map(e => e.id)),
  move: new Set(dfi.MOVE.map(e => e.id)),
  item: new Set(dfi.ITEM.map(e => e.id)),
  ability: new Set(dfi.ABILITY.map(e => e.id)),
};
// sanity: every DuoForge id must resolve to a Showdown entry of the right kind
const dfiUnresolved = [];
for (const e of dfi.FORME) if (!dex.species.get(e.id).exists) dfiUnresolved.push(e.name);
for (const e of dfi.MOVE) if (!dex.moves.get(e.id).exists) dfiUnresolved.push(e.name);
for (const e of dfi.ITEM) if (!dex.items.get(e.id).exists) dfiUnresolved.push(e.name);
for (const e of dfi.ABILITY) if (!dex.abilities.get(e.id).exists) dfiUnresolved.push(e.name);

// ------------------------------------------------------------ record builders
const statsOf = sp => ({ hp: sp.baseStats.hp, atk: sp.baseStats.atk, def: sp.baseStats.def, spa: sp.baseStats.spa, spd: sp.baseStats.spd, spe: sp.baseStats.spe });
const abilitiesOf = sp => {
  const o = {};
  for (const [k, v] of Object.entries(sp.abilities)) o[k] = toID(v);
  return o;
};
function sameMechanics(a, b) {
  const sig = s => JSON.stringify([s.types, statsOf(s), abilitiesOf(s), s.weightkg, s.gender]);
  return sig(a) === sig(b);
}

const speciesOut = [];
const selectableIds = new Set(selectable.map(s => s.id));
const megaByHolder = new Map(); // holder id -> [mega ids]
for (const r of legalMegas) for (const h of r.holders) if (h.ok) {
  if (!megaByHolder.has(h.base.id)) megaByHolder.set(h.base.id, []);
  megaByHolder.get(h.base.id).push({ mega: r.megaSpecies.id, item: h.item.id });
}
const battleByBase = new Map();
for (const r of battleOnly) {
  if (!battleByBase.has(r.base.id)) battleByBase.set(r.base.id, []);
  battleByBase.get(r.base.id).push(r.sp.id);
}

for (const sp of selectable) {
  const base = dex.species.get(sp.baseSpecies);
  const identical = sp.id !== base.id && selectableIds.has(base.id) && sameMechanics(sp, base) &&
    JSON.stringify(sortIds(movesBySpecies.get(sp.id))) === JSON.stringify(sortIds(movesBySpecies.get(base.id)));
  speciesOut.push({
    id: sp.id,
    name: sp.name,
    kind: 'selectable',
    num: sp.num,
    base_species: base.id,
    forme: sp.forme || '',
    is_cosmetic_forme: !!sp.isCosmeticForme,
    mechanically_identical_to: identical ? base.id : null,
    types: sp.types,
    base_stats: statsOf(sp),
    abilities_declared: abilitiesOf(sp),
    abilities_legal: speciesScan.get(sp.id).legalAbilities.map(toID),
    weightkg: sp.weightkg,
    gender: sp.gender || null,
    mega_formes: (megaByHolder.get(sp.id) || []).map(x => x.mega),
    mega_items: (megaByHolder.get(sp.id) || []).map(x => x.item),
    battle_only_formes: battleByBase.get(sp.id) || [],
    cosmetic_formes_accepted: (sp.cosmeticFormes || []).filter(n => {
      const c = dex.species.get(n);
      return c.exists && !validate(mkSet(c.name, speciesScan.get(sp.id).legalAbilities[0], '', [speciesScan.get(sp.id).probeMove]));
    }).map(toID),
    in_duoforge: dfiSets.forme.has(sp.id),
    moves: sortIds(movesBySpecies.get(sp.id)),
  });
}
for (const r of legalMegas) {
  const ms = r.megaSpecies;
  const holders = r.holders.filter(h => h.ok);
  speciesOut.push({
    id: ms.id,
    name: ms.name,
    kind: 'mega',
    num: ms.num,
    base_species: dex.species.get(ms.baseSpecies).id,
    forme: ms.forme,
    holders: holders.map(h => ({ species: h.base.id, item: h.item.id })),
    required_item: toID(ms.requiredItem),
    types: ms.types,
    base_stats: statsOf(ms),
    abilities_declared: abilitiesOf(ms),
    abilities_legal: Object.values(abilitiesOf(ms)),
    weightkg: ms.weightkg,
    gender: ms.gender || null,
    moves_via: holders.map(h => h.base.id),
    validator_accepts_mega_name_directly: holders.every(h => h.okDirect),
    in_duoforge: dfiSets.forme.has(ms.id),
  });
}
for (const r of battleOnly) {
  const sp = r.sp;
  speciesOut.push({
    id: sp.id,
    name: sp.name,
    kind: 'battle_only',
    num: sp.num,
    base_species: dex.species.get(sp.baseSpecies).id,
    forme: sp.forme,
    reached_from: r.base.id,
    required_ability: sp.requiredAbility ? toID(sp.requiredAbility) : null,
    types: sp.types,
    base_stats: statsOf(sp),
    abilities_declared: abilitiesOf(sp),
    abilities_legal: Object.values(abilitiesOf(sp)),
    weightkg: sp.weightkg,
    moves_via: [r.base.id],
    in_duoforge: dfiSets.forme.has(sp.id),
  });
}

const movesOut = [...legalMoveSet].sort().map(id => {
  const m = dex.moves.get(id);
  return {
    id, name: m.name, num: m.num, type: m.type, category: m.category,
    base_power: m.basePower, accuracy: m.accuracy === true ? 'always' : m.accuracy,
    pp: m.pp, priority: m.priority, target: m.target,
    flags: Object.keys(m.flags).sort(),
    calls_move: !!m.callsMove,
    learned_by_count: selectable.filter(sp => movesBySpecies.get(sp.id).includes(id)).length,
    in_duoforge: dfiSets.move.has(id),
  };
});

const abilitiesOut = [...abilityInfo.keys()].sort().map(id => {
  const a = dex.abilities.get(id);
  const i = abilityInfo.get(id);
  const sel = i.onSelectable.size > 0;
  return {
    id, name: a.name, num: a.num,
    reachable_as: sel ? (i.onMega.size ? 'selectable+mega' : 'selectable') : (i.onMega.size ? 'mega_only' : 'battle_only_forme_only'),
    selectable_on_count: i.onSelectable.size,
    mega_formes: sortIds(i.onMega),
    battle_only_formes: sortIds(i.onBattleOnly),
    dex_is_nonstandard: a.isNonstandard || null,
    in_duoforge: dfiSets.ability.has(id),
  };
});

const itemsOut = legalItems.map(i => ({
  id: i.id, name: i.name, num: i.num,
  is_mega_stone: !!i.megaStone,
  mega_stone: i.megaStone ? Object.fromEntries(Object.entries(i.megaStone).map(([b, m]) => [toID(b), toID(m)])) : null,
  is_berry: !!i.isBerry,
  is_choice: !!i.isChoice,
  in_duoforge: dfiSets.item.has(i.id),
})).sort((a, b) => a.id < b.id ? -1 : 1);

// ------------------------------------------------- derived reachability checks
// Moves that call other moves, among the legal moves.
const callsMoveLegal = movesOut.filter(m => m.calls_move).map(m => m.id);
// Abilities / moves / items that can set an ability by literal id (source scan).
const setAbilityLiterals = new Set();
const scanFns = (label, obj) => {
  for (const [k, v] of Object.entries(obj)) {
    if (typeof v === 'function') {
      const src = v.toString();
      const re = /setAbility\(\s*['"`]([A-Za-z0-9 ]+)['"`]/g;
      let m;
      while ((m = re.exec(src))) setAbilityLiterals.add(`${label}:${toID(m[1])}`);
    } else if (v && typeof v === 'object' && !Array.isArray(v) && ['condition', 'secondary', 'self'].includes(k)) {
      scanFns(label, v);
    }
  }
};
for (const m of movesOut) scanFns(m.id, dex.moves.get(m.id));
for (const a of abilitiesOut) scanFns(a.id, dex.abilities.get(a.id));
const setAbilityByLegal = [...setAbilityLiterals].map(s => { const [src, ab] = s.split(':'); return { source: src, sets_ability: ab, ability_in_pool: abilityInfo.has(ab) }; });

// ------------------------------------------------------------- coverage
const cov = (kind, poolIds, dfiList, dexGet) => {
  const pool = new Set(poolIds);
  const dfiIds = dfiList.map(e => e.id);
  return {
    pool_count: pool.size,
    duoforge_count: dfiIds.length,
    duoforge_in_pool: dfiIds.filter(i => pool.has(i)),
    duoforge_not_in_pool: dfiIds.filter(i => !pool.has(i)),
    pool_not_in_duoforge_count: [...pool].filter(i => !dfiIds.includes(i)).length,
  };
};
const selectableIdsList = speciesOut.filter(s => s.kind === 'selectable').map(s => s.id);
const megaIdsList = speciesOut.filter(s => s.kind === 'mega').map(s => s.id);
const battleOnlyIdsList = speciesOut.filter(s => s.kind === 'battle_only').map(s => s.id);
const coverage = {
  naming: 'DFI_<KIND>_<NAME> lowercased == Showdown id (closure_tables.h + extended_tables.h, Team C included)',
  unresolved_duoforge_ids: dfiUnresolved,
  formes_all: cov('forme', [...selectableIdsList, ...megaIdsList, ...battleOnlyIdsList], dfi.FORME),
  formes_selectable: cov('forme', selectableIdsList, dfi.FORME.filter(e => selectableIdsList.includes(e.id))),
  formes_mega: cov('forme', megaIdsList, dfi.FORME.filter(e => megaIdsList.includes(e.id))),
  moves: cov('move', movesOut.map(m => m.id), dfi.MOVE),
  abilities: cov('ability', abilitiesOut.map(a => a.id), dfi.ABILITY),
  items: cov('item', itemsOut.map(i => i.id), dfi.ITEM),
};

// tagged-available-but-not-in-pool lists
const poolMoveIds = new Set(movesOut.map(m => m.id));
const poolAbilityIds = new Set(abilitiesOut.map(a => a.id));
const poolItemIds = new Set(itemsOut.map(i => i.id));
const movesTaggedNotLearnable = allMoves.filter(m => !m.isNonstandard && !poolMoveIds.has(m.id)).map(m => m.id).sort();
const abilitiesTaggedNotReachable = allAbilities.filter(a => !a.isNonstandard && !poolAbilityIds.has(a.id)).map(a => a.id).sort();
const itemsTaggedNotLegal = allItems.filter(i => !i.isNonstandard && !poolItemIds.has(i.id)).map(i => i.id).sort();
const abilitiesReachableButTagged = abilitiesOut.filter(a => a.dex_is_nonstandard).map(a => ({ id: a.id, tag: a.dex_is_nonstandard, mega_formes: a.mega_formes }));
const poolFormeIds = new Set(speciesOut.map(s => s.id));
const speciesTaggedNotInPool = allSpecies.filter(s => !s.isNonstandard && !poolFormeIds.has(s.id)).map(s => s.id).sort();
// DuoForge id lists with kind of pool entry
const dfiLists = {
  formes: dfi.FORME.map(e => ({ dfi: e.name, id: e.id, pool_kind: (speciesOut.find(s => s.id === e.id) || {}).kind || null })),
  moves: dfi.MOVE.map(e => ({ dfi: e.name, id: e.id, in_pool: poolMoveIds.has(e.id) })),
  abilities: dfi.ABILITY.map(e => ({ dfi: e.name, id: e.id, in_pool: poolAbilityIds.has(e.id) })),
  items: dfi.ITEM.map(e => ({ dfi: e.name, id: e.id, in_pool: poolItemIds.has(e.id) })),
};
coverage.lists = dfiLists;

// -------------------------------------------------------------------- counts
const nonCosmetic = speciesOut.filter(s => s.kind === 'selectable' && !s.is_cosmetic_forme);
const distinctBase = new Set(speciesOut.filter(s => s.kind === 'selectable').map(s => s.base_species));
const counts = {
  selectable_species_formes: speciesOut.filter(s => s.kind === 'selectable').length,
  selectable_flagged_cosmetic: speciesOut.filter(s => s.kind === 'selectable' && s.is_cosmetic_forme).length,
  selectable_non_cosmetic: nonCosmetic.length,
  selectable_mechanically_identical_to_base: speciesOut.filter(s => s.mechanically_identical_to).length,
  selectable_distinct_mechanics: nonCosmetic.filter(s => !s.mechanically_identical_to).length,
  distinct_base_species: distinctBase.size,
  cosmetic_formes_accepted_not_in_dex_all: uniq(speciesOut.flatMap(s => s.cosmetic_formes_accepted || []))
    .filter(id => !selectableIds.has(id)).length,
  mega_formes: megaIdsList.length,
  mega_stones: itemsOut.filter(i => i.is_mega_stone).length,
  battle_only_formes_non_mega: battleOnlyIdsList.length,
  moves: movesOut.length,
  species_move_pairs: [...movesBySpecies.values()].reduce((n, l) => n + l.length, 0),
  abilities_reachable: abilitiesOut.length,
  abilities_on_selectable_species: abilitiesOut.filter(a => a.selectable_on_count > 0).length,
  abilities_mega_only: abilitiesOut.filter(a => a.reachable_as === 'mega_only').map(a => a.id),
  items: itemsOut.length,
  items_non_mega_stone: itemsOut.filter(i => !i.is_mega_stone).length,
  dex_totals_for_reference: {
    species_all: allSpecies.length, moves_all: allMoves.length, abilities_all: allAbilities.length, items_all: allItems.length,
    species_no_isNonstandard: allSpecies.filter(s => !s.isNonstandard).length,
    moves_no_isNonstandard: allMoves.filter(m => !m.isNonstandard).length,
    abilities_no_isNonstandard: allAbilities.filter(a => !a.isNonstandard).length,
    items_no_isNonstandard: allItems.filter(i => !i.isNonstandard).length,
  },
};

// ------------------------------------------------------------- the file
const out = {
  meta: {
    generated_by: 'build_legal_pool.js',
    showdown_checkout: SD,
    showdown_commit: PIN,
    format_id: FORMAT_ID,
    node: process.version,
    cross_product_validateSet_calls: selectable.length * allMoves.length,
    cross_product_ms: crossProductMs,
  },
  rules,
  method: {
    species: 'validator.validateSet accepts a full set (level 50, Adamant, 2 Stat Points, IVs 31, one probe move, one declared ability) naming the species; Gmax placeholder names are skipped (the validator aliases X-Gmax to X + gigantamax flag, which does nothing without Dynamax)',
    selectable: 'validated species that are not battleOnly formes',
    mega: 'for every item.megaStone entry (base -> mega): validateSet(base holding stone) must pass; the validator maps the stone to the Mega forme (getValidationSpecies) and runs checkSpecies/checkTagRules on it; naming the Mega forme directly is cross-checked',
    battle_only: 'non-Mega battleOnly formes whose base is selectable and whose required ability/item/move set validates',
    moves: 'for each selectable species and each of the dex moves: validateSet with that single move',
    abilities: 'validateSet per declared ability slot of each selectable species; Mega-only and battle-only-forme abilities added from the in-battle forme records',
    items: 'validateSet on Garchomp and Charizard holding the item; legal iff both pass',
  },
  counts,
  coverage_duoforge: coverage,
  checks: {
    item_probe_disagreements: itemProbeDisagree,
    mega_stone_pairs_rejected_by_validator: illegalMegaPairs,
    learnset_vs_validator_mismatches: learnsetMismatch,
    battle_only_excluded: battleOnlyExcluded.map(r => ({ id: r.sp.id, base: r.base.id, base_legal: r.baseLegal, problems: r.validatorProblems })),
    battle_only_nonexistent_but_base_legal: battleOnlyNonexistentWithLegalBase,
    legal_moves_that_call_other_moves: callsMoveLegal,
    set_ability_by_literal_in_legal_moves_and_abilities: setAbilityByLegal,
    gmax_placeholder_names_skipped: allSpecies.filter(s => /-Gmax$/.test(s.name)).length,
    moves_tagged_available_but_learnable_by_no_legal_species: movesTaggedNotLearnable,
    abilities_tagged_available_but_on_no_legal_species_or_mega: abilitiesTaggedNotReachable,
    items_tagged_available_but_rejected_by_validator: itemsTaggedNotLegal,
    abilities_reachable_but_tagged_nonstandard_in_dex: abilitiesReachableButTagged,
    species_tagged_available_but_not_in_pool: speciesTaggedNotInPool,
  },
  species: speciesOut,
  moves: movesOut,
  abilities: abilitiesOut,
  items: itemsOut,
};
// header blocks pretty-printed, the four big arrays one record per line
{
  const NL = String.fromCharCode(10);
  const parts = [];
  for (const k of ['meta', 'rules', 'method', 'counts', 'coverage_duoforge', 'checks']) {
    parts.push('  ' + JSON.stringify(k) + ': ' + JSON.stringify(out[k], null, 2).split(NL).join(NL + '  '));
  }
  for (const k of ['species', 'moves', 'abilities', 'items']) {
    parts.push('  ' + JSON.stringify(k) + ': [' + NL + out[k].map(x => '    ' + JSON.stringify(x)).join(',' + NL) + NL + '  ]');
  }
  fs.writeFileSync(path.join(OUT_DIR, 'legal_pool.json'), '{' + NL + parts.join(',' + NL) + NL + '}' + NL);
}
console.log(JSON.stringify({ counts, crossProductMs }, null, 1));
console.log('coverage:', JSON.stringify(coverage, null, 1));
console.log('checks:', JSON.stringify(out.checks, null, 1));
