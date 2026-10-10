#!/usr/bin/env bash
# shellcheck shell=bash disable=SC2034
# Shared by launch.sh and check.sh (tools/cloud/p1_pilot/README.md): the identity guard, the fixed names (profile,
# region, security group, instance profile, AMI parameter, instance types), the validation of every value that reaches
# an AWS call or the user data, and the one place that builds the run-instances request, so that the dry run of
# check.sh and the request of launch.sh cannot differ. Modelled on tools/cloud/aws_fuzz/lib.sh.
#
# Nothing here prints or stores an access key, and every account id in an output is masked (df_mask).

DF_PROFILE_DEFAULT=pokeengine
DF_REGION=eu-central-1
DF_USER_SUFFIX=':user/pokeengine'
DF_SG_NAME=duoforge-fuzz
DF_INSTANCE_PROFILE=duoforge-fuzz
# The public SSM parameter of the AWS Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04), as the DLAMI
# developer guide gives it ("SSM Parameter Query" of that AMI's page).
DF_AMI_PARAM=/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-24.04/latest/ami-id
DF_AMI_NAME_PREFIX='Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04)'
# 16 vCPUs each: one of them fills the account's 16-vCPU "All G and VT Spot Instance Requests" quota, so there is
# never more than one box.
DF_ALLOWED_TYPES='g6.4xlarge g5.4xlarge'
DF_DEFAULT_TYPES='g6.4xlarge,g5.4xlarge'
DF_TYPE_VCPUS=16
DF_SPOT_QUOTA_CODE=L-3819A6DF # EC2 "All G and VT Spot Instance Requests" (vCPUs)
DF_MAX_HOURS_LIMIT=4
DF_DEFAULT_MAX_HOURS=3
DF_PRICE_LIMIT=1.50 # dollars per instance hour: the hard maximum of --max-price
DF_PRICE_FLOOR=0.10
DF_DEFAULT_PRICE=1.50
DF_DISK_GB=150
DF_PURPOSE=p1-pilot
DF_S3_TOP=p1 # every object of a run is under p1/<run id>/

DF_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

df_die() {
    printf 'p1_pilot: %s\n' "$*" >&2
    exit 2
}

df_log() {
    printf 'p1_pilot: %s\n' "$*" >&2
}

# Account ids must not be in the repository nor in a log pasted into a chat: twelve digits between colons (an ARN or a
# message), and a bare twelve-digit number between slashes.
df_mask() {
    sed -E -e 's/:[0-9]{12}:/:************:/g' -e 's#/[0-9]{12}/#/************/#g'
}

df_init() {
    AWS_PROFILE=${AWS_PROFILE:-$DF_PROFILE_DEFAULT}
    AWS_REGION=$DF_REGION
    AWS_DEFAULT_REGION=$DF_REGION
    export AWS_PROFILE AWS_REGION AWS_DEFAULT_REGION
}

# Every AWS call goes through here. Git Bash would turn an argument such as /aws/service/... into a Windows path before
# it reaches the CLI, so the conversion is switched off for this one command only (exported, it would break git).
df_aws() {
    # aws.exe on Windows ends its text output with CRLF: the carriage returns are no part of any value.
    MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' aws --region "$DF_REGION" "$@" | tr -d '\r'
    return "${PIPESTATUS[0]}"
}

# The first AWS action of every script: who is calling. Anything but the user pokeengine is refused.
df_identity_guard() {
    local arn
    if ! arn=$(df_aws sts get-caller-identity --query Arn --output text 2> /dev/null); then
        df_die "aws sts get-caller-identity failed for the profile '$AWS_PROFILE': refusing to do anything"
    fi
    case $arn in
        *"$DF_USER_SUFFIX") ;;
        *) df_die "the caller is $(printf '%s' "$arn" | df_mask), not a ':user/pokeengine': refusing" ;;
    esac
    DF_CALLER=$(printf '%s' "$arn" | df_mask)
    df_log "caller $DF_CALLER, profile $AWS_PROFILE, region $DF_REGION"
}

