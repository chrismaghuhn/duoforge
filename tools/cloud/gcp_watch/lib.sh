#!/usr/bin/env bash
# shellcheck shell=bash disable=SC2034
# Shared by create.sh, start.sh, stop.sh and delete.sh (tools/cloud/gcp_watch/README.md): the identity guard, the fixed
# names, the validation of every value that reaches a gcloud call, the read-only inspection of what the owner's
# session created (network, subnet, firewall, service account, bucket, machine type), and the one place that builds
# the `gcloud compute instances create` request, so that the dry run and the real call cannot differ.
#
# Nothing here creates a key, prints a token or reads a credential: the scripts only use the gcloud session that is
# already signed in, and ask which project it is for.

GW_PROJECT='project-d498a888-995e-4142-82a'
GW_REGION=europe-west4
GW_ALLOWED_ZONES='europe-west4-a europe-west4-b europe-west4-c'
GW_DEFAULT_ZONE=europe-west4-a
GW_NETWORK=duoforge-net
GW_SUBNET=duoforge-subnet
GW_SUBNET_CIDR=10.20.0.0/24
GW_SA_NAME=duoforge-watch
GW_SA_EMAIL="$GW_SA_NAME@$GW_PROJECT.iam.gserviceaccount.com"
GW_INSTANCE=duoforge-watch
GW_ALLOWED_MACHINES='t2d-standard-8 t2d-standard-4'
GW_DEFAULT_MACHINE=t2d-standard-8
GW_IMAGE_FAMILY=ubuntu-2404-lts-amd64
GW_IMAGE_PROJECT=ubuntu-os-cloud
GW_DISK_GB=60
GW_DISK_TYPE=pd-balanced
GW_LABELS='project=duoforge,purpose=watch'

GW_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
GW_GCLOUD=${GW_GCLOUD:-gcloud}

gw_die() {
    printf 'gcp_watch: %s\n' "$*" >&2
    exit 2
}

gw_log() {
    printf 'gcp_watch: %s\n' "$*" >&2
}

# Every gcloud call that names a resource goes through here: the project is always explicit, so the active
# configuration cannot redirect it (the identity guard checks that it is the same one, too).
gw_gcloud() {
    "$GW_GCLOUD" --project "$GW_PROJECT" --quiet "$@"
}

# The first gcloud action of every script: which project is active, and that an account is signed in. Anything but the
# project of the watchdog is refused before another call is made. The account itself is neither printed nor stored.
gw_identity_guard() {
    local project accounts
    project=$("$GW_GCLOUD" config get project 2> /dev/null) || project=''
    [ -n "$project" ] || gw_die "the active gcloud project could not be read: refusing to do anything"
    [ "$project" = "$GW_PROJECT" ] ||
        gw_die "the active gcloud project is '$project', not '$GW_PROJECT': refusing (gcloud config set project is yours to run)"
    accounts=$("$GW_GCLOUD" auth list --filter=status:ACTIVE --format='value(account)' 2> /dev/null) || accounts=''
    [ -n "$accounts" ] || gw_die "no active gcloud account: refusing (gcloud auth login is yours to run)"
    gw_log "project $GW_PROJECT, an account is active, region $GW_REGION"
}

# ---------------------------------------------------------------------------------------------- validation

gw_valid_bucket() { [[ $1 =~ ^[a-z0-9][a-z0-9._-]{2,62}$ ]]; }

gw_in_list() { # value list
    local x
    for x in $2; do
        [ "$x" = "$1" ] && return 0
    done
    return 1
}

gw_valid_zone() { gw_in_list "$1" "$GW_ALLOWED_ZONES"; }
gw_valid_machine() { gw_in_list "$1" "$GW_ALLOWED_MACHINES"; }

# ---------------------------------------------------------------------------------------------- inspection

# Read-only: what the owner's session created must be what the scripts assume. Fills GW_PROBLEMS (an array; empty when
# it is all right). Never exits. The bucket is optional (start, stop and delete do not need it).
gw_inspect() { # machine-type bucket-or-empty
    GW_PROBLEMS=()
    local machine=$1 bucket=$2 out
    out=$(gw_gcloud compute networks describe "$GW_NETWORK" --format='value(autoCreateSubnetworks)' 2> /dev/null) || out='?'
    case $out in
        False | false) ;;
        '?') GW_PROBLEMS+=("the network '$GW_NETWORK' was not found") ;;
        *) GW_PROBLEMS+=("the network '$GW_NETWORK' is not a custom-mode network (autoCreateSubnetworks: ${out:-empty})") ;;
    esac

    out=$(gw_gcloud compute networks subnets describe "$GW_SUBNET" --region "$GW_REGION" --format='value(ipCidrRange)' 2> /dev/null) || out='?'
    if [ "$out" = '?' ]; then
        GW_PROBLEMS+=("the subnet '$GW_SUBNET' was not found in $GW_REGION")
    else
        [ "$out" = "$GW_SUBNET_CIDR" ] || GW_PROBLEMS+=("the subnet '$GW_SUBNET' has the range '$out', not $GW_SUBNET_CIDR")
        out=$(gw_gcloud compute networks subnets describe "$GW_SUBNET" --region "$GW_REGION" --format='value(network)' 2> /dev/null) || out=''
        case $out in
            */"$GW_NETWORK") ;;
            *) GW_PROBLEMS+=("the subnet '$GW_SUBNET' is not in the network '$GW_NETWORK' (it is in '${out##*/}')") ;;
        esac
    fi

    out=$(gw_gcloud compute firewall-rules list --filter="network~/$GW_NETWORK\$" --format='value(name)' 2> /dev/null) || out='?'
    if [ "$out" = '?' ]; then
        GW_PROBLEMS+=("the firewall rules of '$GW_NETWORK' could not be listed")
    elif [ -n "$out" ]; then
        GW_PROBLEMS+=("the network '$GW_NETWORK' has firewall rule(s) ($(printf '%s' "$out" | tr '\n' ' ')); it must have none: no ingress")
    fi

    out=$(gw_gcloud iam service-accounts describe "$GW_SA_EMAIL" --format='value(email)' 2> /dev/null) || out=''
    [ "$out" = "$GW_SA_EMAIL" ] || GW_PROBLEMS+=("the service account $GW_SA_EMAIL was not found")

    out=$(gw_gcloud compute machine-types list --filter="name=$machine AND zone~^$GW_REGION" --format='value(zone)' 2> /dev/null) || out=''
    [ -n "$out" ] || GW_PROBLEMS+=("the machine type $machine is not offered in $GW_REGION")

    if [ -n "$bucket" ]; then
        out=$(gw_gcloud storage buckets describe "gs://$bucket" --format='value(uniform_bucket_level_access,public_access_prevention)' 2> /dev/null) || out='?'
        if [ "$out" = '?' ]; then
            GW_PROBLEMS+=("the bucket gs://$bucket was not found or cannot be read")
        else
            case $out in
                True$'\t'enforced | true$'\t'enforced) ;;
                *) GW_PROBLEMS+=("the bucket is not private (uniform access and enforced public access prevention are required; found: $(printf '%s' "$out" | tr '\t' ' '))") ;;
            esac
        fi
    fi
    return 0
}

