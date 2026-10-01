# Third reference team (Team C): research data (draft)

Status: **research draft of 2026-10-01**. It prepares the data for a usage-based third team (Sneasler, Incineroar, Salamence, Indeedee-F, Kingambit, Basculegion). It is not a contract and not a support claim; it changes no engine code, no fixture and no decision. Showdown (pin `b2cb775b0616115b775534eaeff50300e1fc81fc`) stays authoritative; the usage numbers only choose the sets.

| File | Content |
|---|---|
| `pokechamdb-doubles-m6-2026-10-01.json` | Machine-readable snapshot of what the site shows for the six Pokémon (doubles, season M-6): rank, moves, items, abilities, natures, stat point spreads, partners, with the source facts |
| `team-c.txt` | The team as a Showdown paste (`Level: 50`, genders stated, same style as `tests/reference/specs/*.json`) |
| `mechanics.md` | What the closure already supports and what it does not, with Showdown file:line, hooks, draws, risk and a suggested order |
| `validate-team.js` | Validates a paste with the pinned `TeamValidator` for `gen9championsvgc2026regmc` |
| `experiments.js` | 27 assertions behind the "executed" statements of `mechanics.md` (needs the built pin; `PS_ROOT` overrides `C:/Dev/src/pokemon-showdown`) |
| `probe-generator.py` | Read-only probe: which Team C moves and formes `tools/datagen/gen_closure.py` accepts or rejects today |

## Source and how it was read

