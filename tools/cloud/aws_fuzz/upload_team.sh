#!/usr/bin/env bash
# Uploads the private foe team of a preview-oracle campaign (#458) to the bucket as teams/<sha256>.txt: the ONLY way a
# team file reaches the bucket (tools/cloud/aws_fuzz/README.md, "Preview-oracle campaigns"). Only the HauptSession runs
# this, from its chat, with the owner present and the owner's credentials (owner rule; Owner-Entscheidung 2026-10-15,
# nur #458): the user pokeengine has no S3 write permission, so there is no pokeengine identity guard here, as for the
# upload of the networks (README, the ladder's step 2).
#
# usage: upload_team.sh --file PATH --sha256 SHA --bucket B [--i-have-owner-approval]
#   --file      the team file (never printed: neither its content nor its path or name, not even in an error)
#   --sha256    the sha256 the campaign names (foe_team=): the file's own sha256 must be exactly this
#   --bucket    the private bucket; the target is s3://<B>/teams/<sha256>.txt (server-side encryption AES256)
#   --i-have-owner-approval  actually upload. WITHOUT it nothing is uploaded: the target is printed.
# The profile is $AWS_PROFILE (the owner's; required, and never pokeengine), the region eu-central-1. The file is
# streamed to the CLI on stdin, so that its path never reaches the CLI, its arguments or its messages either.
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=lib.sh
. "$HERE/lib.sh"

file=''
sha=''
bucket=''
approved=no
while [ $# -gt 0 ]; do
    case $1 in
        --file) [ $# -ge 2 ] || df_die '--file needs a value'; file=$2; shift 2 ;;
        --sha256) [ $# -ge 2 ] || df_die '--sha256 needs a value'; sha=$2; shift 2 ;;
        --bucket) [ $# -ge 2 ] || df_die '--bucket needs a value'; bucket=$2; shift 2 ;;
        --i-have-owner-approval) approved=yes; shift ;;
        -h | --help) sed -n '2,14p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) df_die 'unknown argument (see --help; no argument is echoed here)' ;;
    esac
done

# --- the values: no message names the file, and a bad value is not echoed (a path in the wrong place would be)
[[ $sha =~ ^[0-9a-f]{64}$ ]] || df_die 'bad or missing --sha256: 64 lowercase hex digits'
df_valid_bucket "$bucket" || df_die 'bad or missing --bucket: lowercase letters, digits, dots and dashes'
[ -n "$file" ] || df_die 'missing --file: the team file'
[ -f "$file" ] || df_die 'the team file does not exist or is not a regular file'
[ -r "$file" ] || df_die 'the team file cannot be read'
# sha256sum reads stdin: its output names no file
got=$(sha256sum < "$file" 2> /dev/null | cut -d' ' -f1) || got=''
[[ $got =~ ^[0-9a-f]{64}$ ]] || df_die 'the team file cannot be read'
[ "$got" = "$sha" ] || df_die "the team file has the sha256 $got, not $sha: refusing"
size=$(wc -c < "$file" | tr -d ' ')

profile=${AWS_PROFILE:-}
[ -n "$profile" ] || df_die "AWS_PROFILE is not set: the owner's profile uploads the team (pokeengine cannot write)"
[ "$profile" != "$DF_PROFILE_DEFAULT" ] ||
    df_die "AWS_PROFILE is $DF_PROFILE_DEFAULT, which has no S3 write permission: the owner's profile uploads the team"
AWS_REGION=$DF_REGION
AWS_DEFAULT_REGION=$DF_REGION
export AWS_PROFILE AWS_REGION AWS_DEFAULT_REGION
key="teams/$sha.txt"

echo "team sha256   $sha (the file has it)"
echo "target        s3://$bucket/$key (server-side encryption AES256; read-only for the box)"

if [ "$approved" != yes ]; then
    echo
    echo 'nothing was uploaded: --i-have-owner-approval is not given (the default).'
    exit 0
fi

# --- only past the owner's approval: one upload, the file on stdin; its messages masked, the file never named
if ! err=$(df_aws s3 cp - "s3://$bucket/$key" --sse AES256 --only-show-errors < "$file" 2>&1 > /dev/null); then
    df_die "the upload of the team file to s3://$bucket/$key failed: $(printf '%s' "$err" | df_mask | tr '\n' ' ')"
fi
# The object is there, encrypted, and as long as the file (a stream cut short would be shorter).
if ! head=$(df_aws s3api head-object --bucket "$bucket" --key "$key" --query '[ContentLength,ServerSideEncryption]' \
    --output text 2>&1); then
    df_die "s3://$bucket/$key could not be checked after the upload: $(printf '%s' "$head" | df_mask | tr '\n' ' ')"
fi
head=${head//$'\r'/} # a Windows CLI ends its lines with CRLF
read -r length encryption <<< "$head"
[ "$length" = "$size" ] && [ "$encryption" = AES256 ] ||
    df_die "s3://$bucket/$key is not as uploaded (length ${length:-none} of $size bytes, encryption ${encryption:-none}): check it"
echo "uploaded      s3://$bucket/$key (checked: the length of the file, AES256)"