# The state of the instance: prints its status (RUNNING, TERMINATED, ...) or nothing when there is none.
gw_instance_status() { # zone
    gw_gcloud compute instances describe "$GW_INSTANCE" --zone "$1" --format='value(status)' 2> /dev/null || true
}

# ---------------------------------------------------------------------------------------------- the request

# Fills GW_CREATE_ARGS with the arguments of `gcloud compute instances create`: one spot VM that STOPs (the disk and the
# build cache stay) when it is preempted or when the round has powered it off, no instance group and no template; the
# network and subnet of the owner's setup with an ephemeral external address (egress only: there is no firewall rule, so
# nothing can come in); the service account duoforge-watch with the cloud-platform scope (what it may do is its role,
# objectUser on the one bucket); a shielded VM; no SSH key and no OS Login; the bucket as metadata (not in the
# repository); the labels project=duoforge and purpose=watch.
gw_build_create_args() { # zone machine bucket
    local zone=$1 machine=$2 bucket=$3
    GW_CREATE_ARGS=(
        compute instances create "$GW_INSTANCE"
        --zone "$zone"
        --machine-type "$machine"
        --provisioning-model SPOT
        --instance-termination-action STOP
        --maintenance-policy TERMINATE
        --image-family "$GW_IMAGE_FAMILY"
        --image-project "$GW_IMAGE_PROJECT"
        --boot-disk-size "${GW_DISK_GB}GB"
        --boot-disk-type "$GW_DISK_TYPE"
        --network-interface "network=$GW_NETWORK,subnet=$GW_SUBNET"
        --service-account "$GW_SA_EMAIL"
        --scopes cloud-platform
        --shielded-secure-boot
        --shielded-vtpm
        --shielded-integrity-monitoring
        --metadata "block-project-ssh-keys=TRUE,enable-oslogin=FALSE,duoforge-bucket=$bucket"
        --metadata-from-file "startup-script=$GW_DIR/startup.sh"
        --labels "$GW_LABELS"
    )
}

# `start`, `stop` or `delete` of the one instance: the guard, a dry run by default, the real call only with the approval flag.
# The instance must carry the labels project=duoforge and purpose=watch (a machine that is not the watchdog is never touched).
gw_instance_action() { # action args...
    local action=$1 zone=$GW_DEFAULT_ZONE approved=no status labels
    shift
    while [ $# -gt 0 ]; do
        case $1 in
            --zone)
                [ $# -ge 2 ] || gw_die "--zone needs a value"
                zone=$2
                shift 2
                ;;
            --i-have-owner-approval)
                approved=yes
                shift
                ;;
            *) gw_die "unknown argument '$1' (usage: $action.sh [--zone ZONE] [--i-have-owner-approval])" ;;
        esac
    done
    gw_valid_zone "$zone" || gw_die "the zone '$zone' is not one of: $GW_ALLOWED_ZONES"
    gw_identity_guard
    status=$(gw_instance_status "$zone")
    [ -n "$status" ] || gw_die "there is no instance '$GW_INSTANCE' in $zone"
    labels=$(gw_gcloud compute instances describe "$GW_INSTANCE" --zone "$zone" --format='value(labels.project,labels.purpose)' 2> /dev/null | tr '\t' ',') || labels=''
    [ "$labels" = "duoforge,watch" ] || gw_die "the instance '$GW_INSTANCE' does not carry the labels $GW_LABELS: refusing to touch it"
    gw_log "the instance $GW_INSTANCE in $zone is $status"
    local cmd=(compute instances "$action" "$GW_INSTANCE" --zone "$zone")
    case $action in
        start) [ "$status" != RUNNING ] || gw_die "the instance is already RUNNING (a round is under way, or it was just started)" ;;
        stop) [ "$status" = RUNNING ] || gw_die "the instance is $status, not RUNNING: nothing to stop" ;;
        delete) ;;
    esac
    if [ "$approved" != yes ]; then
        gw_log "dry run: without --i-have-owner-approval nothing is changed. The call would be:"
        printf '%s %s\n' "$GW_GCLOUD" "--project $GW_PROJECT --quiet ${cmd[*]}"
        return 0
    fi
    gw_log "approved: $action $GW_INSTANCE"
    gw_gcloud "${cmd[@]}"
}