# ---------------------------------------------------------------------------------------------- validation

df_valid_commit() { [[ $1 =~ ^[0-9a-f]{40}$ ]]; }
df_valid_bucket() { [[ $1 =~ ^[a-z0-9][a-z0-9.-]{2,62}$ ]]; }

# The run id: <the first 12 digits of the commit>-<the launch time (UTC)>. A run's objects are under p1/<run id>/.
DF_RUN_ID_RE='^[0-9a-f]{12}-[0-9]{8}T[0-9]{6}Z$'
df_valid_run_id() { [[ $1 =~ $DF_RUN_ID_RE ]]; }

df_type_allowed() {
    local t
    for t in $DF_ALLOWED_TYPES; do
        [ "$t" = "$1" ] && return 0
    done
    return 1
}

# --max-hours: a whole number from 1 to DF_MAX_HOURS_LIMIT.
df_valid_hours() {
    [[ $1 =~ ^[0-9]+$ ]] && [ "$1" -ge 1 ] && [ "$1" -le "$DF_MAX_HOURS_LIMIT" ]
}

# --max-price: dollars per hour with at most two decimals, from DF_PRICE_FLOOR to DF_PRICE_LIMIT.
df_valid_price() {
    [[ $1 =~ ^[0-9]{1,2}(\.[0-9]{1,2})?$ ]] || return 1
    awk -v p="$1" -v lo="$DF_PRICE_FLOOR" -v hi="$DF_PRICE_LIMIT" 'BEGIN { exit !(p + 0 >= lo + 0 && p + 0 <= hi + 0) }'
}

df_price2() { awk -v p="$1" 'BEGIN { printf "%.2f", p }'; }

# The most a run can cost in instance hours: hours x the price ceiling (two decimals).
df_cost_cap() { # hours price
    awk -v h="$1" -v p="$2" 'BEGIN { printf "%.2f", h * p }'
}

# The sha must be one of main's: an ancestor of origin/main, and tools/cloud/p1_pilot/run.sh (the workload, written
# elsewhere) must exist in it. Without a repository or an origin/main the check cannot run, and that is refused too,
# unless the caller says so explicitly (DUOFORGE_P1_NO_GIT_CHECK=1: the offline tests).
df_check_commit_on_main() { # commit
    if [ "${DUOFORGE_P1_NO_GIT_CHECK:-}" = 1 ]; then
        df_log "warning: DUOFORGE_P1_NO_GIT_CHECK=1, the commit and its run.sh are not checked against origin/main"
        return 0
    fi
    git -C "$DF_DIR" rev-parse --verify --quiet "$1^{commit}" > /dev/null ||
        df_die "commit $1 is not in this repository: fetch origin first"
    git -C "$DF_DIR" rev-parse --verify --quiet origin/main > /dev/null ||
        df_die "no origin/main here to check the commit against: fetch origin first"
    git -C "$DF_DIR" merge-base --is-ancestor "$1" origin/main || df_die "commit $1 is not on origin/main"
    git -C "$DF_DIR" cat-file -e "$1:tools/cloud/p1_pilot/run.sh" 2> /dev/null ||
        df_die "commit $1 has no tools/cloud/p1_pilot/run.sh: the box would have no workload to run"
}

# ---------------------------------------------------------------------------------------------- AWS lookups

