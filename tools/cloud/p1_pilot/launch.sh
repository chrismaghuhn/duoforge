#!/usr/bin/env bash
# Launches the stage-3 P1 pilot on ONE GPU spot instance (tools/cloud/p1_pilot/README.md). The launcher only: the box
# runs tools/cloud/p1_pilot/run.sh of the given commit.
#
# usage: launch.sh --commit SHA --bucket B [--max-hours H] [--max-price P] [--types t1,t2] [--sg-name NAME]
#                  [--resume RUN_ID]
#                  [--i-have-owner-approval]
#   --commit    the exact 40-digit sha of a commit on main that has tools/cloud/p1_pilot/run.sh
#   --bucket    the results bucket (objects go under p1/<run id>/ only)
#   --max-hours the wall cap: the box powers itself off after this long (1 to 4, default 3)
#   --max-price the spot price ceiling in dollars per instance hour (0.10 to 1.50, default 1.50); a run costs at most
#               max-hours x max-price in instance hours
#   --types     candidate instance types, tried in this order until one has capacity (default g6.4xlarge,g5.4xlarge)
#   --sg-name   must be duoforge-fuzz (any other group is refused; the option only makes the refusal testable)
#   --i-have-owner-approval  actually request the instance. WITHOUT it nothing is launched: the request is printed and
#               the script exits. That is the default; the flag is for the lead, with the owner present (README).
# The profile is $AWS_PROFILE (default pokeengine), the region eu-central-1.
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
. "$HERE/lib.sh"

commit=''
bucket=${DUOFORGE_P1_BUCKET:-}
max_hours=$DF_DEFAULT_MAX_HOURS
max_price=$DF_DEFAULT_PRICE
types=$DF_DEFAULT_TYPES
sg_name=$DF_SG_NAME
approved=no
resume=
while [ $# -gt 0 ]; do
    case $1 in
        --commit) [ $# -ge 2 ] || df_die '--commit needs a value'; commit=$2; shift 2 ;;
        --bucket) [ $# -ge 2 ] || df_die '--bucket needs a value'; bucket=$2; shift 2 ;;
        --max-hours) [ $# -ge 2 ] || df_die '--max-hours needs a value'; max_hours=$2; shift 2 ;;
        --max-price) [ $# -ge 2 ] || df_die '--max-price needs a value'; max_price=$2; shift 2 ;;
        --types) [ $# -ge 2 ] || df_die '--types needs a value'; types=$2; shift 2 ;;
        --sg-name) [ $# -ge 2 ] || df_die '--sg-name needs a value'; sg_name=$2; shift 2 ;;
        --resume) [ $# -ge 2 ] || df_die '--resume needs a run id'; resume=$2; shift 2 ;;
        --i-have-owner-approval) approved=yes; shift ;;
        -h | --help) sed -n '2,18p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) df_die "unknown argument '$1' (see --help)" ;;
    esac
done

df_init
df_identity_guard # the first AWS action

# --- the values: nothing reaches AWS or the user data unchecked
df_valid_commit "$commit" || df_die "bad or missing --commit '$commit': the exact 40-digit sha of a commit on main"
df_valid_bucket "$bucket" || df_die "bad or missing --bucket '$bucket'"
df_valid_hours "$max_hours" || df_die "--max-hours '$max_hours': a whole number from 1 to $DF_MAX_HOURS_LIMIT"
df_valid_price "$max_price" ||
    df_die "--max-price '$max_price': dollars per hour (at most two decimals) from $DF_PRICE_FLOOR to $DF_PRICE_LIMIT"
