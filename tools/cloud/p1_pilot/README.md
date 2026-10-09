# P1 pilot launcher (AWS, one GPU spot box)

The launcher of the stage-3 P1 pilot: ONE GPU spot instance in `eu-central-1` that clones the public repository at an
exact commit of `main`, runs `tools/cloud/p1_pilot/run.sh` of that commit, writes its results and log to
`s3://<BUCKET>/p1/<run id>/` and terminates itself. This directory is the launcher only; `run.sh` (the workload) is
written separately, and `launch.sh` refuses a commit that does not have it.

**Status: nothing here has been launched, and the launch path is blocked.** `launch.sh` without
`--i-have-owner-approval` only prints the request. The flag is used by the lead alone, with the owner present, after
the owner has approved the cost cap below and the role statement of "Owner approval" is in place. Until then the
scripts are used with `check.sh`, which makes read-only and `--dry-run` calls only.

Modelled on `tools/cloud/aws_fuzz/` (the same identity guard, security group, instance profile, request builder and
test approach); read its README for the background.

## What is in this directory

| File | Purpose |
| --- | --- |
| `lib.sh` | the identity guard, the fixed names, the validation, the one place that builds the `run-instances` request |
| `check.sh` | the permission check: read-only and `--dry-run` calls, a list of what is missing, the role statement to add |
| `launch.sh` | prints the request (default) or, with `--i-have-owner-approval`, makes it |
| `user_data.sh` | what the box runs around `run.sh`: wall cap, clone, log sync, interruption hook, upload, power off |
| `test_guards.py` | offline tests with a stub `aws` and stand-ins for the box (CTest: `duoforge.cloud.p1_pilot_guards`) |

## The rules every script follows

- **Identity.** `AWS_PROFILE` (default `pokeengine`), region `eu-central-1`. The first AWS call is
  `aws sts get-caller-identity`; the script refuses unless the ARN ends in `:user/pokeengine`. Account ids are masked in
  every output, no access key is read, printed or stored, and no account id or bucket name is in this repository (the
  policies use `<ACCOUNT_ID>` and `<BUCKET>`; the bucket is `--bucket` or `DUOFORGE_P1_BUCKET`).
- **One box.** `--count 1`; the types are `g6.4xlarge` then `g5.4xlarge` (16 vCPUs each, so one fills the account's
  16-vCPU "All G and VT Spot Instance Requests" quota); `launch.sh` refuses while an instance tagged
  `purpose=p1-pilot` is pending, running, stopping or shutting down.
- **The image.** The public SSM parameter of the AWS Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04),
  `/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-24.04/latest/ami-id` (from the DLAMI developer
  guide, "SSM Parameter Query" of that AMI). The image it names must be called
  `Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04) <date>`; its root device (read with `describe-images`)
  gets a 150 GB gp3 volume that goes with the instance.
- **The network and the role.** Only the security group `duoforge-fuzz` (exists once, no inbound rule, tagged
  `project=duoforge`); the instance profile `duoforge-fuzz` (S3 through the role, no secret on the box); IMDSv2 only;
  no key pair.
- **Tags** `project=duoforge`, `purpose=p1-pilot`, `run-id=<run id>` on the instance, its volume and the spot request.
- **An exact commit.** `--commit` is the 40-digit sha of a commit on `main`: `launch.sh` checks it is an ancestor of
  `origin/main` and that `tools/cloud/p1_pilot/run.sh` exists in it. The box fetches exactly that commit.
