#!/bin/bash
shutdown -h +@MAX_MINUTES@ "duoforge watchdog: at most @MAX_MINUTES@ minutes"
# The user data of every AWS box (#484; HauptSession 2026-10-15: EC2 takes at most 16,384 bytes of user data, and the
# ladder's box script outgrew it), rendered by lib.sh's df_render_bootstrap with values the launcher validated. The
# watchdog above is the first command. Then it fetches the exact commit, renders that commit's box script
# (tools/cloud/aws_fuzz/@SCRIPT@) with the same values through render_box.sh, the rendering of the launcher's dry run,
# and runs it. The box script's own watchdog gets the whole minutes left, so the box never outlives the one above.
# A failure here, before the box script has its AWS CLI, uploads nothing and powers the box off at once: the console
# output is all that is left of it (as failed_in_packages).
set -euo pipefail
started=$(date +%s)
trap '[ $? -eq 0 ] || shutdown -h now' EXIT
commit='@COMMIT@'
max_minutes=@MAX_MINUTES@
boot=/opt/duoforge-boot
export DEBIAN_FRONTEND=noninteractive HOME=/root
command -v git > /dev/null || { apt-get update -qq && apt-get install -y -qq git; }
mkdir -p "$boot"
git -C "$boot" init -q
git -C "$boot" remote add origin https://github.com/chrismaghuhn/duoforge.git
git -C "$boot" fetch -q --depth 1 origin "$commit"
git -C "$boot" checkout -q --detach FETCH_HEAD
[ "$(git -C "$boot" rev-parse HEAD)" = "$commit" ] || { echo "bootstrap: the checkout is not at $commit" >&2; exit 1; }
left=$((max_minutes - ($(date +%s) - started + 59) / 60))
[ "$left" -ge 1 ] || { echo "bootstrap: no whole minute left of $max_minutes" >&2; exit 1; }
# shellcheck source=render_box.sh
. "$boot/tools/cloud/aws_fuzz/render_box.sh"
df_render_box "$boot/tools/cloud/aws_fuzz/@SCRIPT@" '@CAMPAIGN@' "$commit" '@BUCKET@' "$left" '@RUN_ID@' '@RESUME@' \
    > /opt/duoforge-box.sh
trap - EXIT
exec bash /opt/duoforge-box.sh
