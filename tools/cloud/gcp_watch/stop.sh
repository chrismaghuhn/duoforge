#!/usr/bin/env bash
# Stops the running watchdog VM before its round is over (it stops itself after a round, or after at most 120 minutes).
# The disk and the build cache stay. A dry run by default; the real call needs --i-have-owner-approval.
#
#   stop.sh [--zone europe-west4-a] [--i-have-owner-approval]
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
gw_instance_action stop "$@"
