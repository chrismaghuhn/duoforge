#!/usr/bin/env bash
# Launches the arms of one AWS ladder campaign (#484), side by side on one spot instance (tools/cloud/aws_fuzz/README.md,
# "Ladder campaigns"). Only the HauptSession runs this, from its chat, with the owner present (owner rule): no lane and
# no script of a lane starts, stops or changes anything on AWS.
#
# usage: launch_ladder.sh --campaign ID --commit SHA --bucket B [--max-hours H] [--sg-name NAME] [--i-have-owner-approval]
#   --campaign  a ladder campaign: runs/fuzz/<id>/campaign.conf at the commit, kind=ladder
#   --commit    the exact 40-digit sha of a commit on main; the box fetches and builds this commit
#   --bucket    the private bucket: the networks are read from nets/<sha256>.npz (read-only for the box), the results go
#               to fuzz/ladder/<campaign>/<commit12>-ladder-<launch time>/
#   --max-hours the watchdog: the box powers itself off after this long (default 2, hard maximum 2)
#   --sg-name   must be duoforge-fuzz (any other group is refused; the option only makes the refusal testable)
#   --i-have-owner-approval  actually request the instance. WITHOUT it nothing is launched: the request is printed.
# One instance type for every run of a series: c7a.16xlarge, never another and never a fallback (HauptSession). Without
# spot capacity the launch fails: wait, or restart the whole series on another type (a code change, reviewed).
# The profile is $AWS_PROFILE (default pokeengine), the region eu-central-1.
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
. "$HERE/lib.sh"

campaign=''
commit=''
bucket=${DUOFORGE_FUZZ_BUCKET:-}
max_hours=$DF_DEFAULT_MAX_HOURS
sg_name=$DF_SG_NAME
approved=no
while [ $# -gt 0 ]; do
    case $1 in
        --campaign) [ $# -ge 2 ] || df_die '--campaign needs a value'; campaign=$2; shift 2 ;;
        --commit) [ $# -ge 2 ] || df_die '--commit needs a value'; commit=$2; shift 2 ;;
        --bucket) [ $# -ge 2 ] || df_die '--bucket needs a value'; bucket=$2; shift 2 ;;
        --max-hours) [ $# -ge 2 ] || df_die '--max-hours needs a value'; max_hours=$2; shift 2 ;;
        --sg-name) [ $# -ge 2 ] || df_die '--sg-name needs a value'; sg_name=$2; shift 2 ;;
        --i-have-owner-approval) approved=yes; shift ;;
        -h | --help) sed -n '2,16p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) df_die "unknown argument '$1' (see --help)" ;;
    esac
done

df_init
df_identity_guard # the first AWS action

# --- the values: nothing reaches AWS or the user data unchecked
df_valid_campaign "$campaign" || df_die "bad or missing --campaign '$campaign' (lowercase letters, digits and dashes, at most 40)"
df_valid_commit "$commit" || df_die "bad or missing --commit '$commit': the exact 40-digit sha of a commit on main"
df_valid_bucket "$bucket" || df_die "bad or missing --bucket '$bucket'"
[[ $max_hours =~ ^[0-9]+$ ]] || df_die "--max-hours '$max_hours' is not a whole number of hours"
if [ "$max_hours" -lt 1 ] || [ "$max_hours" -gt "$DF_MAX_HOURS_LIMIT" ]; then
    df_die "--max-hours $max_hours: between 1 and $DF_MAX_HOURS_LIMIT (the hard maximum; the cost cap is \$$DF_COST_CAP_USD)"
fi
[ "$sg_name" = "$DF_SG_NAME" ] || df_die "security group '$sg_name' refused: only $DF_SG_NAME is ever used"
df_check_commit_on_main "$commit" "$campaign"

# --- the campaign at that commit: a valid ladder conf (the same check the box makes, ladder_conf.py)
conf=$(mktemp)
trap 'rm -f "$conf"' EXIT
if [ "${DUOFORGE_FUZZ_NO_GIT_CHECK:-}" = 1 ]; then  # the offline tests: the working copy's campaign
    df_campaign_conf "$commit" "$campaign" > "$conf" || df_die "campaign '$campaign' has no campaign.conf"
else
    df_campaign_conf "$commit" "$campaign" > "$conf" || df_die "cannot read campaign.conf of '$campaign' at $commit"
fi
python3 "$DF_DIR/ladder_conf.py" check "$conf" || df_die "campaign '$campaign' is not a valid ladder campaign"
# tr: a Windows Python ends its lines with CRLF
mapfile -t shas < <(python3 "$DF_DIR/ladder_conf.py" shas "$conf" | tr -d '\r')
mapfile -t arms < <(python3 "$DF_DIR/ladder_conf.py" arms "$conf" | tr -d '\r')
workers=$(python3 "$DF_DIR/ladder_conf.py" workers "$conf" | tr -d '\r')
probe=$(python3 "$DF_DIR/ladder_conf.py" probe "$conf" | tr -d '\r')
[[ $workers =~ ^[0-9]+$ ]] || df_die "campaign '$campaign': no worker count"

