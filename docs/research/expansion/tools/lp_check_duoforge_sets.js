// Do the 18 reference sets in tools/datagen/gen_closure.py validate in the format?
const {Dex, TeamValidator} = require('C:/Dev/src/pokemon-showdown/dist/sim');
const format = Dex.formats.get('gen9championsvgc2026regmc');
const dex = Dex.forFormat(format);
const v = TeamValidator.get(format.id);
const SETS = [
 ['rillaboom','grassysurge','miracleseed',['woodhammer','grassyglide','fakeout','highhorsepower']],
 ['staraptor','intimidate','staraptite',['bravebird','closecombat','tailwind','protect']],
 ['milotic','competitive','sitrusberry',['muddywater','coil','icebeam','hypnosis']],
 ['ceruledge','flashfire','grassyseed',['bitterblade','shadowsneak','swordsdance','protect']],
 ['raichu','lightningrod','raichunitey',['zapcannon','focusblast','fakeout','protect']],
 ['gholdengo','goodasgold','lifeorb',['makeitrain','shadowball','nastyplot','protect']],
 ['politoed','drizzle','mysticwater',['weatherball','muddywater','icebeam','protect']],
 ['golisopod','emergencyexit','golisopite',['leechlife','ironhead','drillrun','protect']],
 ['archaludon','stamina','leftovers',['dragonpulse','electroshot','snarl','protect']],
 ['farigiraf','armortail','sitrusberry',['psychic','grassknot','trickroom','protect']],
 ['charizard','blaze','charizarditey',['heatwave','weatherball','hurricane','protect']],
 ['grimmsnarl','prankster','lightclay',['spiritbreak','reflect','lightscreen','partingshot']],
 ['sneasler','unburden','whiteherb',['closecombat','direclaw','protect','fakeout']],
 ['incineroar','intimidate','sitrusberry',['fakeout','flareblitz','partingshot','darkestlariat']],
 ['salamence','intimidate','salamencite',['protect','hypervoice','dracometeor','tailwind']],
 ['indeedeef','psychicsurge','rockyhelmet',['followme','trickroom','helpinghand','psychic']],
 ['kingambit','defiant','chopleberry',['kowtowcleave','suckerpunch','ironhead','protect']],
 ['basculegion','adaptability','choicescarf',['wavecrash','lastrespects','flipturn','aquajet']],
];
let bad = 0;
for (const [sp, ab, it, mv] of SETS) {
  const s = {name: '', species: dex.species.get(sp).name, item: dex.items.get(it).name, ability: dex.abilities.get(ab).name, moves: mv.map(m => dex.moves.get(m).name), nature: 'Adamant', gender: '', evs: {hp: 2, atk: 0, def: 0, spa: 0, spd: 0, spe: 0}, ivs: {hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31}, level: 50};
  const p = v.validateSet(s, {});
  if (p) { bad++; console.log('INVALID', sp, JSON.stringify(p)); }
}
console.log('DuoForge reference sets validating:', SETS.length - bad, 'of', SETS.length);
