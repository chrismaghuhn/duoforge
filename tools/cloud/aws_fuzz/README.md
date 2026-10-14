# AWS fuzz campaigns

Differential fuzz campaigns (`tools/reference/diff_driver.py random`) on AWS spot capacity: one box per campaign,
sized for about ten times the battles of a step campaign on a development machine, results in S3, every finding
reproduced locally before it counts.

**Status: nothing here has been launched, and the launch path is blocked.** `launch.sh` without
`--i-have-owner-approval` only prints the request. The flag stays unused until the owner has approved the three
things at the end of "Owner approval": the cost cap ($10 per campaign), the monthly budget ($50) and the role. Until
then the scripts are used with `check.sh`, which makes read-only and `--dry-run` calls only.

## What is in this directory

| File | Purpose |
| --- | --- |
| `lib.sh` | the identity guard, the fixed names, the validation, the one place that builds the `run-instances` request |
| `check.sh` | the permission check: read-only and `--dry-run` calls, then a list of what is missing |
| `launch.sh` | prints the request (default) or, with `--i-have-owner-approval`, makes it |
| `user_data.sh` | what the box runs: build as the hosted `linux-full` job does, optional bench, play the chunks, upload, power off |
| `chunks.sh` | the chunk scheduler the box sources: parallel chunks, background uploads, done-manifest, partial uploads |
| `bench_run.py` | the raw engine benchmark of `bench=1`: `duoforge_bench` on all vCPUs, `bench.json` |
| `collect.sh` | downloads a campaign and replays every kept case locally (`diff_driver.py corpus`) |
| `campaigns/<id>/` | `campaign.conf` (pairings, teams, base seed, chunks, and optionally chunk_battles, parallel or sweep, bench) and the team pastes of a campaign |
| `test_guards.py` | offline tests with a stub `aws` (CTest: `duoforge.cloud.aws_fuzz_guards`) |

## The rules every script follows

- **Identity.** `AWS_PROFILE` (default `pokeengine`), region `eu-central-1`. The first AWS call is
  `aws sts get-caller-identity`; the script refuses unless the ARN ends in `:user/pokeengine`. Account ids are masked
  in every output, no access key is read, printed or stored, and no account id is in this repository (the policies
  below use `<ACCOUNT_ID>` and `<BUCKET>`).
- **One security group.** Only `duoforge-fuzz` is ever used. It must exist exactly once, have no inbound rule and be
  tagged `project=duoforge`; `launch.sh --sg-name` takes no other name.
- **Two hours at most.** `--max-hours` is 1 or 2 (default 2). The first command of the user data is
  `shutdown -h +<minutes>`, and the instance-initiated shutdown behaviour is `terminate`, so the box is gone after
  that long whatever happens on it.
- **A price ceiling.** The spot request carries `MaxPrice = 10 / hours` dollars per instance hour, so one campaign cannot
  cost more than the $10 cap (plus a 60 GB gp3 volume that goes with the instance, a few cents).
- **An exact commit.** `--commit` is the 40-digit sha of a commit on `main`: `launch.sh` checks it is an ancestor of
  `origin/main` and that the campaign exists in it. The box fetches and builds exactly that commit.
- **No secret on the box.** S3 is reached with the instance profile `duoforge-fuzz`; IMDSv2 only; no key pair; no
  inbound rule; no user data holds a credential (a test looks).
- **Only the allow-listed types.** `c7a.16xlarge c6a.16xlarge c7i.16xlarge m7a.16xlarge`, tried in this order (`--types`
  takes a subset).

## Usage

```sh
# who am I and what is missing: read-only and dry-run only
AWS_PROFILE=pokeengine tools/cloud/aws_fuzz/check.sh --bucket <BUCKET>

# print the request of a campaign (nothing is launched)
tools/cloud/aws_fuzz/launch.sh --campaign weather-sand-snow --commit <sha of main> --bucket <BUCKET>

# after the owner's approval only (it prints the run id; the results are under fuzz/<campaign>/<run id>/):
tools/cloud/aws_fuzz/launch.sh --campaign weather-sand-snow --commit <sha of main> --bucket <BUCKET> --i-have-owner-approval

# continue an interrupted run, explicitly (the same commit, chunk_battles and base_seed, or the box refuses):
tools/cloud/aws_fuzz/launch.sh --campaign weather-sand-snow --commit <sha of main> --bucket <BUCKET> --resume <run id> --i-have-owner-approval

# the results; every kept case is replayed on this machine (build the runner of the same commit first)
tools/cloud/aws_fuzz/collect.sh --campaign weather-sand-snow --run <run id> --bucket <BUCKET> --runner build/<dir>/tools/difftest/duoforge_diff_runner
```

