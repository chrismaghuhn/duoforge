#ifndef DUOFORGE_TESTS_SUPPORT_TEAM_C_H
#define DUOFORGE_TESTS_SUPPORT_TEAM_C_H
/*
 * Team C fixtures (docs/decisions/0009): the contexts of the two TEAM_C data
 * kinds and the real Team C of docs/research/third-team/team-c.txt.
 */
#include <duoforge/duoforge.h>

/* TEAM_C and TEAM_C_DEV, roster 6 and brought 4. */
extern const duoforge_context_config df_config_team_c;
extern const duoforge_context_config df_config_team_c_dev;

/* Writes the real Team C into a side: six members with the sets, genders
 * and Stat Points of team-c.txt, in its order (Sneasler, Incineroar,
 * Salamence, Indeedee-F, Kingambit, Basculegion). */
void df_put_team_c(duoforge_side_setup *side);

#endif
