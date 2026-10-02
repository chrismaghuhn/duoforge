#!/usr/bin/env bash
# Launches one differential fuzz campaign on one spot instance (tools/cloud/aws_fuzz/README.md).
#
# usage: launch.sh --campaign ID --commit SHA --bucket B [--max-hours H] [--types t1,t2,...] [--sg-name NAME]
#                  [--i-have-owner-approval]
#   --campaign  campaign id: the directory tools/cloud/aws_fuzz/campaigns/<id>/ at the commit
#   --commit    the exact 40-digit sha of a commit on main; the box fetches and builds this commit
#   --bucket    the results bucket (objects go under fuzz/<campaign>/)
#   --max-hours the watchdog: the box powers itself off after this long (default 2, hard maximum 2)
#   --types     candidate instance types, tried in order (default c7a.16xlarge,c6a.16xlarge,c7i.16xlarge,m7a.16xlarge)
#   --sg-name   must be duoforge-fuzz (any other group is refused; the option only makes the refusal testable)
#   --i-have-owner-approval  actually request the instance. WITHOUT it nothing is launched: the request is printed and
#               the script exits. That is the default and the only mode until the owner has approved the cost cap
#               ($10 per campaign), the monthly budget ($50) and the role (README).
# The profile is $AWS_PROFILE (default pokeengine), the region eu-central-1.
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
. "$HERE/lib.sh"

campaign=''
commit=''
bucket=${DUOFORGE_FUZZ_BUCKET:-}
max_hours=$DF_DEFAULT_MAX_HOURS
types=$DF_DEFAULT_TYPES
sg_name=$DF_SG_NAME
approved=no
while [ $# -gt 0 ]; do
    case $1 in
        --campaign) [ $# -ge 2 ] || df_die '--campaign needs a value'; campaign=$2; shift 2 ;;
        --commit) [ $# -ge 2 ] || df_die '--commit needs a value'; commit=$2; shift 2 ;;
        --bucket) [ $# -ge 2 ] || df_die '--bucket needs a value'; bucket=$2; shift 2 ;;
        --max-hours) [ $# -ge 2 ] || df_die '--max-hours needs a value'; max_hours=$2; shift 2 ;;
        --types) [ $# -ge 2 ] || df_die '--types needs a value'; types=$2; shift 2 ;;
        --sg-name) [ $# -ge 2 ] || df_die '--sg-name needs a value'; sg_name=$2; shift 2 ;;
        --i-have-owner-approval) approved=yes; shift ;;
        -h | --help) sed -n '2,17p' "${BASH_SOURCE[0]}"; exit 0 ;;
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
IFS=',' read -r -a type_list <<< "$types"
[ ${#type_list[@]} -gt 0 ] || df_die '--types is empty'
for t in "${type_list[@]}"; do
    df_type_allowed "$t" || df_die "instance type '$t' is not one of: $DF_ALLOWED_TYPES"
done
df_check_commit_on_main "$commit" "$campaign"

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
userdata=$(df_render_user_data "$campaign" "$commit" "$bucket" "$max_minutes")
price=$(df_max_price "$max_hours")

echo "campaign      $campaign"
echo "commit        $commit"
echo "bucket        s3://$bucket/fuzz/$campaign/"
echo "types         ${type_list[*]} (in this order)"
echo "max hours     $max_hours (watchdog: shutdown -h +$max_minutes, behaviour terminate)"
echo "price ceiling \$$price per instance hour ($DF_COST_CAP_USD / $max_hours: at most \$$DF_COST_CAP_USD for the campaign)"
echo "security grp  $DF_SG_NAME ($DF_SG_ID, no inbound rule)"
echo "ami           $ami"
echo "subnet        ${subnets[0]}"
echo "user data     $(printf '%s' "$userdata" | wc -c | tr -d ' ') bytes, first command: shutdown -h +$max_minutes"

df_build_run_args "$ami" "${type_list[0]}" "${subnets[0]}" "$DF_SG_ID" "$campaign" "$max_hours" "$userdata"
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

# --- only past the owner's approval: request the instance, the next candidate type when there is no capacity
for t in "${type_list[@]}"; do
    df_build_run_args "$ami" "$t" "${subnets[0]}" "$DF_SG_ID" "$campaign" "$max_hours" "$userdata"
    if out=$(df_aws ec2 run-instances "${DF_RUN_ARGS[@]}" --query 'Instances[0].InstanceId' --output text 2>&1); then
        echo "launched $out ($t, campaign $campaign): watch s3://$bucket/fuzz/$campaign/"
        exit 0
    fi
    case $out in
        *InsufficientInstanceCapacity* | *SpotMaxPriceTooLow* | *MaxSpotInstanceCountExceeded* | *Unsupported* | *capacity*)
            df_log "no capacity for $t: $(printf '%s' "$out" | df_mask | tr '\n' ' ')"
            ;;
        *) df_die "run-instances $t failed: $(printf '%s' "$out" | df_mask | tr '\n' ' ')" ;;
    esac
done
df_die 'no candidate type could be launched'
