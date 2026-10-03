# Fuzz watchdog on Google Cloud

One spot VM that plays **one round of differential fuzz campaigns on the current head of `main` per boot**, uploads the
results to a private bucket and powers itself off. It runs only when the owner's session starts it (no scheduler), so
between rounds it costs a disk and nothing else. It reuses the campaigns of `tools/cloud/aws_fuzz/campaigns` and the
scheduler code `chunks.sh` (`campaign.conf` parser) of that directory; nothing else of the AWS tooling is needed.

**Status: nothing here has been created.** `create.sh` without `--i-have-owner-approval` only prints the request. The
scripts make read-only `gcloud` calls (`config get`, `auth list`, `describe`, `list`) and, with the flag, exactly one
changing call each. The infrastructure around the VM (network, subnet, service account, bucket, budget) was created
by the owner's session and is not touched by anything here.

## What exists in Google Cloud

Created before these scripts (by the owner's main session, with the owner's OK):

| Resource | Name | Notes |
| --- | --- | --- |
| project | `project-d498a888-995e-4142-82a` | the identity guard refuses any other active project |
| network | `duoforge-net` | custom mode, **no firewall rule**: nothing can come in |
| subnet | `duoforge-subnet` | `10.20.0.0/24`, `europe-west4` |
| service account | `duoforge-watch@<project>.iam.gserviceaccount.com` | only `roles/storage.objectUser` on the one bucket |
| bucket | a launch parameter (`--bucket`), never in the repository | private: uniform access, public access prevention enforced, objects deleted after 30 days |
| budget | 80 EUR per month, alerts at 50, 80 and 100 percent | |

Created by `create.sh` (the only call that creates anything), when the owner approves:

| Resource | Name | Notes |
| --- | --- | --- |
| VM | `duoforge-watch`, `europe-west4-a` (`-b`, `-c` allowed) | `t2d-standard-8` (or `t2d-standard-4`), **SPOT**, termination action **STOP**, shielded VM (secure boot, vTPM, integrity monitoring), Ubuntu 24.04 LTS, 60 GB `pd-balanced` boot disk that goes with the VM when it is deleted |
| labels | `project=duoforge`, `purpose=watch` | `start.sh`, `stop.sh` and `delete.sh` touch only an instance that carries both |
| network interface | `duoforge-net` / `duoforge-subnet`, an ephemeral external address | egress only (git, npm, apt, the bucket): there is no firewall rule, so no ingress |
| identity | the service account `duoforge-watch`, scope `cloud-platform` | what it may do is its role: objects of the one bucket |
| metadata | `block-project-ssh-keys=TRUE`, `enable-oslogin=FALSE`, `duoforge-bucket=<BUCKET>`, `startup-script` | no SSH key is on the VM, none can be added; the bucket name is not in the repository |

There is **no instance template and no managed instance group**: a spot preemption stops the VM (the disk stays), the
round ends early, and the next start plays a new, complete round (nothing of a half round is resumed: what a campaign had
uploaded stays in the bucket, and fresh seeds make a new round of the same head a different one).

## What is in this directory

| File | Purpose |
| --- | --- |
| `lib.sh` | the identity guard, the fixed names, the validation, the read-only inspection, the one place that builds the request |
| `create.sh` | the guard, the inspection, then prints the request (default) or creates the VM (`--i-have-owner-approval`) |
| `start.sh` | `gcloud compute instances start`: one boot is one round |
| `stop.sh` | `gcloud compute instances stop` of a VM whose round must end early |
| `delete.sh` | `gcloud compute instances delete` (the VM and its disk, so the build cache) |
| `startup.sh` | the startup script of the VM: the 120-minute watchdog, the head of `main`, then `round.sh` of that head |
| `round.sh` | one round: build when the head changed, every campaign once, upload, heartbeat, power off |
| `test_guards.py` | offline tests with a stub `gcloud` (CTest: `duoforge.cloud.gcp_watch_guards`) |

## The rules every script follows

