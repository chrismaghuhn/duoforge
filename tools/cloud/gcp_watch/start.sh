#!/usr/bin/env bash
# Starts the stopped watchdog VM: one boot is one round on the head of main (README.md). A dry run by default; the real
# `gcloud compute instances start` needs --i-have-owner-approval. There is no scheduler: the owner's session starts it.
#
#   start.sh [--zone europe-west4-a] [--i-have-owner-approval]
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
gw_instance_action start "$@"
