#ifndef DUOFORGE_COMBAT_ITEMS_ITEMS_H
#define DUOFORGE_COMBAT_ITEMS_ITEMS_H

#include "combat/items/families.h"
#include "combat/items/held.h"
#include "combat/run_internal.h"

/* Only the newly shared item helpers are hidden. Existing DLL exports remain
 * unchanged. On Windows these definitions live in an archive outside CMake's
 * WINDOWS_EXPORT_ALL_SYMBOLS object scan (see the shared target wiring). */
#if (defined(__GNUC__) || defined(__clang__)) && !defined(_WIN32)
#define DFI_ITEM_PRIVATE __attribute__((visibility("hidden")))
#else
#define DFI_ITEM_PRIVATE
#endif

typedef void (*dfi_item_use_fn)(dfi_run *r, uint32_t flat);

DFI_ITEM_PRIVATE bool dfi_type_booster_base_power(const struct duoforge_battle *b, const dfi_member *a,
                                                 uint32_t move_type, bool ok, uint32_t *bp_chain);
DFI_ITEM_PRIVATE duoforge_status dfi_resist_berry_hit(dfi_run *r, uint32_t target, uint32_t berry_item,
                                                    bool *ok, uint32_t *chain, uint32_t *mlist, uint32_t *mods,
                                                    dfi_item_use_fn use_item);

/* The turn chooses handler order and supplies its unchanged useItem path. */
DFI_ITEM_PRIVATE bool dfi_herb_due(struct duoforge_battle *b, uint32_t flat);
DFI_ITEM_PRIVATE bool dfi_herb_holder(struct duoforge_battle *b, uint32_t flat);
DFI_ITEM_PRIVATE void dfi_white_herb(dfi_run *r, uint32_t flat, dfi_item_use_fn use_item);

#endif
