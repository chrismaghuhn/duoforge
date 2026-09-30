# 0004 — Owner selections: rules basis, reference revision, teams

Status: **owner decisions recorded 2026-09-30**. They are recorded only: nothing in this note is implemented as game mechanics yet. They satisfy the ROADMAP prerequisites before M3 (teams, operational reference commit, rules profile). The conservative mechanics inventory of the resulting closure is a separate artifact.

## Rules basis and profile

- **Rules basis:** Pokémon Champions. The only special battle mechanic is **Mega Evolution** (no Tera, no Z-Moves, no Dynamax). This is the owner's statement, consistent with the pinned Showdown `champions` mod.
- **Format:** `[Gen 9 Champions] VGC 2026 Reg M-C`, Showdown id `gen9championsvgc2026regmc`: mod `champions`, game type doubles, ruleset `Flat Rules`, `VGC Timer`, `Open Team Sheets` (`config/formats.ts` at the pin below).
  - The owner named "Champions"; Reg M-C is the regulation named in the selected team's own format note.
  - Best-of-3 orchestration, timers and ladder behaviour are outside the combat core (ARCHITECTURE §1).
- **Not claimed:** cartridge-perfect behaviour, or VGC compliance of any engine output. Showdown's `champions` mod is a practical reference, not proof of in-game behaviour.

## Operational reference

The owner decision was "take the newest", so the pin is Pokémon Showdown `master` as of 2026-09-30:

| Field | Value |
|---|---|
| Repository | https://github.com/smogon/pokemon-showdown |
| Commit | `b2cb775b0616115b775534eaeff50300e1fc81fc` (2026-09-30T12:00:40-06:00, "National Dex Doubles OU: Ban Marshadow (#12335)"; equal to `HEAD`/`master` per `git ls-remote` on 2026-09-30) |
| License | MIT (`LICENSE` sha256 below) |
| Used for | Reference fixtures, differential tests and data provenance from M3 on. **No Showdown code is vendored or linked into the core.** |

File hashes at the pin (sha256):

| File | sha256 |
|---|---|
| `LICENSE` | `b2002a9fd52ba8db3783a05fbdebfb09c34fd09513b90f6b390a2c0dfbc93ed0` |
| `sim/SIM-PROTOCOL.md` | `d4fea2abe286651a92aeecac54d9ac31b75ae6c2f0d5c667808e93e50a682f56` |
| `sim/battle.ts` | `852dc6eed2876100787090cf049e27d2b061fdb6e808a1edd261468390afaa1f` |
| `sim/side.ts` | `a18946aefe31018162956b1c708a9cce27bb33fe0f098cb58c44d8521d53b1f1` |
| `sim/battle-queue.ts` | `3d9dd71dfb7abc788f961d6123b1b9f7308ccab947af6527f1752dd1d94b95ed` |
| `sim/prng.ts` | `faff50532b3fde14de1a544f759acf466649279f6640e1a3fd0f7dff6fa538bc` |
| `sim/battle-actions.ts` | `a30408e2f9a53a43333bf4a865366d6adbe26d3d91a836ba51042accce4d9437` |
| `sim/pokemon.ts` | `f40260351baf649b15ad3beacfa4269c3418b2da27947af8f5c1097c888ab122` |
| `sim/field.ts` | `3c46a9923736a9a0aaa35791e99d491308c255934553c9d104a0cc2ea453aa79` |
| `data/moves.ts` | `6b44af2a393739e00fc444dc574eaa79659b68867777012b0f7ce4727a9b7734` |
| `data/pokedex.ts` | `73048386b864be5aff093e9393acf32e8016299e9d7b76078bf5120b769e2fe0` |
| `data/abilities.ts` | `818edd100c8eb5bdf4d4ded8dd1b1ce9d394f87f40f7d9d53a5414276e84f82b` |
| `data/items.ts` | `75da206e2cb09868bb549360f38a144c2f50b24e1d189e03b485d550a4f6357a` |
| `data/conditions.ts` | `03ec1b90913f864a0baab0574a70abb856d5e84f722acf96ab11a7601a72fc35` |
| `data/typechart.ts` | `7b0eae126bdcf98edfd71cbe75af00b763f5f0d5db36024b6f3e7c5e4aea95ac` |
| `data/learnsets.ts` | `26969c5e9ca7310b701612da8c9cea217b7d43efb8cd22a7e46783a6ca9b386e` |

