#ifndef DUOFORGE_STATE_DATA_QUERY_H
#define DUOFORGE_STATE_DATA_QUERY_H
/*
 * The data query API (duoforge_data_*): the parts that take the kind's limits
 * and the support manifest as arguments, so that a test can run them over a
 * manifest of its own. The public functions pass the context's limits and the
 * manifest of this build. The rules themselves are those of
 * state/closure_member.h, which the setup uses too.
 */
#include <stdbool.h>
#include <stdint.h>

#include <duoforge/duoforge.h>

#include "data/support_manifest.h"
#include "state/closure_member.h"

/* The support answer of duoforge_data_supported for an id of the table
 * (DUOFORGE_DATA_TABLE_*). Precondition: the id is below the kind's count. */
bool dfi_data_supported(const dfi_support_manifest *manifest, uint32_t table, uint32_t id);

/* Fills *out for the species (duoforge_forme_info). Precondition: species is
 * below the kind's forme count. */
void dfi_data_forme_info(const dfi_kind_limits *lim, const dfi_support_manifest *manifest, uint32_t species,
                         duoforge_forme_info *out);

#endif
