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
| `pseudonymize.py` | a copy of a replay dataset without its replay ids (public battle ids): each becomes a meaningless label, and the map label -> replay id stays local in a file of its own, apart from the copy (HauptSession 2026-10-15). Only the copy goes into a content list |
| `test_kaggle.py` | the tests, against a stub `kaggle` only |

## The rules the commands follow

- **Nothing reaches Kaggle without `--i-have-owner-approval`.** Without the flag a command only shows what it would do.
- **The key** is read only from `--env`, a file outside the repository. The default is
  `C:\Users\chris\.duoforge-kaggle.env`, with the lines `KAGGLE_USERNAME=...` and `KAGGLE_KEY=...`.
  - It reaches the Kaggle CLI only through its environment, never on a command line.
  - The CLI's own configuration directory is an empty temporary one, so no other credentials are used.
  - Every output of the CLI that is shown is masked. Neither the key nor the user name appears in a log or an error, even when the CLI itself prints them.
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
- **No replay ids:** a replay dataset goes to Kaggle only as its `pseudonymize.py` copy. `duoforge_learn.bc` reads the
  replay id for its messages only, so it trains on the copy as on the original.

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

1. **The env file:** create it with the owner's Kaggle key, outside the repository.
2. **Install the CLI:** `pip install kaggle` (the HauptSession's environment, not a lane's).
3. **The content list:** `python tools/cloud/kaggle/kaggle_run.py plan --name <name> --data <dirs> --out <plan.json outside the repository>`. Read it and release it (or not).
4. **Privacy:** `kaggle_run.py privacy --i-have-owner-approval` checks the account.
5. **Upload:** `kaggle_run.py upload --plan <plan.json>`, first without the flag, then with it.
6. **Start:** `kaggle_run.py start --plan <plan.json> --commit <sha of main> --job bc-short`, without the flag, then with it.
7. **Fetch:** when the notebook has finished, `kaggle_run.py fetch --plan <plan.json> --job bc-short --out <a directory outside the repository> --i-have-owner-approval`.

## The first run: a short BC test

The job `bc-short` proves the chain in minutes on a GPU: `--preset S --epochs 2 --patience 2 --batch 1024` on the content list's data, with seed 1.

It is compared with the same run on this machine, at the same commit, on the same data:
- the loss curve (train and validation NLL per epoch);
- the validation accuracy.

They are not bit-identical: another device, XLA on a GPU. The check is that both lie in the expected range of each other. The local run's numbers are recorded below before the first Kaggle run; the Kaggle run's are added after it.

## Tests

`test_kaggle.py` runs with a stub `kaggle` first on the PATH and never against Kaggle.
- `setUp` checks that `kaggle` is the stub. The environment holds no `KAGGLE_*` variable of the caller and no `~/.kaggle`; `test_no_test_has_a_way_to_the_real_kaggle` checks exactly that.
- The key of the tests is made up, and every output is searched for it.
- **The commands:**
  - nothing reaches Kaggle without the flag;
  - the key never appears, even when the CLI echoes it;
  - the env file is read only from outside the repository.
- **The content list:** every file with its size, sha256 and origin; the tournament sun team and repository files are refused; a file changed after the list is refused.
- **Privacy:** a public or unknown dataset or notebook stops a command before anything is done, and privacy is checked again after each step (the stub can make a new dataset appear public).
- **Upload, start, resume and fetch:**
  - the upload is one private dataset;
  - the start is a private GPU notebook at the commit;
  - a run stopped at its deadline resumes from its state as a dataset of its own, at its own commit only;
  - the fetch writes the manifest.
- **The job's pieces:** the data check, the arguments of the full job (no path, no other flag) and the deadline.