- **Identity.** The first call is `gcloud config get project`, then `gcloud auth list`: the active project must be the
  one above and an account must be signed in, or the script refuses before any other call. Every later call passes
  `--project` explicitly. No key is created, read, printed or stored; the scripts use the owner's signed-in session and
  never ask for a login (`gcloud auth login` and `gcloud config set project` are the owner's).
- **Dry run by default.** `create.sh`, `start.sh`, `stop.sh` and `delete.sh` print what they would call. Only
  `--i-have-owner-approval` makes the call, and it is the only changing call of the script.
- **The setup must be what is assumed.** Before it creates anything, `create.sh` checks (read-only) that the network is
  custom-mode, the subnet has the range `10.20.0.0/24` and belongs to that network, the network has **no firewall
  rule**, the service account exists, the machine type is offered in `europe-west4`, and the bucket is private (uniform
  access, enforced public access prevention). Any difference is printed and nothing is created.
- **Allow-lists.** Machine types `t2d-standard-8` (default) and `t2d-standard-4`; zones `europe-west4-a`, `-b`, `-c`;
  one instance name.
- **Two hours at most per boot.** The first command of the startup script is `shutdown -h +120`; every campaign also
  has its own cap (20 minutes, `RD_CAMPAIGN_CAP_MINUTES`). The VM's termination action is STOP, so a power-off is a stop.
- **No secret on the box.** The bucket is reached with the token of the VM's service account, fetched from the
  metadata server into a shell variable for one upload; nothing is logged or written. The startup script holds no value
  of the owner's.

## Usage

```sh
# is everything where the scripts expect it (read-only), and what would be created
tools/cloud/gcp_watch/create.sh --bucket <BUCKET>

# after the owner's approval only:
tools/cloud/gcp_watch/create.sh --bucket <BUCKET> --i-have-owner-approval   # creates the VM; it boots and plays the first round

# a later round (the VM is TERMINATED = stopped): start it
tools/cloud/gcp_watch/start.sh                                  # prints the call
tools/cloud/gcp_watch/start.sh --i-have-owner-approval

# end a round early / remove everything
tools/cloud/gcp_watch/stop.sh --i-have-owner-approval
tools/cloud/gcp_watch/delete.sh --i-have-owner-approval
```

Add `--zone europe-west4-b` to `start.sh`, `stop.sh` or `delete.sh` when the VM was created in another zone. If a start
fails for lack of spot capacity in the zone, the VM stays stopped and costs the disk only; the owner starts it again later.
`create.sh` has no `--zone` fallback: a spot VM lives in one zone.

## What a boot does

1. `startup.sh` (GCE runs it on every boot): `shutdown -h +120`; reads the head of `main` from the public repository
   (`git ls-remote`); fetches that commit into the cache on the disk (`/opt/duoforge-watch/duoforge`); runs its
   `round.sh`, so the round logic follows `main` without recreating the VM.
2. `round.sh`: the bucket from the instance metadata; a heartbeat object; the tools (packages and Node 22, cached after
   the first boot).
3. **Build only when the head changed** since the build in the cache: the pinned Pokemon Showdown (cached while the pin is
   unchanged) and the engine in Release (`duoforge_diff_runner`, incremental in `/opt/duoforge-watch/build`). The head
   of the last build is in `/opt/duoforge-watch/state/built-head`. A boot on an unchanged head rebuilds nothing.
4. **The campaigns**: every `tools/cloud/aws_fuzz/campaigns/<id>/campaign.conf` of that head, in name order (the step
   campaigns, `closure-mirror`, `team-c-mirror`, `registry-mix`; not the `throughput-*` sweeps and nothing with a
   `sweep` key). Each plays `RD_ROUND_BATTLES` battles (600; override with the environment of `round.sh`) of its pairings and teams with the
   diff driver (`--no-lock`, all vCPUs as workers) under a **fresh seed**: the base seed of the campaign, plus 10,000,000,
   plus the minutes since the epoch, so no round replays another and none replays a seed of an AWS run.
5. **Upload** after each campaign, to `gs://<BUCKET>/watch/<commit12>/<round>/<campaign>/`: `summary.json`, `run.json`,
   `cases.tgz` (the kept cases, only when there are some) and `status.json` (the seed, the exit status, `ok`, `capped` or
   `failed`, the seconds, the buckets). Per round: `meta.json` and `round.json` (the statuses of all campaigns) one level
   up and `log.txt` (the tail of the log). `<round>` is `r<UTC time of the boot>`.
6. **Heartbeat**: `gs://<BUCKET>/watch/heartbeat.json` is rewritten every minute (`time`, `boot`, `round`, `head`,
   `state` = `starting`, `building`, `running`, `done` or `off`, `campaign`); a stale `time` with a state other than `off` means the VM was
   preempted or stopped.
7. The VM powers itself off (`shutdown -h now`; the exit trap uploads the log first). A build that fails ends the boot the
   same way (the log says why).

Reading a finding: `gs://<BUCKET>/watch/<commit12>/<round>/<campaign>/cases.tgz` holds the cases of the driver; they are
replayed and reproduced locally before they count (`tools/cloud/aws_fuzz/collect.sh` does that for the AWS runs, the
same `diff_driver.py corpus` replay applies).

## Cost

All figures are USD, from a **third-party mirror of Google's price list** (gcloud-compute.com, "last updated Sunday,
September 27, 2026"), read on 2026-10-03 for `europe-west4`; the `gcloud` CLI has no price listing and these scripts
handle no token to call the Billing Catalog API, so the figures are to be checked in the Console (Billing, Pricing, or
<https://cloud.google.com/compute/vm-instance-pricing>) before they are relied on.

| | Price | Notes |
| --- | --- | --- |
| `t2d-standard-8`, **Spot price** | **0.1889 per hour** | on demand 0.3721 per hour; a spot price can change |
| `t2d-standard-4`, Spot price | not queried | about half of the above, because the price is per vCPU and GB |
| 60 GB `pd-balanced` boot disk | 0.11 per GB and month, so **6.60 per month** | charged while the VM exists, running or **stopped** |
| a **stopped** VM | the disk only (6.60 per month) | no instance hours; an ephemeral external address is released when the VM stops |

- A boot costs at most 2 hours x 0.1889 = **0.38**, because of the watchdog; a boot that only reads an unchanged head
  and plays the rotation costs its run time x 0.1889. The time of a round (and of the first boot, which installs and
  builds) has not been measured on this machine type, so no figure is given for it: the heartbeat and `round.json` give it after the first round.
- A month with a round every day costs at most 30 x 0.38 + 6.60 = **18.00** (a worst case with every boot at the cap).
  A VM left running all month would cost 0.1889 x 730 = 137.9: this is why it stops itself.
- Egress to the bucket (same continent) and to GitHub is small (a few MB per campaign); not measured, not charged for here.
- The 80 EUR monthly budget of the project alerts at 50, 80 and 100 percent; it does not stop anything.
- Quotas seen by the owner's session on 2026-10-02: 12 vCPUs in all regions, 16 `T2D` vCPUs in the region: one
  `t2d-standard-8` fits; a second VM of that size would not at the same time as other work.

## Not done here, on purpose

- No instance template, managed group, scheduler, Cloud Run job or alert policy: the owner's session starts the VM after a
  batch of merges.
- No platform-level run limit (`--max-run-duration`): the 120-minute `shutdown` inside the VM is the watchdog; a platform
  limit could be added after a first round shows that the flag behaves as documented with a STOP action.
- Nothing is read back from the bucket by these scripts.
