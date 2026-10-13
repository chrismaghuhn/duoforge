#ifndef DUOFORGE_COMBAT_ABILITY_FAMILY_H
#define DUOFORGE_COMBAT_ABILITY_FAMILY_H
/* Existing family rules, grouped by family. The turn still selects their
 * position in the damage chain and owns setter scheduling and event order.
 * Pure column predicates are checked by tests/abilities/test_ability_family.c. */
#include "combat/abilities/current.h"
#include "combat/abilities/ate.h"
#include "combat/abilities/pinch.h"
#include "combat/abilities/weather_setter.h"
#include "combat/abilities/terrain_setter.h"

#endif
