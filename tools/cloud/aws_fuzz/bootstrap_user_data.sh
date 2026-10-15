#!/bin/bash
shutdown -h +@MAX_MINUTES@ "duoforge watchdog: at most @MAX_MINUTES@ minutes"
# The user data of every AWS box (#484; HauptSession 2026-10-15: EC2 takes at most 16,384 bytes of user data, and the
# ladder's box script outgrew it), rendered by lib.sh's df_render_bootstrap with values the launcher validated. The
# watchdog above is the first command. Then it fetches the exact commit, renders that commit's box script
# (tools/cloud/aws_fuzz/@SCRIPT@) with the same values and runs it. The rendering is render_box.sh's, written out here
# (a test keeps the two alike) so that it needs nothing of the commit but the box script: a commit before the bootstrap
# (a resumed series) works as well. The box script's own watchdog gets the whole minutes left, so the box never
# outlives the one above. A failure here, before the box script has its AWS CLI, uploads nothing and powers the box off
# at once: the console output is all that is left of it (as failed_in_packages).
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
# render_box.sh's df_render_box, with this box's values; its patterns are spelt with $p, which the launcher's rendering
# of this file leaves alone
set -- "$boot/tools/cloud/aws_fuzz/@SCRIPT@" '@CAMPAIGN@' "$commit" '@BUCKET@' "$left" '@RUN_ID@' '@RESUME@'
p=@
sed -e "s|${p}CAMPAIGN${p}|$2|g" -e "s|${p}COMMIT${p}|$3|g" -e "s|${p}BUCKET${p}|$4|g" -e "s|${p}MAX_MINUTES${p}|$5|g" \
    -e "s|${p}RUN_ID${p}|$6|g" -e "s|${p}RESUME${p}|${7:-no}|g" "$1" > /opt/duoforge-box.sh
trap - EXIT
exec bash /opt/duoforge-box.sh