The `champions` and `championsregmb` mod files must be hashed and added here when M3 first derives data or fixtures from them.

## Teams

Both teams are level 50, with Champions "stat points" in the `EVs` lines (66 each). They are retrieved from pokepast.es on 2026-09-30 and reproduced below with trailing whitespace trimmed; the sha256 is of the raw paste text.

**Team A: "Balt Top 8"** (author field: "Guest 10677393", note: `Format: gen9championsvgc2026regmc`). Source: https://pokepast.es/470a6ec2468af8a4, raw sha256 `63506178f543ee07dcbfb9902a833982934ab3246729c29d60097588a28b9ca3`.

```text
Rillaboom @ Miracle Seed
Ability: Grassy Surge
Level: 50
EVs: 18 HP / 32 Atk / 2 Def / 6 SpD / 8 Spe
Adamant Nature
- Wood Hammer
- Grassy Glide
- Fake Out
- High Horsepower

Staraptor @ Staraptite
Ability: Intimidate
Level: 50
EVs: 32 HP / 2 SpD / 32 Spe
Jolly Nature
- Brave Bird
- Close Combat
- Tailwind
- Protect

Milotic @ Sitrus Berry
Ability: Competitive
Level: 50
EVs: 32 HP / 29 Def / 5 SpD
Calm Nature
- Muddy Water
- Coil
- Ice Beam
- Hypnosis

Ceruledge @ Grassy Seed
Ability: Flash Fire
Level: 50
EVs: 31 HP / 7 Atk / 24 Def / 3 SpD / 1 Spe
Adamant Nature
- Bitter Blade
- Shadow Sneak
- Swords Dance
- Protect

Raichu @ Raichunite Y
Ability: Lightning Rod
Level: 50
EVs: 29 HP / 5 Def / 32 Spe
Timid Nature
- Zap Cannon
- Focus Blast
- Fake Out
- Protect

Gholdengo @ Life Orb
Ability: Good as Gold
Level: 50
EVs: 17 HP / 2 Def / 17 SpA / 16 SpD / 14 Spe
Modest Nature
- Make It Rain
- Shadow Ball
- Nasty Plot
- Protect
```

**Team B: "Baltimore Regional Finalist"** (author field: "Adi (ck49)"). Source: https://pokepast.es/7c9c0663ef60180e, raw sha256 `08237e5a4f2d926b20490d891a721850d382d34899f9e64ca6c01202e0f07e78`.

```text
Politoed @ Mystic Water
Ability: Drizzle
Level: 50
EVs: 32 HP / 30 SpA / 4 Spe
Modest Nature
- Weather Ball
- Muddy Water
- Ice Beam
- Protect

Golisopod @ Golisopite
Ability: Emergency Exit
Level: 50
EVs: 32 HP / 32 Atk / 1 SpD / 1 Spe
Adamant Nature
- Leech Life
- Iron Head
- Drill Run
- Protect

Archaludon @ Leftovers
Ability: Stamina
Level: 50
EVs: 32 HP / 1 Def / 24 SpD / 9 Spe
Bold Nature
- Dragon Pulse
- Electro Shot
- Snarl
- Protect

Farigiraf @ Sitrus Berry
Ability: Armor Tail
Level: 50
EVs: 29 HP / 20 Def / 17 SpD
Bold Nature
- Psychic
- Grass Knot
- Trick Room
- Protect

Charizard @ Charizardite Y
Ability: Blaze
Level: 50
EVs: 16 HP / 18 Def / 3 SpA / 29 Spe
Timid Nature
- Heat Wave
- Weather Ball
- Hurricane
- Protect

Grimmsnarl (M) @ Light Clay
Ability: Prankster
Level: 50
EVs: 32 HP / 14 Def / 20 SpD
Sassy Nature
- Spirit Break
- Reflect
- Light Screen
- Parting Shot
```

A first candidate for Team A (https://pokepast.es/9088ce7f283bf776) was replaced by the owner because it has no stat points.

## Consequences

- The M2 decision domain needs a side-wide, once-per-battle Mega Evolution declaration: at most one per side per battle, only for the holder of a matching Mega Stone.
- M3 data comes from the pinned `champions` mod, with provenance per record. This includes the Champions stat formula, the PP formula and cap, and Mega formes.
- Setup must reject any team outside the implemented closure explicitly; nothing may be silently ignored.
