# Run definitions

`runs/<kind>/<name>/` holds the **definition** of a named, repeatable run (restructure step 8, plan "Runs: one place,
one format"): the exact configuration a launcher reads, never its outputs.

| directory | what it holds | read by |
|---|---|---|
| `fuzz/<id>/` | `campaign.conf` (and `campaign-<n>.conf`) plus the campaign's team texts (`*.txt`) | `tools/cloud/aws_fuzz/` launchers and box scripts, `tools/cloud/gcp_watch/round.sh` |

Launch scripts stay in `tools/cloud/`. Outputs never land here or anywhere in the repository (AGENTS.md): a run
writes to `--out` or `$DUOFORGE_RUNS/<kind>/<date>-<name>/` (`duoforge.runs`, restructure step 8 eval), and S3 results keep their
own layout. `.gitignore` and `python/tests/engine/test_repo_hygiene.py` let only the definition files of `runs/fuzz/` in (a team text
must be named by its campaign); a new kind of definition is added there explicitly.

Before step 8 the fuzz campaigns were `tools/cloud/aws_fuzz/campaigns/<id>/`; a launch of a commit from then reads
them there (`df_campaign_conf_path` in `tools/cloud/aws_fuzz/lib.sh`).
