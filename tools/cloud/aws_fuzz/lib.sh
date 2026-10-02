#!/usr/bin/env bash
# shellcheck shell=bash disable=SC2034
# Shared by launch.sh, check.sh and collect.sh (tools/cloud/aws_fuzz/README.md): the identity guard, the fixed names
# (profile, region, security group, instance profile, AMI parameter), the validation of every value that reaches an
# AWS call or the user data, and the one place that builds the run-instances request, so that the dry run of check.sh
# and the request of launch.sh cannot differ.
#
# Nothing here prints or stores an access key, and every account id in an output is masked (df_mask).

DF_PROFILE_DEFAULT=pokeengine
DF_REGION=eu-central-1
DF_USER_SUFFIX=':user/pokeengine'
DF_SG_NAME=duoforge-fuzz
DF_INSTANCE_PROFILE=duoforge-fuzz
DF_AMI_PARAM=/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id
DF_ALLOWED_TYPES='c7a.16xlarge c6a.16xlarge c7i.16xlarge m7a.16xlarge'
DF_DEFAULT_TYPES='c7a.16xlarge,c6a.16xlarge,c7i.16xlarge,m7a.16xlarge'
DF_MAX_HOURS_LIMIT=2
DF_DEFAULT_MAX_HOURS=2
DF_COST_CAP_USD=10
DF_DISK_GB=60
DF_CHUNK_BATTLES=500

DF_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

df_die() {
    printf 'aws_fuzz: %s\n' "$*" >&2
    exit 2
}

df_log() {
    printf 'aws_fuzz: %s\n' "$*" >&2
}

# Account ids are not secrets of the repo's but must not be in it, and a log pasted into a chat must not hold one:
# twelve digits between colons (an ARN or a message), and a bare twelve-digit number between slashes.
df_mask() {
    sed -E -e 's/:[0-9]{12}:/:************:/g' -e 's#/[0-9]{12}/#/************/#g'
}

df_init() {
    AWS_PROFILE=${AWS_PROFILE:-$DF_PROFILE_DEFAULT}
    AWS_REGION=$DF_REGION
    AWS_DEFAULT_REGION=$DF_REGION
    export AWS_PROFILE AWS_REGION AWS_DEFAULT_REGION
}

# Every AWS call goes through here. Git Bash would turn an argument such as /aws/service/... into a Windows path before it
# reaches the CLI, so the conversion is switched off for this one command only: exported, it would also break git and
# every other program that is given a POSIX path.
df_aws() {
    MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' aws --region "$DF_REGION" "$@"
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

df_valid_campaign() { [[ $1 =~ ^[a-z0-9][a-z0-9-]{0,39}$ ]]; }
df_valid_commit() { [[ $1 =~ ^[0-9a-f]{40}$ ]]; }
df_valid_bucket() { [[ $1 =~ ^[a-z0-9][a-z0-9.-]{2,62}$ ]]; }

df_type_allowed() {
    local t
    for t in $DF_ALLOWED_TYPES; do
        [ "$t" = "$1" ] && return 0
    done
    return 1
}

# The sha must be one of main's: with a repository at hand it is an ancestor of origin/main and the campaign is in it.
# Without one (or with no origin/main) the check cannot run, and that is refused too, unless the caller says so
# explicitly (DUOFORGE_FUZZ_NO_GIT_CHECK=1: the offline tests).
df_check_commit_on_main() { # commit campaign
    if [ "${DUOFORGE_FUZZ_NO_GIT_CHECK:-}" = 1 ]; then
        df_log "warning: DUOFORGE_FUZZ_NO_GIT_CHECK=1, the commit is not checked against origin/main"
        return 0
    fi
    git -C "$DF_DIR" rev-parse --verify --quiet "$1^{commit}" > /dev/null ||
        df_die "commit $1 is not in this repository: fetch origin first"
    git -C "$DF_DIR" rev-parse --verify --quiet origin/main > /dev/null ||
        df_die "no origin/main here to check the commit against: fetch origin first"
    git -C "$DF_DIR" merge-base --is-ancestor "$1" origin/main || df_die "commit $1 is not on origin/main"
    git -C "$DF_DIR" cat-file -e "$1:tools/cloud/aws_fuzz/campaigns/$2/campaign.conf" 2> /dev/null ||
        df_die "campaign '$2' has no tools/cloud/aws_fuzz/campaigns/$2/campaign.conf at commit $1"
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

# ---------------------------------------------------------------------------------------------- the request

# $DF_DIR/user_data.sh with its placeholders filled; every value is validated before it gets here.
df_render_user_data() { # campaign commit bucket max-minutes
    sed -e "s|@CAMPAIGN@|$1|g" -e "s|@COMMIT@|$2|g" -e "s|@BUCKET@|$3|g" -e "s|@MAX_MINUTES@|$4|g" "$DF_DIR/user_data.sh"
}

# The price ceiling per instance hour that keeps the campaign under the cost cap: cap / hours (two decimals).
df_max_price() { # hours
    awk -v cap="$DF_COST_CAP_USD" -v h="$1" 'BEGIN { printf "%.2f", cap / h }'
}

# Fills DF_RUN_ARGS with the arguments of `aws ec2 run-instances` (without --dry-run): spot, the instance profile, the
# group, the tags project=duoforge, purpose=fuzz and campaign=<id> on the instance, its volume and the spot request,
# shutdown behaviour terminate, IMDSv2 only, a gp3 root volume that goes with the instance.
df_build_run_args() { # ami type subnet sg campaign max-hours user-data
    local ami=$1 type=$2 subnet=$3 sg=$4 campaign=$5 hours=$6 userdata=$7 tags price
    price=$(df_max_price "$hours")
    tags="Tags=[{Key=project,Value=duoforge},{Key=purpose,Value=fuzz},{Key=campaign,Value=$campaign}]"
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
        --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$DF_DISK_GB,VolumeType=gp3,DeleteOnTermination=true}"
        --tag-specifications "ResourceType=instance,$tags" "ResourceType=volume,$tags" "ResourceType=spot-instances-request,$tags"
        --user-data "$userdata"
    )
}
