#!/usr/bin/env bash
# Creates the watchdog VM (tools/cloud/gcp_watch/README.md). A dry run by default: the guard and the read-only
# inspection run, the request is printed, nothing is created. The real `gcloud compute instances create` needs
# --i-have-owner-approval, and it is the only call of these scripts that creates anything.
#
#   create.sh --bucket <BUCKET> [--zone europe-west4-a|b|c] [--machine-type t2d-standard-8|t2d-standard-4]
#             [--i-have-owner-approval]
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

bucket=''
zone=$GW_DEFAULT_ZONE
machine=$GW_DEFAULT_MACHINE
approved=no
while [ $# -gt 0 ]; do
    case $1 in
        --bucket | --zone | --machine-type)
            [ $# -ge 2 ] || gw_die "$1 needs a value"
            case $1 in
                --bucket) bucket=$2 ;;
                --zone) zone=$2 ;;
                --machine-type) machine=$2 ;;
            esac
            shift 2
            ;;
        --i-have-owner-approval)
            approved=yes
            shift
            ;;
        *) gw_die "unknown argument '$1'" ;;
    esac
done
[ -n "$bucket" ] || gw_die "--bucket is required (the name is a launch parameter and is not in the repository)"
gw_valid_bucket "$bucket" || gw_die "'$bucket' is not a bucket name"
gw_valid_zone "$zone" || gw_die "the zone '$zone' is not one of: $GW_ALLOWED_ZONES"
gw_valid_machine "$machine" || gw_die "the machine type '$machine' is not one of: $GW_ALLOWED_MACHINES"
[ -f "$GW_DIR/startup.sh" ] || gw_die "startup.sh is missing"

gw_identity_guard
gw_inspect "$machine" "$bucket"
if [ "${#GW_PROBLEMS[@]}" -gt 0 ]; then
    for p in "${GW_PROBLEMS[@]}"; do gw_log "PROBLEM: $p"; done
    gw_die "what the owner's session created is not what this script assumes: nothing is created"
fi
[ -z "$(gw_instance_status "$zone")" ] || gw_die "the instance '$GW_INSTANCE' already exists in $zone (start.sh starts it, delete.sh removes it)"

gw_build_create_args "$zone" "$machine" "$bucket"
if [ "$approved" != yes ]; then
    gw_log "dry run: without --i-have-owner-approval nothing is created. The request would be:"
    printf '%s --project %s --quiet' "$GW_GCLOUD" "$GW_PROJECT"
    printf ' %q' "${GW_CREATE_ARGS[@]}"
    printf '\n'
    exit 0
fi
gw_log "approved: creating $GW_INSTANCE ($machine, spot, $zone)"
gw_gcloud "${GW_CREATE_ARGS[@]}"
gw_log "created. It boots, plays one round on the head of main, uploads it and powers itself off (STOP)."
