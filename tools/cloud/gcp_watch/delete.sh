#!/usr/bin/env bash
# Deletes the watchdog VM and its boot disk (the build cache goes with it). The network, the subnet, the service account
# and the bucket are not touched: they are the owner's. A dry run by default; the real call needs --i-have-owner-approval.
#
#   delete.sh [--zone europe-west4-a] [--i-have-owner-approval]
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
gw_instance_action delete "$@"
