# Champions to 100 %: inventory of the Reg M-C gaps (C0)

Status: **research inventory**, lane A content lane, 2026-10-16. Inventory only: no change to `src/` or `include/`.
Measured on main `4d4bebf8` (library built from that commit, data kind POOL = 6). Showdown pin `b2cb775b`
(the local checkout's HEAD verified). Aggregates only: no player names, no replay ids, no per-game rows; the
per-game files stay in the private dataset directory. Data: [`data/champions-100.json`](data/champions-100.json).

## 0. The number

| | b7 `0bc8d8d9` (old report) | b8 `f779a8e6` (old report) | **main `4d4bebf8` (today)** |
|---|---:|---:|---:|
| games, both sides playable (of 34,430) | 26,540 (77.1 %) | 28,181 (81.9 %) | **28,373 (82.4 %)** |
| team sides playable (of 68,860) | 60,240 (87.5 %) | 62,151 (90.3 %) | **62,361 (90.6 %)** |
| distinct team sheets playable (of 54,270) | 46,822 (86.3 %) | 48,408 (89.2 %) | **48,593 (89.5 %)** |
| distinct blocker tokens | – | 287 | **281** |

The b7 and b8 columns are the reconstruction run against libraries built from those commits; both are identical to the
old reports (section 1.3). Since b8, Psychic Terrain (117 games contain it), Gravity (103), Temper Flare (79),
Excadrite with Mega Excadrill (46) and Speed Swap (30) became supported: +192 games.

16 games carry a name the Reg M-C pool does not have (illegal sets on the server, 51 tokens: Florges-Blue, Flutter
Mane, Assault Vest, ...). They can never become playable; **the ceiling is 34,414 games (99.95 %)**.



## 1. Method (reconstructed, validated)

### 1.1 Source

The 34,430 games are every game of `gen9championsvgc2026regmc` (1,577) and `gen9championsvgc2026regmcbo3` (32,853)
with exactly two `|showteam|` lines in the Hugging Face replay set as downloaded on 2026-10-02 (HolidayOugi
`pokemon-showdown-replays`, `[Gen 9] CHAMPIONS VGC 2026` parts 1-4; private, no licence, never committed). The
private sheet extract of the 2026-10-09 coverage run holds exactly these sheets (same games, same order as the old
`games-*.jsonl`). The newer part 4 of 2026-10-05 adds about 14,400 Reg M-C sheet games (48,800 in all); it is not used
here, so that the numbers stay comparable with 77.1 % / 81.9 %. 

### 1.2 Rules (`tools/research/champions_coverage.py`)

Per side, per member of the packed sheet:

- the species through `duoforge_data_find` (which maps the tables' cosmetic aliases, #118: Vivillon patterns,
  Sinistcha-Masterpiece, ...); no row: `unknown:FORME <name>`, and the member is not read further;
- item, ability, moves and nature through the same lookup; no row: `unknown:ITEM|ABILITY|MOVE|NATURE <name>`;
- a row that `duoforge_data_supported` (POOL) refuses: `item:<id>`, `ability:<id>`, `move:<id>`;
- the item is one of the species' Mega Stones (`duoforge_data_mega_at`) and that Mega Evolution is not supported
  (`mega_info.supported` 0): `mega:<Species>@<Stone>` (in addition to `item:<stone>` when the stone itself is unmarked).

A side is playable when it has no token; a game when both sides are. A distinct team is a distinct sheet text. The
greedy order takes, step by step, the token that is the only blocker of the most remaining games; ties go to the token
first met in game order (`Counter.most_common`), which is what the old script did.

Two details found while reconstructing, both kept so that the numbers stay comparable:

- **The unknown-name skip.** A side with any `unknown:*` token is reported by its unknown tokens alone: the old script
  ran its name pass before the support pass. At b8 this hides support tokens on 9 sides, all of them already blocked
  by the unknown name (Bronzong's Fire Fang, Eelektrossite on a side with Assault Vest, ...). It changes no count of
  playable games or sides.
- **The create check with the #512 placeholder.** The old reports count "create-accepted-but-blocked notes": sides
  that `duoforge_battle_create` (the side against itself) accepts although a token blocks them; 0 then and now. A sheet
  shows no Stat Points, and an empty nature field means Serious. Since #406 setup refuses exactly 0 Stat Points with
  Serious (the pinned validator does), so with 0 Stat Points today's main refused 1,949 blocker-free sides with
  `E_INVALID_ARGUMENT`. The check now uses `SP_PLACEHOLDER` of #512 (one point in HP, `duoforge_live/teams.py`):
  0 refusals of blocker-free sides on main, and b8 is unchanged (0 notes, identical rows).

### 1.3 Validation

Libraries were built (under the machine lock) from the exact commits of two old reports, each run with its own
`python/duoforge` package:

| commit | games playable | sides | distinct | blocker kinds (game-weighted) | per-side rows vs old `games-*.jsonl` | greedy order |
|---|---:|---:|---:|---|---|---|
| b8 `f779a8e6` | 28,181 | 62,151 | 48,408 / 54,270 | ability 3,525, item 1,910, mega 1,019, move 5,448, unknown 51 | 68,860 / 68,860 identical | lines 1-35 of `report-b8.txt` byte-identical |
| b7 `0bc8d8d9` | 26,540 | 60,240 | 46,822 / 54,270 | move 7,584, ability 4,254, item 2,212, mega 1,019, unknown 51 | 68,860 / 68,860 identical | – |

The difference to the old method is zero.

### 1.4 Usage weights

- **Games** (both sides playable) and **team sides**: from the run above. "In games" counts games that contain the
  token; "alone" counts games where it is the only blocker.
- **Turns and move uses**: pending: the per-token turns, `|move|` uses and brought counts are implemented in `champions_coverage.py --replays` but need pyarrow to read the parquet files; not yet run.
- **Smogon** (secondary; the public monthly statistics 2026-09 of `gen9championsvgc2026regmc`, 1,631,943 Bo1 ladder
  battles, and of the Bo3 ladder): share of team slots (Pokémon) carrying an entry. Only the aggregate coverage below is
  written here; per-entry shares stay out of the repository (the content lane's rule) and went to the lead with the
  report.
- **Arena teams** (the two private open-sheet arena teams of 2026-10-12): both fully playable today.

The greedy order over today's blockers (section 3) reaches 85 % after 10 gaps, 90 % after 48, 95 % after 117 and 99 %
after 240 of the 281 tokens. Usage-weighted on Smogon's public 2026-09 statistics of the same format (share of team
slots on supported entries, the content lane's measure; aggregates only): moves / abilities / items 98.7 / 97.0 /
98.6 % at baseline 0, 99.6 / 98.8 / 99.5 % at 1760, and 99.9 / 99.7 / 99.8 % on the Bo3 ladder at 1760. The games
metric is stricter: one unsupported entry anywhere on either sheet blocks the game.

## 2. What is missing

Measured with the library of main against the pool files `data/formats/pools/reg-mc.json` and `champions-ou.json`:

| | Reg M-C pool | supported | gaps | of them in ≥ 1 replay game | in the Champions OU pool |
|---|--:|--:|--:|--:|--:|
| moves | 510 | 343 | 167 | 140 | 162 |
| abilities | 215 | 126 | 89 | 76 | 88 |
| items (incl. Mega Stones) | 166 | 133 | 33 | 30 | 31 |
| Mega Evolutions (`mega_info.supported` 0 or stone unmarked) | 82 | 67 | 15 | 12 (3 more blocked only through their stone) | 15 |
| battle-only formes missing from the tables | 7 | 1 | 6 | – | 5 |
| selectable formes | 293 | 293 | 0 | – | – |

Every selectable forme of the pool is a row of the tables (cosmetic formes through aliases). The six missing
battle-only formes are Castform-Sunny/-Rainy/-Snowy, Mimikyu-Busted, Morpeko-Hangry and Palafin-Hero; each waits on its
ability (Forecast, Disguise, Hunger Switch, Zero to Hero). 49 gaps never occur in the 34,430 games.

Every gap is listed in section 5 under its batch, and in the data file with its pin lines, the closest engine code,
its family and a note. The classification (area, `turn.c` core parts, effort, dependencies, new public values) was
read from the pin (Champions mod first) and the engine at `4d4bebf8` by seven read-only agents, one per slice, with
file:line citations in the data file; every entry is marked `basis: read`. C0 spot-checked the top entries against the
content lane's private effort notes of 2026-10-15 (see section 8). `classify_unsupported.py`'s own class
(modelled-unmarked / data-only / hand-work) is kept beside it.

**Effort scale.** S: a mark or generator row plus recordings, or one more member of an existing family. M: one new
handler or hook with a few interactions. L: new state, a new public value or engine concept, or many interactions.
For batch sums the units are S = 1, M = 3, L = 8 (a convention for ranking, not a time estimate; Mega rows that share
their stone's cause are not counted twice).

**Core of `turn.c`.** The column names the core parts a gap must touch: `flow` (queue, switching, entries, Update),
`move_body` (`dfi_run_move_body` and its helpers: hit loop, TryHit, secondaries), `damage` (`dfi_get_damage` and the
modifier chain), `residual` (`dfi_residual_events_run`). "–" means the work is a mark, a generator row, or a member of
a family that already lives in a moved area (`src/combat/items`, `field`, `forms`, `abilities`, `moves`). Of the 310
gaps, 69 are S without any core part, 62 are S with one clause in a core function, 120 are M and 59 are L, all of them
in the core.

### 2.1 Partial support (marked, with a named refusal path)

Marked mechanics still refuse some situations by name (`DUOFORGE_E_UNSUPPORTED`). The catalogue reads every refusal
return in `src/combat/**`, `request.c` and `battle.c` (104 in `turn.c`): 7 wait for a decision (Illusion 0026 and Baton Pass/Ally Switch cases), 25 leave out a rare case of a marked mechanic, 11 refuse an unmodelled handler order, 9 an unmodelled tie or draw, 2 a full fixed list (proved unreachable) and 25 are defensive. Defensive returns
(never reached) are left out of the table; the encoder, view, digest and search refusals are API limits, not
mechanics. None of the most used mechanics (Fake Out, Protect, Intimidate, Tailwind, Trick Room, the terrains,
Unburden, Sitrus Berry, Choice Scarf) has a refusal of its own; they appear only in rare combinations. The ones a real
game reaches most often (all "uncommon", a guess from reading): Dragon Darts into two stopped targets or into a
Substitute / Red Card / Eject Button, Upper Hand into a Prankster or Gale Wings holder, Mega Meganium's weather moves
outside sun, an Outrage user stopped by a flinch or paralysis, and the Illusion cases that wait for decision 0026.

| where | kind | core | entries | refuses | frequency (guess) |
|---|---|---|---|---|---|
| turn.c:10006 | api-pending | other | frisk, illusion | Frisk against a foe whose Illusion disguise is up and that holds an item. | rare (guess) |
| turn.c:5257 | api-pending | move_body | allyswitch, illusion | Ally Switch when the user or its partner has Illusion. | uncommon (guess; needs Zoroark beside an Ally Switch user) |
| turn.c:6420 | api-pending | move_body | batonpass, encore, disable | Baton Pass with Encore or Disable on the passer. | rare (guess; Encore on a passer) |
| turn.c:6427 | api-pending | move_body | batonpass, illusion | Baton Pass while an Illusion name is shown on the passer's side. | rare (guess; Zoroark + Baton Pass team) |
| turn.c:9792 | api-pending | flow | illusion | An Illusion holder entering whose disguise would be the other active Pokemon (every bench member to its right fainted). | uncommon (guess; late game with Zoroark) |
| turn.c:9804, turn.c:9811, turn.c:9822 | api-pending | flow | illusion | Illusion one-name-per-side conflicts: the shown name's real member entering while the holder is disguised as it, an Illusion holder needing a second name, or the real member entering while a disguised holder lies fainted. | rare (guess) |
| turn.c:9829 | api-pending | flow | illusion, revivalblessing | An instaswitch (revive) that would also be disguised by Illusion. | rare (guess) |
| turn.c:10041 | unmodelled-case | other | trace | Trace with no copyable foe ability (seeking at later Updates). | rare (guess; foes are Trace/Illusion/Stance Change) |
| turn.c:10053, turn.c:10058, turn.c:10... | unmodelled-case | other | trace, limber, waterbubble, magmaarmor, oblivious | Trace copying an ability whose onUpdate would act at once: Limber while paralysed, Water Bubble while burned, Magma Armor while frozen, Oblivious while taunted. | rare (guess) |
| turn.c:10072 | unmodelled-case | other | trace, cloudnine | Trace copying Cloud Nine. | rare (guess) |
| turn.c:10256 | unmodelled-case | move_body | skillswap, limber, thermalexchange, oblivious, magmaarmor | Skill Swap that hands an ability whose onUpdate would act at once (Limber/paralysis, Thermal Exchange/burn, Oblivious/taunt, Magma Armor/freeze). | rare (guess) |
| turn.c:11812 | unmodelled-case | flow |  | A singles battle reaching turn 101 (Endless Battle Clause not modelled). | rare (guess; singles only, not Reg M-C doubles) |
| turn.c:12154 | unmodelled-case | flow | outrage, fakeout | A lockedmove user (Outrage) stopped before its move (flinch, full paralysis, freeze, confusion) while not asleep, keeping the lock into the residual. | uncommon (guess; Fake Out or paralysis on an Outrage user) |
| turn.c:12173 | unmodelled-case | flow | whiteherb, rockyhelmet | A spread-move user that fainted during its move while a White Herb's AnyAfterMove would matter (runMove's target undrawn). | rare (guess) |
| turn.c:1684 | unmodelled-case | damage | stompingtantrum, temperflare | Stomping Tantrum / Temper Flare when the user's last move result was not classified exactly (bit 5 UNCLASSIFIED_LAST). | rare (guess; needs an unclassified engine exit the turn befo |
| turn.c:1750 | unmodelled-case | damage | lastrespects, revivalblessing | Last Respects when a brought member of the user's side has spent Revival Blessing PP (totalFainted no longer equals the 0-HP roster count). | rare (guess; both moves on one team) |
| turn.c:2284 | unmodelled-case | other | leafguard, megasol | Leaf Guard's sun test while a Mega Sol holder stands and the field is not sun (per-move effectiveWeather not modelled). | rare (guess; needs Leaf Guard + Mega Meganium) |
| turn.c:3303, turn.c:3307 | unmodelled-case | other | symbiosis, whiteherb, grassyseed, psychicseed | Symbiosis passing an item to a user that still holds one (defensive), or an item whose Start uses it at once (White Herb with a lowered stat, Grassy/Psychic Seed under its terrain); returned via r->deferred. | rare (guess; needs Symbiosis + herb/seed condition) |
| turn.c:3338 | unmodelled-case | move_body | trick, switcheroo, whiteherb, grassyseed, psychicseed | Trick/Switcheroo that would give a White Herb to a Pokemon with a lowered stat or a Grassy/Psychic Seed under its terrain (item Start on setItem). | rare (guess) |
| turn.c:3391 | unmodelled-case | move_body | thief, covet, whiteherb, grassyseed, psychicseed | Thief/Covet stealing a White Herb onto a stat-lowered user or a terrain seed under its terrain. | rare (guess) |
| turn.c:4368, turn.c:6149 | unmodelled-case | move_body | doubleshock | Double Shock by an Electric-type user that is not Pawmot (dex 923) with exactly Electric/Fighting types. | rare (guess; only Pawmot learns it, needs a type change) |
| turn.c:5282 | unmodelled-case | move_body | allyswitch, healingwish | Ally Switch with a pending Healing Wish on either slot (the arrival's onSwap heal is not modelled). | rare (guess; pending Healing Wish slot) |
| turn.c:5588 | unmodelled-case | move_body | lifedew, healpulse, psychicnoise | A heal move (Life Dew, Heal Pulse) on an ally target under Heal Block (Psychic Noise). | rare (guess; Psychic Noise then ally heal) |
| turn.c:5942, turn.c:5948, turn.c:5952 | unmodelled-case | move_body | tripleaxel, populationbomb, compoundeyes, widelens, snowcloak ... | A later hit of Triple Axel/Population Bomb with a Compound Eyes or Wide Lens user, a Snow Cloak/Sand Veil target in its weather, or a Bright Powder target (ModifyAccuracy after the stages). | rare (guess) |
| turn.c:6371 | unmodelled-case | move_body | bellydrum, contrary | Belly Drum by a Contrary holder (ChangeBoost reverses the +12). | rare (guess) |
| turn.c:6424 | unmodelled-case | move_body | batonpass, choicescarf, outrage, electroshot | Baton Pass with a move lock, two-turn charge, recharge, Protect volatile or Choice lock on the passer. | rare (guess; Choice Scarf Baton Pass) |
| turn.c:7276 | unmodelled-case | move_body | magicbounce, followme, ragepowder | A Magic Bounce whose bounced move would be redirected by a Follow Me/Rage Powder holder on the original user's side. | rare (guess) |
| turn.c:7435 | unmodelled-case | move_body | dragondarts, substitute, redcard, ejectbutton | Dragon Darts split over two targets when either has a Substitute, a Red Card or an Eject Button. | uncommon (guess; Dragapult into a Substitute or Eject Button |
| turn.c:7557 | unmodelled-case | move_body | megasol, solarbeam, weatherball, electroshot, cloudnine | A Mega Sol holder's weather-reading move (Solar Beam, Weather Ball, Thunder, Hurricane) outside sun, or any of them plus Electro Shot while Cloud Nine suppresses weather. | uncommon (guess; Mega Meganium Weather Ball outside sun) |
| turn.c:8119 | unmodelled-case | move_body | upperhand, prankster, galewings | Upper Hand against a target with Prankster or Gale Wings (its queued priority may exceed the table). | uncommon (guess; Upper Hand into Prankster support) |
| turn.c:9272 | unmodelled-case | move_body | dragondarts, rockyhelmet | Dragon Darts split over two targets when the user faints mid-move (e.g. Rocky Helmet). | rare (guess) |
| turn.c:9778 | unmodelled-case | flow | revivalblessing, regenerator | An instaswitch (Revival Blessing revive) of a Regenerator holder. | rare (guess) |
| turn.c:11519 | interaction-order | residual | protect, perishsong | The battle ends at a standing Pokemon's no-order handler (stall counter, charge, recharge) while its other no-order handler also ends. | rare (guess; game-ending Perish + Protect) |
| turn.c:12183, turn.c:12206 | interaction-order | flow | outrage, whiteherb | A lockedmove ending with confusion in the same AfterMove as a White Herb that would act (order not modelled). | rare (guess) |
| turn.c:2135 | interaction-order | damage | glaiverush, lifeorb, expertbelt, chopleberry, reflect ... | Three or more ModifyDamage modifiers whose chained value depends on their (speed-sorted, unmodelled) order, e.g. Glaive Rush x2 with Life Orb + resist berry + screen, or Expert Belt + berry + Glaive Rush. | rare (guess; needs Glaive Rush state or 3+ odd modifiers on  |
| turn.c:2344, turn.c:2358, turn.c:2371 | interaction-order | other | thermalexchange, waterbubble, limber, flowerveil | A burn on a Thermal Exchange / Water Bubble holder, or a paralysis on a Limber holder, that is also a Grass type covered by a Flower Veil holder (SetStatus handler order). | rare (guess; needs Flower Veil on field) |
| turn.c:2399 | interaction-order | other | leafguard, flowerveil | A status on a Leaf Guard holder in sun that is also covered by a Flower Veil holder (handler order). | rare (guess; needs Flower Veil + sun) |
| turn.c:4709 | interaction-order | move_body | perishsong, prankster | Perish Song with positive priority (Prankster), which would meet Psychic Terrain's and Armor Tail's TryHit. | rare (guess; Prankster Perish Song user) |
| turn.c:5337 | interaction-order | move_body | yawn, leafguard, flowerveil | Yawn on a Leaf Guard holder in sun on a side with a Flower Veil holder (TryAddVolatile order). | rare (guess) |
| turn.c:6955 | interaction-order | move_body | widelens, brightpowder | A Wide Lens attacker against a Bright Powder target when the two ModifyAccuracy orders round apart. | rare (guess) |
| turn.c:7283, turn.c:7288 | interaction-order | move_body | magicbounce, prankster, psychicsurge, psychicterrain, armortail | A Prankster-boosted bounced move under Psychic Terrain or with an Armor Tail holder on the original user's side. | rare (guess; Prankster into Magic Bounce under Psychic Terra |
| turn.c:7698 | interaction-order | move_body | followme, ragepowder | Two active redirectors (Follow Me / Rage Powder) on the same side for one single-target move. | rare (guess; two redirectors same turn) |
| turn.c:8180 | interaction-order | move_body | psychicterrain, psychicsurge, prankster, howl | A positive-priority move with more than one target under Psychic Terrain (per-target TryHit order). | rare (guess; Prankster multi-target status move in Psychic T |
| turn.c:10957 | tie-or-draw | residual | encore, disable, taunt, yawn, perishsong ... | A residual handler list whose result depends on the unrecorded volatile insertion order (dfi_residual_order_ambiguous; needs a tied callback group). | rare (guess; needs speed tie + several volatiles) |
| turn.c:11318 | tie-or-draw | residual | tailwind, reflect, lightscreen, auroraveil | The same side condition on both sides, one ending and one not, with a faint still queued (the tie shuffle decides line order). | rare (guess; Tailwind/screen mirror + queued faint, e.g. Per |
| turn.c:11340 | tie-or-draw | residual | tailwind, reflect, lightscreen, auroraveil | The battle ends at a side condition's countdown while the other side's same condition still had to count down. | rare (guess; game-ending residual faint in a Tailwind/screen |
| turn.c:11411 | tie-or-draw | residual | whiteherb | Two White Herb holders due in the same equal-speed group at order 29. | rare (guess) |
| turn.c:11523, turn.c:11576 | tie-or-draw | residual | protect, helpinghand | The battle ends at a no-order handler with an equal-Speed neighbour holding such handlers (or a tie group bigger than Protect's pair). | rare (guess; speed tie) |
| turn.c:6730 | tie-or-draw | move_body | dragondarts, protect, spikyshield, kingsshield, banefulbunker ... | Dragon Darts whose two split targets are both stopped (Protect, guards): the second stop's line order is a speed-tie draw. | uncommon (guess; double Protect into Dragapult) |
| turn.c:7918 | tie-or-draw | move_body | magicbounce, stealthrock, spikes, toxicspikes | A reflectable hazard move against a side with two Magic Bounce holders (TryHitSide speed order). | rare (guess) |
| turn.c:8261 | tie-or-draw | move_body | spikyshield, kingsshield, banefulbunker | A contact move stopped by two punishing protect variants (Spiky Shield, King's Shield, Baneful Bunker) whose lines are speed-sorted. | rare (guess) |
| turn.c:9367 | tie-or-draw | move_body | ejectbutton | Two Eject Button holders hit by one move with an exact speed tie. | rare (guess) |
| items/families.c:30 | capacity | – | chopleberry, occaberry, yacheberry, shucaberry, cobaberry | A resist berry's 2048 modifier pushed onto a full 6-slot ModifyDamage list. | rare (guess; bound proven in damage_chain.h) |
| turn.c:2026, turn.c:2034, turn.c:2062... | capacity | damage | lifeorb, expertbelt, glaiverush, reflect, lightscreen ... | A seventh ModifyDamage modifier pushed onto the 6-slot commutation list (DFI_MODIFY_DAMAGE_MAX). | rare (guess; damage_chain.h proves 6 is the bound, so effect |

The runtime stops of the replay pipeline (the M11 funnel: Forme Change, Partial Trap, Roost, Protean type change,
Substitute, charge targets) are the Python tracker's limits, not engine refusals; they are not counted here.

## 3. Weighted by usage: greedy order (main `4d4bebf8`)

Cumulative games with both sides playable if the gaps are supported in this order (the first 40 of 281; the data file
has all of them). "In games" counts the games that still contain the token at that step.

| step | gap | + games | games playable | in games |
|--:|---|--:|--:|--:|
| 1 | `move:meteorassault` | 157 | 28,530 (82.9 %) | 234 |
| 2 | `ability:protean` | 129 | 28,659 (83.2 %) | 350 |
| 3 | `ability:pickpocket` | 95 | 28,754 (83.5 %) | 136 |
| 4 | `ability:magician` | 78 | 28,832 (83.7 %) | 111 |
| 5 | `move:payback` | 77 | 28,909 (84.0 %) | 123 |
| 6 | `move:bittermalice` | 74 | 28,983 (84.2 %) | 192 |
| 7 | `move:metalburst` | 69 | 29,052 (84.4 %) | 79 |
| 8 | `move:focusenergy` | 68 | 29,120 (84.6 %) | 190 |
| 9 | `move:snipeshot` | 102 | 29,222 (84.9 %) | 168 |
| 10 | `ability:disguise` | 67 | 29,289 (85.1 %) | 107 |
| 11 | `ability:supremeoverlord` | 53 | 29,342 (85.2 %) | 114 |
| 12 | `item:leppaberry` | 53 | 29,395 (85.4 %) | 83 |
| 13 | `move:instruct` | 51 | 29,446 (85.5 %) | 93 |
| 14 | `move:wish` | 52 | 29,498 (85.7 %) | 111 |
| 15 | `move:highjumpkick` | 47 | 29,545 (85.8 %) | 179 |
| 16 | `ability:libero` | 95 | 29,640 (86.1 %) | 160 |
| 17 | `move:worryseed` | 59 | 29,699 (86.3 %) | 84 |
| 18 | `move:pollenpuff` | 49 | 29,748 (86.4 %) | 95 |
| 19 | `move:mirrorcoat` | 49 | 29,797 (86.5 %) | 73 |
| 20 | `move:lastresort` | 45 | 29,842 (86.7 %) | 72 |
| 21 | `move:painsplit` | 44 | 29,886 (86.8 %) | 87 |
| 22 | `ability:furcoat` | 44 | 29,930 (86.9 %) | 59 |
| 23 | `move:hex` | 42 | 29,972 (87.1 %) | 112 |
| 24 | `ability:electromorphosis` | 46 | 30,018 (87.2 %) | 73 |
| 25 | `ability:cudchew` | 42 | 30,060 (87.3 %) | 62 |
| 26 | `item:normalgem` | 41 | 30,101 (87.4 %) | 60 |
| 27 | `ability:moldbreaker` | 41 | 30,142 (87.5 %) | 223 |
| 28 | `move:gigatonhammer` | 104 | 30,246 (87.8 %) | 189 |
| 29 | `ability:owntempo` | 67 | 30,313 (88.0 %) | 99 |
| 30 | `move:mortalspin` | 45 | 30,358 (88.2 %) | 77 |
| 31 | `ability:healer` | 41 | 30,399 (88.3 %) | 62 |
| 32 | `ability:icebody` | 41 | 30,440 (88.4 %) | 68 |
| 33 | `ability:surgesurfer` | 40 | 30,480 (88.5 %) | 62 |
| 34 | `ability:insomnia` | 39 | 30,519 (88.6 %) | 59 |
| 35 | `move:firefang` | 39 | 30,558 (88.8 %) | 62 |
| 36 | `move:magicpowder` | 39 | 30,597 (88.9 %) | 52 |
| 37 | `item:chesnaughtite` | 38 | 30,635 (89.0 %) | 70 |
| 38 | `item:quickclaw` | 37 | 30,672 (89.1 %) | 91 |
| 39 | `ability:wanderingspirit` | 36 | 30,708 (89.2 %) | 57 |
| 40 | `ability:heatproof` | 35 | 30,743 (89.3 %) | 41 |

Per gap, the games containing it, the games where it is the only blocker, team sides and the greedy step are in
section 5 and in the data file. Turn and move-use weights are pending: they need the replay logs, and no parquet reader is installed on this machine (the lead has asked the owner about installing pyarrow).

## 4. Batch proposal

The batches group gaps by shared mechanic and by the part of the engine they touch, in an order of benefit per effort
that respects the dependencies (a Mega waits for its ability, Jet Punch for Zero to Hero, Gigaton Hammer for a marked
Tinkaton ability, Mirror Coat and Counter for Metal Burst). "Alone" is what the batch unlocks if only it lands;
"cumulative" follows the order of the table (tool: `champions_batches.py`).

| batch | entries (S/M/L) | effort units | alone: games / sides | cumulative games | cumulative sides | turn.c core parts | entries outside the core | new public values |
|---|---|--:|--:|--:|--:|---|--:|--:|
| **A0** Marks and generator rows (no turn.c code) | 47 (47/0/0) | 45 | +498 / +547 | 28,871 (83.9 %) | 62,908 (91.4 %) | none | 47 | 0 |
| **A1** Damage chain: one more member of an existing modifier/base-power branch | 25 (22/3/0) | 31 | +246 / +283 | 29,148 (84.7 %) | 63,219 (91.8 %) | damage, residual | 0 | 0 |
| **A2** One clause on an existing move-body, entry or residual hook | 42 (39/3/0) | 43 | +716 / +815 | 29,983 (87.1 %) | 64,156 (93.2 %) | damage, flow, move_body, residual | 5 | 0 |
| **P** Paused lane A branches (finish after re-sync) | 7 (0/3/4) | 41 | +297 / +330 | 30,351 (88.1 %) | 64,552 (93.7 %) | damage, flow, move_body | 0 | 4 |
| **B1** Protean / Libero (+ Mega Greninja, Mimicry's type storage) | 5 (1/4/0) | 10 | +203 / +235 | 30,658 (89.0 %) | 64,884 (94.2 %) | flow, move_body | 1 | 0 |
| **B2** Item steal: Pickpocket, Magician | 2 (0/2/0) | 6 | +170 / +182 | 30,862 (89.6 %) | 65,093 (94.5 %) | move_body | 0 | 0 |
| **B3** Mold Breaker (+ Mega Gyarados, Ampharos, Emboar; Gigaton Hammer) | 8 (3/1/4) | 14 | +361 / +403 | 31,298 (90.9 %) | 65,555 (95.2 %) | damage, flow, move_body | 3 | 0 |
| **B4** Forme abilities: Zero to Hero, Disguise, Hunger Switch, Forecast | 12 (7/2/3) | 37 | +184 / +210 | 31,541 (91.6 %) | 65,822 (95.6 %) | damage, flow, move_body, residual | 7 | 1 |
| **B5** Mega abilities: Berserk, Eelevate, Innards Out/Aftermath, Healer/Hydration, Strong Jaw, Parental Bond | 20 (7/11/2) | 33 | +211 / +255 | 31,818 (92.4 %) | 66,136 (96.0 %) | damage, flow, move_body, residual | 6 | 0 |
| **B6** Common move-body mechanics (M): crash, removal, pivots, self-KO, absorb, veils | 51 (0/49/2) | 163 | +421 / +485 | 32,694 (95.0 %) | 67,074 (97.4 %) | damage, flow, move_body, residual | 0 | 6 |
| **B7** Flow and residual hooks (M): Supreme Overlord, entry abilities, priority tiers, cures | 13 (0/13/0) | 39 | +96 / +115 | 32,888 (95.5 %) | 67,276 (97.7 %) | damage, flow, move_body, residual | 0 | 2 |
| **B8** Berries and held items (M) | 18 (5/11/2) | 54 | +198 / +227 | 33,242 (96.5 %) | 67,646 (98.2 %) | damage, flow, move_body, residual | 0 | 2 |
| **B9** Ability change and copy (Skill Swap machinery) | 7 (0/5/2) | 31 | +89 / +98 | 33,442 (97.1 %) | 67,853 (98.5 %) | move_body | 0 | 2 |
| **B10** HP, heal and sleep (Pain Split, Wish, Rest, Sleep Talk, ...) | 8 (0/5/3) | 39 | +117 / +143 | 33,788 (98.1 %) | 68,203 (99.1 %) | damage, flow, move_body, residual | 0 | 3 |
| **C** New state or engine concepts (L): Transform/Imposter, Instruct, Future Sight, traps, rooms, stockpile, ... | 45 (0/8/37) | 320 | +227 / +269 | 34,414 (100.0 %) | 68,837 (100.0 %) | damage, flow, move_body, residual | 0 | 39 |

**Before the restructure ends.** A0 touches no `turn.c` code at all (marks, generator rows, recordings; about 500 games
alone, mostly through stale refusal reasons: Meteor Assault, Horn Leech and Bitter Malice were blocked by abilities or
gaps that are marked or fixed since). It can start now. A1 and A2 add one clause each to existing branches inside
`dfi_get_damage` and the move body; they are small but conflict with the restructure's phase cuts of exactly those
functions, so they are best done right after the damage and move-body phases are cut, or batched with them by the
restructure lane. Everything from P on needs the core.

**Order rationale.**

1. **A0** (S, no core): the largest benefit per effort; one evidence campaign for many rows.
2. **A1, A2** (mostly S, one clause each): 67 entries, +246 and +716 games alone.
3. **P** (paused branches): engine work largely done; the cost is the re-sync and the open evidence (section 7).
4. **B1 Protean/Libero**, **B2 item steal**, **B3 Mold Breaker**: the three largest single mechanics. Mold Breaker is
   L (19 "no Mold Breaker is marked" assumptions in `turn.c`) but unlocks three Megas and Gigaton Hammer.
5. **B4 forme abilities** and **B5 Mega abilities**: each Mega and battle-only forme is cheap once its ability lands.
6. **B6–B10**: the M long tail by engine part.
7. **C**: 45 L entries with new state or public values (Transform/Imposter, Instruct, Future Sight, traps, Wish,
   rooms, Stockpile, Fling, ...): +227 games alone for about 320 effort units; each needs its own decision note.

## 5. Every gap, by batch

Columns: games that contain the gap; games where it is the only blocker; greedy step (section 3; "–" when a
co-blocker, e.g. the Mega row of a stone, carries the count); area; `turn.c` core parts; effort; new public values;
family and dependencies. "(not in Champions OU)" marks the nine gaps outside the singles pool.

### A0: Marks and generator rows (no turn.c code)

| gap | in games | alone | greedy | area | core | E | new values | family / depends on |
|---|--:|--:|--:|---|---|:-:|:-:|---|
| `move:meteorassault` | 234 | 157 | 1 | move | – | S | no | mark only (modelled, no recording) |
| `move:bittermalice` | 192 | 74 | 6 | move | – | S | no | plain data rows awaiting a recording — needs: Illusion duplicate-name gap (support_manifest.c:585-586) |
| `move:watershuriken` | 88 | 1 | 156 | move | – | S | no | multihit 2-5 (Icicle Spear, Rock Blast, Tail Slap, Bullet Seed, Water Shuriken) |
| `item:chesnaughtite` | 70 | 32 | 37 | item | – | S | no | Mega Stone mark (generic Mega path) — needs: mega:chesnaught@chesnaughtite (same cause) |
| `move:storedpower` | 62 | 12 | 70 | move | – | S | no | positive-stage power (Power Trip, Stored Power) |
| `move:shelter` | 59 | 27 | 44 | move | – | S | no | self boost status move — needs: converter fix: Goodra-Hisui switch id (tools/reference/trace_to_c.py swap_partners) |
| `move:rockblast` | 56 | 12 | 101 | move | – | S | no | multihit 2-5 (Icicle Spear, Rock Blast, Tail Slap, Bullet Seed, Water Shuriken) |
| `item:altarianite` | 49 | 23 | 48 | item | – | S | no | Mega Stone mark (generic Mega path) — needs: mega:altaria@altarianite (same cause) |
| `move:bulletseed` | 44 | 10 | 91 | move | – | S | no | random multi-hit 2-5 (Icicle Spear, Bone Rush, Bullet Seed) |
| `move:aircutter` | 42 | 28 | 41 | move | – | S | no | plain data rows awaiting a recording |
| `move:hornleech` | 40 | 0 | 164 | move | – | S | no | mark only (modelled, no recording) |
| `move:pinmissile` | 37 | 0 | 248 | move | – | S | no | multi-hit 2-5 (Icicle Spear, Bullet Seed, Rock Blast) |
| `move:whirlpool` | 34 | 19 | 68 | move | – | S | no | partial trap (Bind, Wrap, Fire Spin, Sand Tomb, Infestation, Snap Trap, Whirlpool) — needs: move:dive (x2 against a diver, unmarked) |
| `move:decorate` | 33 | 0 | 122 | move | – | S | no | primary target boosts (Charm, Howl, Cotton Spore) |
| `move:heatcrash` | 31 | 15 | 86 | move | – | S | no | weight BP (Heavy Slam, Heat Crash) |
| `move:dragonrush` | 21 | 4 | 138 | move | – | S | no | plain data rows awaiting a recording |
| `move:crabhammer` | 20 | 13 | 83 | move | – | S | no | plain data rows awaiting a recording |
| `move:stringshot` | 19 | 11 | 95 | move | – | S | no | spread status stat drop (allAdjacentFoes boosts) |
| `move:bite` | 18 | 4 | 135 | move | – | S | no | plain data rows awaiting a recording |
| `ability:whitesmoke` | 17 | 9 | 142 | ability | – | S | no | drop guard (Clear Body, White Smoke) |
| `move:crosschop` | 17 | 10 | 105 | move | – | S | no | plain data rows awaiting a recording |
| `move:solarblade` | 15 | 7 | 104 | move | – | S | no | two-turn charge (Solar Beam, Electro Shot, Phantom Force, Sky Attack) |
| `move:thrash` | 10 | 9 | 140 | move | – | S | no | lockedmove (Outrage, Thrash, Petal Dance) |
| `move:cottonspore` | 8 | 2 | 145 | move | – | S | no | primary target boosts (Charm, Howl, Cotton Spore) |
| `ability:gluttony` | 7 | 0 | 173 | ability | – | S | no | pinch berry threshold (Gluttony) |
| `move:nightdaze` | 7 | 4 | 153 | move | – | S | no | mark only (modelled, no recording) — needs: Illusion duplicate-name refusal (decision 0026 section 4) |
| `move:snaptrap` | 7 | 0 | 259 | move | – | S | no | partial trap (Bind, Wrap, Fire Spin, Sand Tomb, Infestation, Snap Trap, Whirlpool) |
| `item:shedshell` | 6 | 3 | 171 | item | – | S | no | trap escape (Shed Shell, Run Away) — needs: ability:runaway (same handlers in the Champions mod) |
| `move:ragingfury` | 6 | 3 | 163 | move | – | S | no | locked move (Outrage lock) |
| `move:sweetscent` | 3 | 0 | 186 | move | – | S | no | spread status stat drop (allAdjacentFoes boosts) |
| `move:bonerush` | 2 | 2 | 211 | move | – | S | no | random multi-hit 2-5 (Icicle Spear, Bone Rush, Bullet Seed) |
| `move:mountaingale` | 1 | 0 | 227 | move | – | S | no | mark only (modelled, no recording) — needs: converter fix for Avalugg-Hisui (swap_partners KeyError) |
| `ability:runaway` | 0 | 0 | – | ability | – | S | no | anti-trap (Run Away in Champions, Shed Shell) |
| `mega:altaria@altarianite` | 0 | 0 | – | item | – | S | no | Mega Stone mark (generic Mega path) — needs: item:altarianite (same cause) |
| `mega:chesnaught@chesnaughtite` | 0 | 0 | – | item | – | S | no | Mega Stone mark (generic Mega path) — needs: item:chesnaughtite (same cause) |
| `move:aromaticmist` | 0 | 0 | – | move | – | S | no | ally boost status move (Coaching, Aromatic Mist) |
| `move:crushclaw` | 0 | 0 | – | move | – | S | no | plain data rows awaiting a recording |
| `move:doublehit` | 0 | 0 | – | move | – | S | no | fixed multi-hit 2 (Dual Wingbeat, Twin Beam, Double Hit) |
| `move:doubleteam` (not in Champions OU) | 0 | 0 | – | move | – | S | no | plain data rows awaiting a recording |
| `move:firelash` | 0 | 0 | – | move | – | S | no | plain data rows awaiting a recording |
| `move:inferno` | 0 | 0 | – | move | – | S | no | mark only (modelled, no recording) |
| `move:petaldance` | 0 | 0 | – | move | – | S | no | locked move (Outrage lock) |
| `move:seismictoss` | 0 | 0 | – | move | – | S | no | level damage (Night Shade, Seismic Toss) |
| `move:sweetkiss` | 0 | 0 | – | move | – | S | no | primary confusion (Confuse Ray, Sweet Kiss) |
| `move:tailslap` | 0 | 0 | – | move | – | S | no | multihit 2-5 (Icicle Spear, Rock Blast, Tail Slap, Bullet Seed, Water Shuriken) |
| `move:tearfullook` | 0 | 0 | – | move | – | S | no | target stat drop status move (Charm, Feather Dance) |
| `move:toxicthread` | 0 | 0 | – | move | – | S | no | status plus stat drop status move |

### A1: Damage chain: one more member of an existing modifier/base-power branch

| gap | in games | alone | greedy | area | core | E | new values | family / depends on |
|---|--:|--:|--:|---|---|:-:|:-:|---|
| `move:hex` | 112 | 39 | 23 | move | damage | S | no | status-doubled BP (Hex, Infernal Parade) |
| `ability:furcoat` | 59 | 37 | 22 | ability | damage | S | no | defense stat modifier (Marvel Scale, Fur Coat, Grass Pelt) |
| `ability:steelyspirit` | 57 | 23 | 42 | ability | damage | S | no | base power ability (Iron Fist, Strong Jaw, Steely Spirit) |
| `move:facade` | 47 | 16 | 46 | move | damage | M | no | conditional base power x2 (Barb Barrage, Facade, Assurance) |
| `move:gyroball` | 47 | 8 | 66 | move | damage | S | no | speed-ratio BP (Gyro Ball) |
| `move:barbbarrage` | 42 | 11 | 85 | move | damage | M | no | conditional base power x2 (Barb Barrage, Facade, Assurance) |
| `ability:heatproof` | 41 | 35 | 40 | ability | damage, residual | S | no | type damage reducer at the target (Thick Fat, Water Bubble, Heatproof) |
| `move:bulldoze` | 33 | 14 | 75 | move | damage | S | no | Grassy-weakened ground moves (Earthquake, Bulldoze) |
| `ability:grasspelt` | 26 | 0 | 166 | ability | damage | S | no | defense stat modifier (Marvel Scale, Fur Coat, Grass Pelt) |
| `ability:guts` | 24 | 14 | 90 | ability | damage | S | no | attack stat modifier (Huge Power, Guts, Hustle) |
| `move:infernalparade` | 21 | 2 | 96 | move | damage | S | no | status-doubled BP (Hex, Infernal Parade) — needs: move:hex |
| `ability:heavymetal` | 18 | 6 | 108 | ability | damage | S | no | weight modifier (Heavy Metal, Light Metal) |
| `item:lightball` | 18 | 7 | 111 | item | damage | S | no | species stat item (Light Ball) |
| `move:venoshock` | 18 | 0 | 129 | move | damage | S | no | status-conditional power (Venoshock, Hex, Barb Barrage) |
| `ability:analytic` | 17 | 3 | 114 | ability | damage | S | no | attacker base-power ability (Technician, Iron Fist, Analytic, ...) |
| `ability:plus` | 17 | 0 | 206 | ability | damage | S | no | ally-pair SpA boost (Plus/Minus) — needs: ability:minus |
| `ability:fluffy` | 13 | 0 | 136 | ability | damage | S | no | target final-damage modifier (Multiscale, Solid Rock, Fluffy) |
| `ability:lightmetal` | 11 | 11 | 128 | ability | damage | S | no | weight modifier (Heavy Metal, Light Metal) — needs: ability:heavymetal (shared getWeight helper) |
| `move:electroball` | 11 | 4 | 146 | move | damage | M | no | stat-ratio base power (Electro Ball, Gyro Ball) |
| `ability:stakeout` | 10 | 0 | 174 | ability | damage | S | no | conditional attack modifier (Stakeout) |
| `move:gravapple` | 10 | 0 | 200 | move | damage | S | no | field-conditional BP (Grav Apple, Misty Explosion) |
| `ability:merciless` | 8 | 3 | 147 | ability | damage | S | no | crit stage (Super Luck, Leek, Merciless) |
| `ability:minus` | 2 | 0 | 219 | ability | damage | S | no | ally-pair SpA boost (Plus/Minus) — needs: ability:plus |
| `move:reversal` | 2 | 0 | 203 | move | damage | S | no | HP-ratio base power (Flail, Reversal, Eruption family) |
| `move:flail` | 0 | 0 | – | move | damage | S | no | HP-based base power (Eruption, Hard Press, Flail, Reversal) |

### A2: One clause on an existing move-body, entry or residual hook

| gap | in games | alone | greedy | area | core | E | new values | family / depends on |
|---|--:|--:|--:|---|---|:-:|:-:|---|
| `item:starminite` | 243 | 0 | 63 | item | – | S | no | Mega Stone mark (generic Mega path) — needs: ability:illuminate (S, Keen Eye clone) or ability:naturalcure / ability:analytic; mega:starm... |
| `ability:naturalcure` | 202 | 21 | 62 | ability | flow | S | no | switch-out ability (Regenerator, Natural Cure) |
| `move:snipeshot` | 168 | 43 | 9 | move | move_body | S | no | tracksTarget (Stalwart, Snipe Shot) |
| `item:golurkite` | 77 | 0 | 242 | item | – | S | no | Mega Stone mark (generic Mega path) — needs: ability:unseenfist; mega:golurk@golurkite (same cause) |
| `mega:golurk@golurkite` | 77 | 0 | 243 | ability | – | S | no | protect bypass (Piercing Drill, Unseen Fist) — needs: ability:unseenfist; item:golurkite (same cause) |
| `ability:illuminate` | 75 | 2 | 64 | ability | move_body | S | no | accuracy protection (Keen Eye, Illuminate) |
| `ability:eartheater` | 70 | 29 | 47 | ability | move_body | S | no | absorb ability (Volt Absorb, Earth Eater, Dry Skin) |
| `ability:icebody` | 68 | 35 | 32 | ability | residual | S | no | weather residual heal (Rain Dish, Ice Body) |
| `move:synthesis` | 65 | 14 | 69 | move | move_body | M | no | weather-scaled heal (Synthesis, Moonlight, Morning Sun) |
| `ability:surgesurfer` | 62 | 34 | 33 | flow | flow | S | no | Speed ability (weather Speed family, Quick Feet, Surge Surfer) |
| `move:firefang` | 62 | 28 | 35 | move | move_body | S | no | status + flinch double secondary (Ice Fang, Fire Fang, Thunder Fang) |
| `ability:insomnia` | 59 | 31 | 34 | ability | move_body | S | no | status refusal ability (Limber, Thermal Exchange, Immunity, Insomnia) |
| `ability:corrosion` | 52 | 18 | 54 | ability | move_body | S | no | status immunity bypass (Corrosion) |
| `move:magicpowder` | 52 | 36 | 36 | move | move_body | S | no | type set (Soak, Magic Powder) |
| `ability:waterabsorb` | 51 | 21 | 50 | ability | move_body | S | no | absorb ability (Water Absorb, Sap Sipper, Motor Drive) |
| `item:shellbell` | 46 | 17 | 65 | item | move_body | S | no | after-move item (Life Orb, Shell Bell) |
| `item:heracronite` | 44 | 0 | 246 | item | – | S | no | Mega Stone mark (generic Mega path) — needs: ability:skilllink; mega:heracross@heracronite (same cause) |
| `mega:heracross@heracronite` | 44 | 0 | 247 | ability | move_body | M | no | multi-hit count (Skill Link) — needs: ability:skilllink; item:heracronite (same cause); move:pinmissile / move:rockblast / move:bulletsee... |
| `move:moonlight` | 44 | 17 | 67 | move | move_body | M | no | weather heal (Moonlight, Morning Sun, Synthesis) |
| `move:ragingbull` | 40 | 12 | 55 | move | move_body, damage | S | no | screen break (Brick Break, Psychic Fangs, Raging Bull) |
| `ability:vitalspirit` | 39 | 29 | 43 | ability | move_body | S | no | status immunity (Leaf Guard, Purifying Salt, Vital Spirit) |
| `ability:poisonpoint` | 35 | 17 | 78 | ability | move_body | S | maybe | contact status ability (Static, Flame Body, Poison Point) |
| `ability:purifyingsalt` | 32 | 5 | 150 | ability | move_body, damage | S | no | status immunity (Leaf Guard, Purifying Salt, Vital Spirit) |
| `item:zoomlens` | 30 | 19 | 79 | item | move_body | S | no | accuracy modifier item (Wide Lens, Zoom Lens) |
| `move:grassyterrain` | 27 | 14 | 77 | field | move_body | S | no | terrain setter move (Electric/Misty/Psychic Terrain) |
| `move:growth` | 26 | 13 | 110 | move | move_body | S | no | weather-conditional boost (Growth) |
| `ability:gooey` | 20 | 5 | 113 | ability | move_body | S | no | contact boost retaliation (Gooey, Tangling Hair) |
| `move:thunderfang` | 20 | 0 | 102 | move | move_body | S | no | fang double secondary (Ice Fang, Thunder Fang, Fire Fang) |
| `move:morningsun` | 15 | 7 | 139 | move | move_body | S | no | weather heal (Moonlight, Morning Sun, Synthesis) — needs: move:moonlight |
| `ability:tangledfeet` | 6 | 0 | 169 | ability | move_body | S | no | evasion ability (Sand Veil, Snow Cloak, Tangled Feet) |
| `ability:motordrive` | 5 | 1 | 187 | ability | move_body | S | no | absorb ability (Water Absorb, Sap Sipper, Motor Drive) |
| `ability:skilllink` | 4 | 0 | 194 | ability | move_body | S | no | multi-hit (Parental Bond, Skill Link) |
| `move:meteorbeam` | 4 | 0 | 176 | move | move_body | S | no | charge move (Electro Shot, Solar Beam, Phantom Force) |
| `ability:immunity` | 3 | 0 | 190 | ability | move_body | S | no | status refusal ability (Limber, Thermal Exchange, Immunity, Insomnia) |
| `move:shiftgear` | 3 | 1 | 193 | move | move_body | S | no | boost key order (Shell Smash, Shift Gear) |
| `move:skyattack` | 3 | 0 | 197 | move | move_body | S | no | two-turn charge (Solar Beam, Electro Shot, Phantom Force, Sky Attack) |
| `ability:quickfeet` | 2 | 2 | 204 | flow | flow | S | no | Speed ability (weather Speed family, Quick Feet, Surge Surfer) |
| `item:oranberry` | 1 | 1 | 221 | item | flow | S | no | HP berry (Sitrus) — needs: berry isBerry column (item:chestoberry) |
| `ability:anticipation` | 0 | 0 | – | ability | flow | S | no | entry announcement (Pressure, Unnerve, Fairy Aura, Anticipation) |
| `ability:unseenfist` | 0 | 0 | – | ability | move_body, damage | S | no | protect bypass (Piercing Drill, Unseen Fist) |
| `mega:starmie@starminite` | 0 | 0 | – | item | – | S | no | Mega Stone mark (generic Mega path) — needs: item:starminite (same cause); ability:illuminate or ability:naturalcure or ability:analytic |
| `move:pluck` | 0 | 0 | – | move | move_body | S | no | berry steal-eat (Bug Bite, Pluck) |

### P: Paused lane A branches (finish after re-sync)

| gap | in games | alone | greedy | area | core | E | new values | family / depends on |
|---|--:|--:|--:|---|---|:-:|:-:|---|
| `move:focusenergy` | 190 | 65 | 8 | move | move_body, damage | M | maybe | crit stage (Focus Energy, Dragon Cheer) — needs: paused Focus Energy branch (the lead covers it) |
| `move:payback` | 123 | 75 | 5 | move | damage | M | maybe | queue-read BP (Payback) — needs: queue order known (dfi_will_move); newly switched flag |
| `move:metalburst` | 79 | 69 | 7 | move | move_body, damage | L | yes | damage reflection (Counter, Mirror Coat, Metal Burst) |
| `move:mirrorcoat` | 73 | 45 | 19 | move | flow, move_body, damage | L | yes | damage reflection (Counter, Mirror Coat, Metal Burst) — needs: move:metalburst |
| `move:lastresort` | 72 | 41 | 20 | move | move_body | M | maybe | move history (Last Resort) |
| `move:counter` | 21 | 2 | 141 | move | flow, move_body, damage | L | yes | damage retaliation (Counter, Metal Burst, Comeuppance) — needs: move:metalburst (paused branch, same mechanic) |
| `move:comeuppance` | 0 | 0 | – | move | move_body, damage, flow | L | yes | damage retaliation (Counter, Metal Burst, Comeuppance) — needs: move:metalburst (paused branch, same mechanic) |

### B1: Protean / Libero (+ Mega Greninja, Mimicry's type storage)

| gap | in games | alone | greedy | area | core | E | new values | family / depends on |
|---|--:|--:|--:|---|---|:-:|:-:|---|
| `ability:protean` | 350 | 129 | 2 | ability | move_body | M | no | type change on move (Protean/Libero) |
| `ability:libero` | 160 | 21 | 16 | ability | move_body | M | maybe | type change on move (Protean/Libero) — needs: ability:protean (same mechanic, DFI_ABILITY_PROTEAN 136 is in the pool) |
| `item:greninjite` | 155 | 0 | 232 | item | – | S | no | Mega Stone mark (generic Mega path) — needs: ability:protean; mega:greninja@greninjite (same cause) |
| `mega:greninja@greninjite` | 155 | 0 | 233 | ability | move_body | M | maybe | type change on move (Protean/Libero) — needs: ability:protean; ability:libero (same mechanic); item:greninjite (same cause) |
| `ability:mimicry` | 7 | 0 | 258 | ability | flow | M | maybe | weather/terrain-driven forme or type (Forecast, Mimicry) — needs: ability:protean/libero type-change storage (shared soak_type/type2) |

### B2: Item steal: Pickpocket, Magician

| gap | in games | alone | greedy | area | core | E | new values | family / depends on |
|---|--:|--:|--:|---|---|:-:|:-:|---|
| `ability:pickpocket` | 136 | 93 | 3 | ability | move_body | M | no | item steal (Thief/Covet, Pickpocket) |
| `ability:magician` | 111 | 77 | 4 | ability | move_body | M | no | item steal (Thief, Magician, Pickpocket) |

### B3: Mold Breaker (+ Mega Gyarados, Ampharos, Emboar; Gigaton Hammer)

| gap | in games | alone | greedy | area | core | E | new values | family / depends on |
|---|--:|--:|--:|---|---|:-:|:-:|---|
| `ability:moldbreaker` | 223 | 36 | 27 | ability | flow, move_body, damage | L | no | ability ignoring (Mold Breaker) — needs: every marked breakable ability |
| `item:gyaradosite` | 202 | 0 | 230 | item | – | S | no | Mega Stone mark (generic Mega path) — needs: ability:moldbreaker; mega:gyarados@gyaradosite (same cause) |
| `mega:gyarados@gyaradosite` | 202 | 0 | 231 | ability | flow, move_body, damage | L | maybe | ability suppression by the attacker (Mold Breaker; no Teravolt/Turboblaze in the pool) — needs: ability:moldbreaker; item:gyaradosite (sa... |
| `move:gigatonhammer` | 189 | 0 | 28 | move | flow | M | no | cantusetwice (Gigaton Hammer, Blood Moon) — needs: an ability of Tinkaton marked (Mold Breaker, Own Tempo or Pickpocket) |
| `item:ampharosite` | 131 | 0 | 234 | item | – | S | no | Mega Stone mark (generic Mega path) — needs: ability:moldbreaker; mega:ampharos@ampharosite (same cause) |
| `mega:ampharos@ampharosite` | 131 | 0 | 235 | ability | flow, move_body, damage | L | maybe | ability suppression by the attacker (Mold Breaker; no Teravolt/Turboblaze in the pool) — needs: ability:moldbreaker; item:ampharosite (sa... |
| `item:emboarite` | 14 | 0 | 254 | item | – | S | no | Mega Stone mark (generic Mega path) — needs: ability:moldbreaker; mega:emboar@emboarite (same cause) |
| `mega:emboar@emboarite` | 14 | 0 | 255 | ability | flow, move_body, damage | L | maybe | ability suppression by the attacker (Mold Breaker; no Teravolt/Turboblaze in the pool) — needs: ability:moldbreaker; item:emboarite (same... |

### B4: Forme abilities: Zero to Hero, Disguise, Hunger Switch, Forecast

| gap | in games | alone | greedy | area | core | E | new values | family / depends on |
|---|--:|--:|--:|---|---|:-:|:-:|---|
| `ability:zerotohero` (not in Champions OU) | 218 | 11 | 80 | forme | flow | L | maybe | permanent forme on switch (Zero to Hero) — needs: Palafin-Hero forme row in the pool; move:jetpunch (only learner Palafin) |
| `move:jetpunch` (not in Champions OU) | 184 | 0 | 81 | move | – | S | no | mark only (modelled, no recording) — needs: ability:zerotohero |
| `ability:disguise` | 107 | 57 | 10 | forme | damage, move_body, flow | L | yes | damage-absorbing forme ability (Disguise, Ice Face) — needs: Mimikyu-Busted forme data (pool has DFI_FORME_MIMIKYU only); permanent forme... |
| `ability:hungerswitch` | 19 | 1 | 223 | forme | residual | M | no | temporary forme change (Stance Change, Hunger Switch) — needs: Morpeko-Hangry forme row (pool has DFI_FORME_MORPEKO only); move:aurawheel... |
| `move:aurawheel` | 18 | 0 | 224 | move | damage | M | maybe | species-locked move (Aura Wheel, Double Shock) — needs: ability:hungerswitch; forme Morpeko-Hangry (not in the pool tables) |
| `ability:forecast` | 6 | 2 | 161 | forme | flow, residual, move_body | L | maybe | weather/terrain-driven forme or type (Forecast, Mimicry) — needs: Castform-Sunny/Rainy/Snowy forme rows (pool has DFI_FORME_CASTFORM only... |
| `forme:castformrainy` | 0 | 0 | – | forme | – | S | no | battle-only forme (Forecast) — needs: ability:forecast |
| `forme:castformsnowy` | 0 | 0 | – | forme | – | S | no | battle-only forme (Forecast) — needs: ability:forecast |
| `forme:castformsunny` | 0 | 0 | – | forme | – | S | no | battle-only forme (Forecast) — needs: ability:forecast |
| `forme:mimikyubusted` | 0 | 0 | – | forme | – | S | no | battle-only forme (Disguise) — needs: ability:disguise |
| `forme:morpekohangry` | 0 | 0 | – | forme | – | S | no | battle-only forme (Hunger Switch) — needs: ability:hungerswitch |
| `forme:palafinhero` (not in Champions OU) | 0 | 0 | – | forme | – | S | maybe | battle-only forme (Zero to Hero) — needs: ability:zerotohero |

### B5: Mega abilities: Berserk, Eelevate, Innards Out/Aftermath, Healer/Hydration, Strong Jaw, Parental Bond

| gap | in games | alone | greedy | area | core | E | new values | family / depends on |
|---|--:|--:|--:|---|---|:-:|:-:|---|
| `item:kangaskhanite` | 124 | 0 | 237 | item | – | S | no | Mega Stone mark (generic Mega path) — needs: ability:parentalbond; mega:kangaskhan@kangaskhanite (same cause) |
| `mega:kangaskhan@kangaskhanite` | 124 | 0 | 238 | ability | move_body, damage | L | no | extra hit (Parental Bond) — needs: ability:parentalbond; item:kangaskhanite (same cause) |
| `item:drampanite` | 104 | 0 | 239 | item | – | S | no | Mega Stone mark (generic Mega path) — needs: ability:berserk; mega:drampa@drampanite (same cause) |
| `mega:drampa@drampanite` | 104 | 0 | 240 | ability | move_body, flow | M | no | half-HP crossing trigger (Emergency Exit, Berserk) — needs: ability:berserk; item:drampanite (same cause) |
| `ability:healer` | 62 | 34 | 31 | ability | residual | M | maybe | residual status cure (Healer, Hydration, Shed Skin) |
| `item:eelektrossite` | 55 | 0 | 244 | item | – | S | no | Mega Stone mark (generic Mega path) — needs: ability:eelevate; mega:eelektross@eelektrossite (same cause) |
| `mega:eelektross@eelektrossite` | 55 | 0 | 245 | ability | flow, move_body | M | no | Levitate grounding + Moxie-like after-faint boost — needs: ability:eelevate; item:eelektrossite (same cause) |
| `item:victreebelite` | 40 | 0 | 249 | item | – | S | no | Mega Stone mark (generic Mega path) — needs: ability:innardsout; mega:victreebel@victreebelite (same cause) |
| `mega:victreebel@victreebelite` | 40 | 0 | 250 | ability | move_body | M | no | DamagingHit counter-damage (Rocky Helmet, Innards Out) — needs: ability:innardsout; item:victreebelite (same cause) |
| `ability:berserk` | 33 | 0 | 241 | ability | move_body, flow | M | no | half-HP threshold after a move (Emergency Exit, Berserk, Anger Shell) — needs: HP-threshold after-move hook (as Emergency Exit's hp_before) |
| `item:audinite` | 18 | 0 | 252 | item | – | S | no | Mega Stone mark (generic Mega path) — needs: ability:healer; mega:audino@audinite (same cause) |
| `mega:audino@audinite` | 18 | 0 | 253 | ability | residual | M | no | residual ally status cure (Healer) — needs: ability:healer; item:audinite (same cause) |
| `item:sharpedonite` | 9 | 0 | 256 | item | – | S | no | Mega Stone mark (generic Mega path) — needs: ability:strongjaw; mega:sharpedo@sharpedonite (same cause) |
| `mega:sharpedo@sharpedonite` | 9 | 0 | 257 | ability | damage | M | maybe | move-flag base power booster (Iron Fist, Mega Launcher, Strong Jaw) — needs: ability:strongjaw; bite flag column (lead decision); item:sh... |
| `ability:hydration` | 7 | 0 | 152 | ability | residual | M | maybe | residual status cure (Healer, Hydration, Shed Skin) |
| `ability:strongjaw` | 2 | 0 | 226 | ability | damage | S | no | base power ability (Iron Fist, Strong Jaw, Steely Spirit) — needs: bite move flag column (generator) |
| `ability:aftermath` | 0 | 0 | – | ability | move_body | M | no | retaliation when the holder is knocked out (Aftermath, Innards Out) — needs: Damp's onAnyDamage veto of Aftermath (Damp is marked as iner... |
| `ability:eelevate` | 0 | 0 | – | ability | move_body, flow | M | no | Levitate airborneness + Moxie-like KO boost (Eelevate) — needs: ability:levitate grounding paths (marked) |
| `ability:innardsout` | 0 | 0 | – | ability | move_body | M | no | retaliation when the holder is knocked out (Aftermath, Innards Out) — needs: ability:aftermath (same knocked-out holder DamagingHit slot) |
| `ability:parentalbond` | 0 | 0 | – | ability | move_body, damage | L | no | multi-hit (Parental Bond, Skill Link) — needs: a multi-hit loop for every single-target move |

### B6: Common move-body mechanics (M): crash, removal, pivots, self-KO, absorb, veils

| gap | in games | alone | greedy | area | core | E | new values | family / depends on |
|---|--:|--:|--:|---|---|:-:|:-:|---|
| `move:highjumpkick` | 179 | 47 | 15 | move | move_body | M | yes | crash damage (High Jump Kick, Axe Kick, Supercell Slam) — needs: gravity flag rule (gravity-flagged moves disabled under Gravity) |
| `ability:owntempo` | 99 | 31 | 29 | ability | move_body | M | no | volatile immunity (Own Tempo, Oblivious, Inner Focus) |
| `move:mortalspin` | 77 | 34 | 30 | move | move_body | M | yes | hazard/seed removal after hit (Rapid Spin, Mortal Spin) — needs: move:rapidspin |
| `ability:electromorphosis` | 73 | 33 | 24 | ability | move_body, damage | L | yes | Charge volatile (Charge, Electromorphosis, Wind Power) — needs: move:charge (the charge volatile is not modelled; DFI_MOVE_CHARGE has no ... |
| `move:shedtail` (not in Champions OU) | 71 | 10 | 73 | move | move_body, flow | M | maybe | pivot with volatile pass (Baton Pass, Shed Tail) — needs: move:batonpass pivot (decision 0042); Substitute (decision 0032) |
| `ability:dryskin` | 70 | 22 | 72 | ability | move_body, damage, residual | M | no | absorb ability (Volt Absorb, Earth Eater, Dry Skin) + weather residual (Rain Dish, Solar Power) |
| `move:chillyreception` | 69 | 13 | 52 | move | move_body, flow | M | no | pivot status move (Parting Shot, Chilly Reception) — needs: pivot switch flag for a status selfSwitch move |
| `ability:sapsipper` | 63 | 21 | 71 | ability | move_body | M | no | absorb ability (Water Absorb, Sap Sipper, Motor Drive) |
| `move:topsyturvy` | 60 | 11 | 49 | move | move_body | L | yes | boost rewrite (Haze, Topsy-Turvy) |
| `move:clearsmog` | 46 | 16 | 61 | move | move_body | M | maybe | boost clearing (Haze, Clear Smog) |
| `ability:aromaveil` | 41 | 2 | 121 | ability | move_body | M | maybe | side-wide volatile/status veil (Flower Veil, Aroma Veil) |
| `move:endure` | 38 | 16 | 82 | move | move_body, damage | M | maybe | protect-family stall moves (Protect, Detect, Endure) |
| `move:triplearrows` | 35 | 22 | 59 | move | move_body | M | no | double secondary (Ice Fang shape, boost + flinch) |
| `move:burningjealousy` | 32 | 14 | 58 | move | move_body | M | no | raised-this-turn secondary (Alluring Voice, Burning Jealousy) |
| `move:selfdestruct` | 32 | 1 | 99 | move | move_body, flow | M | no | self-faint moves (Explosion, Self-Destruct, Misty Explosion) — needs: ability:damp rule (marked, no turn.c reader yet) |
| `move:supercellslam` | 26 | 1 | 137 | move | move_body | M | no | crash damage (High Jump Kick, Axe Kick, Supercell Slam) |
| `move:burnup` | 25 | 12 | 88 | move | move_body | M | no | type-loss self move (Double Shock, Burn Up) |
| `move:explosion` | 25 | 4 | 87 | move | move_body | M | maybe | self-KO moves (Memento, Final Gambit, Explosion) — needs: Damp rule (Damp is marked but inert) |
| `ability:seedsower` | 24 | 3 | 93 | ability | move_body | M | no | field setter on hit (Sand Spit, Seed Sower) — needs: terrain set outside the entry |
| `move:acupressure` (not in Champions OU) | 24 | 3 | 130 | move | move_body | M | maybe | random stat boost (Acupressure, Moody) — needs: target class adjacentAllyOrSelf in dfi_move_targets; new draw site (stat sample) |
| `move:defog` | 24 | 7 | 84 | move | move_body | M | maybe | hazard and screen removal (Defog, Rapid Spin, Tidy Up) |
| `move:ficklebeam` | 24 | 4 | 118 | move | damage | M | maybe | random power doubling (Fickle Beam) — needs: new draw site |
| `move:tidyup` | 24 | 4 | 119 | move | move_body | M | no | hazard/substitute clear (Tidy Up, Rapid Spin, Defog) — needs: Substitute (decision 0032) |
| `move:dive` | 16 | 6 | 126 | move | move_body, damage, residual | M | maybe | two-turn semi-invulnerable (Fly, Bounce, Dig, Dive, Phantom Force) — needs: semi-invulnerable family generalised from Phantom Force |
| `move:eeriespell` | 16 | 2 | 134 | move | move_body | M | maybe | PP reduction (Eerie Spell, Spite) |
| `move:fellstinger` | 16 | 11 | 106 | move | move_body | M | no | after-hit self boost on KO (Fell Stinger, Moxie) |
| `ability:effectspore` | 13 | 0 | 127 | ability | move_body | M | maybe | contact status retaliation (Static, Flame Body, Effect Spore) |
| `move:shellsidearm` | 13 | 0 | 208 | move | move_body, damage | M | maybe | category by stats (Shell Side Arm) |
| `ability:liquidooze` | 11 | 7 | 148 | ability | move_body, residual | M | no | drain reversal (Liquid Ooze) |
| `move:charge` | 11 | 3 | 155 | move | damage, move_body | M | maybe | next-move power volatile (Charge) |
| `move:rapidspin` | 11 | 0 | 168 | move | move_body | M | yes | hazard/seed removal after hit (Rapid Spin, Mortal Spin) |
| `move:sparklingaria` | 11 | 4 | 167 | move | move_body | M | no | burn cure on hit (Sparkling Aria) |
| `ability:sweetveil` | 10 | 0 | 143 | ability | move_body | M | no | ally status guard (Flower Veil, Sweet Veil) — needs: ordering with Flower Veil and Leaf Guard |
| `ability:sandspit` | 8 | 5 | 162 | ability | move_body | M | no | field setter on hit (Sand Spit, Seed Sower) — needs: weather set outside the entry |
| `ability:hustle` | 7 | 0 | 201 | ability | damage, move_body | M | no | attack stat modifier (Huge Power, Guts, Hustle) + accuracy modifier (Compound Eyes) |
| `ability:shielddust` | 7 | 5 | 160 | ability | move_body | M | no | secondary suppression (Sheer Force, Shield Dust, Covert Cloak) |
| `move:attract` | 6 | 0 | 209 | move | move_body | M | maybe | attract volatile (Cute Charm, Attract, Destiny Knot) |
| `move:fly` | 6 | 2 | 175 | move | move_body, damage | M | maybe | two-turn semi-invulnerable (Fly, Bounce, Dig, Dive, Phantom Force) — needs: gravity-flag rule (moves barred under Gravity); semi-invulner... |
| `move:bounce` | 5 | 0 | 192 | move | move_body, damage | M | maybe | two-turn semi-invulnerable (Fly, Bounce, Dig, Dive, Phantom Force) — needs: gravity-flag rule (moves barred under Gravity); semi-invulner... |
| `move:courtchange` | 4 | 0 | 189 | field | move_body | M | yes | side condition swap (Court Change) |
| `move:mistyexplosion` | 4 | 4 | 179 | move | move_body, damage | M | no | self-KO (Explosion, Self-Destruct, Misty Explosion) — needs: self-KO move (Explosion, Self-Destruct) |
| `move:dig` | 3 | 0 | 205 | move | move_body, damage, residual | M | maybe | two-turn semi-invulnerable (Fly, Bounce, Dig, Dive, Phantom Force) — needs: semi-invulnerable family generalised from Phantom Force |
| `move:flyingpress` | 1 | 0 | 213 | move | damage | M | maybe | custom effectiveness (Freeze-Dry, Flying Press) — needs: gravity-flag rule (moves barred under Gravity) |
| `move:magneticflux` | 1 | 0 | 236 | move | move_body | M | no | plus/minus ally boost (Magnetic Flux) — needs: ability:plus; ability:minus |
| `ability:longreach` | 0 | 0 | – | ability | move_body, damage | M | no | contact removal (Long Reach, Protective Pads) |
| `ability:rattled` | 0 | 0 | – | ability | move_body | M | no | reactive boost on hit (Rattled, Stamina, Justified) |
| `ability:stench` | 0 | 0 | – | ability | move_body | M | no | secondary addition (Stench, King's Rock) |
| `move:axekick` | 0 | 0 | – | move | move_body, damage | M | no | crash damage (Axe Kick, High Jump Kick, Supercell Slam) |
| `move:corrosivegas` | 0 | 0 | – | move | move_body | M | no | item removal (Knock Off, Corrosive Gas) |
| `move:electrify` | 0 | 0 | – | move | move_body, damage | M | maybe | type-forcing volatile (Electrify, Ion Deluge) — needs: one-turn volatile bit (single_turn has free bits) |
| `move:spite` | 0 | 0 | – | move | move_body | M | maybe | PP reduction (Spite) |

### B7: Flow and residual hooks (M): Supreme Overlord, entry abilities, priority tiers, cures

| gap | in games | alone | greedy | area | core | E | new values | family / depends on |
|---|--:|--:|--:|---|---|:-:|:-:|---|
| `ability:supremeoverlord` | 114 | 50 | 11 | ability | flow, damage | M | maybe | fallen-ally power (Supreme Overlord, Last Respects) |
| `move:round` | 50 | 24 | 45 | move | flow, move_body, damage | M | no | queue reorder (After You, Quash, Round) — needs: queue reorder (After You) |
| `ability:earlybird` | 33 | 8 | 103 | ability | flow | M | maybe | sleep counter (Early Bird, Sleep Talk/Snore) — needs: decision 0066 sleep counter posterior (double decrement) |
| `ability:screencleaner` | 28 | 8 | 92 | ability | flow | M | no | entry field clear (Screen Cleaner) |
| `ability:quickdraw` | 18 | 0 | 207 | flow | flow | M | maybe | fractional priority (Quick Draw, Stall, Quick Claw) — needs: fractional priority in the action key |
| `ability:curiousmedicine` | 17 | 5 | 133 | ability | flow | M | yes | entry ability acting on the ally (Hospitality, Curious Medicine) |
| `ability:supersweetsyrup` | 9 | 1 | 195 | ability | flow | M | yes | entry stat drop (Intimidate, Supersweet Syrup) |
| `ability:receiver` | 4 | 0 | 178 | ability | flow | M | maybe | ability copy (Trace, Receiver) — needs: Trace copy path |
| `ability:forewarn` | 2 | 0 | 202 | ability | flow | M | maybe | entry announcement (Frisk, Anticipation, Forewarn) |
| `ability:stall` | 2 | 0 | 210 | flow | flow | M | no | fractional priority (Quick Draw, Stall, Quick Claw) — needs: fractional priority in the action key |
| `ability:poisonheal` | 1 | 0 | 228 | ability | residual | M | no | poison residual replacement (Poison Heal) |
| `ability:klutz` | 0 | 0 | – | item | flow | M | no | item suppression (Klutz, Embargo, Magic Room) |
| `ability:shedskin` | 0 | 0 | – | ability | residual | M | maybe | residual status cure (Shed Skin) |

### B8: Berries and held items (M)

| gap | in games | alone | greedy | area | core | E | new values | family / depends on |
|---|--:|--:|--:|---|---|:-:|:-:|---|
| `item:quickclaw` (not in Champions OU) | 91 | 32 | 38 | item | flow | M | maybe | fractional priority (Quick Claw) |
| `item:leppaberry` | 83 | 41 | 12 | item | flow | M | no | berry onUpdate (Sitrus/Lum) — needs: berry isBerry column (item:chestoberry) |
| `item:chestoberry` | 75 | 23 | 51 | item | flow | M | no | status-cure berry (Lum family) |
| `item:kingsrock` (not in Champions OU) | 68 | 19 | 53 | item | move_body | M | no | added secondary (flinch) |
| `ability:cudchew` | 62 | 28 | 25 | ability | residual, flow, damage | L | yes | after-eating-berry ability (Cheek Pouch, Cud Chew) — needs: ability:cheekpouch (shared EatItem hook); berry re-eat path (singleEvent Eat ... |
| `item:normalgem` | 60 | 35 | 26 | item | move_body, damage | M | no | gem (one-shot type boost) |
| `ability:harvest` | 33 | 7 | 109 | ability | residual | M | maybe | berry restore (Harvest, Recycle) — needs: lastItem tracking (item_consumed + sheet/item_now) |
| `item:bigroot` | 15 | 5 | 112 | item | move_body, residual | M | no | heal modifier (TryHeal) |
| `item:focusband` | 11 | 3 | 158 | item | move_body | M | no | survive-at-1-HP (Sturdy, Focus Sash, Focus Band) |
| `ability:ripen` | 7 | 2 | 199 | item | move_body, damage | L | yes | berry modifiers (Ripen) — needs: coverage of the berry family |
| `ability:cheekpouch` | 5 | 0 | 184 | ability | flow, damage, move_body | M | no | after-eating-berry ability (Cheek Pouch, Cud Chew) — needs: a common EatItem hook at every berry-eat site |
| `item:aspearberry` | 1 | 0 | 225 | item | flow | S | no | status-cure berry (Lum family) — needs: item:chestoberry (status-cure berry family) |
| `item:persimberry` | 1 | 0 | 217 | item | flow | S | no | status-cure berry (Lum family) — needs: item:chestoberry (status-cure berry family) |
| `item:cheriberry` | 0 | 0 | – | item | flow | S | no | status-cure berry (Lum family) — needs: item:chestoberry (status-cure berry family) |
| `item:pechaberry` | 0 | 0 | – | item | flow | S | no | status-cure berry (Lum family) — needs: item:chestoberry (status-cure berry family) |
| `item:rawstberry` | 0 | 0 | – | item | flow | S | no | status-cure berry (Lum family) — needs: item:chestoberry (status-cure berry family) |
| `move:stuffcheeks` | 0 | 0 | – | item | move_body | M | no | berry eat by move (Bug Bite, Stuff Cheeks, Teatime) — needs: berry eat path (Bug Bite, Sitrus) |
| `move:teatime` | 0 | 0 | – | item | move_body | M | no | berry eat by move (Bug Bite, Stuff Cheeks, Teatime) — needs: berry eat path (Bug Bite, Sitrus) |

### B9: Ability change and copy (Skill Swap machinery)

| gap | in games | alone | greedy | area | core | E | new values | family / depends on |
|---|--:|--:|--:|---|---|:-:|:-:|---|
| `move:worryseed` | 84 | 39 | 17 | move | move_body | M | maybe | ability set by move (Skill Swap, Role Play, Simple Beam, Worry Seed) — needs: ability:insomnia; ability set by move (Skill Swap helpers) |
| `ability:wanderingspirit` | 57 | 34 | 39 | ability | move_body | M | maybe | ability overwrite on contact (Mummy, Wandering Spirit) — needs: Skill Swap (G70) |
| `ability:mummy` | 50 | 7 | 97 | ability | move_body | M | maybe | ability overwrite on contact (Mummy, Wandering Spirit) — needs: Skill Swap ability-change helpers (G70) |
| `move:entrainment` | 34 | 6 | 98 | move | move_body | M | no | ability transfer (Skill Swap, Entrainment, Role Play) — needs: Skill Swap machinery (decision 0041) |
| `move:simplebeam` | 21 | 1 | 116 | move | move_body | L | yes | ability set by move (Skill Swap, Role Play, Simple Beam, Worry Seed) — needs: ability:simple (not in the pool); ability set by move (Skil... |
| `move:roleplay` | 8 | 2 | 154 | move | move_body | M | maybe | ability set by move (Skill Swap, Role Play, Simple Beam, Worry Seed) — needs: ability_now tail and Skill Swap helpers (decision 0041) |
| `move:gastroacid` | 6 | 0 | 182 | ability | move_body | L | yes | ability suppression (Gastro Acid) |

### B10: HP, heal and sleep (Pain Split, Wish, Rest, Sleep Talk, ...)

| gap | in games | alone | greedy | area | core | E | new values | family / depends on |
|---|--:|--:|--:|---|---|:-:|:-:|---|
| `move:wish` | 111 | 48 | 14 | move | move_body, residual | L | yes | slot condition heal (Healing Wish, Wish) |
| `move:pollenpuff` | 95 | 33 | 18 | move | move_body, damage | M | no | ally heal targeting (Milk Drink, Pollen Puff) |
| `move:painsplit` | 87 | 27 | 21 | move | move_body | M | yes | HP set (Pain Split) |
| `move:rest` | 67 | 4 | 74 | move | move_body | L | yes | self sleep / sleep counter (Rest, Sleep Talk, Snore) — needs: decision 0066 Rest path (source bit, point mass S=3); ability:insomnia; abi... |
| `move:milkdrink` | 28 | 0 | 165 | move | move_body | M | no | ally heal targeting (Milk Drink, Pollen Puff) — needs: an ability of Gogoat marked (Sap Sipper or Grass Pelt) |
| `move:sleeptalk` | 11 | 2 | 144 | move | flow, move_body | L | maybe | self sleep / sleep counter (Rest, Sleep Talk, Snore) — needs: move:rest or another sleep source; decision 0066 sleepUsable path; calling ... |
| `move:snore` | 1 | 1 | 220 | move | flow, move_body | M | maybe | self sleep / sleep counter (Rest, Sleep Talk, Snore) — needs: decision 0066 sleepUsable path |
| `move:healbell` | 0 | 0 | – | move | move_body | M | no | team status cure (Heal Bell) |

### C: New state or engine concepts (L): Transform/Imposter, Instruct, Future Sight, traps, rooms, stockpile, ...

| gap | in games | alone | greedy | area | core | E | new values | family / depends on |
|---|--:|--:|--:|---|---|:-:|:-:|---|
| `move:transform` | 114 | 1 | 124 | forme | move_body, flow | L | yes | transformed state (Transform, Imposter) — needs: decision 0028 transformed state (not built) |
| `ability:imposter` | 101 | 0 | 125 | forme | flow, move_body, damage | L | yes | Transform (Transform, Imposter) — needs: move:transform (transformInto: no engine state yet) |
| `move:instruct` | 93 | 40 | 13 | move | flow, move_body | L | yes | move replay (Instruct) |
| `move:noretreat` | 50 | 22 | 57 | move | move_body, flow | L | yes | trap volatile (Mean Look, Jaw Lock, Octolock, No Retreat, Ingrain) — needs: move:meanlook |
| `move:octolock` | 48 | 16 | 60 | move | move_body, residual, flow | L | yes | trap volatile (Mean Look, Jaw Lock, Octolock, No Retreat, Ingrain) — needs: move:meanlook |
| `move:futuresight` | 38 | 11 | 76 | move | move_body, residual, damage | L | yes | delayed slot attack (Future Sight) |
| `move:saltcure` | 34 | 0 | 149 | move | move_body, residual | L | yes | residual damage volatile (Salt Cure, Syrup Bomb) |
| `move:fling` | 30 | 6 | 56 | move | move_body, damage | L | yes | item use by move (Fling, Bug Bite, Natural Gift) — needs: item fling data column; member ateBerry bit (Belch) |
| `move:avalanche` | 24 | 11 | 107 | move | damage, flow | L | yes | turn history: hit by this target this turn (Avalanche, Revenge, Comeuppance) — needs: per-source hurt-this-turn record (shared with Payba... |
| `item:metronome` | 23 | 11 | 89 | item | flow, move_body, damage | L | yes | consecutive-use counter (Metronome item) |
| `move:stockpile` | 23 | 1 | 132 | move | move_body | L | yes | Stockpile family (Stockpile, Spit Up, Swallow) |
| `move:focuspunch` | 22 | 4 | 120 | move | flow, move_body | L | yes | focus charge (Focus Punch) |
| `move:minimize` (not in Champions OU) | 18 | 0 | 131 | move | move_body, damage | L | maybe | accuracy volatile (Lock-On, Minimize) |
| `move:safeguard` | 18 | 9 | 100 | field | move_body, residual | L | yes | side condition (Safeguard) — needs: ability:infiltrator interplay (marked) |
| `move:smackdown` | 17 | 0 | 123 | move | move_body | L | yes | grounding volatile (Smack Down, Thousand Arrows) — needs: move:fly / move:bounce cancel (unmarked); groundedness readers (Levitate, Air B... |
| `move:uproar` | 17 | 15 | 94 | move | move_body, flow, residual | L | yes | locked move (Outrage, Uproar) — needs: lockedmove-style lock (Outrage) |
| `move:powerswap` | 14 | 10 | 115 | move | move_body | M | yes | boost swap (Guard Swap, Power Swap) — needs: move:guardswap |
| `move:copycat` | 12 | 5 | 117 | move | move_body, flow | L | yes | called moves (Copycat, Metronome, Assist) |
| `move:trickortreat` | 12 | 2 | 159 | move | move_body, damage | L | yes | type change by move (Soak, Reflect Type, Trick-or-Treat) — needs: type change state |
| `move:beakblast` | 7 | 1 | 183 | move | flow, move_body | L | yes | priority charge callback — needs: priorityChargeCallback turn-start step (Beak Blast, Focus Punch, Shell Trap) |
| `move:meanlook` | 7 | 1 | 170 | move | move_body, flow | L | yes | trap volatile (Mean Look, Jaw Lock, Octolock, No Retreat, Ingrain) |
| `move:wonderroom` | 7 | 3 | 157 | field | move_body, damage, residual | L | yes | room pseudo-weather (Trick Room, Wonder Room) |
| `move:jawlock` | 6 | 0 | 185 | move | move_body, flow | M | no | trap volatile (Mean Look, Jaw Lock, Octolock, No Retreat, Ingrain) — needs: move:meanlook |
| `move:forestscurse` | 5 | 0 | 172 | move | move_body, damage | L | yes | type add (Forest's Curse, Trick-or-Treat) |
| `move:guardswap` | 5 | 3 | 177 | move | move_body | M | yes | boost swap (Guard Swap, Power Swap) |
| `move:aquaring` | 4 | 0 | 229 | move | residual, move_body | L | yes | self residual heal volatile (Aqua Ring, Ingrain) |
| `move:belch` | 4 | 0 | 181 | move | move_body | L | yes | berry-eaten gate (Belch) — needs: member ateBerry bit, set at every berry eaten (Bug Bite and Cud Chew included) |
| `move:torment` | 4 | 3 | 180 | move | move_body, flow | L | yes | move lockout volatile (Disable, Taunt, Torment) — needs: Disable request filtering |
| `ability:opportunist` | 3 | 0 | 222 | ability | flow, residual | L | yes | boost copy (Opportunist, Mirror Herb) — needs: AfterMove / AfterMega / AnySwitchIn hook points |
| `move:fairylock` | 3 | 0 | 188 | field | flow, move_body | L | yes | trap volatile (Block, Mean Look, Fairy Lock) |
| `move:guardsplit` | 3 | 1 | 215 | move | move_body | M | yes | stored-stat swap/average (Speed Swap, Power/Guard Split, Power Trick) |
| `move:powersplit` | 3 | 0 | 191 | move | move_body | M | yes | stored-stat swap/average (Speed Swap, Power/Guard Split, Power Trick) — needs: move:guardsplit |
| `move:recycle` | 3 | 1 | 198 | item | move_body | L | maybe | lost-item restore (Recycle) |
| `move:syrupbomb` | 3 | 0 | 196 | move | move_body, residual, flow | L | yes | residual damage volatile (Salt Cure, Syrup Bomb) |
| `move:spitup` | 2 | 0 | 251 | move | move_body, damage | M | no | Stockpile family (Stockpile, Spit Up, Swallow) — needs: move:stockpile |
| `move:block` | 1 | 0 | 216 | move | flow, move_body | L | yes | trap volatile (Block, Mean Look, Fairy Lock) |
| `move:magicroom` | 1 | 0 | 212 | field | move_body, residual | L | yes | item suppression room (Magic Room) |
| `move:powertrick` | 1 | 0 | 218 | move | move_body | L | yes | stored-stat swap/average (Speed Swap, Power/Guard Split, Power Trick) |
| `move:spiritshackle` | 1 | 0 | 214 | move | move_body, flow | L | yes | trap volatile (Spirit Shackle, Anchor Shot, Block, Mean Look) |
| `ability:pickup` | 0 | 0 | – | ability | residual | L | yes | item recovery (Pickup, Recycle) — needs: lastItem / usedItemThisTurn state |
| `move:ingrain` | 0 | 0 | – | move | move_body, residual, flow | L | yes | trap volatile (Mean Look, Jaw Lock, Octolock, No Retreat, Ingrain) — needs: move:meanlook |
| `move:lockon` | 0 | 0 | – | move | move_body | L | yes | accuracy volatile (Lock-On, Minimize) |
| `move:magnetrise` | 0 | 0 | – | move | move_body, residual | L | yes | ground immunity volatile (Magnet Rise) — needs: gravity flag rule |
| `move:reflecttype` | 0 | 0 | – | move | move_body | M | maybe | type change by move (Soak, Reflect Type, Trick-or-Treat) — needs: type change state (tail soak_type/type2); move:trickortreat (addedType ... |
| `move:swallow` | 0 | 0 | – | move | move_body | M | no | Stockpile family (Stockpile, Spit Up, Swallow) — needs: move:stockpile |

## 6. Champions singles (Champions OU)

**Data: none local.** There are no Champions singles replays and no Champions OU usage statistics on this machine
(the local Smogon statistics are `gen9championsvgc2026regmc[bo3]` only; the local Hugging Face copies hold Champions VGC,
Gen 9 VGC 2023-2025 and Random Doubles, no Champions singles file). The OU design (`docs/superpowers/specs/2026-10-15-gen9-ou-design.md` section 5.4) quotes the
aggregate Smogon coverage of `gen9championsou` 2026-09 (145,642 battles) at f6b924a: moves 91.1 / 90.8 %, abilities
87.4 / 91.2 %, items 97.6 / 98.9 % at baselines 0 / 1760; those raw files were on the Windows machine and are gone.

**Pool gaps (unweighted; doubles proxy marked).** The Champions OU pool is a subset of Reg M-C's: every OU gap is a Reg
M-C gap. 301 of the 310 gaps are in the OU pool (162 moves, 88 abilities, 31 items, 15 Megas, 5 battle-only formes);
the nine Reg M-C-only gaps are Zero to Hero, Palafin-Hero, Jet Punch, Quick Claw, King's Rock, Shed Tail, Acupressure,
Minimize and Double Team (banned or unobtainable in OU). Section 5 marks them. The game counts in section 5 are a
**doubles proxy only**: singles values different mechanics. Gaps that weigh more in singles than the proxy says (by
reading the format, not measured): the hazard removal moves (Rapid Spin, Defog, Mortal Spin, Court Change, Tidy Up;
batch B6), pivots and phazing, Protean/Libero, Supreme Overlord and Mold Breaker (named as the main Champions OU gaps in
the OU design 5.4).

**Singles in the engine today.** Only the development kind `POOL_SINGLES_DEV` (8, decision 0083) plays singles; it uses
the same support manifest. Singles-specific refusals: a singles battle reaching turn 101 (`dfi_end_turn`, Endless
Battle Clause not modelled) and Last Respects after a spent Revival Blessing (Last Respects is banned in OU). A
certified singles kind, the OU banlist in setup (Moody, Damp Rock, King's Rock, Light Clay, Quick Claw, Baton Pass,
Last Respects, Shed Tail, Uber species) and the singles encoder are OU-lane steps (O2–O4), not content gaps.

**A note on method.** Champions OU has no open team sheets (its ruleset is `Standard`, no `Open Team Sheets`), so the
game metric of this report (both sheets fully supported) cannot be computed from singles replays; a singles replay
gives only revealed moves, items and abilities (a lower bound per game, like the Bo1 belief source of M11).

**Proposed download (the lead asks the owner; nothing was fetched):**

1. Smogon `chaos` statistics 2026-09 for `gen9championsou`, baselines 0 and 1760 (and 1500, 1630 for comparison):
   `https://www.smogon.com/stats/2026-09/chaos/gen9championsou-{0,1500,1630,1760}.json`. Public; already used by the
   OU lane on 2026-10-14. Size not checked from here: the Reg M-C files of the same month are 4–19 MB each, so about
   5–15 MB per file is expected. This gives a usage-weighted singles ranking of the same 301 gaps.
2. Replays: whether the Hugging Face set (`HolidayOugi/pokemon-showdown-replays`) has a `[Gen 9] CHAMPIONS OU` file,
   and its size, has to be checked on its file list first (not done: no network use without the lead). With it, a
   revealed-entry coverage per game and turn becomes measurable.

## 7. Paused and unmerged branches

All four lane A branches stopped on 2026-10-11 (goal lowered to 75 %); since then main has moved through the
restructure steps (per-battle reference data and pins, items/abilities/forms moved out of `turn.c`, the format axis).
Each of them therefore needs a merge of main that re-homes its `turn.c` hunks and regenerates the pins in the
per-battle format before its remaining evidence; that merge is part of the remaining work in every row.

| branch (head) | gaps it covers | games (in / alone, today) | state at the pause (its notes) | left to do |
|---|---|---|---|---|
| `chris/expansion-cheap-c3` (`65901c29`) | 12 moves: Rock Blast, Bullet Seed, Pin Missile, Bone Rush (2-5 hits), Crabhammer, Cross Chop, Air Cutter (data), Solar Blade, Stored Power, Meteor Assault (recharge), Sky Attack (new SKY_ATTACK), Triple Arrows (new TRIPLE_ARROWS) | 276 games alone together (Meteor Assault alone +157) | marks, generator ids 101/102, covering pool battles, campaign 3033 600/600 PASS, the Sheer Force mutant for Triple Arrows killed (0015 entry 5cr) | merge main (generator ids and UNMODELED sentinels renumber against everything since), regenerate pins per battle, the remaining data mutants; review. 11 of the 12 are S rows of A0/A2 here; Triple Arrows (M, new handler) sits in B6 |
| `chris/expansion-cheap-c5b` (`073b8ad7`) | Payback; Focus Energy (not started) | Payback +75, Focus Energy +65 alone | Payback built in `dfi_get_damage` (`dfi_will_move`, newly-switched flag), recorded (`c5b_payback`) and conformant; **open:** its mutants and campaign. Focus Energy: only `DUOFORGE_VOLATILE_FOCUS_ENERGY` = 15 and view feature 46 reserved (0015 5cy) | Payback: re-sync + mutants + campaign. Focus Energy: the +2 crit stage and its START line; tail byte, view bit, Psych Up/Baton Pass copies already exist on main (M) |
| `chris/expansion-g96-terrain-burst` (`e7a35beb`) | Metal Burst (Psychic Terrain, resumed on its own branch, is on main since) | +69 alone | engine (the foe's last numeric hit ×1.5, tail bytes 33-35, cause 64 PIVOT refusal), six recordings conformant after attempt 3, `test_pool_g97.c` 47 checks (note 0064) | nine mutants and the 300-battle campaign (seed 9701); re-sync of tail bytes 33-35 against later tail users; then Mirror Coat and Counter reuse the record (P) |
| `chris/expansion-g94-protect-misc` (`f543660d`) | Last Resort (Baneful Bunker from the same branch is on main) | +41 alone | used-since-entering bits in tail bytes 8-9, view bits `volatiles2` 0-3, feature 44, three+ recordings incl. holder on p2 (note 0061 §2-6) | known gap: Ally Switch transfer of the bits (needs `dfi_swap_position_state`, which landed with G80 on main); campaign/mutants; re-sync of the feature number and tail bytes. The content lane's note of 2026-10-15 suggests a cheaper stateless variant (used = pp < pp_max); the branch's state version is the pin-exact one (PP persists across switches, `used` does not) |

Two content branches of 2026-10-14/15 (outside the brief, found while reading) are also relevant:

- `content/475-magic-room` (`5763a380`, 27 commits ahead of main, no PR open): Magic Room (K5, 0015 entry 5dm), built
  with 21 recordings and 33 mutants, two review rounds, plus fixes of older gaps (Air Balloon under Gravity, item
  presence on tie draws, all four terrain seeds received on the spot now refused). Magic Room is in 1 game; its value is
  correctness of item presence, not coverage. Its PR body draft says "finish after the review agent and after K4
  merges" (K4 Gravity merged as #593).
- `content/413-mold-breaker` (`55391ee9`, 3 commits ahead, "work in progress (paused)"): a site table of the
  Mold Breaker read sites and spec drafts; the plan is in the content lane's private notes. It is the start of B3.


## 8. Sources and caveats

- Effort and area are read, not measured. Where the content lane's private notes of 2026-10-15 (an effort estimate in
  K4 units for about 40 entries) cover an entry, the classes here agree in order; the
  notes agree on the cheapest block (Meteor Assault, Chesnaughtite, Illuminate + Starminite, Hex, Ice Body, Poison
  Point, Raging Bull, Golurkite) and on Mold Breaker, Protean/Libero, Pickpocket and Zero to Hero as the large
  single mechanics.
- Several stale refusal reasons were found (Meteor Assault, Horn Leech, Heracronite, Altarianite, Bitter Malice): their
  manifest comments name abilities or gaps that are marked or fixed since. These are the cheapest games in the list;
  each still needs its recordings before the mark.
- Two converter bugs block marks (Shelter: Goodra-Hisui switch id KeyError; Mountain Gale: Avalugg-Hisui partner
  swap) and Bulldoze needs one more name in Grassy Terrain's halving (`turn.c:1844` checks Earthquake only, as its comment
  says, while the pin's list at `data/moves.ts:7694` has Earthquake, Bulldoze and Magnitude).
- Turns and move uses: pending (see section 1.4).

## 9. Reproduce

Private inputs stay outside the repository; outputs with per-game rows go to a directory outside it.

```
# library of the commit to measure (under the machine lock), then:
DUOFORGE_LIBRARY=<build>/libduoforge_shared.so python3 tools/research/champions_coverage.py \
    --sheets <private sheet extract .jsonl> --out <private dir> [--package <python/ of that commit>]
#   or --replays <parquet files or dirs> (needs pyarrow; adds turns, |move| uses and "brought" per token)
python3 tools/research/champions_batches.py --games <private dir>/games.jsonl --batches <batches.json>
python3 tools/datagen/classify_unsupported.py <pinned Showdown checkout> --out <file>
```

The per-gap classification fields (area, core, effort, dependencies, pin, engine references, notes) were written by
reading, not by a tool; they are in `data/champions-100.json`.


## 10. Addendum: turn, move-use and brought weights; the newer replay set; singles weights

Added on 2026-10-16 after the owner approved two downloads (pyarrow and NumPy from PyPI into a private virtual
environment; the four public Smogon `chaos` files of `gen9championsou` 2026-09). Same commit (`4d4bebf8`), same method;
the headline number of section 0 is unchanged. Data: [`data/champions-100-weights.json`](data/champions-100-weights.json).

### 10.1 The replay logs read directly

`champions_coverage.py --replays` now reads the parquet files itself. On the 2026-10-02 files it yields the same
34,430 games in the same order, and every side's blockers are identical to the sheet-extract run of section 1. One
detail of the old extraction was found on the way: 25 Bo1 games print each side's sheet twice (four `|showteam|`
lines, two identical texts per side); the old extraction took them, so the reader takes a game when each side shows
exactly one distinct sheet text.

| | 2026-10-02 set (the headline set) | 2026-10-05 set (part 4 refreshed) |
|---|--:|--:|
| games (open sheets on both sides) | 34,430 | 48,835 |
| games, both sides playable | 28,373 (82.4 %) | 39,786 (81.5 %) |
| team sides playable | 62,361 (90.6 %) | 87,830 (89.9 %) |
| distinct team sheets playable | 48,593 / 54,270 (89.5 %) | 66,174 / 74,610 (88.7 %) |
| turns (last `|turn|` of each game) | 237,170 | 341,545 |
| turns in games with both sides playable | 196,704 (82.9 %) | 279,900 (82.0 %) |
| `|move|` lines | 674,083 | 973,635 |
| blocker tokens | 281 | 297 |

The 2026-10-05 set holds every game of the headline set plus 14,405 newer ones (2,568
Bo1 + 46,267 Bo3; the scan of 2026-10-10 counted 48,800 with exactly two sheet lines, the
other 35 are the twice-printed sheets). It is a second column, not the headline. Of its 16 extra blocker tokens, 7
are illegal names (unknown formes or items, e.g. Ogerpon-Hearthflame, Black Sludge) and 9 are pool gaps already listed
in section 5 that the older games never used: `move:reflecttype` (6), `move:toxicthread` (4), `item:rawstberry` (4), `move:aromaticmist` (3), `ability:pickup` (3), `ability:shedskin` (2), `ability:longreach` (2), `move:seismictoss` (1), `move:doubleteam` (1). No token outside the gap list appears.

Turn weighting barely changes the picture: blocked games are not shorter or longer than the rest (82.9 % of turns vs
82.4 % of games). Moves the engine does not support are 1,739 of the
674,083 `|move|` lines (0.26 %): a blocked game is blocked by a sheet entry that is
rarely used, which is what makes the long tail cheap to play around and expensive to finish.

**Brought.** In Reg M-C a side brings four of six; a token counts as "brought" on a side when a member carrying it
was sent out (`|switch|` or `|drag|` of its species). Over all gaps, 57.5 % of the sides that carry a gap sent its
holder out. The figure undercounts Illusion holders, which enter under another name (Bitter Malice: 7 of 192 sides,
its only learners are Illusion holders, yet 101 `|move|` lines).

### 10.2 Batches with turn weights and the newer set

| batch | alone: turns | cumulative turns | alone: games (newer set) | cumulative games (newer set) | Smogon OU 1760: summed share of its entries |
|---|--:|--:|--:|--:|--:|
| **A0** Marks and generator rows (no turn.c code) | +3,352 | 200,056 (84.4 %) | +762 | 40,548 (83.0 %) | 0.49 % |
| **A1** Damage chain: one more member of an existing modifier/base-power branch | +1,589 | 201,803 (85.1 %) | +379 | 40,973 (83.9 %) | 2.15 % |
| **A2** One clause on an existing move-body, entry or residual hook | +4,775 | 207,332 (87.4 %) | +1038 | 42,226 (86.5 %) | 5.95 % |
| **P** Paused lane A branches (finish after re-sync) | +2,082 | 209,936 (88.5 %) | +414 | 42,738 (87.5 %) | 0.37 % |
| **B1** Protean / Libero (+ Mega Greninja, Mimicry's type storage) | +1,224 | 211,735 (89.3 %) | +275 | 43,142 (88.3 %) | 2.18 % |
| **B2** Item steal: Pickpocket, Magician | +1,204 | 213,136 (89.9 %) | +226 | 43,410 (88.9 %) | 0.01 % |
| **B3** Mold Breaker (+ Mega Gyarados, Ampharos, Emboar; Gigaton Hammer) | +2,640 | 216,307 (91.2 %) | +495 | 44,018 (90.1 %) | 3.06 % |
| **B4** Forme abilities: Zero to Hero, Disguise, Hunger Switch, Forecast | +1,290 | 218,007 (91.9 %) | +267 | 44,379 (90.9 %) | 0.06 % |
| **B5** Mega abilities: Berserk, Eelevate, Innards Out/Aftermath, Healer/Hydration, Strong Jaw, Parental Bond | +1,401 | 219,769 (92.7 %) | +316 | 44,804 (91.8 %) | 0.12 % |
| **B6** Common move-body mechanics (M): crash, removal, pivots, self-KO, absorb, veils | +2,725 | 225,491 (95.1 %) | +646 | 46,183 (94.6 %) | 22.18 % |
| **B7** Flow and residual hooks (M): Supreme Overlord, entry abilities, priority tiers, cures | +675 | 226,785 (95.6 %) | +148 | 46,471 (95.2 %) | 2.09 % |
| **B8** Berries and held items (M) | +1,341 | 229,087 (96.6 %) | +237 | 46,946 (96.1 %) | 0.76 % |
| **B9** Ability change and copy (Skill Swap machinery) | +643 | 230,562 (97.2 %) | +148 | 47,265 (96.8 %) | 0.10 % |
| **B10** HP, heal and sleep (Pain Split, Wish, Rest, Sleep Talk, ...) | +786 | 232,881 (98.2 %) | +190 | 47,786 (97.9 %) | 3.70 % |
| **C** New state or engine concepts (L): Transform/Imposter, Instruct, Future Sight, traps, rooms, stockpile, ... | +1,466 | 237,063 (100.0 %) | +354 | 48,808 (99.9 %) | 3.46 % |

The order of section 4 holds on both sets and with turns. The last column is a singles weight (section 10.4): the
sum of the batch entries' shares of team slots, so an entry on many Pokémon counts once per slot.

### 10.3 The gaps with the most turns

Turns of the games that contain the gap; sides that carry it and sides that sent its holder out; `|move|` lines of
the move (both sides) in those games; Smogon Reg M-C shares of team slots (Bo1 ladder 1760, Bo3 ladder 1760). All
per-gap values for all 310 gaps are in the data file.

| gap | batch | turns | games | sides / brought | move uses | Reg M-C 1760 | Reg M-C Bo3 1760 |
|---|---|--:|--:|--:|--:|--:|--:|
| `ability:protean` | B1 | 2,096 | 350 | 352 / 206 | – | 0.12 % | 0.01 % |
| `ability:moldbreaker` | B3 | 1,633 | 223 | 223 / 95 | – | 0.13 % | 0.03 % |
| `item:starminite` | A2 | 1,509 | 243 | 243 / 126 | – | 0.05 % | 0.02 % |
| `move:gigatonhammer` | B3 | 1,469 | 189 | 189 / 87 | 77 | 0.05 % | 0.01 % |
| `item:gyaradosite` | B3 | 1,410 | 202 | 202 / 103 | – | 0.04 % | 0.01 % |
| `ability:zerotohero` | B4 | 1,409 | 218 | 221 / 128 | – | 0.07 % | 0.02 % |
| `move:meteorassault` | A0 | 1,402 | 234 | 234 / 139 | 70 | 0.06 % | 0.03 % |
| `ability:naturalcure` | A2 | 1,312 | 202 | 202 / 100 | – | 0.02 % | 0.01 % |
| `move:focusenergy` | P | 1,294 | 190 | 190 / 122 | 57 | 0.05 % | 0.02 % |
| `move:jetpunch` | B4 | 1,240 | 184 | 187 / 108 | 72 | 0.06 % | 0.02 % |
| `move:bittermalice` | A0 | 1,221 | 192 | 192 / 7 | 101 | 0.04 % | 0.00 % |
| `move:snipeshot` | A2 | 1,141 | 168 | 168 / 103 | 102 | 0.04 % | 0.01 % |
| `move:highjumpkick` | B6 | 1,137 | 179 | 179 / 119 | 45 | 0.06 % | 0.00 % |
| `ability:libero` | B1 | 1,035 | 160 | 160 / 107 | – | 0.02 % | 0.00 % |
| `item:ampharosite` | B3 | 938 | 131 | 131 / 68 | – | 0.04 % | 0.00 % |
| `item:greninjite` | B1 | 925 | 155 | 155 / 85 | – | 0.02 % | 0.01 % |
| `ability:pickpocket` | B2 | 888 | 136 | 136 / 97 | – | 0.05 % | 0.03 % |
| `ability:supremeoverlord` | B7 | 805 | 114 | 114 / 66 | – | 0.02 % | 0.00 % |
| `ability:magician` | B2 | 798 | 111 | 111 / 61 | – | 0.01 % | 0.00 % |
| `ability:disguise` | B4 | 776 | 107 | 107 / 77 | – | 0.05 % | 0.01 % |
| `item:kangaskhanite` | B5 | 770 | 124 | 124 / 75 | – | 0.04 % | 0.09 % |
| `move:transform` | C | 756 | 114 | 114 / 51 | 3 | 0.02 % | 0.01 % |
| `move:payback` | P | 754 | 123 | 123 / 69 | 24 | 0.03 % | 0.03 % |
| `move:hex` | A1 | 717 | 112 | 112 / 64 | 22 | 0.02 % | 0.00 % |
| `ability:imposter` | C | 692 | 101 | 101 / 47 | – | 0.02 % | 0.01 % |
| `move:painsplit` | B10 | 686 | 87 | 87 / 62 | 30 | 0.04 % | 0.00 % |

(Mega rows are left out of this table: their stone's row carries the same games.)

### 10.4 Champions singles weighted by Smogon

Source: Smogon `chaos` statistics 2026-09 of `gen9championsou`, 145,642 battles, cutoffs 0, 1500, 1630 and
1760 (<https://www.smogon.com/stats/2026-09/chaos/gen9championsou-0.json>, <https://www.smogon.com/stats/2026-09/chaos/gen9championsou-1500.json>, <https://www.smogon.com/stats/2026-09/chaos/gen9championsou-1630.json>, <https://www.smogon.com/stats/2026-09/chaos/gen9championsou-1760.json>). The raw files stay in the
private dataset directory. Shares are % of team slots (Pokémon) carrying the entry, rounded to two decimals. Per-entry
public Smogon shares are written here by the HauptSession's decision of 2026-10-16 (source, month, format and cutoff
named; only the values that weight the gaps; no copy of the statistics files); this supersedes the per-entry rule
of section 1.4 for public Smogon shares. Replay values stay counts without ids.

Usage-weighted coverage on main (share of team slots on supported entries; the content lane's measure):

| cutoff | moves | abilities | items |
|---|--:|--:|--:|
| Champions OU 0 | 91.13 % | 87.38 % | 97.54 % |
| Champions OU 1500 | 91.00 % | 88.27 % | 98.01 % |
| Champions OU 1630 | 90.86 % | 89.62 % | 98.45 % |
| Champions OU 1760 | 90.76 % | 91.14 % | 98.93 % |
| Reg M-C 1760 (for comparison) | 99.56 % | 98.82 % | 99.52 % |
| Reg M-C Bo3 1760 | 99.91 % | 99.69 % | 99.80 % |

The values at 0 and 1760 agree with the OU design's section 5.4 (measured at f6b924a), and every species in the OU
statistics is a row of the tables. Singles needs other gaps than doubles. The largest singles gaps at 1760:

| gap | batch | effort | OU 0 | OU 1760 | Reg M-C games (doubles) |
|---|---|:-:|--:|--:|--:|
| `move:defog` | B6 | M | 5.94 % | 7.21 % | 24 |
| `move:rapidspin` | B6 | M | 4.00 % | 4.71 % | 11 |
| `move:mortalspin` | B6 | M | 2.27 % | 3.72 % | 77 |
| `move:chillyreception` | B6 | M | 2.70 % | 2.99 % | 69 |
| `ability:moldbreaker` | B3 | L | 2.33 % | 2.92 % | 223 |
| `move:moonlight` | A2 | M | 1.26 % | 2.38 % | 44 |
| `move:painsplit` | B10 | M | 1.49 % | 2.17 % | 87 |
| `ability:supremeoverlord` | B7 | M | 2.27 % | 1.81 % | 114 |
| `move:hex` | A1 | S | 1.51 % | 1.70 % | 112 |
| `move:futuresight` | C | L | 2.06 % | 1.63 % | 38 |
| `move:firefang` | A2 | S | 0.93 % | 1.27 % | 62 |
| `move:synthesis` | A2 | M | 0.82 % | 1.26 % | 65 |
| `move:courtchange` | B6 | M | 0.87 % | 1.13 % | 4 |
| `ability:libero` | B1 | M | 1.05 % | 1.07 % | 160 |
| `ability:protean` | B1 | M | 2.06 % | 1.01 % | 350 |
| `move:wish` | B10 | L | 1.02 % | 1.00 % | 111 |
| `move:transform` | C | L | 0.91 % | 0.74 % | 114 |
| `ability:imposter` | C | L | 0.90 % | 0.74 % | 101 |
| `move:endure` | B6 | M | 0.38 % | 0.74 % | 38 |
| `move:sparklingaria` | B6 | M | 0.43 % | 0.66 % | 11 |
| `move:rest` | B10 | L | 0.81 % | 0.51 % | 67 |
| `move:highjumpkick` | B6 | M | 0.76 % | 0.45 % | 179 |
| `item:chestoberry` | B8 | M | 0.52 % | 0.38 % | 75 |
| `move:morningsun` | A2 | S | 0.43 % | 0.31 % | 15 |
| `move:triplearrows` | B6 | M | 0.18 % | 0.28 % | 35 |

**For singles the order changes.** Hazard removal and the pivot (Defog, Rapid Spin, Mortal Spin, Court Change,
Chilly Reception) carry most of B6's singles weight (22 % of team slots summed at 1760, against 0.5 % in Reg M-C), and
the healing moves (Moonlight, Synthesis, Pain Split, Wish) weigh far more than in doubles. A singles-first plan
would take A2's heals, a hazard-removal family helper out of B6 (Rapid Spin, Defog, Mortal Spin, Court Change, Tidy
Up; they share one removal helper) and B3 Mold Breaker right after A0. That needs the certified singles kind of the
OU lane first; today only `POOL_SINGLES_DEV` plays singles.

### 10.5 Greedy order on the newer set

The first twelve steps on the 2026-10-05 set (48,835 games): 1. `move:meteorassault` +204; 2. `ability:protean` +163; 3. `move:payback` +117; 4. `ability:pickpocket` +117; 5. `ability:magician` +112; 6. `move:bittermalice` +110; 7. `ability:disguise` +114; 8. `ability:electromorphosis` +102; 9. `move:focusenergy` +98; 10. `move:snipeshot` +131; 11. `item:altarianite` +99; 12. `move:hex` +89. The top five are the same mechanics
as on the headline set, in nearly the same order.

### 10.6 Reproduce

```
python3 -m venv <private venv> && <private venv>/bin/pip install pyarrow numpy
DUOFORGE_LIBRARY=<build>/libduoforge_shared.so <private venv>/bin/python tools/research/champions_coverage.py \
    --replays <the replay parquet files> --out <private dir>
python3 tools/research/champions_batches.py --games <private dir>/games.jsonl --batches <batches> --out <file>
```
The Smogon weights come from the public `chaos` files named above (a share per entry: the summed weight of the entry
over all Pokémon divided by the summed ability weight, which counts each Pokémon slot once).

## 11. Long games: mechanics no usage statistic shows

PP, Struggle, the Toxic counter and the turn limits never show up as a blocker of a team sheet; they matter in long
games (singles, self-play stalls). Read against the pin (Champions mod first) and the engine at `4d4bebf8`; the
entries with all citations are `long_game_mechanics` in `data/champions-100-weights.json`.

| mechanic | status | evidence | what is left | area / core / effort / batch |
|---|---|---|---|---|
| PP use and Pressure (spread, several Pressure foes, redirection, Imprison's mustpressure, field moves, locked turns) | supported | 11 recorded `g53_*`/`g78`/`o2` Pressure battles, `g27_disable_pp`; pin `battle-actions.ts:278-291, 467-484`; engine `turn.c:6004-6040, 7561-7581` | latent: the `cant nopp` path (`turn.c:7567`) emits no line; unreachable today, reachable once Spite, Eerie Spell or Instruct land; Snatch is not in the pool | move_body, S, with B6 |
| Struggle (0 PP on all moves or none selectable; typeless; `-activate`; recoil round(maxHP/4), direct damage) | supported | 70 recorded battles contain a Struggle (`s2_struggle`, `s2_typeless_struggle`, `s3_struggle_end`, `g4_rock_head_struggle`, `g67_mg_struggle`, ...); `request.c:124-269`, `turn.c:562, 7606, 9293-9296` | – | – |
| Toxic counter (stage +1 to 15, reset on switch-in, Baton Pass, Natural Cure) | supported | `g36_toxic_*`, `g47_toxic_reset`, `g47_switch_tox_tie`; `test_pool_g36.c`; invariant caps 15 (`invariants.c:1010`); no battle reaches stage 15 | engine clears the stage when the Pokemon leaves, the pin when it comes back (same value whenever read); Baton Pass passes no status; Natural Cure (A2) must clear it with the status | flow, S, A2 |
| Turn limit: a tie when the turn passes 1000, every format (not the Endless Battle Clause); warnings from turn 500 | **missing in doubles**; singles refuses turn 101 by name | pin `battle.ts:1624, 1834-1852`; engine `turn.c:11797-11813`; no battle passes turn 100 | a doubles battle past turn 1000 plays on where the reference ties: a silent divergence. Real VGC games never reach it (server timer), self-play can. End as a tie (RESULT_TIE exists) or refuse by name | flow, S, A2 (or as a fix before) |
| Endless Battle Clause: staleness from turn 101, berry-cycling loser (Champions OU only; Reg M-C's Flat Rules lack it) | partial: singles refuses turn 101 | `rulesets.ts:2-8` vs `formats.ts:288-299`; `battle.ts:1803-1903`; `pokemon.ts:41-45, 1787-1797, 1868-1879`; test `duoforge.state.singles` | staleness bits per member, position and item; the loser rule from the sheets; reachable only through Trick/Switcheroo/Symbiosis, Skill Swap/Entrainment, and the Recycle/Harvest/Pickup gaps. A cheaper exact step: refuse at 101 only when some Pokemon could be stale | flow (+ move_body), M, B7, singles only |
| Restoration loops: Leppa Berry, Recycle, Harvest, Pickup, Rest/Sleep Talk, Wish | gaps (section 5) | replay games: Leppa 83, Wish 111, Rest 67, Harvest 33, Recycle 3 | each needs its gap row; Recycle/Harvest/Pickup make the clause's staleness reachable | B8 / B10 / C |
| VGC Timer, timeout tiebreak, harness step caps | not simulator rules | `rulesets.ts:778-786`; `duoforge_battle_tiebreak`; `recipes.py` max_steps | – | – |

The one item to act on is the doubles turn limit: today a self-play battle past turn 1000 diverges silently.
Everything else is supported, refused by name, or waits on its own gap row.
