#!/usr/bin/env bash
# Starts the stopped watchdog VM: one boot is one round on the head of main (README.md). A dry run by default; the real
# `gcloud compute instances start` needs --i-have-owner-approval. There is no scheduler: the owner's session starts it.
#
#   start.sh [--zone europe-west4-a] [--i-have-owner-approval]
#   start.sh --bench SHA1,SHA2 [--families copy,codec,batch] [--zone europe-west4-a] [--i-have-owner-approval]
#
# With --bench the boot is a bench round (README.md): two commits of this repository (origin chrismaghuhn/duoforge; a head of
# a branch with a pull request is one) are built and duoforge_bench is run on both, A and B alternately, and bench.json goes
# to the bucket. The instance metadata bench_refs, bench_families and bench_run are set first, with one more call that the
# dry run prints too. Families: step,events,request,copy,codec,episode,batch (default copy,codec,batch).
set -euo pipefail
# shellcheck source=lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
gw_instance_action start "$@"
