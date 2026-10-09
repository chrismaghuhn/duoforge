#ifndef DUOFORGE_RNG_DRAW_H
#define DUOFORGE_RNG_DRAW_H
/*
 * RNG draw sites (docs/decisions/0006 section 5). Every gameplay draw goes
 * through dfi_draw with a named site and the reference's bounds: random(lo,
 * hi) is an integer in [lo, hi) (sim/prng.ts:86-104). In play the value
 * comes from the battle's PCG32 (decision 0001) as lo + bounded(hi - lo).
 *
 * TEST-ONLY TAPE: conformance tests replace the PCG by a tape of outcomes
 * recorded from the reference. Each entry states the site and bounds it
 * answers; a different site or bound, a value outside the bounds, or an
 * exhausted tape fails the draw (E_INVARIANT) and marks the source failed.
 * There is no silent fallback. The tape is not reachable from the public
 * API; replay and normal play always use the PCG.
 *
 * An optional log records the sites in draw order for draw-count tests.
 */
#include <stdbool.h>
#include <stdint.h>

#include <duoforge/duoforge.h>

#include "rng/pcg32.h"

/* Stable site ids (recorded in fixtures; never renumber). */
#define DFI_SITE_SPEED_TIE 1u      /* shuffle of a tied group: random(i, n) */
#define DFI_SITE_ACCURACY 2u       /* random(100) < accuracy */
#define DFI_SITE_CRIT 3u           /* random(24) or random(8) == 0 */
#define DFI_SITE_DAMAGE_ROLL 4u    /* random(16) */
#define DFI_SITE_SECONDARY 5u      /* random(100) < chance */
#define DFI_SITE_STALL 6u          /* random(counter) == 0 */
#define DFI_SITE_SLEEP_TURNS 7u    /* sample([2, 3, 3]): random(3) */
#define DFI_SITE_FREEZE_THAW 8u    /* random(4) == 0 */
#define DFI_SITE_FULL_PARALYSIS 9u /* random(8) == 0 */
#define DFI_SITE_CONFUSION_TURNS 10u /* random(2, 6) */
#define DFI_SITE_CONFUSION_HIT 11u /* random(100) < 33 */
#define DFI_SITE_RANDOM_TARGET 12u /* random(n) over the valid foes */
#define DFI_SITE_STATUS_PICK 13u   /* Dire Claw: sample(['psn', 'par', 'slp']), random(3) (Team C) */
#define DFI_SITE_INSERT_TIE 14u    /* BattleQueue.insertChoice: random(firstIndex, lastIndex + 1) among the tied actions (Encore, POOL data) */
#define DFI_SITE_TRACE 15u         /* Trace: sample(the foes whose ability it can copy), random(n) (POOL) */
#define DFI_SITE_POISON_TOUCH 16u  /* Poison Touch (POOL data): randomChance(3, 10), random(10) < 3 */
#define DFI_SITE_CURSED_BODY 17u   /* Cursed Body (POOL data, step G27): randomChance(3, 10), random(10) < 3 */
#define DFI_SITE_FLAME_BODY 18u    /* Flame Body (POOL data, step G30): randomChance(3, 10), random(10) < 3 */
#define DFI_SITE_STATIC 19u        /* Static (POOL data, step G39): randomChance(3, 10), random(10) < 3 */
#define DFI_SITE_DRAG 20u          /* the drag of Roar, Whirlwind, Dragon Tail, Circle Throw and Red Card (POOL data, step G46):
                                    * sample(the bench, non-fainted, in side.pokemon order): random(n), n >= 1 (sim/battle.ts:1570-1588) */
#define DFI_SITE_LOCK_TURNS 21u    /* the lock of Outrage, Thrash and Petal Dance (POOL data, step G56): lockedmove's onStart,
                                    * random(2, 4) = 2 or 3 turns (data/conditions.ts:265) */
#define DFI_SITE_MULTIHIT_COUNT 22u /* Scale Shot, Icicle Spear (POOL data, step G54): sample of 20 hit counts, random(20) */
#define DFI_SITE_COUNT 23u

typedef struct dfi_tape_entry {
    uint32_t site;
    uint32_t lo;
    uint32_t hi;
    uint32_t value;
} dfi_tape_entry;

typedef struct dfi_draws {
    dfi_rng *rng;               /* play: the working copy's generator */
    const dfi_tape_entry *tape; /* TEST-ONLY; NULL in play */
    uint32_t tape_len;
    uint32_t tape_pos;
    bool failed;       /* a tape mismatch or exhaustion happened */
    uint8_t *log;      /* optional: sites in draw order */
    uint32_t log_cap;
    uint32_t log_len;  /* counts every draw, also beyond log_cap */
} dfi_draws;

/* A source that draws from rng (no tape, no log). */
dfi_draws dfi_draws_from_rng(dfi_rng *rng);

/* random(lo, hi) at a site; hi > lo. E_INVARIANT for bad arguments or a tape
 * failure, E_EXHAUSTED from the generator. *out is written only on OK. */
duoforge_status dfi_draw(dfi_draws *d, uint32_t site, uint32_t lo, uint32_t hi, uint32_t *out);

/* randomChance(numerator, denominator): random(denominator) < numerator. */
duoforge_status dfi_draw_chance(dfi_draws *d, uint32_t site, uint32_t numerator, uint32_t denominator,
                                bool *out);

#endif
