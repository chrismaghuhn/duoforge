#!/usr/bin/env bash
# The permission check of the AWS fuzz campaigns (tools/cloud/aws_fuzz/README.md). Read-only and --dry-run calls only:
# nothing is created, started or written. It says what the user pokeengine can do and what is missing.
#
# usage: check.sh [--bucket B] [--campaign ID] [--types t1,t2,...]
#   --bucket    the results bucket (default $DUOFORGE_FUZZ_BUCKET)
#   --campaign  the id that the dry-run request is tagged with (default "check")
#   --types     the candidate instance types (default c7a.16xlarge,c6a.16xlarge,c7i.16xlarge,m7a.16xlarge)
# The profile is $AWS_PROFILE (default pokeengine), the region eu-central-1. Exit status: 0 when nothing is missing, 1
# when something is, 2 for a refusal (wrong caller, bad argument).
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
. "$HERE/lib.sh"

campaign=check
bucket=${DUOFORGE_FUZZ_BUCKET:-}
types=$DF_DEFAULT_TYPES
while [ $# -gt 0 ]; do
    case $1 in
        --bucket) [ $# -ge 2 ] || df_die '--bucket needs a value'; bucket=$2; shift 2 ;;
        --campaign) [ $# -ge 2 ] || df_die '--campaign needs a value'; campaign=$2; shift 2 ;;
        --types) [ $# -ge 2 ] || df_die '--types needs a value'; types=$2; shift 2 ;;
        -h | --help) sed -n '2,12p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) df_die "unknown argument '$1' (see --help)" ;;
    esac
done

df_init
df_identity_guard # the first AWS action

df_valid_campaign "$campaign" || df_die "bad --campaign '$campaign' (lowercase letters, digits and dashes, at most 40)"
[ -z "$bucket" ] || df_valid_bucket "$bucket" || df_die "bad bucket name '$bucket'"
IFS=',' read -r -a type_list <<< "$types"
for t in "${type_list[@]}"; do
    df_type_allowed "$t" || df_die "instance type '$t' is not one of: $DF_ALLOWED_TYPES"
done

missing=()
ok() { printf 'ok       %s\n' "$1"; }
bad() {
    printf 'MISSING  %s\n' "$1"
    missing+=("$1")
}

# --- 1. the security group
df_sg_inspect "$DF_SG_NAME"
if [ ${#DF_SG_PROBLEMS[@]} -eq 0 ]; then
    ok "security group $DF_SG_NAME: exists, no inbound rule, tagged project=duoforge"
else
    for p in "${DF_SG_PROBLEMS[@]}"; do bad "$p"; done
fi

# --- 2. the bucket
if [ -z "$bucket" ]; then
    bad 'no bucket given (--bucket or DUOFORGE_FUZZ_BUCKET): s3:ListBucket on fuzz/ was not checked'
elif out=$(df_aws s3api list-objects-v2 --bucket "$bucket" --prefix fuzz/ --max-keys 1 --query 'KeyCount' --output text 2>&1); then
    ok "bucket $bucket: s3:ListBucket with the prefix fuzz/ (${out} object(s) in the first page)"
else
    bad "bucket $bucket: listing the prefix fuzz/ failed: $(printf '%s' "$out" | df_mask | tr '\n' ' ')"
fi

# --- 3. the AMI parameter
ami=''
if out=$(df_ami 2>&1) && [[ $out =~ ^ami-[0-9a-f]+$ ]]; then
    ami=$out
    ok "ssm get-parameter of the Ubuntu 24.04 AMI: $ami"
else
    bad "ssm get-parameter $DF_AMI_PARAM failed: $(printf '%s' "$out" | df_mask | tr '\n' ' ')"
fi

# --- 4. the dry runs of run-instances, one per candidate type
decode_unauthorized() { # message
    local msg=$1 enc decoded
    enc=$(printf '%s' "$msg" | sed -n 's/.*Encoded authorization failure message: \([A-Za-z0-9_-]*\).*/\1/p' | head -n 1)
    if [ -n "$enc" ] && decoded=$(df_aws sts decode-authorization-message --encoded-message "$enc" --query DecodedMessage --output text 2>&1); then
        printf '%s' "$decoded" | df_mask
    else
        printf '%s' "$msg" | df_mask
        [ -z "$enc" ] || printf '  (sts:DecodeAuthorizationMessage is not allowed or failed; the message is raw)'
    fi
}

# Without the AMI parameter the dry runs still say what the permissions allow, with a placeholder image: an answer
# of DryRunOperation or UnauthorizedOperation is about the permissions, anything else about the image is reported.
placeholder=no
if [ -z "$ami" ]; then
    ami=ami-0123456789abcdef0
    placeholder=yes
    df_log 'the AMI parameter could not be read: the dry runs use a placeholder image (permissions only)'
fi
if [ -z "$DF_SG_ID" ]; then
    bad 'the run-instances dry runs were skipped: they need the security group'
else
    mapfile -t subnets < <(df_subnets "$DF_VPC_ID")
    if [ ${#subnets[@]} -eq 0 ] || [ -z "${subnets[0]}" ]; then
        bad "no subnet in the VPC of $DF_SG_NAME"
    else
        userdata=$(df_render_user_data "$campaign" "$(printf '%040d' 0)" "${bucket:-placeholder-bucket}" $((DF_MAX_HOURS_LIMIT * 60)))
        last_unauthorized=''
        for t in "${type_list[@]}"; do
            result=''
            attempts=0
            for subnet in "${subnets[@]}"; do
                attempts=$((attempts + 1))
                [ $attempts -le 3 ] || break
                df_build_run_args "$ami" "$t" "$subnet" "$DF_SG_ID" "$campaign" "$DF_MAX_HOURS_LIMIT" "$userdata"
                out=$(df_aws ec2 run-instances --dry-run "${DF_RUN_ARGS[@]}" 2>&1)
                case $out in
                    *DryRunOperation*) result=pass; break ;;
                    *UnauthorizedOperation*) result=unauthorized; break ;;
                    *) result=other ;;
                esac
            done
            case $result in
                pass) ok "run-instances --dry-run $t (spot, profile $DF_INSTANCE_PROFILE, group $DF_SG_NAME, tags, terminate on shutdown): DryRunOperation$([ "$placeholder" = yes ] && echo ' (placeholder AMI)')" ;;
                unauthorized)
                    bad "run-instances --dry-run $t: UnauthorizedOperation"
                    # the message is the same for every type unless the missing permission differs: say it once
                    key=$(printf '%s' "$out" | sed 's/Encoded authorization failure message:.*//' | df_mask)
                    if [ "$key" = "$last_unauthorized" ]; then
                        echo '         (same message as above)'
                    else
                        last_unauthorized=$key
                        { decode_unauthorized "$out"; echo; } | sed -e '/^[[:space:]]*$/d' -e 's/^/         /'
                    fi
                    ;;
                *) bad "run-instances --dry-run $t: $(printf '%s' "$out" | df_mask | tr '\n' ' ')" ;;
            esac
        done
    fi
fi

# --- the report
echo
if [ ${#missing[@]} -eq 0 ]; then
    echo 'nothing is missing: every check passed (nothing was created).'
    exit 0
fi
echo "missing (${#missing[@]}):"
for m in "${missing[@]}"; do printf '  - %s\n' "$m"; done
exit 1