# The security group by name: it must exist once, have no inbound rule and carry the tag project=duoforge. Sets
# DF_SG_ID and DF_VPC_ID and fills DF_SG_PROBLEMS (an array; empty when it is all right). Never exits.
df_sg_inspect() { # name
    DF_SG_ID=''
    DF_VPC_ID=''
    DF_SG_PROBLEMS=()
    local name=$1 count inbound tag
    count=$(df_aws ec2 describe-security-groups --filters "Name=group-name,Values=$name" \
        --query 'length(SecurityGroups)' --output text 2> /dev/null) || count=''
    if [ "$count" != 1 ]; then
        DF_SG_PROBLEMS+=("the security group '$name' was not found exactly once (found: ${count:-the call failed})")
        return 0
    fi
    DF_SG_ID=$(df_aws ec2 describe-security-groups --filters "Name=group-name,Values=$name" \
        --query 'SecurityGroups[0].GroupId' --output text)
    DF_VPC_ID=$(df_aws ec2 describe-security-groups --filters "Name=group-name,Values=$name" \
        --query 'SecurityGroups[0].VpcId' --output text)
    inbound=$(df_aws ec2 describe-security-groups --filters "Name=group-name,Values=$name" \
        --query 'length(SecurityGroups[0].IpPermissions)' --output text)
    tag=$(df_aws ec2 describe-security-groups --filters "Name=group-name,Values=$name" \
        --query "SecurityGroups[0].Tags[?Key=='project'].Value | [0]" --output text)
    [ "$inbound" = 0 ] || DF_SG_PROBLEMS+=("the security group '$name' has $inbound inbound rule(s), it must have none")
    [ "$tag" = duoforge ] || DF_SG_PROBLEMS+=("the security group '$name' is not tagged project=duoforge (tag: $tag)")
    return 0
}

# The subnets of the group's VPC, one per line: the default subnets of the zones, else every subnet of the VPC.
df_subnets() { # vpc-id
    local found
    found=$(df_aws ec2 describe-subnets --filters "Name=vpc-id,Values=$1" "Name=default-for-az,Values=true" \
        --query 'Subnets[].SubnetId' --output text)
    if [ -z "$found" ] || [ "$found" = None ]; then
        found=$(df_aws ec2 describe-subnets --filters "Name=vpc-id,Values=$1" --query 'Subnets[].SubnetId' --output text)
    fi
    printf '%s\n' "$found" | tr '\t' '\n'
}

df_ami() {
    df_aws ssm get-parameter --name "$DF_AMI_PARAM" --query Parameter.Value --output text
}

# The image behind the parameter: its name must be the DLAMI's, and its root device (whose size the request sets) must
# be found with a snapshot no larger than DF_DISK_GB. Sets DF_AMI_NAME, DF_ROOT_DEVICE and DF_ROOT_SNAPSHOT_GB and fills
# DF_AMI_PROBLEMS (empty when it is all right). Never exits.
df_ami_inspect() { # ami
    DF_AMI_NAME=''
    DF_ROOT_DEVICE=''
    DF_ROOT_SNAPSHOT_GB=''
    DF_AMI_PROBLEMS=()
    local dev size
    if ! DF_AMI_NAME=$(df_aws ec2 describe-images --image-ids "$1" --query 'Images[0].Name' --output text 2>&1); then
        DF_AMI_PROBLEMS+=("describe-images $1 failed: $(printf '%s' "$DF_AMI_NAME" | df_mask | tr '\n' ' ')")
        DF_AMI_NAME=''
        return 0
    fi
    case $DF_AMI_NAME in
        "$DF_AMI_NAME_PREFIX"*) ;;
        *) DF_AMI_PROBLEMS+=("the image $1 is '$DF_AMI_NAME', not a '$DF_AMI_NAME_PREFIX'") ;;
    esac
    DF_ROOT_DEVICE=$(df_aws ec2 describe-images --image-ids "$1" --query 'Images[0].RootDeviceName' --output text 2> /dev/null) ||
        DF_ROOT_DEVICE=''
    if ! [[ $DF_ROOT_DEVICE =~ ^/dev/[a-z0-9]+$ ]]; then
        DF_AMI_PROBLEMS+=("the image $1 has no readable root device name (got '$DF_ROOT_DEVICE')")
        DF_ROOT_DEVICE=''
        return 0
    fi
    while IFS=$'\t' read -r dev size; do
        [ "$dev" = "$DF_ROOT_DEVICE" ] && DF_ROOT_SNAPSHOT_GB=$size
    done < <(df_aws ec2 describe-images --image-ids "$1" \
        --query 'Images[0].BlockDeviceMappings[].[DeviceName, Ebs.VolumeSize]' --output text 2> /dev/null)
    if ! [[ $DF_ROOT_SNAPSHOT_GB =~ ^[0-9]+$ ]]; then
        DF_AMI_PROBLEMS+=("the image $1 has no EBS size for its root device $DF_ROOT_DEVICE")
    elif [ "$DF_ROOT_SNAPSHOT_GB" -gt "$DF_DISK_GB" ]; then
        DF_AMI_PROBLEMS+=("the root snapshot of $1 is $DF_ROOT_SNAPSHOT_GB GB, more than the $DF_DISK_GB GB volume")
    fi
    return 0
}

