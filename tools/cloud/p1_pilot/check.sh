#!/usr/bin/env bash
# The permission check of the P1 pilot launcher (tools/cloud/p1_pilot/README.md). Read-only and --dry-run calls only:
# nothing is created, started or written. It says what the user pokeengine can do and what is missing, and prints the
# S3 statement for p1/ that the role behind the instance profile needs (IAM is not visible to the user, so that one is
# never checked, only shown).
#
# usage: check.sh [--bucket B] [--types t1,t2]
#   --bucket    the results bucket (default $DUOFORGE_P1_BUCKET)
#   --types     the candidate instance types (default g6.4xlarge,g5.4xlarge)
# The profile is $AWS_PROFILE (default pokeengine), the region eu-central-1. Exit status: 0 when nothing is missing, 1
# when something is, 2 for a refusal (wrong caller, bad argument).
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
. "$HERE/lib.sh"

bucket=${DUOFORGE_P1_BUCKET:-}
types=$DF_DEFAULT_TYPES
while [ $# -gt 0 ]; do
    case $1 in
        --bucket) [ $# -ge 2 ] || df_die '--bucket needs a value'; bucket=$2; shift 2 ;;
        --types) [ $# -ge 2 ] || df_die '--types needs a value'; types=$2; shift 2 ;;
        -h | --help) sed -n '2,11p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) df_die "unknown argument '$1' (see --help)" ;;
    esac
done

df_init
df_identity_guard # the first AWS action