- **Results only under `p1/<run id>/`.** The run id is `<first 12 digits of the commit>-<launch time UTC>`.
- **Self-termination, three independent ways.**
  1. The first command of the user data is `shutdown -h +<max-hours x 60>`: the hard wall cap.
  2. Every way out of the user data (the workload's success or failure, an error, a stop) goes through `trap finish
     EXIT`, which stops the workload, syncs `out/` and the log to S3 and runs `shutdown -h now`. Five minutes before
     the wall cap the workload is stopped so that this upload happens before the hard cap.
  3. `InstanceInitiatedShutdownBehavior=terminate`, and the spot request is one-time with interruption behaviour
     `terminate`: a powered-off box is gone, not stopped.

  A test checks all three in the generated request and user data, and runs the user data with stand-ins (success,
  failure, no `run.sh`, a spot interruption notice, the soft deadline): the watchdog comes first, the last action is
  `shutdown -h now`, the upload comes before it.

## Cost

The spot request carries `MaxPrice` (`--max-price`, default and hard maximum **$1.50 per instance hour**, minimum
$0.10), and the box cannot live longer than `--max-hours` (1 to 4, default **3**). So one run costs at most

    max-hours x MaxPrice  =  3 x $1.50 = $4.50 (default)      4 x $1.50 = $6.00 (the most the arguments allow)

in instance hours. Spot bills the market price, which is at most `MaxPrice`; when the market goes above it, AWS
interrupts the box (the interruption path below runs). On top: the 150 GB gp3 root volume for as long as the box
lives (a few cents per hour at the gp3 list price; it is deleted with the instance) and the S3 objects of the run.
`launch.sh` prints the cap of the run it would request (`cost cap $<hours x price>`).

## Usage

```sh
# who am I and what is missing: read-only and dry-run only (prints the role statement to add, see below)
AWS_PROFILE=pokeengine tools/cloud/p1_pilot/check.sh --bucket <BUCKET>

# print the request (nothing is launched): run id, results prefix, cost cap, the full run-instances line
tools/cloud/p1_pilot/launch.sh --commit <sha of main with run.sh> --bucket <BUCKET> [--max-hours 3] [--max-price 1.50]

# the lead, with the owner present, after the owner's approval only:
tools/cloud/p1_pilot/launch.sh --commit <sha> --bucket <BUCKET> --i-have-owner-approval

# the results
aws s3 ls s3://<BUCKET>/p1/<run id>/ --recursive
```

`check.sh` verifies, with read-only and `--dry-run` calls only:

1. the security group `duoforge-fuzz`: exists once, no inbound rule, tagged `project=duoforge`;
2. the bucket: `s3:ListBucket` with the prefix `p1/` (the user's read access to the results);
3. the AMI parameter above is readable, and the image it names is the DLAMI, with a root device whose snapshot fits in
   150 GB;
4. no pilot box exists, and the spot quota `L-3819A6DF` (All G and VT Spot Instance Requests) is at least 16 vCPUs (a
   note, not a failure, when `servicequotas:GetServiceQuota` is not allowed);
5. `run-instances --dry-run` for each candidate type with every option of the real request (one-time spot at $1.50,
   interruption and shutdown behaviour terminate, the instance profile, the group, IMDSv2, the 150 GB gp3 root volume,
   the three tag specifications). `DryRunOperation` is a pass; an `UnauthorizedOperation` is decoded with
   `sts decode-authorization-message` when that is allowed and printed raw when it is not;
6. **not verifiable**: the role behind the instance profile. It was written for `fuzz/` only and the user `pokeengine`
   cannot read IAM, so `check.sh` always prints the statement below as UNVERIFIED. When the SSM or S3 checks fail it
   also prints the user policy statements that are missing.

The exit status is 0 when nothing is missing (the role statement is still unverified), 1 when something is, 2 for a
refusal.

## The box (`user_data.sh`)

1. `shutdown -h +<minutes>` (the wall cap), the exit trap, the log syncer (the log to `p1/<run id>/log/<boot>.log`
   every minute), the soft deadline (five minutes before the cap) and the interruption poller (step 4).
2. `git` and the AWS CLI if the image lacks them (the DLAMI has both), `nvidia-smi -L` into the log.
3. The public repository at the exact commit (`git fetch --depth 1 origin <sha>`, checked with `rev-parse`). No
   `run.sh` at that commit: a failure (upload, power off).
4. The interruption poller, from the start: IMDSv2 `spot/instance-action` every 5 seconds. On a notice:
   `run.sh --on-interrupt` (at most 60 seconds, with the environment below) when `run.sh` is checked out and contains
   the text `--on-interrupt`, else nothing; then the final sync, then the end.
5. `run.sh` in a session of its own, from the repository's root, with this environment:

   | Variable | Value |
   | --- | --- |
   | `BUCKET` | the results bucket |
   | `RUN_PREFIX` | `p1/<run id>/` (with the trailing slash) |
   | `RUN_ID` | `<commit12>-<launch time>` |
   | `COMMIT` | the 40-digit sha |
   | `OUT_DIR` | a local directory that is synced to `s3://$BUCKET/${RUN_PREFIX}out/` at the end, whatever the end is |

   `run.sh` may upload by itself under `s3://$BUCKET/$RUN_PREFIX`; the role allows nothing else. It must expect a
   `SIGTERM` (soft deadline, interruption) and should keep `OUT_DIR` current. IMDS has a hop limit of 1: a container
   started by `run.sh` cannot reach the instance profile's credentials.
6. The end: `run.sh`'s exit status is the script's; the exit trap stops what is left, syncs `OUT_DIR` and the log,
   and runs `shutdown -h now`.

## Owner approval, and the owner's console steps

Needed before `--i-have-owner-approval` is ever used: the owner's OK of the cost cap (at most `max-hours x $1.50`,
$4.50 by default, $6.00 at most per run), of the spot quota use (one 16-vCPU GPU box), and the role statement below.
The security group `duoforge-fuzz`, the instance profile `duoforge-fuzz` and the bucket already exist (aws_fuzz).

