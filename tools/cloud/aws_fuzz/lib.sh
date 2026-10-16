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
# A ladder campaign (#484): one instance type for a whole series, never mixed (HauptSession); no fallback to another.
DF_LADDER_TYPE=c7a.16xlarge
# A preview-oracle campaign (#458) runs on DF_LADDER_TYPE too, never another and no fallback. Its watchdog and cost cap
# are its own (HauptSession, 2026-10-15): caps, not expectations; the fuzz and ladder caps above stay as they are.
DF_ORACLE_MAX_HOURS_LIMIT=12
DF_ORACLE_DEFAULT_MAX_HOURS=12
# Its price ceiling is a limit of its own, apart from the hours (owner decision 2026-10-15, the default): at most $2.00
# per instance hour, so at most $24 for 12 hours. The HauptSession may set both at the launch, with the owner.
DF_ORACLE_DEFAULT_PRICE_USD=2.00
DF_ORACLE_PRICE_SANITY_USD=10.00 # a guard against a mistyped price only, not a decision

# Decimals (prices, cost caps, rates) are printed by printf and awk after LC_NUMERIC: under a German locale they would
# read 1,50, and the spot request must say MaxPrice=1.50. LC_ALL overrides LC_NUMERIC, so a set LC_ALL is handed to
# every other category first; only the numbers change (tools/cloud/test_numeric_locale.py).
if [ -n "${LC_ALL:-}" ]; then
    for df_category in CTYPE COLLATE MESSAGES MONETARY TIME PAPER NAME ADDRESS TELEPHONE MEASUREMENT IDENTIFICATION; do
        export "LC_$df_category=$LC_ALL"
    done
    unset df_category LC_ALL
fi
export LC_NUMERIC=C

DF_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DF_ROOT=$(cd "$DF_DIR/../../.." && pwd)  # the repository's work tree

# The campaign definitions, runs/fuzz/<id>/ (restructure step 8: runs/ holds the definitions of named runs). A commit
# from before that move has them in tools/cloud/aws_fuzz/campaigns/<id>/ (DF_CAMPAIGNS_BEFORE_RUNS): a launch of such
# a commit reads them there, and its box runs that commit's own box script, which knows that path.
DF_CAMPAIGNS=runs/fuzz
DF_CAMPAIGNS_BEFORE_RUNS=tools/cloud/aws_fuzz/campaigns

# The repository path of the campaign's campaign.conf at the commit: runs/fuzz/<id>/campaign.conf, or for a commit from
# before the move tools/cloud/aws_fuzz/campaigns/<id>/campaign.conf; status 1 when the commit has neither.
df_campaign_conf_path() { # commit campaign
    local dir
    for dir in "$DF_CAMPAIGNS" "$DF_CAMPAIGNS_BEFORE_RUNS"; do
        if git -C "$DF_DIR" cat-file -e "$1:$dir/$2/campaign.conf" 2> /dev/null; then
            printf '%s\n' "$dir/$2/campaign.conf"
            return 0
        fi
    done
    return 1
}

# The campaign's campaign.conf: the working copy's for the offline tests (DUOFORGE_FUZZ_NO_GIT_CHECK=1), else the
# commit's (df_campaign_conf_path). Status 1 when there is none.
df_campaign_conf() { # commit campaign
    if [ "${DUOFORGE_FUZZ_NO_GIT_CHECK:-}" = 1 ]; then
        cat "$DF_ROOT/$DF_CAMPAIGNS/$2/campaign.conf" 2> /dev/null
    else
        local path
        path=$(df_campaign_conf_path "$1" "$2") || return 1
        git -C "$DF_DIR" show "$1:$path"
    fi
}

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
    df_campaign_conf_path "$1" "$2" > /dev/null ||
        df_die "campaign '$2' has no $DF_CAMPAIGNS/$2/campaign.conf at commit $1 (nor $DF_CAMPAIGNS_BEFORE_RUNS/$2/, before the move)"
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

# A run is one launch and everything it writes: fuzz/<campaign>/<run id>/. The id is <the first 12 digits of the commit>-
# <chunk_battles>-<base_seed>-<the launch time (UTC)>, so a run of another commit or geometry, or an earlier launch,
# can never be the same prefix; a launch continues a run only when told to (launch.sh --resume <run id>).
DF_RUN_ID_RE='^[0-9a-f]{12}-[0-9]{3,5}-[0-9]{1,12}-[0-9]{8}T[0-9]{6}Z$'
df_valid_run_id() { [[ $1 =~ $DF_RUN_ID_RE ]]; }
# A ladder run: fuzz/ladder/<campaign>/<commit12>-ladder-<launch time>/ (one arm, never resumed: a new launch is a new run).
DF_LADDER_RUN_ID_RE='^[0-9a-f]{12}-ladder-[0-9]{8}T[0-9]{6}Z$'
df_valid_ladder_run_id() { [[ $1 =~ $DF_LADDER_RUN_ID_RE ]]; }
# A preview-oracle run: fuzz/oracle/<campaign>/<commit12>-oracle-<launch time>/ (one series; a launch continues it only
# when told to, launch_oracle.sh --resume <run id>, from its state/).
DF_ORACLE_RUN_ID_RE='^[0-9a-f]{12}-oracle-[0-9]{8}T[0-9]{6}Z$'
df_valid_oracle_run_id() { [[ $1 =~ $DF_ORACLE_RUN_ID_RE ]]; }