run_id="${commit:0:12}-ladder-$(date -u +%Y%m%dT%H%M%SZ)"
df_valid_ladder_run_id "$run_id" || df_die "internal error: the run id '$run_id' is malformed"

# --- the security group, the AMI and the subnet
df_sg_inspect "$DF_SG_NAME"
if [ ${#DF_SG_PROBLEMS[@]} -gt 0 ]; then
    for p in "${DF_SG_PROBLEMS[@]}"; do df_log "$p"; done
    df_die 'the security group is not as required: refusing'
fi
ami=$(df_ami) || df_die "could not read the AMI parameter $DF_AMI_PARAM"
[[ $ami =~ ^ami-[0-9a-f]+$ ]] || df_die "the AMI parameter gave '$ami', not an AMI id"
mapfile -t subnets < <(df_subnets "$DF_VPC_ID")
if [ ${#subnets[@]} -eq 0 ] || [ -z "${subnets[0]}" ]; then
    df_die "no subnet in the VPC of $DF_SG_NAME"
fi

max_minutes=$((max_hours * 60))
userdata=$(df_render_bootstrap ladder_user_data.sh "$campaign" "$commit" "$bucket" "$max_minutes" "$run_id" no)
df_check_user_data_size "$userdata"
box=$(df_render_ladder_user_data "$campaign" "$commit" "$bucket" "$max_minutes" "$run_id")
price=$(df_max_price "$max_hours")

echo "ladder campaign $campaign"
echo "commit        $commit"
echo "run id        $run_id"
echo "networks      s3://$bucket/nets/<sha256>.npz, read-only for the box:"
for s in "${shas[@]}"; do echo "                $s"; done
echo "arms          ${arms[*]} (side by side, 16 CPUs and $workers workers each, 16 CPUs left to the box)"
if [ -n "$probe" ]; then
    read -r probe_inputs probe_sha <<< "$probe"
    echo "mode          PROBE: the network probe of ${arms[0]} under five pin variants (probe/<variant>/), then the"
    echo "              arms under the first variant giving $probe_sha, or no game (probe_no_match)"
    echo "probe inputs  s3://$bucket/probes/$probe_inputs.npz, read-only for the box"
fi
echo "results       s3://$bucket/fuzz/ladder/$campaign/$run_id/ (<arm>/ladder.json, env.json, status.json, log/)"
echo "type          $DF_LADDER_TYPE (the only type of a series, no fallback)"
echo "max hours     $max_hours (watchdog: shutdown -h +$max_minutes, behaviour terminate)"
echo "price ceiling \$$price per instance hour ($DF_COST_CAP_USD / $max_hours: at most \$$DF_COST_CAP_USD for the run)"
echo "security grp  $DF_SG_NAME ($DF_SG_ID, no inbound rule)"
echo "ami           $ami"
echo "subnet        ${subnets[0]}"
echo "user data     $(printf '%s' "$userdata" | wc -c | tr -d ' ') bytes (the bootstrap; at most $DF_USER_DATA_LIMIT), first command: shutdown -h +$max_minutes"
echo "box script    ladder_user_data.sh at the commit, $(printf '%s' "$box" | wc -c | tr -d ' ') bytes rendered, run by the bootstrap"

df_build_run_args "$ami" "$DF_LADDER_TYPE" "${subnets[0]}" "$DF_SG_ID" "$campaign" "$max_hours" "$userdata" ladder
echo
echo 'request (the user data is left out here):'
printf '  aws --region %s ec2 run-instances' "$DF_REGION"
skip_next=no
for a in "${DF_RUN_ARGS[@]}"; do
    if [ "$skip_next" = yes ]; then
        printf ' <user data>'
        skip_next=no
    else
        printf ' %q' "$a"
        [ "$a" = --user-data ] && skip_next=yes
    fi
done
echo

if [ "$approved" != yes ]; then
    echo
    echo 'nothing was launched: --i-have-owner-approval is not given (the default).'
    exit 0
fi

# --- only past the owner's approval: one request, one type
if out=$(df_aws ec2 run-instances "${DF_RUN_ARGS[@]}" --query 'Instances[0].InstanceId' --output text 2>&1); then
    echo "launched $out ($DF_LADDER_TYPE, ladder campaign $campaign, run $run_id): watch s3://$bucket/fuzz/ladder/$campaign/$run_id/"
    exit 0
fi
case $out in
    *InsufficientInstanceCapacity* | *SpotMaxPriceTooLow* | *MaxSpotInstanceCountExceeded* | *capacity*)
        df_die "no spot capacity for $DF_LADDER_TYPE: wait and launch again, or restart the whole series on another type (never mix): $(printf '%s' "$out" | df_mask | tr '\n' ' ')"
        ;;
    *) df_die "run-instances $DF_LADDER_TYPE failed: $(printf '%s' "$out" | df_mask | tr '\n' ' ')" ;;
esac
