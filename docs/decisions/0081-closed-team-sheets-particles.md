# 0081 - Closed team sheets: the particle tracker (M14, CTS lane)

Status: plan accepted by HauptSession on 2026-10-12 (#385, number 0081, one lean PR with this note, `cts.py`, the tracker hook and
the tests). Builds on decision 0016 (the live adapter and its tracker), decision 0023 (the public view and its worlds), and decision
0019 together with the M11 Bo1 spec (the replay's set belief, `bo1_belief`). The arena switch (`pkmn_arena`), the set-prior table
from Smogon's usage stats and the honest search over one record per world each come in their own PRs.

## The problem

The live tracker folds the protocol into DuoForge's observation and public record. That observation is the one of decision 0007:
both teams' **open** sheets. Under closed team sheets (CTS, the Bo1 ladder `gen9championsvgc2026regmc`), no `|showteam|` line
comes, so the tracker never becomes ready. The arena mode therefore answered every CTS battle with `/choose default` (reason
`closed_team_sheets`). The CTS bot lost 0:10 that way (#385, 2026-10-12).

## What a CTS player knows

- **Team preview:** the foe's six species and genders (`|poke|`). The Champions pin shows no held-item flag there: the field after
  the details is empty for every member, with or without an item (`data/mods/champions/rulesets.ts:40` at the pin). A preview of
  fewer than six members is refused by `side_facts` (`skip:belief-preview`), as the replay refuses it; the Bo1 ladder brings six.
- **The battle:** everything the log reveals, folded from the log's **prefix up to the decision point** and nothing later. The facts
  are those of `duoforge_replay.facts.side_facts`:
  - the moves each member used as its own move;
  - its original item, from the first line that names it (`-enditem`, `-item`, `[from] item:`, a Mega Evolution's stone, Knock
    Off, Frisk);
  - its original ability, from the first line that names it.
  `side_facts` names a fact only where no earlier line could have changed it (Trick, Switcheroo, Thief, Skill Swap, Entrainment,
  Mummy, a forme change, and others). After such a line it records nothing more for that member, and it never guesses.
  This PR adds one form it missed: `cant|X|ability: A|Move|[of] Y` names X's own ability (Armor Tail, Queenly Majesty, Dazzling,
  Damp print the holder first; Truant has no `[of]`). The fixture's turn 1 has such a line. Without it, a particle with another
  ability for Farigiraf was kept. The replay's `bo1_belief` gets the same, more complete facts.
- **Hidden:** the rest of each set (moves, item, ability, nature) and the stat points. The stat points stay the honest search's
  spread draw, as under open sheets.

The replay's `bo1_belief` takes the facts of the **whole** game: a training row of turn 3 knows a move first used on turn 7. That is
right for hindsight labels, but wrong live. The particle tracker calls `side_facts` on the lines received so far only. Two tests pin
this. A move first used on turn 2 counts from its line on, never before. And two streams with the same first turn and different
second turns give the same particles up to turn 2's decision point.

## The particles

A particle is one complete hypothesis of the foe's team: six whole sets (species, gender, moves, item, ability, nature, level 50).
The particle tracker (`python/duoforge_live/cts.py`, `ParticleTracker`) holds `n` particles (live: 16, one per search world). Each
particle owns an ordinary `Tracker`.

**Draw.**
- A particle's sets are drawn per member from a set prior (`SetPrior`): a list of whole sets per species with integer weights.
- Only sets that agree with the member's facts can be drawn: every used move is among its moves, and a revealed item or ability is
  its own.
- A team that breaks the Item Clause (two members with the same item) is redrawn.
- A whole set is drawn jointly: moves, item, ability and nature never come from independent marginals here. The prior's table
  (a later PR) builds those sets from the team registry's published sets, reweighted by Smogon's usage stats. Marginals with
  explicit consistency rules only fill species without enough joint sets, and that table counts each such case.
- No set of the species agrees with the facts: the tracker stops with `cts:no-consistent-set <species>` (a `lines.Stop`). The
  prior is never widened silently, and no set is borrowed from another species.

**Fold.** At the team-preview request, every particle's tracker receives the stream as received. Right after the request come two
synthesized `|showteam|` lines:
- the own side's, from the own paste;
- the foe's, from the particle's drawn sets.

This is the place and form of the real lines under open sheets (`teams.pack`, level 50, no stat points). From then on, every
particle folds every line. The tracker is the **unchanged** open-sheet tracker: no battle rule moves into Python. Each particle
gives its own observation and public record. The honest search builds world `w` from particle `w`'s record (that PR comes later).

**Conditioning.** Before a batch of lines is folded, the facts of the prefix including the batch are taken.
- A particle whose sets contradict a fact is replaced: a fresh draw under the current facts, then a fold of the whole received
  stream from the start.
- A contradiction the facts cannot express is found by the particle's fold itself. The tracker has a hook, off by default and on
  only in particles (`Tracker.check_foe_sheet`). It raises `SheetContradiction` with a named reason:
  - `move-not-on-set`: a foe position's own move (cause NONE) is not on the drawn set (Struggle excepted);
  - `choice-lock`: a foe position that holds a Choice item and is locked into a move uses another own move (#423). The lock is the
    tracker's own `choice_slot`, which the open-sheet fold already keeps: it is set by the move line of a holder, and cleared when
    the item is gone or the holder leaves.
  The particle is then replaced as above.
- A contradicted Choice lock names its member (#385 step 3). The tracker assumes a lock only for an item no line changed, and
  Showdown enforces the lock (a Klutz holder aside, #448). So that member's **original** item is no Choice item, and every
  set with one contradicts the log in every particle. From then on, the member's draws leave Choice sets out. This changes
  only how fast rejection finds a set, not which sets are kept. It is counted once per member (`choice-excluded`).
  Without it, a species the prior gives mostly Choice items, met with an unusual moveset, ran into the redraw cap.
- Some contradictions make the open-sheet fold raise. For example, `lines.check` stops at an ability or item announcement that is
  not the holder's sheet's. Another example is the own-PP check of the request, which disagrees when a drawn foe has a Pressure
  the lines never showed. The rule:
  - A particle whose fold raises (a `lines.Stop` or a `ValueError`) is replaced, counted as `stop:<reason>` or
    `error:<type>`.
  - A line that stops every fold (a feature the tracker does not fold) makes every draw fail too. Rejection cannot tell that
    from a set the log needs that is rare in the prior. In the wide-prior test, no particle held Politoed's Damp Rock and all
    four were refused alike, and 64 draws did not find it either. So the tracker never guesses which of the two it is:
    after `MAX_ATTEMPTS` failed draws it stops by name with `cts:redraw-cap stop:<reason>` or
    `cts:redraw-cap error:<type>`, the last exception chained as the cause. The live mode's fallback takes such a stop as
    it takes a tracker stop today.
  - The cost is `MAX_ATTEMPTS` folds of one particle, once, at the line that ends the battle's tracking.
- **The engine's record check.** At each decision point, every particle's record goes through the engine's check
  (`public_parts`). A record the engine refuses contradicts the particle's sets: for example, a rain that outlasts a drawn
  Politoed's 5 turns without Damp Rock. This is the only "absent line" evidence that version 1 catches, and the engine
  catches it.
- An item consumed or knocked off needs no rule here: the open-sheet fold follows it (`item_used`, `item_now`, `REVEALED_*`), and
  `side_facts` takes the item the line names as the original.
- Redraws are capped. `MAX_ATTEMPTS` (64) folded draws of one particle that all fail stop the tracker with
  `cts:redraw-cap <reason>`. A draw that breaks the Item Clause is drawn again **before** any fold, because drawing is cheap;
  `MAX_DRAWS` (4096) such draws stop it with `cts:redraw-cap item-clause`.
- Every redraw is counted by its reason (`facts`, `move-not-on-set`, `choice-lock`, `item-clause`, `stop:<reason>`,
  `error:<type>`), and every named stop by its first word (`stop.cts:facts`, `stop.cts:no-consistent-set`,
  `stop.cts:redraw-cap`).
- **Before the team preview,** the particles do not exist yet. An open-sheet tracker folds the lines meanwhile, so a battle line
  before the sheets raises and a battle over before them has ended, exactly as under open sheets. A stream that never brings a
  team-preview request is never ready; the arena mode's deadline fallback answers it, as today.

**Exactness.** A particle is a draw from the prior given the facts and the absence of a contradiction. With a 0/1 consistency
check, keeping the consistent particles and replacing the others by rejection gives draws of the same posterior as drawing all of
them anew. The posterior weights a set only by whether it agrees with the log, not by how likely the log is under it (a set with
Protect does not become likelier because Protect was used). That is the replay's set belief too, and it is named here as the model.

**Determinism.** The draw of member `m` of particle `i` at attempt `a` uses the word SHA-256(`seed|key|side|m|a|i`), as
`setbelief.word`. The same stream in the same batches, with the same seed and key, always gives the same particles. The facts are
taken per batch, so where the batches split decides when a particle is redrawn. A live log that is to reproduce the particles
must keep the batches (the arena PR).

**A redrawn particle passes every check a kept one passed.** A particle drawn anew folds the stream from the start and takes its
parts at every decision point it reaches, so the engine checks its record at each of them. It is kept only if every check passes.
Without this, a fresh draw would skip the record checks of earlier decision points (review of 2026-10-12). The decision point's
parts are those taken when its request was folded, so a particle redrawn mid-turn shows the same decision point as the others.

## The set prior (#385 step 3)

The live prior is the committed table `data/belief/smogon-sets-regmc-2026-09.json`, loaded with `SetPrior.from_table`. Its
file is pinned by `smogon_sets.TABLE_SHA256`, and the engine checks every set again on load (8,613 sets, 0.3 to 0.6 s on
this machine). `python -m duoforge_search.smogon_sets --stats DIR [--fetch] [--check]` builds it.
- It uses the pinned Smogon files of `smogon_spreads` (the same cache outside the repository) and the team registry
  (`data/teams`).
- `--check` rebuilds the table, compares its bytes, and checks the pin.
- The credit is in its header and in `THIRD_PARTY_NOTICES.md`.

**Whole sets, not marginals.** The table holds item, ability, nature and moves as one set: the registry's 12,372 members,
3,140 distinct sets, each counted once per team. A set the engine's setup refuses, or with a name the tables lack, is dropped
and counted. A set that holds its species' Mega Stone belongs to the Mega forme's bucket.

**Smogon reweights them, at one cutoff per species.** A species takes the highest cutoff at which its buckets together weigh
enough (the spread table's threshold, both formats summed); every bucket is read there. Mixing buckets read at different
cutoffs mixed weights of different scales: in review, Aggron's stone came out at 9 % instead of 97 %. Per bucket, the
registry counts are raked toward Smogon's shares by iterative proportional fitting: the item, the ability, the nature (from
the spreads) and each move's share of sets.
- A move's share is its weight over the bucket's sets. Smogon's move weights sum to four slots per set, empty slots
  included.
- A target blends Smogon with the registry's own share (20 sets' worth), so a part Smogon never saw keeps a small weight.
  Where Smogon names none of the support's parts, the support's own shares are the target.
- A Mega bucket has no ability target: Smogon records the Mega's ability there, not the sheet's.
- Smogon's mass outside the support is counted (`uncovered_share`).
- Raking does not always meet its targets: the support may not allow them. The largest gap (`residual_max`) and the number of
  buckets left more than 0.1 from a target (`buckets.residual_over_0.1`, 98 of 315) are counted.

**Mixing.** A species' buckets mix by their Smogon weights, each blended with 20 sets' worth of its registry share. A species
Smogon does not name is the registry's alone (counted).

**Thin buckets get drawn sets.** A bucket is thin when it has fewer than 4 registry sets, or when its sets leave more than 25 %
of Smogon's item, ability or move mass uncovered.
- 32 sets are drawn from its marginals and raked with its registry sets.
- The drawn sets follow explicit rules: four distinct moves; no Protect or Detect beside a Choice item; a Mega bucket's stone
  with the base species' ability; the engine's setup accepts the set.
- Every such case is counted in the table's `derivation`.

**Dex siblings.** A setup-legal forme the table lacks takes the sets its own setup accepts of **the one** species of the
table with its dex number **and its types**. That is the case for a forme Smogon counts under its sibling's name:
Toxtricity-Low-Key under "Toxtricity", Squawkabilly-White and -Yellow under "Squawkabilly" (counted:
`species.from_dex_sibling`). A forme of other types (Tauros-Paldea-Combat beside Tauros), or with several such siblings, has
its own Smogon entry when it is played. Its absence means no data, and it gets no sets.

**Levels at the draw.** When no set agrees with a member's facts, the tracker does not stop at once.
- **Level 1** (as the replay's `SetBelief`): every set that agrees on the revealed item and ability is a base for the used
  moves. The used moves come first; the base's own other moves fill up to four.
- **Level 2:** when level 1 finds no base (an item or ability the prior never pairs with the species), every set of the
  species is a base for the revealed item, ability and used moves.
- At both levels, a Choice item's holder gets no Protect or Detect from the base. A result the engine's setup refuses, or
  with a name the tables lack, is left out and counted (`levels.refused`). Any other failure of the setup check raises.
- `level1` and `level2` count the distinct facts of a member that needed them, once, not each particle's draw.
- `cts:no-consistent-set` remains for a member no level can give a legal set. In the held-out measurement below that is
  only Ditto, which the table lacks (one move, Transform).

**The levels are outside the exactness argument.** The rejection argument of "The particles" holds for members with a set
that agrees with the facts. A level-1 or level-2 member's candidates are built from the current facts: a particle kept from
an earlier batch was drawn from the level of those earlier facts, which is not the later level's distribution conditioned on
agreeing. Such a member's sets are a named approximation, counted, not a posterior draw.

**Measuring it.** `tools/research/cts_set_prior_eval.py` prints the two measurements below:
- `quality --corpus` against a private set corpus;
- `levels --replays` on private replay files (needs pyarrow).

Both print aggregates only.

## Explicitly refused (never silent)

| reason | cause |
|---|---|
| `cts:no-consistent-set <species>` | no set of the prior agrees with the member's facts, and levels 1 and 2 give no set the engine accepts (a species outside the prior included) |
| `cts:redraw-cap <reason>` | `MAX_ATTEMPTS` folded draws of one particle all failed: they contradicted the log, or the line stops every fold (`stop:<reason>`, `error:<type>`; the last exception is the cause) |
| `cts:redraw-cap item-clause` | `MAX_DRAWS` draws of one particle all broke the Item Clause |
| `cts:facts <skip>` | `side_facts` cannot describe the prefix (a Transform, a possible Illusion, a preview it cannot match) |

## Not conditioned on in version 1: the absence of a line (named, to be measured)

The conditioning above uses what the log **shows**. Some evidence is a line that did **not** come:
- an entry ability that announces itself (Intimidate, a weather or terrain setter, Pressure, Unnerve) and did not;
- an item whose effect would have printed and did not: Leftovers or Black Sludge at the end of a turn, a Sitrus Berry below half
  HP, a Focus Sash at a KO;
- a duration an item lengthens, where it ends on turn 5 although the drawn set holds Light Clay or a rock. The reverse, a rain
  outlasting a drawn Politoed's 5 turns, is caught: the engine refuses that record (see above). Whether every duration of this
  kind is caught that way is part of the audit below.

The open-sheet fold never predicts lines, so a particle that holds such a set is kept. Predicting them means knowing when the
rule would print a line, which is a battle rule. Under AGENTS.md it belongs in the engine, not in a Python list. Version 1
therefore does not condition on missing lines. Two measurements, reported with the arena PR, show how much this costs:
- **Set-prior check:** the share of true sets among the drawn particles over held-out CTS games.
- **Audit:** the cases where a kept particle's ability or item would have printed a line that the log does not have.

The engine query that would close this gap is an item for HauptSession to decide.

## A known gap of the hook: Klutz (#448)

At the pin, a Choice item adds the `choicelock` volatile to every holder, but a holder that ignores its item (Klutz) is not held
by it (`data/conditions.ts` choicelock: `onBeforeMove` and `onDisableMove` skip `ignoringItem()`). Such a holder may use another
move while it carries the lock. The tracker's `choice_slot` follows the volatile, but the `choice-lock` hook assumes that a locked
holder never uses another move. It would count a Klutz holder's true Choice set as a contradiction and draw it again: a bias,
never a silent stop.

Today the case is not reachable. The engine marks Klutz `DFI_HANDLER_UNMODELED`, so every world with a Klutz holder is refused by
the support gate. The fix belongs with Klutz's modelling: the hook asks the engine whether the item is ignored, never a Python list
of abilities. Issue #448 holds the minimal example.

## The named limit of version 1 (HauptSession, 2026-10-12)

DuoForge's observation and public record have only one shape: both sheets open. In every particle, therefore:
- the foe's model sees our whole sets, although under CTS the foe does not know them;
- our root sees the drawn foe sets as if they were open.

This bias is measured, not assumed: the same CTS games are searched once with particles and once with the true open sheets (the
upper bound), and the difference is what version 1 costs. Reveal tracking in the state and view (the engine marks which facts each
player has seen) is the version-2 item of #385.

## Evidence (PR #447)

- **Pin**, reference tier (`duoforge.python.live`, `ClosedSheetsPoolTest`). Input: every committed pool battle's client streams
  without their `|showteam|` lines, both players, with a prior that holds only the true foe team. Result over 1932 streams:
  - 1929 are equal at every decision point, byte for byte: request, domain, observation, and the public record with its status,
    causes and reason.
  - Where the open tracker stops or fails while folding, the particles stop by name (`cts:redraw-cap stop:<reason>`,
    `cts:redraw-cap error:ValueError`). Where the decision point's own calls fail, they fail alike.
  - The 3 streams against an Illusion sheet stop with `cts:facts skip:illusion`.
  - A stream that runs to its end draws nothing again.
- **Wide prior**, reference tier. The prior holds every set of every pool team (1485 sets, weighted by count). Every stream ends
  by name, with 4 particles:
  - 1749 complete;
  - 175 stop at a feature the tracker does not fold (`cts:redraw-cap stop:feature:SUBSTITUTE` and others);
  - 14 stop with `cts:redraw-cap error:ValueError` (own-PP and record-check streams);
  - 3 stop on Illusion;
  - 6 decision points fail in the own options as the open tracker's do.

  The redraws include `facts`, `choice-lock` (#423) and `item-clause`.
- **Damp Rock**, reference tier. A rain past 5 turns rules out a drawn Politoed without Damp Rock, through the engine's record
  check.
- **Unit tier** (`duoforge.python.live_cts`, 23 tests):
  - the live fixture's pin;
  - no hindsight;
  - contradictions: Choice lock, move off the set, revealed ability, Item Clause, and a cheap Item Clause redraw;
  - a redrawn particle passes the engine check of every earlier decision point;
  - lines before the team preview fold as under open sheets;
  - the named stops, each counted;
  - determinism and weights;
  - the hook off for every plain tracker.
- **Cost**, measured on this machine (Windows, under the machine lock, with another lane's job in the other slot):
  - One open-sheet tracker folds a pool stream at 30 us per line at p50 (42 us at p95). A full refold of a 600-line game is
    therefore about 20 ms per particle.
  - The particle tracker's `feed` per message with 16 particles and the wide prior (28384 messages): p50 18 ms, p95 87 ms,
    p99 168 ms, max 3.4 s.
    - Before the review's fix: p50 17, p95 53, p99 77 ms, max 1.4 s. A redrawn particle now passes the engine check at every
      earlier decision point, which costs the tail.
    - The maximum is a redraw cap (64 folds with their checks), which ends the battle's tracking. It is far below the arena's
      45 s per request.
  - This cost includes the 16 records and observations of each decision point, which the search needs anyway.
  - The decision latency of the search over 16 records is measured with the arena PR.

## Evidence of the set prior (#385 step 3)

**Prior quality on real sets** (`cts_set_prior_eval.py quality`). The measure is the 403,107 sets of the open-sheet replays'
training split, counted once per team. It stays private outside the repository and is not an input of the table.

| | registry, raw counts | set table |
|---|---|---|
| the true set is in the prior | 73.4 % | 73.6 % |
| a set with its item, ability and moves | 79.5 % | 80.0 % |
| a set with its item, ability and two of its moves | 87.2 % | 88.8 % |
| a set with its item and ability | 93.3 % | 95.7 % |
| the species is missing | 1.6 % | 0.03 % |
| mean log probability of the true set, where present | −2.63 | −2.51 |

**Levels on held-out closed-sheet games** (`cts_set_prior_eval.py levels`). 2,000 Bo1 games without sheets of the test split
(`gen9championsvgc2026regmc`, the replay dump of 2026-10-10). Each member is checked with the facts of the **whole** game,
the strictest case:

| level | members |
|---|---|
| level 0 (a table set agrees) | 21,902 (93.2 %) |
| level 1 | 1,197 (5.1 %) |
| level 2 | 397 (1.7 %) |
| no legal set (Ditto) | 12 (0.1 %) |

- Sides that would stop on the prior: 12 of 3,918, all of them Ditto. Without level 2 it would be about 9 %, mostly an item
  the table never pairs with the species (Leppa Berry on Pawmot, Rocky Helmet on Farigiraf).
- Sides refused by `side_facts` before any draw, by name:
  - 41 with a possible Illusion;
  - 22 with a Transform;
  - 19 with a forme name the tables lack: Palafin-Hero 12, Alcremie-Salted-Cream 3, Mimikyu-Busted 2, Latios 1, Tapu Lele 1.
