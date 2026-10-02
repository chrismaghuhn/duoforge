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
| `campaigns/<id>/` | `campaign.conf` (pairings, teams, base seed, chunks, and optionally chunk_battles, parallel, bench) and the team pastes of a campaign |
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

# after the owner's approval only:
tools/cloud/aws_fuzz/launch.sh --campaign weather-sand-snow --commit <sha of main> --bucket <BUCKET> --i-have-owner-approval

# the results; every kept case is replayed on this machine (build the runner of the same commit first)
tools/cloud/aws_fuzz/collect.sh --campaign weather-sand-snow --bucket <BUCKET> --runner build/<dir>/tools/difftest/duoforge_diff_runner
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
  spec and `trace.json.gz` of every battle that is not a PASS) go to `s3://<BUCKET>/fuzz/<campaign>/chunk-<NNNN>/`.
- **Parallel chunks and overlapped uploads** (`chunks.sh`). One driver process cannot keep a big machine busy: its
  Python side (the converter, the JSON of the traces) runs under the interpreter lock, which is the likely reason that the first pilot
  (one driver, 64 workers, 500-battle chunks) ran 55 battles/s inside its chunks with only about 24 of 64 vCPUs busy.
  `parallel` in the `campaign.conf` is the number of chunks computed at the same time, each its own driver process with
  `vCPUs / parallel` workers; `auto` (the default) is `vCPUs / 20` (3 on 64 vCPUs). The upload of a finished chunk runs
  in the background while the next chunks compute. The figure to compare is the one the log gives (below); the target is
  about 140 battles/s on 64 vCPUs, **to be measured**, not yet a result.
- **Done-manifest.** `fuzz/<campaign>/manifest/done.txt` lists the finished chunks; a chunk is added only after every
  file of it is uploaded. A relaunch of the same campaign skips them.
- **Spot interruption.** IMDSv2 is polled every 5 seconds for `spot/instance-action`; on a notice every chunk in
  flight (computing, or computed and not yet in the manifest) is synced to `fuzz/<campaign>/partial/chunk-<NNNN>/`. A
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
  `fuzz/<campaign>/bench.json`: `games_per_second`, `decisions_per_second`, `steps_per_second`, `threads`, `vcpus`,
  `instance_type` (from IMDSv2), the same figures for 16 threads under `threads_16`, and every run.
- **Rate.** Every minute the log says how many battles were played and the battles per second. The local rate is about
  24 battles per second; if the first ten minutes are below 2 times that, the box aborts, uploads the log and the
  partial chunk and powers off.
- **End.** The log goes to `fuzz/<campaign>/log/`, then `shutdown -h now` (also on any error).

## `collect.sh`

Downloads `fuzz/<campaign>/` (not `partial/`), prints the totals and signatures of the finished chunks, checks that this
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
       }
     ]
   }
   ```

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

## The pilot campaigns

Every POOL step team (G7 to G13, the weather step, Encore) at ten times the battles of the step's own campaign, plus the
CLOSURE mirrors and the Team C mirror. The table gives the chunks of the campaign (`chunk_battles` of each is in its `campaign.conf`).

| Campaign id | Teams and pairings | Chunks | In this directory |
| --- | --- | --- | --- |
| `weather-sand-snow` | sand team D, snow team E: `DE,ED,DD,EE,DA,AD,EA,AE` (POOL) | 4 x 1000 = 4000 battles, ten times the step's 400; `bench=1` | yes |
| `closure-mirror` | team A and team B mirrors: `AA,BB` (CLOSURE) | 5 x 1000 | yes |
| `team-c-mirror` | Team C mirror: `CC` (TEAM_C) | 5 x 1000 | yes |
| `g7-wide-guard` | the step's teams (Wide Guard) | ten times the step's | to be added by the step's owner |
| `g8-throat-chop-heal-block` | the step's teams | ten times the step's | to be added |
| `g9-encore` | the step's teams (Encore) | ten times the step's | to be added |
| `g10-moves` | the step's teams | ten times the step's | to be added |
| `g11-soak` | the step's teams | ten times the step's | to be added |
| `g12-floette` | the step's teams | ten times the step's | to be added |
| `g13` | the step's teams | ten times the step's | to be added |

A campaign is a directory `campaigns/<id>/` with `campaign.conf` (`pairings`, `teams`, `base_seed`, `chunks`: four
required `key=value` lines, and the optional `chunk_battles` (100 to 20000, default 2000), `parallel` (`auto` or 1 to 16)
and `bench` (0 or 1); see the three that exist) and the team pastes it names (`teams=D=sand.txt E=snow.txt`: a letter, a
file of six sets with every gender stated, as `diff_driver.py random --team` takes them; or the id of a team of the
registry). It is read from the commit that is built, so a campaign is reviewed with the PR that adds it. Pick a base seed
range that no other campaign uses: the names of the battles are `fz_<seed>_<index>`.

## Tests

`duoforge.cloud.aws_fuzz_guards` (`test_guards.py`, needs bash; no AWS access, a stub `aws` is first on the PATH): the
guards refuse a wrong ARN, a wrong or unsafe security group, a missing approval flag and `--max-hours` above 2; the
request has the required shape; the user data starts with the watchdog and holds no secret; the policy of this file
says what the task asks; no account id or key is in the directory; `shellcheck` is clean when it is installed. The scheduler (`chunks.sh`) is tested with a stand-in driver: parallelism
of exactly `parallel`, the seed of each chunk, skipped chunks, the manifest written only after the upload of the chunk
it adds, a failing chunk, the partial upload of every chunk in flight; `bench_run.py` with a fake `duoforge_bench`.
