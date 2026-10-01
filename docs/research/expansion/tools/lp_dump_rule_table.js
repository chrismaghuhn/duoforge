// Dumps the expanded rule table of gen9championsvgc2026regmc (read-only).
const {Dex, TeamValidator} = require('C:/Dev/src/pokemon-showdown/dist/sim');
const format = Dex.formats.get('gen9championsvgc2026regmc');
console.log('format id', format.id, 'name', format.name, 'mod', format.mod, 'gameType', format.gameType, 'exists', format.exists);
const rt = Dex.formats.getRuleTable(format);
console.log('ruleTable size', rt.size);
const rules = [];
for (const [k, v] of rt) rules.push(k + ' => ' + JSON.stringify(v));
console.log(rules.join('\n'));
console.log('minTeamSize', rt.minTeamSize, 'maxTeamSize', rt.maxTeamSize, 'pickedTeamSize', rt.pickedTeamSize, 'maxTotalLevel', rt.maxTotalLevel, 'maxMoveCount', rt.maxMoveCount, 'minSourceGen', rt.minSourceGen, 'minLevel', rt.minLevel, 'maxLevel', rt.maxLevel, 'defaultLevel', rt.defaultLevel, 'adjustLevel', rt.adjustLevel, 'adjustLevelDown', rt.adjustLevelDown, 'evLimit', rt.evLimit, 'cupTierBans', rt.cupTierBans);
console.log('complexBans', JSON.stringify(rt.complexBans));
console.log('complexTeamBans', JSON.stringify(rt.complexTeamBans));
console.log('restricted', rt.restricted && [...rt.restricted]);
