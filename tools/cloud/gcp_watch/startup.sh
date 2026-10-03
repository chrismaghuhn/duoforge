#!/bin/bash
shutdown -h +120 "duoforge watch: at most 120 minutes per boot"
# The startup script of the watchdog VM (tools/cloud/gcp_watch/README.md), run by GCE as root on every boot. The first
# command is the hard watchdog: whatever happens below, the VM powers off 120 minutes after the boot (the instance's
# termination action is STOP, so the disk and the build cache stay). Then it fetches the head of main from the public
# repository and hands over to tools/cloud/gcp_watch/round.sh of that head, so the round logic follows main without
# the VM being recreated. The only input from outside the repository is the instance metadata (the bucket). There is
# no secret on the box: the bucket is reached with the token of the instance's service account.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a HOME=/root
WORK=/opt/duoforge-watch
REPO_URL=https://github.com/chrismaghuhn/duoforge.git
mkdir -p "$WORK/state"
LOG=$WORK/boot.log
exec > >(tee -a "$LOG") 2>&1

echo "$(date -u +%FT%TZ) boot: bootstrap"
if ! command -v git > /dev/null 2>&1 || ! command -v curl > /dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y -qq git curl ca-certificates
fi

REPO=$WORK/duoforge
HEAD=$(git ls-remote "$REPO_URL" refs/heads/main | cut -f1)
[[ $HEAD =~ ^[0-9a-f]{40}$ ]] || {
    echo "no head of main could be read"
    shutdown -h now
    exit 1
}
if [ ! -d "$REPO/.git" ]; then
    mkdir -p "$REPO"
    git -C "$REPO" init -q
    git -C "$REPO" remote add origin "$REPO_URL"
fi
git -C "$REPO" fetch -q --depth 1 origin "$HEAD"
git -C "$REPO" checkout -q --detach --force FETCH_HEAD
[ "$(git -C "$REPO" rev-parse HEAD)" = "$HEAD" ] || {
    echo "the checkout is not at $HEAD"
    shutdown -h now
    exit 1
}
echo "$(date -u +%FT%TZ) head of main: $HEAD"
export GW_HEAD=$HEAD GW_WORK=$WORK GW_REPO=$REPO GW_BOOT_LOG=$LOG
exec bash "$REPO/tools/cloud/gcp_watch/round.sh"