`check.sh` checks: the security group (exists, 0 inbound rules, tag), the bucket (`s3:ListBucket` with the prefix
`fuzz/`), the AMI parameter `/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id`, and a
`run-instances --dry-run` for each candidate type with the spot market options, the instance profile `duoforge-fuzz`,
the group, the tags `project=duoforge`, `purpose=fuzz` and `campaign=<id>` on the instance, the volume and the spot
request, and shutdown behaviour `terminate`. `DryRunOperation` is a pass. On `UnauthorizedOperation` it decodes the
message with `sts decode-authorization-message` when that is allowed and prints it raw when it is not. The exit status
is 0 when nothing is missing.

## The box (`user_data.sh`)

As the hosted `linux-full` job: Ubuntu 24.04, `build-essential cmake git python3`, Node 22 (the tarball of the latest
22.x, checked against `SHASUMS256.txt`), the public repository at the exact commit, the pinned Showdown
(`b2cb775b0616115b775534eaeff50300e1fc81fc`: `npm ci --ignore-scripts --omit=dev`, `node build`), the engine in Release
with warnings as errors and IPO, then the target `duoforge_diff_runner`.

- **Chunks** are seed ranges: chunk *c* of a campaign is `diff_driver.py random --no-lock --battles <chunk_battles>
  --seed <base_seed + c>` with the campaign's pairings and teams. `chunk_battles` is set per campaign (default 2000,
  100 to 20000). When a chunk is done its `summary.json`, `run.json`, `battles.jsonl`, `timing.json` and `cases/` (the
  spec and `trace.json.gz` of every battle that is not a PASS) go to `s3://<BUCKET>/fuzz/<campaign>/<run id>/chunk-<NNNN>/`.
- **Parallel chunks and overlapped uploads** (`chunks.sh`). One driver process cannot keep a big machine busy: its
  Python side (the converter, the JSON of the traces) runs under the interpreter lock. Measured on a c7a.16xlarge
  (64 vCPUs): one driver with 64 workers made 55 battles/s with about 24 vCPUs busy (pilot 2); three drivers with 21
  workers each made 55.6 to 58.8 battles/s each at 13 to 14% of the vCPUs, about 8.6 vCPUs per driver, and about 167
  battles/s together (pilot 3, 0.278 CPU-s per battle). A driver stays near 58 battles/s whatever its worker count.
  `parallel` in the `campaign.conf` is the number of chunks computed at the same time, each its own driver process with
  `vCPUs / parallel` workers; `auto` (the default) is `vCPUs / 7`, at least 1 (9 on 64 vCPUs). The first sweep (pilot 4,
  64 vCPUs, 24 chunks of 1000 per phase) gave, over the whole phase, 213 battles/s with 5 drivers (56% of the machine
  busy), 239 with 7 (64%) and 274 with 9 (70%): still rising at 9, hence 7 vCPUs per driver. The upload of a finished
  chunk runs in the background while the next chunks compute.
- **Parallel sweep** (`sweep=5,7,9` in the `campaign.conf`, instead of `parallel`): one launch measures several values of
  `parallel`, one **phase** each, played one after the other. Each phase has `chunks` chunks (so the campaign has
  `chunks` x the number of values; the seeds go on across the phases, no battle is played twice) and needs at least
  `parallel` + 3 of them, better 3 x `parallel` (`campaigns/throughput-sweep` has 24 chunks of 1000 for 5, 7 and 9;
  `campaigns/throughput-sweep-9-13` has 40 for 9, 11 and 13). Per phase the log gives two rates and the machine's busy
  share. The **overall** rate is all the chunks over the whole phase: the ramp-up and the tail (the last wave of chunks
  is usually not full and runs with fewer neighbours) are in it. The **steady** rate is what the machine does with all
  `parallel` drivers busy: `parallel x chunk_battles` over the **median duration of the chunks that started before
  the last `parallel` ones** (those had all their neighbours). Equally long chunks start and finish in waves, which
  makes any rate over completion times (a straight line through a staircase) depend on where the window cuts the waves;
  the median of the durations does not, and ignores a slow first wave and a stray slow chunk. The steady rate is never
  reported below the overall rate (with a ramp and a tail it cannot be lower): when the figure from the chunk times
  comes out lower, the overall rate is given and the entry says `steady_clamped`. Needs at least 3 chunks before the last
  wave, else "no steady state". Replayed on the real log of pilot 4 (`testdata/run4_*`) it gives 227, 269 and 300
  battles/s for 5, 7 and 9 drivers (22, 26 and 30 s per chunk), above the overall rates and consistent with the
  per-minute rates of the log (up to 264/s in the phase of 7); the first estimator (a window between completions) had
  given 203, 189 and 195, below the overall rates for 7 and 9. The same figures go to
  `fuzz/<campaign>/<run id>/sweep.jsonl` (one line per phase: `steady_battles_per_second`, `overall_battles_per_second`,
  `median_chunk_seconds`, `steady_chunks`, `steady_clamped`, `machine_busy_percent`), and the per-minute log names the
  phase. The sweep is part of the manifest (`parallel` is recorded as `sweep=5,7,9`), so a resume must use the same
  sweep.
