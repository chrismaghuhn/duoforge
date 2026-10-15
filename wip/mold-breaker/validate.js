// usage: node validate.js spec.json  -> prints problems of both teams (TeamValidator of the pin, regmc)
const path = process.env.DUOFORGE_PS_REFERENCE_DIR + '/dist/sim';
const {TeamValidator} = require(path + '/team-validator');
const {Teams} = require(path + '/teams');
const spec = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));
let bad = 0;
spec.teams.forEach((paste, i) => {
  const v = TeamValidator.get('gen9championsvgc2026regmc');
  const sets = Teams.import(paste);
  const problems = v.validateTeam(sets);
  const stat = sets.map(s => Object.values(s.evs || {}).reduce((a, b) => a + b, 0));
  console.log('team', i + 1, problems ? problems.join(' | ') : 'valid', 'stat points', stat.join(','));
  if (problems) bad++;
});
process.exit(bad ? 1 : 0);
