# Training on Kaggle (owner OK, HauptSession 2026-10-15)

Training runs move to Kaggle so that the local machine stays free. **Only the HauptSession runs anything that reaches
Kaggle, with the owner present.** No lane and no script of a lane uploads, starts or fetches anything there. The lanes
deliver the code, this guide and the tests, which run against a stub `kaggle`.

Weights, checkpoints and data stay private (AGENTS.md). Every dataset and notebook is private, nothing of them goes
into the repository, and nothing is public on Kaggle.

| File | Purpose |
| --- | --- |
| `kaggle_run.py` | the local commands: `plan`, `privacy`, `upload`, `start`, `fetch` (its docstring has the details) |
| `kaggle_job.py` | the job of the private notebook: the repository at the exact commit, its library, the data by sha256, the environment, `python -m duoforge_learn.bc` with a deadline; `status.json`, `env.json` and the run in `/kaggle/working` |
| `pseudonymize.py` | a copy of a replay dataset without its replay ids (public battle ids) and without its player hashes (an unkeyed sha256 of the name): each replay id becomes a meaningless label, each player a 64-bit id from a secret seed that keeps only the hash's class (HauptSession 2026-10-15). The two maps and the seed stay local, apart from the copy. Only the copy goes into a content list |
| `kaggle_requirements.txt` | the Kaggle venv's packages, pinned (`kaggle==2.2.4`, `kagglesdk==0.1.37` and their dependencies) |
| `test_kaggle.py` | the tests, against a stub `kaggle` only |

## The rules the commands follow

- **Nothing reaches Kaggle without `--i-have-owner-approval`.** Without the flag a command only shows what it would do.
- **The token** (owner, 2026-10-15): the owner's Kaggle token lies in WSL at Kaggle's default place, `~/.kaggle/access_token` (chmod 600).
  - The Kaggle CLI finds it there by itself. The script never reads the file and never shows anything of it: it only reports "token present" or "token missing", by the file's existence.
  - Every output of the CLI that is shown has token-like strings (32 or more letters, digits, dashes or underscores) redacted.
  - **Only this script, started by the HauptSession with the owner, calls Kaggle.** No lane and no builder uses `kaggle` directly. The same WSL home holds the lanes' jobs, so the kaggle library lives only in its own venv (below), never in a venv for training, the short run or the tests.
  - `--owner` names the account (its user name, no secret). The datasets and notebooks are named under it, and an entry of another account in the privacy check is a refusal.
- **The Kaggle venv** (WSL), made once: `python3 -m venv ~/df-kaggle && ~/df-kaggle/bin/pip install -r tools/cloud/kaggle/kaggle_requirements.txt`.
  - It pins `kaggle==2.2.4` (with `kagglesdk==0.1.37`), on Python 3.12.3.
  - Its version was read from pip's metadata: importing `kaggle` or running its CLI authenticates, so neither is done outside a run of the HauptSession's.
  - The script runs as `PATH=~/df-kaggle/bin:$PATH ~/df-kaggle/bin/python tools/cloud/kaggle/kaggle_run.py ...`.
- **Privacy, before and after every step.** `privacy` (and every `upload`, `start` and `fetch`, before and after) reads the metadata of every dataset and notebook of the account whose name begins with `duoforge-`.
  - Each must say it is private (`isPrivate` for a dataset, `is_private` for a notebook). If not, the command refuses by name (exit 3) and does nothing more.
  - A metadata file that does not name its visibility is a refusal too ("privacy unknown"): the check fails closed.
  - Kaggle's visibility belongs to the dataset or the notebook. Their versions and a notebook's outputs have none of their own, so checking the dataset or notebook checks all its versions.
  - The field names are the Kaggle CLI's as documented. If the first real `privacy` call refuses with "privacy unknown", the field names are to be checked before anything else is done.
