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
right for hindsight labels, but wrong live. The particle tracker calls `side_facts` on the lines received so far only. A test pins
this: two logs with the same prefix and different futures give the same particles at every decision point of the prefix.

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
  `error:<type>`), and so is every stop.

**Exactness.** A particle is a draw from the prior given the facts and the absence of a contradiction. With a 0/1 consistency
check, keeping the consistent particles and replacing the others by rejection gives draws of the same posterior as drawing all of
them anew. The posterior weights a set only by whether it agrees with the log, not by how likely the log is under it (a set with
Protect does not become likelier because Protect was used). That is the replay's set belief too, and it is named here as the model.

**Determinism.** The draw of member `m` of particle `i` at attempt `a` uses the word SHA-256(`seed|key|side|m|a|i`), as
`setbelief.word`. The same stream, seed and key always give the same particles.

## Explicitly refused (never silent)

| reason | cause |
|---|---|
| `cts:no-consistent-set <species>` | no set of the prior agrees with the member's facts (a species outside the prior included) |
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

## The named limit of version 1 (HauptSession, 2026-10-12)

DuoForge's observation and public record have only one shape: both sheets open. In every particle, therefore:
- the foe's model sees our whole sets, although under CTS the foe does not know them;
- our root sees the drawn foe sets as if they were open.

This bias is measured, not assumed: the same CTS games are searched once with particles and once with the true open sheets (the
upper bound), and the difference is what version 1 costs. Reveal tracking in the state and view (the engine marks which facts each
player has seen) is the version-2 item of #385.

## Evidence (this PR)

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
- **Unit tier** (`duoforge.python.live_cts`, 20 tests):
  - the live fixture's pin;
  - no hindsight;
  - contradictions: Choice lock, move off the set, revealed ability, Item Clause, and a cheap Item Clause redraw;
  - the named stops;
  - determinism and weights;
  - the hook off for every plain tracker.
- **Cost**, measured on this machine (Windows, under the machine lock, with another lane's job in the other slot):
  - One open-sheet tracker folds a pool stream at 30 us per line at p50 (42 us at p95). A full refold of a 600-line game is
    therefore about 20 ms per particle.
  - The particle tracker's `feed` per message with 16 particles and the wide prior (28384 messages): p50 17 ms, p95 53 ms,
    p99 77 ms, max 1.4 s. The maximum is a redraw cap, which ends the battle's tracking.
  - This cost includes the 16 records and observations of each decision point, which the search needs anyway.
  - The decision latency of the search over 16 records is measured with the arena PR.