max_price=$(df_price2 "$max_price")
[ "$sg_name" = "$DF_SG_NAME" ] || df_die "security group '$sg_name' refused: only $DF_SG_NAME is ever used"
IFS=',' read -r -a type_list <<< "$types"
[ ${#type_list[@]} -gt 0 ] || df_die '--types is empty'
for t in "${type_list[@]}"; do
    df_type_allowed "$t" || df_die "instance type '$t' is not one of: $DF_ALLOWED_TYPES"
done
df_check_commit_on_main "$commit"

if [ -n "$resume" ]; then
    # a resume keeps the run id: run.sh restores its markers from p1/<run id>/ and goes on after the last phase done
    df_valid_run_id "$resume" || df_die "--resume '$resume': not a run id (<12 hex>-<YYYYMMDDTHHMMSSZ>)"
    keys=$(df_aws s3api list-objects-v2 --bucket "$bucket" --prefix "$DF_S3_TOP/$resume/markers/" --max-keys 1         --query 'KeyCount' --output text 2> /dev/null) || df_die "--resume '$resume': its prefix cannot be listed"
    [[ $keys =~ ^[1-9][0-9]*$ ]] || df_die "--resume '$resume': no markers under s3://$bucket/$DF_S3_TOP/$resume/markers/"
    run_id=$resume
else
    run_id="${commit:0:12}-$(date -u +%Y%m%dT%H%M%SZ)"
    df_valid_run_id "$run_id" || df_die "internal error: the run id '$run_id' is malformed"
fi

# --- one box at a time
active=$(df_active_pilots) || df_die 'describe-instances failed: cannot tell whether a pilot box is still up'
active=$(printf '%s' "$active" | tr '\t\n' '  ' | sed -e 's/  */ /g' -e 's/^ //' -e 's/ $//')
if [ -n "$active" ] && [ "$active" != None ]; then
    df_die "a pilot box still exists ($active, purpose=$DF_PURPOSE): one at a time, refusing"
fi

# --- the security group, the AMI and the subnet
df_sg_inspect "$DF_SG_NAME"
if [ ${#DF_SG_PROBLEMS[@]} -gt 0 ]; then
    for p in "${DF_SG_PROBLEMS[@]}"; do df_log "$p"; done
    df_die 'the security group is not as required: refusing'
fi
ami=$(df_ami) || df_die "could not read the AMI parameter $DF_AMI_PARAM"
[[ $ami =~ ^ami-[0-9a-f]+$ ]] || df_die "the AMI parameter gave '$ami', not an AMI id"
df_ami_inspect "$ami"
if [ ${#DF_AMI_PROBLEMS[@]} -gt 0 ]; then
    for p in "${DF_AMI_PROBLEMS[@]}"; do df_log "$p"; done
    df_die 'the image is not as required: refusing'
fi
mapfile -t subnets < <(df_subnets "$DF_VPC_ID")
if [ ${#subnets[@]} -eq 0 ] || [ -z "${subnets[0]}" ]; then
    df_die "no subnet in the VPC of $DF_SG_NAME"
fi

max_minutes=$((max_hours * 60))
userdata=$(df_render_user_data "$commit" "$bucket" "$max_minutes" "$run_id")
cap=$(df_cost_cap "$max_hours" "$max_price")

echo "commit        $commit (runs tools/cloud/p1_pilot/run.sh of it)"
echo "run id        $run_id"
echo "results       s3://$bucket/$DF_S3_TOP/$run_id/ (log/ every minute and at the end, out/ at the end)"
echo "types         ${type_list[*]} (in this order; one instance, the first that has capacity)"
echo "max hours     $max_hours (wall cap: shutdown -h +$max_minutes, behaviour terminate; the workload is stopped 5 minutes earlier)"
echo "price ceiling \$$max_price per instance hour (one-time spot, interruption behaviour terminate)"
echo "cost cap      \$$cap in instance hours ($max_hours h x \$$max_price), plus the $DF_DISK_GB GB gp3 volume for as long as the box lives"
echo "security grp  $DF_SG_NAME ($DF_SG_ID, no inbound rule); instance profile $DF_INSTANCE_PROFILE; IMDSv2 only; no key pair"
echo "ami           $ami ($DF_AMI_NAME, root $DF_ROOT_DEVICE)"
echo "subnet        ${subnets[0]}"
echo "user data     $(printf '%s' "$userdata" | wc -c | tr -d ' ') bytes, first command: shutdown -h +$max_minutes"

df_build_run_args "$ami" "${type_list[0]}" "${subnets[0]}" "$DF_SG_ID" "$run_id" "$max_price" "$DF_ROOT_DEVICE" "$userdata"
echo
echo 'request (the user data is left out here):'
df_print_request

if [ "$approved" != yes ]; then
    echo
    echo 'nothing was launched: --i-have-owner-approval is not given (the default).'
    exit 0
fi

# --- only past the owner's approval: request ONE instance, the next candidate type when there is no capacity
for t in "${type_list[@]}"; do
    df_build_run_args "$ami" "$t" "${subnets[0]}" "$DF_SG_ID" "$run_id" "$max_price" "$DF_ROOT_DEVICE" "$userdata"
    if out=$(df_aws ec2 run-instances "${DF_RUN_ARGS[@]}" --query 'Instances[0].InstanceId' --output text 2>&1); then
        echo "launched $out ($t, run $run_id): watch s3://$bucket/$DF_S3_TOP/$run_id/log/"
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