- **Datasets are created only with `kaggle datasets create`, never with `--public`.** Their metadata also says `isPrivate: true`. Notebooks carry `is_private: true` in their metadata.
- **The content list comes first.** `plan` lists every file of a run's dataset: its path, size, sha256 and origin (training data, networks, configurations).
  - Nothing is uploaded before the HauptSession has released this list.
  - The dataset is named after the list's sha256 (`duoforge-<12 digits>`). `upload` and `start` check each file's sha256 again, and a file changed since the list is a refusal.
- **What never goes to Kaggle:**
  - **The tournament sun team** is refused by its sha256 in `plan`, in every later command and again in the notebook. The owner's exception of 2026-10-15 is AWS and #458 only.
  - **Any file inside the repository:** the notebook takes the repository from GitHub at the exact commit.
- **The commit:** the notebook checks out exactly `--commit` and refuses another (`wrong_commit`).
- **No replay ids, no player hashes:** a replay dataset goes to Kaggle only as its `pseudonymize.py` copy.
  - **The main protection is that every Kaggle dataset is private; the pseudonyms are the second.**
  - `duoforge_learn.bc` reads the replay id for its messages only.
  - It reads a player hash only through its class: T0 (`h % 400 == 0`), T (`h % 20 == 0`, not T0) or R (`h % 20 != 0`), in `duoforge_replay.split` and the test-players split.
  - Each player's id is `HMAC-SHA256(seed, hash)` with a residue mod 400 drawn from its hash's class. Every row keeps its split and sub-bucket, and the copy gives away the class only.
  - The seed file, `replay-ids.json` and `player-ids.json` stay local, next to each other, outside the repository and never on Kaggle: whoever knows the seed can recompute the map. A rebuild with the same seed gives a byte-identical copy (tested).

## Runs longer than a session

A Kaggle GPU session ends after 12 hours. The job stops the trainer at 11 hours (`kaggle_job.DEADLINE_SECONDS`) and keeps the state of its last finished epoch. `duoforge_learn.bc` writes `bc-state.npz` after every epoch, and the run's `status.json` says `partial`.

`fetch` brings the state back. `start --resume-from <that directory>` then:
1. uploads the state as a private dataset of its own;
2. starts the notebook again with that dataset;
3. runs `bc --resume`, which continues bit for bit as an uninterrupted run would.

The resumed run must run at the same commit (refused otherwise). On the same Kaggle image and accelerator, `bc --resume` refuses other JAX, jaxlib, NumPy or optax versions or another device kind. `status.json` lists every launch.

## The manifest

`fetch` writes `manifest.json` next to the fetched output:
- the commit;
- the data's sha256 (the content list's);
- the weights' sha256 (`run/bc.npz`);
- the versions of JAX, jaxlib and CUDA;
- the GPU, Python and the library's sha256;
- the seed, the run time and the launches.

## The HauptSession's steps, in this order

1. **The token:** the owner's, at `~/.kaggle/access_token` in WSL (chmod 600). The script only checks that it is there.
2. **The Kaggle venv:** as above, in WSL; every command below runs with it.
3. **The content list:** `python tools/cloud/kaggle/kaggle_run.py plan --name <name> --data <dirs> --out <plan.json outside the repository>`. Read it and release it (or not).
4. **Privacy:** `kaggle_run.py privacy --owner <user> --i-have-owner-approval` checks the account (every command below takes `--owner <user>` too).
5. **Upload:** `kaggle_run.py upload --plan <plan.json>`, first without the flag, then with it.
6. **Start:** `kaggle_run.py start --plan <plan.json> --commit <sha of main> --job bc-short`, without the flag, then with it.
7. **Fetch:** when the notebook has finished, `kaggle_run.py fetch --plan <plan.json> --job bc-short --out <a directory outside the repository> --i-have-owner-approval`.

## The first run: a short BC test

The job `bc-short` proves the chain in minutes on a GPU: `--preset S --epochs 2 --patience 2 --batch 1024
--source-weight bo1_belief=1` on the content list's data, with seed 1 (a Bo1 source needs its weight named).