- Site: https://pokechamdb.com, season **M-6** (the owner confirmed it equals Reg M-C; the site itself only says M-6), format **Doubles**. Ranking page `https://pokechamdb.com/en?format=double&season=M-6&view=pokemon`; per Pokémon `https://pokechamdb.com/en/pokemon/<slug>?season=M-6&format=double` (slugs in the JSON).
- Read on **2026-10-01**. The site's doubles data were last updated 2026-09-30 15:46 PT (2026-09-30T22:46:56Z); its singles data 2026-09-29.
- Method: the built-in Browser pane (JavaScript rendering). The cookie consent dialog was declined, the Doubles toggle clicked, then each of the six pages opened with `format=double`. The rendered English text was parsed and cross-checked, in the same session, against the JSON the page itself loads (`snapshots/pokemon/<slug>.json`, variant `M-6:double`), which carries one-decimal percentages and the stat point rows. After the values were written to the snapshot, the six pages were read a second time and a hash of the canonical values matched the file for all six. No login, no form, no personal data. pokewiki.de was not needed (genders come from Showdown's pokedex).

## How sure: this is the doubles view

High. Evidence, all in the JSON:

- Every Pokémon page header reads "Season M-6 · Doubles · Updated 2026-09-30 15:46 PT" and the URL carries `format=double`.
- The doubles ranking is 1 Rillaboom, 2 Sneasler, 3 Incineroar, 4 Salamence, 5 Indeedee Female, 6 Kingambit, 7 Basculegion; the singles ranking starts Garchomp, Salamence, Primarina. The singles ranks of the six are 15, 86, 2, 85, 35, 20.
- For all six Pokémon the move, item and stat point lists of the variants `M-6:double` and `M-6:single` differ.
- The rendered numbers equal the `M-6:double` values (the page shows floor(pct) from 1 percent upward and one decimal below).
- Singles values were read only to compare; none entered the snapshot.

## Caveats

- **No species usage percent.** The site publishes a rank per Pokémon only. Percentages are shares inside one Pokémon; partners are an ordered top ten without percentages.
- **Marginals, not sets.** Moves, items, abilities, natures and spreads are separate distributions; the site does not say which occur together. The "most common set" is therefore a composite (see Basculegion below). The ten listed spreads cover only 28 (Incineroar) to 75 (Indeedee-F) percent, so spreads are dispersed.
- **Names.** The site's data files use Japanese names; the English names are those of the English page. Every name resolved in the Showdown validator.
- **Third-party, ad-funded, changing.** The numbers move with the ladder. This is a point-in-time record; the SHA-256 of each source file is in the JSON.
- **Stat points.** The site calls them EVs; at most 32 per stat and 66 in total, which are the Champions stat points.

## Derived sets (`team-c.txt`)

Rule applied: top four moves, top item, top ability, top nature, top spread; the Pokémon appear in rank order. The owner changed three points on 2026-10-01 (see Owner decisions): Basculegion's set, Indeedee-F's item and the 50/50 genders.

| Pokémon (rank) | Gender | Item (share) | Ability (share) | Nature (share) | Stat points (share of spreads) | Moves (share) |
|---|---|---|---|---|---|---|
| Sneasler (2) | M | White Herb (31.2) | Unburden (89.1) | Adamant (63.6) | 2 HP / 32 Atk / 32 Spe (46.0) | Close Combat 99.2, Dire Claw 92.4, Protect 64.2, Fake Out 55.5 |
| Incineroar (3) | M | Sitrus Berry (65.6) | Intimidate (99.7) | Careful (36.9) | 32 HP / 14 Def / 20 SpD (9.1) | Fake Out 97.6, Flare Blitz 91.2, Parting Shot 90.9, Darkest Lariat 41.9 |
| Salamence (4) | M | Salamencite (97.6) | Intimidate (98.8) | Timid (52.3) | 2 HP / 32 SpA / 32 Spe (44.4) | Protect 93.6, Hyper Voice 90.6, Draco Meteor 61.4, Tailwind 57.9 |
| Indeedee-F (5) | F | Rocky Helmet (26.5, owner) | Psychic Surge (99.7) | Relaxed (43.5) | 32 HP / 32 Def / 2 SpD (53.3) | Follow Me 97.3, Trick Room 81.6, Helping Hand 79.5, Psychic 62.5 |
| Kingambit (6) | M | Chople Berry (42.0) | Defiant (95.6) | Adamant (81.2) | 32 HP / 32 Atk / 2 SpD (20.0) | Kowtow Cleave 97.5, Sucker Punch 96.8, Iron Head 79.2, Protect 57.8 |
| Basculegion (7) | M | Choice Scarf (45.8) | Adaptability (93.9) | Jolly (44.1, owner) | 2 HP / 32 Atk / 32 Spe (37.9) | Wave Crash 92.8, Last Respects 99.8, Flip Turn 46.4, Aqua Jet 89.9 (owner) |

Decisions and deviations:

- **Item clause: no collision.** The six top items differ. (Sitrus Berry is also Milotic's and Farigiraf's in the closure, but the clause is per team.) **One tie:** Indeedee-F carries Colbur Berry and Rocky Helmet at 26.5 percent each; the owner chose Rocky Helmet.
- **Species clause.** Six different species. Indeedee-F and Basculegion (male) are the formes the site ranks 5 and 7 (Indeedee 25, Basculegion-F 90 are other entries).
- **Stat points: none is a proposal.** Each is the site's top spread and agrees with the top nature (Adamant with an Atk spread, Timid with SpA and Spe, Careful with SpD over Def, Relaxed with Def and without Spe). Each sums to 66.
- **Gender: not published.** From Showdown's pokedex: Indeedee-F (F) and Basculegion (M) are forced; Incineroar is 87.5 percent male; Sneasler, Salamence and Kingambit are 50/50 and male, the owner's standard. Always stated, so battle construction draws no gender.
- **Basculegion is a composite and probably incoherent.** Choice Scarf (45.8) and Protect (51.2) are both literal winners, but the shares mirror each other: Protect 51.2 against 54.2 for all non-Scarf items, and Flip Turn 46.4 against 45.8 for Scarf. So Scarf sets most likely run Flip Turn and not Protect (an inference from marginals only). The owner chose the coherent set: Choice Scarf, Jolly, Wave Crash, Last Respects, Flip Turn, Aqua Jet.
- **Salamence** holds Salamencite (97.6 percent): Intimidate before the Mega, Aerilate after it.

## Validation

`node docs/research/third-team/validate-team.js` (pin checked first) gives for `gen9championsvgc2026regmc`: 6 sets, 66 stat points each, **validator: no problems (team is legal)**. Nothing had to be changed. Negative control: a deliberately broken five-set team is rejected for team size, a stat above 32, totals above 66, illegal moves and abilities, the species clause and the item clause. Also legal in the validator: Basculegion with Flip Turn instead of Protect or with Life Orb, Indeedee-F with Rocky Helmet, Sneasler with Grassy Seed or Psychic Seed, Incineroar with Throat Chop.

## Owner decisions (2026-10-01)

1. **Basculegion** (M) @ Choice Scarf, Adaptability, Jolly, 2 HP / 32 Atk / 32 Spe: Wave Crash, Last Respects, Flip Turn, Aqua Jet.
2. **Indeedee-F** (F) @ Rocky Helmet; the rest of the set as derived.
3. **Scope**: Team C is not part of the closure. It is the expansion track and runs alongside.
4. **Mechanics**: built as they are, no cheaper variants (`mechanics.md` section 9 is kept as a record only).
5. **Gender**: male for every 50/50 species, the standard (Sneasler, Salamence, Kingambit).
