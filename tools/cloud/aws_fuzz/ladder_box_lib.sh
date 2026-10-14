# shellcheck shell=bash
# Functions of the ladder box (#484), sourced by ladder_user_data.sh from the checkout at the exact commit. Kept apart
# so that tests run them against a stub aws: nothing here is ever run against AWS by a test.

# ladder_nets_probe BUCKET KEY: is nets/ read-only for this box (HauptSession: only GetObject there)? Three probes on
# KEY (a key of the run's own under nets/), each of which must be denied:
#   - a plain write (put-object),
#   - a write with server-side encryption (a bucket policy that denies only unencrypted writes would deny the first
#     probe while the role could still write),
#   - a delete (a delete of a missing key succeeds wherever deleting is allowed).
# Prints one line; status 0: every probe was denied (AccessDenied); 3: one succeeded (nets/ is writable; a written
# probe key is deleted again where possible); 4: one failed otherwise (no credentials, no network, an empty answer):
# unclear, which is no proof of read-only.
ladder_nets_probe() {
    local bucket=$1 key=$2 out probe rc empty
    # The body of the probe writes: an empty regular file (the AWS CLI refuses /dev/null, "Blob values must be a path
    # to a file", which would make every probe unclear).
    empty=$(mktemp) || { echo "no temporary file for the probe body"; return 4; }
    for probe in plain sse delete; do
        case $probe in
            plain) out=$(aws s3api put-object --bucket "$bucket" --key "$key" --body "$empty" 2>&1) && rc=0 || rc=$? ;;
            sse) out=$(aws s3api put-object --bucket "$bucket" --key "$key" --body "$empty" \
                --server-side-encryption AES256 2>&1) && rc=0 || rc=$? ;;
            delete) out=$(aws s3api delete-object --bucket "$bucket" --key "$key" 2>&1) && rc=0 || rc=$? ;;
        esac
        if [ "$rc" -eq 0 ]; then
            [ "$probe" = delete ] || aws s3api delete-object --bucket "$bucket" --key "$key" > /dev/null 2>&1 || true
            rm -f "$empty"
            echo "the $probe probe on s3://$bucket/$key succeeded"
            return 3
        fi
        case $out in
            *AccessDenied*) ;;
            *)
                rm -f "$empty"
                echo "the $probe probe on s3://$bucket/$key failed, but not with AccessDenied: ${out:-no output}"
                return 4
                ;;
        esac
    done
    rm -f "$empty"
    echo "every probe on s3://$bucket/$key was denied (plain write, encrypted write, delete)"
    return 0
}