It is compared with the same run on this machine, at the same commit, on the same data:
- the loss curve (train and validation NLL per epoch);
- the validation accuracy.

They are not bit-identical: another device, XLA on a GPU. The check is that both lie in the expected range of each other. The local run's numbers are recorded below before the first Kaggle run; the Kaggle run's are added after it.

**This dataset is only for the chain test; before real training it is built anew once the content has caught up**
(HauptSession 2026-10-15: "Dieser Datensatz ist nur für den Kettentest; vor echtem Training wird nach dem Nachziehen des
Inhalts neu gebaut." Teams with content the engine does not support yet, such as Mold Breaker, Protean or Mega Stones,
drop out of it entirely.)

**The data of the first run** (HauptSession 2026-10-15): `bo1-regmc` built anew on main `779e7693` from the inputs of
the dataset of 2026-10-11 (the source parquet `6a7d913b…`, the corpus `62b37c4a…`, Showdown `b2cb775b`, seed 1, k 1),
its manifest naming commit `779e7693`, dirty false. **It is not an exact rebuild of `bo1-regmc` of 2026-10-11**: that
prior file (`4d377f69…`) is gone, and the prior was made anew from the same pastes (`e72a17ce…`). The code differs
too: the new build refuses points the old one wrote (`world:DUOFORGE_E_UNSUPPORTED` and others), 549,053 rows from
30,741 games against 862,815 from 30,625. Only its `pseudonymize.py` copy goes to Kaggle, without replay ids and player hashes
(content list `duoforge-f3ea014ecbad`, 532 files, 56,633,706 bytes).

**The local run** (2026-10-15, commit `f634143a` of this branch, and again at `8bb4dbcf` on the copy without player
hashes: the same numbers to the last digit and bit-identical parameters, only the weights file's config naming the
dataset differs; library sha256 `4ba34a4d…` built from it, CPU,
`JAX_PLATFORMS=cpu`, the copy above, seed 1; 504,220 training and 44,833 validation rows), 214 s in all:

| epoch | train NLL | validation NLL | validation top-1 (exact) | validation value MSE |
|---|---|---|---|---|
| 1 | 2.4861 | 2.4421 | 0.4936 | 0.8391 |
| 2 | 2.4021 | 2.3958 | 0.5017 | 0.8388 |

The weights (`bc.npz`, sha256 `5cdd7eace05d…`) stay private, outside the repository.

## Tests

`test_kaggle.py` runs with a stub `kaggle` first on the PATH and never against Kaggle.
- **Fail closed, as the AWS tests:**
  - `setUp` checks that `kaggle` is the stub before anything runs.
  - The environment holds no `KAGGLE_*` variable of the caller (`KAGGLE_API_TOKEN`, `KAGGLE_USERNAME`, `KAGGLE_KEY` removed).
  - `KAGGLE_CONFIG_DIR` is a directory that does not exist and `HOME` an empty one, so the owner's real token is out of reach, in WSL too.
  - `test_no_test_has_a_way_to_the_real_kaggle` checks exactly that, and that the script then says "token missing".
- A test that needs a token present gets a made-up one in a directory of its own, which only the stub sees. Every output is searched for it.
- **The commands:**
  - nothing reaches Kaggle without the flag;
  - the token file is never opened (a guarded `open`), only its presence is told, and without it nothing is called;
  - the token never appears, even when the CLI echoes it;
  - an entry of another account is refused.
- **The content list:** every file with its size, sha256 and origin; the tournament sun team and repository files are refused; a file changed after the list is refused.
- **Privacy:** a public or unknown dataset or notebook stops a command before anything is done, and privacy is checked again after each step (the stub can make a new dataset appear public).
- **Upload, start, resume and fetch:**
  - the upload is one private dataset;
  - the start is a private GPU notebook at the commit;
  - a run stopped at its deadline resumes from its state as a dataset of its own, at its own commit only;
  - the fetch writes the manifest.
- **The job's pieces:** the data check, the arguments of the full job (no path, no other flag) and the deadline.