- **Runs and the manifest.** Every launch is a **run** with a prefix of its own,
  `fuzz/<campaign>/<run id>/`, where the run id is `<first 12 digits of the commit>-<chunk_battles>-<base_seed>-<launch
  time>` (launch.sh prints it). Everything the box writes is under that prefix, so a run of another commit or geometry,
  or an earlier launch, can never be read by this one (the second pilot's box found the first pilot's manifest of 8
  chunks of 500 under the old shared prefix, took every chunk of its 4 x 1000 campaign for done, and played nothing).
  `manifest/run.json` says which run it is (`run_id`, `campaign`, `commit`, `chunk_battles`, `base_seed`, `chunks` and
  `parallel` as the campaign.conf has it: `auto` or a number) and `manifest/done.txt` lists the finished chunks, a chunk
  being added only after every file of it is uploaded. A new run needs a prefix without a manifest. A run is continued
  only with an explicit `launch.sh --resume <run id>`, and the box then requires the manifest of exactly this
  commit, `chunk_battles`, `base_seed`, `chunks` and `parallel`, else it stops. A done-list with more finished chunks
  than the campaign has, a duplicate, a malformed line or a chunk out of range is a hard error, never a skip.
- **Spot interruption.** IMDSv2 is polled every 5 seconds for `spot/instance-action`; on a notice every chunk in
  flight (computing, or computed and not yet in the manifest) is synced to `fuzz/<campaign>/<run id>/partial/chunk-<NNNN>/`. A
  relaunch resumes from it (the driver skips battles that have a result) when the same Node made it, else it starts
  that chunk again.
- **Utilisation in the log.** Per chunk: `N battles in W s (B battles/s), C CPU-s, U% of the V vCPUs while it ran`
  (C is the user and system time of the whole driver and its children, from `/usr/bin/time`; U = C / (W x V) is the
  share of the machine that this chunk used, and the chunks that overlap add up). Every minute: the battles played, the
  rate, and how busy the whole machine was (from `/proc/stat`).