# The instances of an earlier pilot that still exist (pending, running, stopping): one box at a time. Prints their ids.
df_active_pilots() {
    df_aws ec2 describe-instances \
        --filters "Name=tag:project,Values=duoforge" "Name=tag:purpose,Values=$DF_PURPOSE" \
        "Name=instance-state-name,Values=pending,running,stopping,shutting-down" \
        --query 'Reservations[].Instances[].InstanceId' --output text
}

# ---------------------------------------------------------------------------------------------- the request

# $DF_DIR/user_data.sh with its placeholders filled; every value is validated before it gets here.
df_render_user_data() { # commit bucket max-minutes run-id [pilot-run-id [pilot-part [distill-preset]]]
    sed -e "s|@COMMIT@|$1|g" -e "s|@BUCKET@|$2|g" -e "s|@MAX_MINUTES@|$3|g" -e "s|@RUN_ID@|$4|g" \
        -e "s|@PILOT_RUN_ID@|${5:-}|g" -e "s|@PILOT_PART@|${6:-}|g" -e "s|@DISTILL_PRESET@|${7:-}|g" \
        "$DF_DIR/user_data.sh"
}

# Fills DF_RUN_ARGS with the arguments of `aws ec2 run-instances` (without --dry-run): one instance, a one-time spot
# request with the price ceiling and interruption behaviour terminate, the instance profile, the group, the tags
# project=duoforge, purpose=p1-pilot and run-id=<id> on the instance, its volume and the spot request, shutdown
# behaviour terminate, IMDSv2 only, a gp3 root volume of DF_DISK_GB that goes with the instance, no key pair.
df_build_run_args() { # ami type subnet sg run-id price root-device user-data
    local ami=$1 type=$2 subnet=$3 sg=$4 run_id=$5 price=$6 root=$7 userdata=$8 tags
    tags="Tags=[{Key=project,Value=duoforge},{Key=purpose,Value=$DF_PURPOSE},{Key=run-id,Value=$run_id}]"
    DF_RUN_ARGS=(
        --image-id "$ami"
        --instance-type "$type"
        --count 1
        --subnet-id "$subnet"
        --security-group-ids "$sg"
        --iam-instance-profile "Name=$DF_INSTANCE_PROFILE"
        --instance-market-options "MarketType=spot,SpotOptions={SpotInstanceType=one-time,MaxPrice=$price,InstanceInterruptionBehavior=terminate}"
        --instance-initiated-shutdown-behavior terminate
        --metadata-options "HttpTokens=required,HttpEndpoint=enabled,HttpPutResponseHopLimit=1"
        --block-device-mappings "DeviceName=$root,Ebs={VolumeSize=$DF_DISK_GB,VolumeType=gp3,DeleteOnTermination=true}"
        --tag-specifications "ResourceType=instance,$tags" "ResourceType=volume,$tags" "ResourceType=spot-instances-request,$tags"
        --user-data "$userdata"
    )
}

# The request as a shell line, the user data left out.
df_print_request() {
    local a skip_next=no
    printf '  aws --region %s ec2 run-instances' "$DF_REGION"
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
}

# The statement that the role behind the instance profile needs for p1/ (the role was written for fuzz/). check.sh
# cannot see IAM, so it prints this for the owner; README.md has the same text, and a test keeps the two equal.
df_role_statement() {
    cat << 'EOF'
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
EOF
}
