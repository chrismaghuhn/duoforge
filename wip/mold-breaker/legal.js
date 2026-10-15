// usage: node legal.js Species   -> abilities + which pool moves legal (via validator probing per move list given)
const base=process.env.DUOFORGE_PS_REFERENCE_DIR + '/dist/sim';
const {TeamValidator}=require(base+'/team-validator');
const {Teams}=require(base+'/teams');
const {Dex}=require(base+'/dex');
const v=TeamValidator.get('gen9championsvgc2026regmc');
const sp=process.argv[2];
const abil=process.argv[3]||'';
const moves=(process.argv[4]||'').split(',').filter(x=>x);
const s=Dex.species.get(sp);
console.log(s.name, JSON.stringify(s.abilities), s.types.join('/'), JSON.stringify(s.baseStats));
for(const m of moves){
  const paste=`${sp}${s.gender?'':''} \nAbility: ${abil||s.abilities[0]}\nLevel: 50\nEVs: 2 HP\n- ${m}`;
  const sets=Teams.import(paste);
  const p=v.validateTeam(sets);
  console.log(m, p?('NO '+p.join(' | ').slice(0,90)):'ok');
}
