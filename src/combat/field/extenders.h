#ifndef DUOFORGE_COMBAT_FIELD_EXTENDERS_H
#define DUOFORGE_COMBAT_FIELD_EXTENDERS_H

/* The held items that lengthen a field effect when its setter holds them (data/conditions.ts and data/moves.ts
 * durationCallback: source.hasItem). One definition for the turn code (weather.h dfi_weather_rock, the terrains and the
 * screens in turn.c) and for the live tracker, which reads them through the state layout dump (#512 D1), never a copy. */
#include "data/formats/reg-mc/pool_tables.h"

#define DFI_WEATHER_ROCK_RAIN DFI_ITEM_DAMPROCK  /* Rain Dance */
#define DFI_WEATHER_ROCK_SUN DFI_ITEM_HEATROCK   /* Sunny Day */
#define DFI_WEATHER_ROCK_SAND DFI_ITEM_SMOOTHROCK /* Sandstorm */
#define DFI_WEATHER_ROCK_SNOW DFI_ITEM_ICYROCK   /* Snowscape */
#define DFI_TERRAIN_EXTENDER DFI_ITEM_TERRAINEXTENDER /* every terrain (step G55) */
#define DFI_SCREEN_EXTENDER DFI_ITEM_LIGHTCLAY /* Reflect, Light Screen, Aurora Veil: DFI_SCREEN_TURNS_MAX */

#endif