1. **The role `duoforge-fuzz`: S3 for `p1/`.** Its permissions are for `fuzz/*` only (`tools/cloud/aws_fuzz/README.md`),
   so the box can neither write its results nor its log under `p1/`. In the IAM console, Roles, `duoforge-fuzz`, its
   permissions policy: add these two statements to the `Statement` list (`<BUCKET>` the results bucket). `check.sh`
   prints the same text.

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "P1PilotResults",
         "Effect": "Allow",
         "Action": ["s3:PutObject", "s3:GetObject"],
         "Resource": "arn:aws:s3:::<BUCKET>/p1/*"
       },
       {
         "Sid": "P1PilotList",
         "Effect": "Allow",
         "Action": "s3:ListBucket",
         "Resource": "arn:aws:s3:::<BUCKET>",
         "Condition": {"StringLike": {"s3:prefix": ["p1/", "p1/*"]}}
       }
     ]
   }
   ```

2. **The user `pokeengine`: the DLAMI parameter and reading `p1/`.** The user's policy (aws_fuzz README) allows
   `ssm:GetParameter` on the Ubuntu parameter only, and S3 reads under `fuzz/` only. `ec2:Describe*` (which covers
   `describe-images` and `describe-instances`), `RunInstances` with the tag `project=duoforge`, `CreateTags` on launch
   and `PassRole` of `duoforge-fuzz` are already there and cover this launcher. Add (the last one is optional: without
   it `check.sh` notes that the quota was not read):

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "ReadDlamiParameter",
         "Effect": "Allow",
         "Action": "ssm:GetParameter",
         "Resource": "arn:aws:ssm:eu-central-1::parameter/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-24.04/latest/ami-id",
         "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-central-1"}}
       },
       {
         "Sid": "ListP1Results",
         "Effect": "Allow",
         "Action": "s3:ListBucket",
         "Resource": "arn:aws:s3:::<BUCKET>",
         "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-central-1"}, "StringLike": {"s3:prefix": ["p1/", "p1/*"]}}
       },
       {
         "Sid": "ReadP1Results",
         "Effect": "Allow",
         "Action": "s3:GetObject",
         "Resource": "arn:aws:s3:::<BUCKET>/p1/*",
         "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-central-1"}}
       },
       {
         "Sid": "ReadSpotQuota",
         "Effect": "Allow",
         "Action": "servicequotas:GetServiceQuota",
         "Resource": "*",
         "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-central-1"}}
       }
     ]
   }
   ```

3. **`AWSServiceRoleForEC2Spot`** and **the budget**: as in the aws_fuzz README (the monthly budget alerts cover this
   launcher too).

## Tests

`duoforge.cloud.p1_pilot_guards` (`test_guards.py`, needs bash; no AWS access, a stub `aws` is first on the PATH):
the identity refusal; the type allow-list and its order; `--max-hours` 1 to 4 and `--max-price` 0.10 to 1.50, and the
printed cost cap; the commit (shape, on `origin/main`, `run.sh` in it, in a repository of the test's own); the
security group; one box at a time; the image checks; the shape of the request and its tags; the three
self-termination mechanisms, statically and by running the user data with stand-ins for `shutdown`, `aws`, `git`,
`curl` and the workload; no secret, account id or bucket name in the user data or this directory; the README's
statements against `check.sh`'s; `shellcheck` when it is installed.