[ -z "$bucket" ] || df_valid_bucket "$bucket" || df_die "bad bucket name '$bucket'"
IFS=',' read -r -a type_list <<< "$types"
[ ${#type_list[@]} -gt 0 ] || df_die '--types is empty'
for t in "${type_list[@]}"; do
    df_type_allowed "$t" || df_die "instance type '$t' is not one of: $DF_ALLOWED_TYPES"
done

missing=()
notes=()
ok() { printf 'ok       %s\n' "$1"; }
bad() {
    printf 'MISSING  %s\n' "$1"
    missing+=("$1")
}
note() {
    printf 'NOTE     %s\n' "$1"
    notes+=("$1")
}

# --- 1. the security group
df_sg_inspect "$DF_SG_NAME"
if [ ${#DF_SG_PROBLEMS[@]} -eq 0 ]; then
    ok "security group $DF_SG_NAME: exists, no inbound rule, tagged project=duoforge"
else
    for p in "${DF_SG_PROBLEMS[@]}"; do bad "$p"; done
fi

# --- 2. the bucket (the user's read access to p1/)
user_s3_missing=no
if [ -z "$bucket" ]; then
    bad "no bucket given (--bucket or DUOFORGE_P1_BUCKET): s3:ListBucket on $DF_S3_TOP/ was not checked"
elif out=$(df_aws s3api list-objects-v2 --bucket "$bucket" --prefix "$DF_S3_TOP/" --max-keys 1 --query 'KeyCount' --output text 2>&1); then
    ok "bucket $bucket: s3:ListBucket with the prefix $DF_S3_TOP/ (${out} object(s) in the first page)"
else
    bad "bucket $bucket: listing the prefix $DF_S3_TOP/ failed: $(printf '%s' "$out" | df_mask | tr '\n' ' ')"
    user_s3_missing=yes
fi

# --- 3. the AMI parameter and the image behind it
ami=''
user_ssm_missing=no
if out=$(df_ami 2>&1) && [[ $out =~ ^ami-[0-9a-f]+$ ]]; then
    ami=$out
    ok "ssm get-parameter of the Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04): $ami"
    df_ami_inspect "$ami"
    if [ ${#DF_AMI_PROBLEMS[@]} -eq 0 ]; then
        ok "image $ami: '$DF_AMI_NAME', root $DF_ROOT_DEVICE ($DF_ROOT_SNAPSHOT_GB GB snapshot, the request gives $DF_DISK_GB GB)"
    else
        for p in "${DF_AMI_PROBLEMS[@]}"; do bad "$p"; done
    fi
else
    bad "ssm get-parameter $DF_AMI_PARAM failed: $(printf '%s' "$out" | df_mask | tr '\n' ' ')"
    case $out in *AccessDenied* | *not\ authorized*) user_ssm_missing=yes ;; esac
fi

# --- 4. one box at a time, and the spot quota
if out=$(df_active_pilots 2>&1); then
    if [ -z "$out" ] || [ "$out" = None ]; then
        ok "no pilot box exists (purpose=$DF_PURPOSE: pending, running, stopping or shutting down)"
    else
        bad "a pilot box still exists: $(printf '%s' "$out" | tr '\t\n' '  ')"
    fi
else
    bad "describe-instances failed: $(printf '%s' "$out" | df_mask | tr '\n' ' ')"
fi
if out=$(df_aws service-quotas get-service-quota --service-code ec2 --quota-code "$DF_SPOT_QUOTA_CODE" \
    --query Quota.Value --output text 2>&1) && [[ $out =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
    if awk -v q="$out" -v n="$DF_TYPE_VCPUS" 'BEGIN { exit !(q + 0 >= n + 0) }'; then
        ok "spot quota $DF_SPOT_QUOTA_CODE (All G and VT Spot Instance Requests): $out vCPUs, one box needs $DF_TYPE_VCPUS"
    else
        bad "spot quota $DF_SPOT_QUOTA_CODE (All G and VT Spot Instance Requests): $out vCPUs, one box needs $DF_TYPE_VCPUS"
    fi
else
    note "the spot quota $DF_SPOT_QUOTA_CODE could not be read (servicequotas:GetServiceQuota is optional): not checked"
fi

# --- 5. the dry runs of run-instances, one per candidate type
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

# Without the image the dry runs still say what the permissions allow, with a placeholder image and root device: an
# answer of DryRunOperation or UnauthorizedOperation is about the permissions, anything else is reported.
placeholder=no
root=${DF_ROOT_DEVICE:-}
if [ -z "$ami" ] || [ -z "$root" ]; then
    [ -n "$ami" ] || ami='ami-0123456789abcdef0'
    root=/dev/sda1
    placeholder=yes
    df_log 'the image could not be read in full: the dry runs use a placeholder (permissions only)'
fi
if [ -z "$DF_SG_ID" ]; then
    bad 'the run-instances dry runs were skipped: they need the security group'
else
    mapfile -t subnets < <(df_subnets "$DF_VPC_ID")
    if [ ${#subnets[@]} -eq 0 ] || [ -z "${subnets[0]}" ]; then
        bad "no subnet in the VPC of $DF_SG_NAME"
    else
        check_run_id="$(printf '%012d' 0)-20000101T000000Z"
        userdata=$(df_render_user_data "$(printf '%040d' 0)" "${bucket:-placeholder-bucket}" \
            $((DF_MAX_HOURS_LIMIT * 60)) "$check_run_id")
        last_unauthorized=''
        for t in "${type_list[@]}"; do
            result=''
            attempts=0
            for subnet in "${subnets[@]}"; do
                attempts=$((attempts + 1))
                [ $attempts -le 3 ] || break
                df_build_run_args "$ami" "$t" "$subnet" "$DF_SG_ID" "$check_run_id" "$DF_PRICE_LIMIT" "$root" "$userdata"
                out=$(df_aws ec2 run-instances --dry-run "${DF_RUN_ARGS[@]}" 2>&1)
                case $out in
                    *DryRunOperation*) result=pass; break ;;
                    *UnauthorizedOperation*) result=unauthorized; break ;;
                    *) result=other ;;
                esac
            done
            case $result in
                pass) ok "run-instances --dry-run $t (one-time spot at \$$DF_PRICE_LIMIT, profile $DF_INSTANCE_PROFILE, group $DF_SG_NAME, tags project/purpose/run-id, terminate on shutdown, $DF_DISK_GB GB gp3): DryRunOperation$([ "$placeholder" = yes ] && echo ' (placeholder image)')" ;;
                unauthorized)
                    bad "run-instances --dry-run $t: UnauthorizedOperation"
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

# --- 6. what this script cannot see: the role's S3 permissions for p1/
echo
echo "UNVERIFIED  the role behind the instance profile $DF_INSTANCE_PROFILE was written for the prefix fuzz/ only."
echo '            The user pokeengine cannot read IAM, so this is not checked. Unless the owner has already done it,'
echo "            the box can NOT write s3://<BUCKET>/$DF_S3_TOP/...: in the IAM console, role $DF_INSTANCE_PROFILE, add these"
echo '            statements to its permissions policy (the Statement list), with <BUCKET> the results bucket:'
echo
df_role_statement
if [ "$user_ssm_missing" = yes ] || [ "$user_s3_missing" = yes ]; then
    echo
    echo 'The policy of the user pokeengine lacks what check.sh needed above; the statements to add (README.md):'
    if [ "$user_ssm_missing" = yes ]; then
        echo "  ssm:GetParameter on arn:aws:ssm:$DF_REGION::parameter$DF_AMI_PARAM"
    fi
    if [ "$user_s3_missing" = yes ]; then
        echo "  s3:ListBucket on arn:aws:s3:::<BUCKET> with s3:prefix [\"$DF_S3_TOP/\", \"$DF_S3_TOP/*\"], s3:GetObject on arn:aws:s3:::<BUCKET>/$DF_S3_TOP/*"
    fi
fi

# --- the report
echo
if [ ${#notes[@]} -gt 0 ]; then
    echo "notes (${#notes[@]}):"
    for n in "${notes[@]}"; do printf '  - %s\n' "$n"; done
fi
if [ ${#missing[@]} -eq 0 ]; then
    echo 'nothing is missing: every check passed (nothing was created). The role statement above is still unverified.'
    exit 0
fi
echo "missing (${#missing[@]}):"
for m in "${missing[@]}"; do printf '  - %s\n' "$m"; done
exit 1