- **Bench (`bench=1`).** Before the campaign, `bench_run.py` runs the native batch benchmark of the repository
  (`duoforge_bench --families batch`: the loop over the games in C on a pool of worker threads, no Python, no
  Showdown; the closure pairings, 5000 battles per pairing, 32 repetitions per invocation) on every vCPU for about 30
  seconds, and on 16 threads for about a third of that (the owner's PC plays 16 threads, so the two compare). It uploads
  `fuzz/<campaign>/<run id>/bench.json`: `games_per_second`, `decisions_per_second`, `steps_per_second`, `threads`, `vcpus`,
  `instance_type` (from IMDSv2), the same figures for 16 threads under `threads_16`, and every run. The parser reads
  what `duoforge_bench` really writes: the `--out` JSON, its `results` entry with `"family": "BATCH_NATIVE"` and the
  `per_second` figures (a real capture is in `testdata/`, and a test reads it). A benchmark that fails, for any reason,
  is recorded as an `error` in `bench.json` (or in `threads_16`) and the campaign goes on.
- **Rate.** Every minute the log says how many battles were played and the battles per second. The local rate is about
  24 battles per second; if the first ten minutes are below 2 times that, the box aborts, uploads the log and the
  partial chunk and powers off.
- **End.** The log goes to `fuzz/<campaign>/<run id>/log/`, then `shutdown -h now` (also on any error).

## `collect.sh`

Downloads `fuzz/<campaign>/<run id>/` (`--run`; without it the runs of the campaign are listed; not `partial/`), prints the totals and signatures of the finished chunks, checks that this
checkout is the commit the campaign ran (`--allow-other-commit` to override), builds a corpus directory from the kept
cases and runs `diff_driver.py corpus` on it. A case is **REPRODUCED** when the local replay is a non-PASS in the same
bucket; only those count as findings. A `domain` finding (the engine's candidate set against Showdown's) cannot be
replayed without Showdown: rerun the random mode with the same seed and the battle index.

## Owner approval, and the owner's console steps

Needed before `--i-have-owner-approval` is ever used: the cost cap ($10 per campaign), the monthly budget ($50), and the
role below. The security group `duoforge-fuzz` and the bucket already exist.

1. **The role `duoforge-fuzz` with an instance profile of the same name.** Trust policy for `ec2.amazonaws.com`:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]
   }
   ```

   Permissions: `s3:PutObject`, `s3:GetObject` and `s3:ListBucket` on `fuzz/*` of the bucket only (nothing else; the box
   has no other permission):

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "WriteResults",
         "Effect": "Allow",
         "Action": ["s3:PutObject", "s3:GetObject"],
         "Resource": "arn:aws:s3:::<BUCKET>/fuzz/*"
       },
       {
         "Sid": "ListResults",
         "Effect": "Allow",
         "Action": "s3:ListBucket",
         "Resource": "arn:aws:s3:::<BUCKET>",
         "Condition": {"StringLike": {"s3:prefix": ["fuzz/", "fuzz/*"]}}
       },
       {
         "Sid": "ReadNets",
         "Effect": "Allow",
         "Action": "s3:GetObject",
         "Resource": "arn:aws:s3:::<BUCKET>/nets/*"
       }
     ]
   }
   ```

   `ReadNets` (#484, the ladder campaigns): the networks under `nets/`, read-only. The role gets no `PutObject` or
   `DeleteObject` there, and a ladder box that could write to `nets/` refuses by name (`nets_writable`).

2. **`AWSServiceRoleForEC2Spot`**, if the account does not have it yet: IAM, Roles, Create role, AWS service, EC2,
   "EC2 - Spot Instances". (The user `pokeengine` has no IAM write permission, on purpose.)
3. **The budget**: AWS Budgets, a monthly cost budget of $50 with alerts at 50, 80 and 100 percent (actual spend) to the
   owner's address.

### The policy of the user `pokeengine` (least privilege)

Every statement is held to the region by `aws:RequestedRegion`. There is no IAM write permission, no `ec2:Create*`
beyond `RunInstances` and the tags it makes, no S3 write permission for the user (the box writes, the user reads).
`sts:GetCallerIdentity` needs no permission; `sts:DecodeAuthorizationMessage` is optional (`check.sh` falls back to the
raw message).

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadEc2",
      "Effect": "Allow",
      "Action": "ec2:Describe*",
      "Resource": "*",
      "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-central-1"}}
    },
    {
      "Sid": "ReadAmiParameter",
      "Effect": "Allow",
      "Action": "ssm:GetParameter",
      "Resource": "arn:aws:ssm:eu-central-1::parameter/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id",
      "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-central-1"}}
    },
    {
      "Sid": "RunInstancesTagged",
      "Effect": "Allow",
      "Action": "ec2:RunInstances",
      "Resource": [
        "arn:aws:ec2:eu-central-1:<ACCOUNT_ID>:instance/*",
        "arn:aws:ec2:eu-central-1:<ACCOUNT_ID>:volume/*",
        "arn:aws:ec2:eu-central-1:<ACCOUNT_ID>:spot-instances-request/*"
      ],
      "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-central-1", "aws:RequestTag/project": "duoforge"}}
    },
    {
      "Sid": "RunInstancesSupporting",
      "Effect": "Allow",
      "Action": "ec2:RunInstances",
      "Resource": [
        "arn:aws:ec2:eu-central-1::image/*",
        "arn:aws:ec2:eu-central-1:<ACCOUNT_ID>:subnet/*",
        "arn:aws:ec2:eu-central-1:<ACCOUNT_ID>:security-group/*",
        "arn:aws:ec2:eu-central-1:<ACCOUNT_ID>:network-interface/*"
      ],
      "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-central-1"}}
    },
    {
      "Sid": "CreateTagsOnLaunch",
      "Effect": "Allow",
      "Action": "ec2:CreateTags",
      "Resource": "arn:aws:ec2:eu-central-1:<ACCOUNT_ID>:*/*",
      "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-central-1", "ec2:CreateAction": "RunInstances"}}
    },
    {
      "Sid": "Terminate",
      "Effect": "Allow",
      "Action": "ec2:TerminateInstances",
      "Resource": "arn:aws:ec2:eu-central-1:<ACCOUNT_ID>:instance/*",
      "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-central-1", "aws:ResourceTag/project": "duoforge"}}
    },
    {
      "Sid": "PassRole",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::<ACCOUNT_ID>:role/duoforge-fuzz",
      "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-central-1", "iam:PassedToService": "ec2.amazonaws.com"}}
    },
    {
      "Sid": "ListResultsBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::<BUCKET>",
      "Condition": {
        "StringEquals": {"aws:RequestedRegion": "eu-central-1"},
        "StringLike": {"s3:prefix": ["fuzz/", "fuzz/*"]}
      }
    },
    {
      "Sid": "ReadResults",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::<BUCKET>/fuzz/*",
      "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-central-1"}}
    }
  ]
}
```

`test_guards.py` parses the JSON documents of this file (the user's policy by its `ReadEc2` statement, the role's by
`WriteResults`) and checks: the region condition on every statement, the tag condition on the three
launch resources and not on the four supporting ones, `CreateTags` only with `ec2:CreateAction=RunInstances`,
`TerminateInstances` only on tagged instances, `PassRole` only for the role `duoforge-fuzz` to `ec2.amazonaws.com`,
and no IAM action but `iam:PassRole`.

## The campaigns

AWS is used for real evidence campaigns only, each with its own owner OK (the throughput sweeps measured the machine and
are done). The evidence campaigns: every merged POOL mechanics step at ten times the battles of the step's own local
campaign (steps that recorded none: 2000), `parallel=auto` (vCPUs / 7, 9 on 64), `bench=0`, and a mix over the registry.
Each `campaign.conf` names in its comment the source of its teams: the step's own campaign team where it is in the
repository or in the builder's files (copied next to the conf), else registry teams (`data/teams`, ids `PP_...` of the
VGCPastes survey) that use the mechanic, else the teams of the step's recorded specs. A local run of a few battles of
each (all PASS under POOL, 2026-10-03) shows that the teams play.

| Campaign id | Teams (source) and pairings | Battles |
| --- | --- | --- |
| `g7-wide-guard` | `tests/reference/teams/team_wide_guard.txt` (D); `DA,AD,DD,DB,BD` | 4 x 1000 (the step ran 400) |
| `g8-throat-chop-heal-block` | registry: Psychic Noise team and a Throat Chop team; against each other, themselves, A, B | 3 x 150 (the step ran 45) |
| `g9-encore` | the Encore builder's `team_encore.txt` (D) and a registry Encore team | 4 x 550 (the step ran 120 and 100) |
| `g10-moves` | registry: First Impression, Scald/Recover and Low Kick teams | 2 x 1000 (no step campaign) |
| `g11-soak` | registry: the two Soak teams | 2 x 1000 (no step campaign) |
| `g12-floette` | registry `PP_8025F0AEF5F2D1B6` (the step's own team) against A, B, itself | 30 x 1000 (the step ran 3000) |
| `g13-moves` | the G13 builder's `team_g13_d.txt` (D) and `team_g13_e.txt` (E); `DE,ED,DD,EE` and against A, B | 3 x 800 (the step ran 240) |
| `g14-abilities` | teams of the step's recorded specs (`g14_poison_touch`, `g14_rough_skin`, `g14_thermal_exchange`: D, E, F) | 13 x 1000 (the step ran 300 and 1000) |
| `g17-hyper-beam` | the G17 builder's `team_hb.txt` (D) and the two teams of `g17_recharge_moves` (E, F) | 4 x 1000 (the step ran 100, 100 and 200) |
| `registry-mix` | the 44 VGCPastes teams of the registry as 88 pairings (every team in both seats) | 10 x 1000 (no step campaign) |
| `weather-sand-snow` | sand team D, snow team E: `DE,ED,DD,EE,DA,AD,EA,AE` (POOL) | 4 x 1000, ten times the step's 400; `bench=1` |
| `closure-mirror` | team A and team B mirrors: `AA,BB` (CLOSURE) | 5 x 1000 |
| `team-c-mirror` | Team C mirror: `CC` (TEAM_C) | 5 x 1000 |
| `throughput-sweep`, `throughput-sweep-9-13` | the closure mirrors at 5/7/9 and 9/11/13 drivers (`sweep=`) | measurements of the machine, done |

Not yet: the steps G15 and G16 (not merged when this was written) and AC1.

A campaign is a directory `campaigns/<id>/` with `campaign.conf` (`pairings`, `teams`, `base_seed`, `chunks`: four
required `key=value` lines, and the optional `chunk_battles` (100 to 20000, default 2000), `parallel` (`auto` or 1 to 16)
or `sweep` (1 to 6 values, not with `parallel`) and `bench` (0 or 1); see the existing ones) and the team pastes it names (`teams=D=sand.txt E=snow.txt`: a letter, a
file of six sets with every gender stated, as `diff_driver.py random --team` takes them; or the id of a team of the
registry). It is read from the commit that is built, so a campaign is reviewed with the PR that adds it. Pick a base seed
range that no other campaign uses: the names of the battles are `fz_<seed>_<index>`.

## Ladder campaigns (#484)

A ladder campaign runs up to three arms of `python -m duoforge_search.ladder` side by side on one spot instance at an
exact commit of main (HauptSession: each arm on 16 CPUs of its own with 8 workers, 16 CPUs left to the box; whether
four arms may run is decided after the first run, by its memory and throughput).
Strength runs may move to AWS (owner, 2026-10-14). **Latency gates stay local (`--exclusive`) or on the VPS: AWS times
are never used for a latency gate.** AWS ladder results count only after the equality proof (below), and only as their
own series. A paired comparison always runs on one machine class: AWS and local runs are never mixed or paired.

**Only the HauptSession runs any of this, from its chat, with the owner present** (owner rule). No lane and no script
of a lane starts, stops or changes anything on AWS, uploads included. The lanes deliver the code, this guide and the
tests (against a stub `aws`).

| File | Purpose |
| --- | --- |
| `campaigns/<id>/campaign.conf` | `kind=ladder`, one to three `arm=NAME step=S [previous=P] [h2h=0\|1]` lines, and for every arm `pairs`, `seed`, `workers` (8), `max_steps` and every network by its sha256 (`ladder_conf.py`'s docstring has the keys) |
| `ladder_conf.py` | checks a ladder conf, lists its networks' sha256 and its arms, and builds each arm's command line (the launcher and the box use the same file) |
| `launch_ladder.sh` | the guards of `launch.sh`; one instance type, `c7a.16xlarge`, for a whole series, no fallback; prints the request unless `--i-have-owner-approval` |
| `ladder_user_data.sh` | the box: the watchdog first; the library at the commit, hashed; Python as pinned; `nets/` checked read-only; the networks by sha256; the pins; the arms side by side, each on CPUs of its own; the aggregates up |
| `ladder_requirements.txt` | the Python packages, pinned to the local machine's versions (CPU only) |
| `ladder_equal.py` | the equality proof: two `ladder.json` compared field by field, timing fields aside |

**What the box pins** (HauptSession condition), for each arm: XLA's instruction set (`XLA_FLAGS=--xla_cpu_max_isa=AVX2`,
the local Ryzen 7 5800X's), OpenBLAS's kernel (`OPENBLAS_CORETYPE=Haswell`, `OPENBLAS_NUM_THREADS=1`), 16 CPUs of its own
(`taskset`: arm *i* on CPUs 16*i* to 16*i*+15, as the local machine has 16), 8 workers, `JAX_PLATFORMS=cpu`, Python 3.12.3 and the packages of `ladder_requirements.txt` (`pip install
--no-deps`, then `pip check`). `env.json` records them with the library's sha256, the instance type, the CPU, whether it
has AVX-512 and `pip freeze`. Whether the pins suffice is what the equality proof shows: if it is not bit-identical,
AWS results count only as their own series, every arm of a comparison runs on the same instance type, and the report
states openly which parts of `ladder.json` are bit-identical (`ladder_equal.py` names every field that differs).

**What leaves the box:** each arm's `ladder.json` (aggregates, per-game scores, decision digests) and its log tail under
`<arm>/`, `env.json` (with the arms' CPUs), `status.json` (done, or the named refusal) and the box's log, under
`fuzz/ladder/<campaign>/<commit12>-ladder-<launch time>/`. No decision file
and no network ever leaves it.

**The box refuses by name** (in `status.json`): `nets_writable` (a probe write to `nets/` succeeded: the role is wrong),
`nets_probe_unclear` (the probe failed with something other than AccessDenied), `nets_unreadable`, `net_sha_mismatch`,
`bad_conf`, `wrong_commit`, `build`, `python_env`, `cpus` (fewer than 16 per arm plus 16) and `ladder_failed` (naming
the arms that failed; the others' results are still uploaded).

### The HauptSession's steps, in this order

1. **IAM check.** The role `duoforge-fuzz` has the statement `ReadNets` above (`s3:GetObject` on `nets/*` only) and
   nothing else on `nets/`. The bucket has Public Access Block on and server-side encryption (in the console, or
   `aws s3api get-public-access-block --bucket <BUCKET>` and `aws s3api get-bucket-encryption --bucket <BUCKET>` with
   the owner's profile). The owner makes the IAM change.
2. **Upload the networks with their sha256.** For each sha256 the campaign names (`python3
   tools/cloud/aws_fuzz/ladder_conf.py shas tools/cloud/aws_fuzz/campaigns/<id>/campaign.conf`):
   - check the local file: `sha256sum <file>` must print that sha256;
   - upload it as `nets/<sha256>.npz` with the owner's credentials (the user `pokeengine` has no S3 write permission):
     `aws s3 cp <file> s3://<BUCKET>/nets/<sha256>.npz --sse AES256`.

   Only the networks the conf names go up; no run directory, no decision file.
3. **Launch.** `tools/cloud/aws_fuzz/launch_ladder.sh --campaign <id> --commit <sha of main> --bucket <BUCKET>` prints
   the request and the networks; read it. Then the same command with `--i-have-owner-approval`. Without spot capacity
   for `c7a.16xlarge` it stops: wait and launch again, or restart the whole series on another type (never mixed).
4. **Download the results**, after `status.json` says `done` (the box has then powered itself off):
   `aws s3 cp s3://<BUCKET>/fuzz/ladder/<id>/<run id>/ <a directory outside the repository> --recursive`.
   `status.json` names any refusal; `env.json` names the pins, the versions and the library's sha256.
5. **Compare** (the equality proof, once per instance type before its results count). It has two campaigns:
   `ladder-equal-2e` runs the arm `main` (step 2e, 8 pairs against `bot`, `bc6` and `ppo`) alone, and
   `ladder-equal-2e-beside` runs the same arm beside two others (steps 0 and 1b). A digest must not depend on what runs
   beside it (HauptSession). Run the same arm on this machine too, at the same commit, under the machine lock:
   `python3 tools/cloud/aws_fuzz/ladder_conf.py argv <conf> main <the local networks' directory, files named
   <sha256>.npz> <out>` gives the arguments of `python -m duoforge_search.ladder`. Then compare each pair:
   `python3 tools/cloud/aws_fuzz/ladder_equal.py <local>/ladder.json <aws alone>/main/ladder.json --out equal-alone.json`
   and the same for `<aws alone>/main/ladder.json` against `<aws beside>/main/ladder.json`. Each gives exit 0 and
   `"equal": true` when every field but the timing ones is bit-identical. Otherwise `differs` names the fields: AWS
   results then count only as their own series, and if alone and beside differ, the arms run one per box.

The first use after the proof is the D1 ladder arm (#481), then D2's arms. Their names are in `ladder.STEPS` (agreed
with the D2 lane), so a campaign names them in its `arm=` lines without a change here. The mirror touchstone stays local:
the private sun team does not go into the bucket (HauptSession).

## Tests

`duoforge.cloud.aws_fuzz_guards` (`test_guards.py`, needs bash; no AWS access, a stub `aws` is first on the PATH): the
guards refuse a wrong ARN, a wrong or unsafe security group, a missing approval flag and `--max-hours` above 2; the
request has the required shape; the user data starts with the watchdog and holds no secret; the policy of this file
says what the task asks; no account id or key is in the directory; `shellcheck` is clean when it is installed. The scheduler (`chunks.sh`) is tested with a stand-in driver: parallelism
of exactly `parallel`, the seed of each chunk, skipped chunks, the manifest written only after the upload of the chunk
it adds, a failing chunk, the partial upload of every chunk in flight; `bench_run.py` with a fake `duoforge_bench`.