# A key of the campaign's campaign.conf in the commit that the box will build (the working copy only for the offline
# tests, which say so with DUOFORGE_FUZZ_NO_GIT_CHECK=1), or the default.
df_conf_value() { # commit campaign key default
    local text
    text=$(df_campaign_conf "$1" "$2") || return 1
    local value
    value=$(printf '%s\n' "$text" | sed -n "s/^$3=//p" | head -n 1)
    printf '%s' "${value:-$4}"
}

# The run id up to the launch time: "<commit12>-<chunk_battles>-<base_seed>-".
df_run_id_prefix() { # commit campaign
    local chunk seed
    chunk=$(df_conf_value "$1" "$2" chunk_battles 2000) || df_die "cannot read campaign.conf of '$2' at $1"
    seed=$(df_conf_value "$1" "$2" base_seed '') || df_die "cannot read campaign.conf of '$2' at $1"
    [[ $chunk =~ ^[0-9]{3,5}$ ]] || df_die "campaign '$2': chunk_battles '$chunk' is not a number"
    [[ $seed =~ ^[0-9]{1,12}$ ]] || df_die "campaign '$2': base_seed '$seed' is not a number"
    printf '%s-%s-%s-' "${1:0:12}" "$chunk" "$seed"
}

# shellcheck source=render_box.sh
. "$DF_DIR/render_box.sh"

# The box scripts with their placeholders filled (render_box.sh): what the bootstrap runs on the box. Every value is
# validated before it gets here.
df_render_ladder_user_data() { # campaign commit bucket max-minutes run-id
    df_render_box "$DF_DIR/ladder_user_data.sh" "$1" "$2" "$3" "$4" "$5" no
}

df_render_oracle_user_data() { # campaign commit bucket max-minutes run-id resume(yes|no)
    df_render_box "$DF_DIR/oracle_user_data.sh" "$1" "$2" "$3" "$4" "$5" "${6:-no}"
}

df_render_user_data() { # campaign commit bucket max-minutes run-id resume(yes|no)
    df_render_box "$DF_DIR/user_data.sh" "$1" "$2" "$3" "$4" "$5" "$6"
}

# EC2 takes at most 16384 bytes of user data, before base64 (HauptSession 2026-10-15: the ladder's box script outgrew
# it and the launch was refused).
DF_USER_DATA_LIMIT=16384

# The user data a launcher sends: bootstrap_user_data.sh with its placeholders filled. It sets the watchdog first,
# fetches the commit and runs that commit's box script `script`, rendered on the box by render_box.sh with these values.
df_render_bootstrap() { # script campaign commit bucket max-minutes run-id resume(yes|no)
    case $1 in user_data.sh | ladder_user_data.sh | oracle_user_data.sh) ;; *) df_die "no box script '$1'" ;; esac
    df_render_box "$DF_DIR/bootstrap_user_data.sh" "$2" "$3" "$4" "$5" "$6" "${7:-no}" | sed -e "s|@SCRIPT@|$1|g"
}

# Refuses, by name, user data longer than EC2 takes: user_data_too_large.
df_check_user_data_size() { # user-data
    local size
    size=$(printf '%s' "$1" | wc -c | tr -d ' ')
    [ "$size" -le "$DF_USER_DATA_LIMIT" ] ||
        df_die "user_data_too_large: the user data has $size bytes, more than EC2's $DF_USER_DATA_LIMIT"
}

# The price ceiling per instance hour that keeps the campaign under the cost cap: cap / hours (two decimals). The cap is
# DF_COST_CAP_USD unless given (a preview-oracle campaign gives its price per hour itself: --max-price).
df_max_price() { # hours [cap]
    awk -v cap="${2:-$DF_COST_CAP_USD}" -v h="$1" 'BEGIN { printf "%.2f", cap / h }'
}

# The cost cap of fuzz and ladder: DF_COST_CAP_USD (a preview-oracle campaign gives its price ceiling itself).
df_cost_cap() { # purpose
    case $1 in
        fuzz | ladder) printf '%s' "$DF_COST_CAP_USD" ;;
        *) df_die "purpose '$1' has no cost cap here: fuzz or ladder (oracle gives its price per hour)" ;;
    esac
}

# Fills DF_RUN_ARGS with the arguments of `aws ec2 run-instances` (without --dry-run): spot, the instance profile, the
# group, the tags project=duoforge, purpose=<fuzz|ladder|oracle> (default fuzz) and campaign=<id> on the instance, its
# volume and the spot request, shutdown behaviour terminate, IMDSv2 only, a gp3 root volume that goes with the instance.
# The price ceiling is the purpose's cost cap over the hours (df_cost_cap); a preview-oracle campaign gives it (price).
df_build_run_args() { # ami type subnet sg campaign max-hours user-data [purpose] [price]
    local ami=$1 type=$2 subnet=$3 sg=$4 campaign=$5 hours=$6 userdata=$7 purpose=${8:-fuzz} tags price cap
    case $purpose in fuzz | ladder | oracle) ;; *) df_die "purpose '$purpose' is not fuzz, ladder or oracle" ;; esac
    if [ "$purpose" = oracle ]; then
        price=${9:-}
        [[ $price =~ ^[0-9]+\.[0-9]{2}$ ]] || df_die "internal error: the oracle's price ceiling '$price' is not given"
    else
        cap=$(df_cost_cap "$purpose")
        price=$(df_max_price "$hours" "$cap")
    fi
    tags="Tags=[{Key=project,Value=duoforge},{Key=purpose,Value=$purpose},{Key=campaign,Value=$campaign}]"
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
