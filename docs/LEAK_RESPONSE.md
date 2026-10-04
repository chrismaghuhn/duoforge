# Leak response plan

Trained weights, checkpoints, league snapshots, run directories, live-play logs and anything derived from the
unlicensed replay dataset are private (AGENTS.md). This plan says what to do if one of them is published by
mistake. It has not been needed so far; the one-time audit of 2026-10-03 found no such file in any commit of
any branch and no public Actions artifact.

## Prevention (in place)

- `.gitignore` patterns and the CI guard `duoforge.python.repo_hygiene` (tracked paths, no `upload-artifact`).
- Tools refuse output directories inside the repository (`refuse_repository`).
- No GitHub Releases and no Git LFS are used; adding either needs the owner's decision.
- Backups go only to the owner's private Hugging Face repos; their visibility is changed only by the owner.

## If something leaks

1. Stop: tell the owner at once. Do not push further commits on top of the leak.
2. Contain: if a pull request carries it, close the pull request without merging and delete its branch. If it
   reached `main`, the owner decides whether to make the repository private immediately.
3. Remove from history: rewrite the affected commits (for example with `git filter-repo --path <file>
   --invert-paths`) on a fresh clone, force-push only with the owner's explicit OK, and ask GitHub support to
   purge cached views and pull-request refs. Treat the leaked content as public from the moment of the push;
   rewriting history only limits further spread.
4. Other channels: delete any Release asset, Actions artifact, Hugging Face file or Kaggle output that holds
   it, and check forks.
5. Record what leaked, for how long and what was done, in the project notes; never in a public file.
