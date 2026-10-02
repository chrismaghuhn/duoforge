#!/usr/bin/env python3
"""Offline tests of tools/cloud/aws_fuzz: the guards of launch.sh, check.sh and collect.sh, with a stub `aws` first on the
PATH (nothing here reaches AWS: the stub logs every call and answers from the environment).

 - the identity guard: a caller that is not ':user/pokeengine' is refused before any other call;
 - launch.sh: any security group but duoforge-fuzz (by name, by inbound rule, by tag, missing), a missing approval flag
   (the request is printed, run-instances is never called), --max-hours above 2 or not a number, a bad sha, campaign,
   bucket or instance type;
 - the request: spot, the instance profile and the group, the three tag specifications, terminate on shutdown;
 - the user data: its first command is the watchdog, no placeholder is left, nothing in it is a secret;
 - check.sh: DryRunOperation is a pass, UnauthorizedOperation is reported (decoded or raw) and is a failure;
 - the repository: no account id, no access key, and the README's policy says what it must;
 - shellcheck over the scripts when it is installed.
Needs bash on the PATH (Git Bash on Windows)."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import shlex
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
BASH = os.environ.get('DUOFORGE_BASH') or shutil.which('bash')
ACCOUNT = '%012d' % 7  # a made-up account id, built here so that no number of that shape is in the repository
SHA = 'a' * 40
SWITCHES = ('MSYS_NO_PATHCONV', 'MSYS2_ARG_CONV_EXCL')

STUB = r'''#!/usr/bin/env bash
# The stub aws of the tests: logs the call, answers from STUB_* variables.
printf '%s\n' "$*" >> "$STUB_LOG"
if [ "$1" = --region ]; then shift 2; fi
svc=$1
op=$2
shift 2
all="$*"
case "$svc $op" in
    "sts get-caller-identity") echo "$STUB_ARN" ;;
    "sts decode-authorization-message")
        if [ "${STUB_DECODE:-fail}" = ok ]; then echo '{"decoded":"ec2:RunInstances on instance"}'; else
            echo "An error occurred (AccessDenied) when calling the DecodeAuthorizationMessage operation" >&2; exit 254; fi ;;
    "ec2 describe-security-groups")
        case $all in
            *"length(SecurityGroups)"*) echo "${STUB_SG_COUNT:-1}" ;;
            *GroupId*) echo sg-0abc123 ;;
            *VpcId*) echo vpc-0abc123 ;;
            *IpPermissions*) echo "${STUB_SG_INBOUND:-0}" ;;
            *"Key=="*) echo "${STUB_SG_TAG:-duoforge}" ;;
        esac ;;
    "s3 ls") exit "${STUB_S3LS:-1}" ;;
    "s3 cp") case "$1" in *done.txt) echo "MANIFEST $(tr '\n' ',' < "$1")" >> "$STUB_LOG" ;; esac ;;
    "ec2 describe-subnets") echo subnet-0abc123 ;;
    "ssm get-parameter") echo "${STUB_AMI:-ami-0abc123}" ;;
    "s3api list-objects-v2")
        if [ "${STUB_S3:-ok}" = deny ]; then echo "An error occurred (AccessDenied) when calling the ListObjectsV2 operation" >&2; exit 254; fi
        echo 0 ;;
    "ec2 run-instances")
        case $all in
            *--dry-run*)
                if [ "${STUB_DRYRUN:-pass}" = pass ]; then
                    echo "An error occurred (DryRunOperation) when calling the RunInstances operation: Request would have succeeded, but DryRun flag is set." >&2
                else
                    echo "An error occurred (UnauthorizedOperation) when calling the RunInstances operation: You are not authorized to perform this operation. User: arn:aws:iam::$STUB_ACCOUNT:user/pokeengine is not authorized to perform: ec2:RunInstances on resource: arn:aws:ec2:eu-central-1:$STUB_ACCOUNT:instance/* Encoded authorization failure message: AbC123-xyz_9" >&2
                fi
                exit 254 ;;
            *) echo i-0abc123 ;;
        esac ;;
esac
exit 0
'''


FAKE_BENCH = """
import json, sys
a = sys.argv
if '--fail' in a:
    sys.exit(1)
threads = int(a[a.index('--workers') + 1])
out = a[a.index('--out') + 1]
entry = {'family': 'batch', 'workers': threads, 'median_wall_ns': 1000000, 'battles': 20000, 'errors': 0,
         'disturbed_repetitions': 0,
         'per_second': {'battles': 1000 * threads, 'turns': 9000 * threads, 'steps': 20000 * threads,
                        'side_decisions': 30000 * threads, 'calls': 0}}
json.dump({'results': [entry], 'errors': 0}, open(out, 'w'))
"""


def posix(path):
    return path.replace('\\', '/')


@unittest.skipIf(BASH is None, 'bash is not on the PATH')
class Guards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='aws_fuzz_test_')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.stubdir = os.path.join(self.tmp, 'bin')
        os.mkdir(self.stubdir)
        stub = os.path.join(self.stubdir, 'aws')
        with open(stub, 'w', newline='\n') as f:
            f.write(STUB)
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self.log = os.path.join(self.tmp, 'calls.log')
        open(self.log, 'w').close()
        self.env = dict(os.environ, PATH=self.stubdir + os.pathsep + os.environ['PATH'], STUB_LOG=posix(self.log),
                        STUB_ARN='arn:aws:iam::%s:user/pokeengine' % ACCOUNT, STUB_ACCOUNT=ACCOUNT,
                        DUOFORGE_FUZZ_NO_GIT_CHECK='1', AWS_CONFIG_FILE=posix(os.path.join(self.tmp, 'none')),
                        AWS_SHARED_CREDENTIALS_FILE=posix(os.path.join(self.tmp, 'none')))
        for var in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'DUOFORGE_FUZZ_BUCKET'):
            self.env.pop(var, None)
        # the stub must be what `aws` is, or a test would reach the real thing
        found = subprocess.run([BASH, '-c', 'command -v aws'], env=self.env, capture_output=True, text=True).stdout.strip()
        self.assertTrue(found.replace('\\', '/').lower().endswith('/bin/aws') and 'aws_fuzz_test_' in found.lower(), found)

    def run_script(self, script, *args, **env):
        e = dict(self.env, **env)
        return subprocess.run([BASH, posix(os.path.join(HERE, script)), *args], env=e, capture_output=True, text=True,
                              timeout=120)

    def calls(self):
        with open(self.log, encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]

    def real_launches(self):
        return [c for c in self.calls() if ' run-instances ' in (' ' + c + ' ') and '--dry-run' not in c]

    LAUNCH = ('--campaign', 'weather-sand-snow', '--commit', SHA, '--bucket', 'my-fuzz-bucket')

    # ------------------------------------------------------------------ the identity guard
    def test_a_caller_that_is_not_pokeengine_is_refused_before_anything_else(self):
        for arn in ('arn:aws:iam::%s:user/someone-else' % ACCOUNT, 'arn:aws:iam::%s:root' % ACCOUNT,
                    'arn:aws:sts::%s:assumed-role/admin/x' % ACCOUNT, 'arn:aws:iam::%s:user/pokeengine2' % ACCOUNT,
                    'arn:aws:iam::%s:user/path/notpokeengine' % ACCOUNT):
            for script, args in (('launch.sh', self.LAUNCH), ('check.sh', ('--bucket', 'my-fuzz-bucket')),
                                 ('collect.sh', ('--campaign', 'weather-sand-snow', '--bucket', 'my-fuzz-bucket',
                                                 '--runner', BASH))):
                with self.subTest(arn=arn, script=script):
                    open(self.log, 'w').close()
                    r = self.run_script(script, *args, STUB_ARN=arn)
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    self.assertIn("not a ':user/pokeengine'", r.stderr)
                    self.assertNotIn(ACCOUNT, r.stdout + r.stderr)  # the account id is masked
                    self.assertEqual(len(self.calls()), 1, self.calls())
                    self.assertIn('sts get-caller-identity', self.calls()[0])

    def test_the_identity_call_comes_first_and_uses_the_profile_and_region(self):
        self.run_script('launch.sh', *self.LAUNCH)
        first = self.calls()[0]
        self.assertTrue(first.startswith('--region eu-central-1 sts get-caller-identity'), first)

    def test_a_failing_identity_call_is_a_refusal(self):
        r = self.run_script('launch.sh', *self.LAUNCH, STUB_ARN='')
        self.assertEqual(r.returncode, 2)

    # ------------------------------------------------------------------ launch.sh
    def test_without_the_approval_flag_the_request_is_printed_and_nothing_is_launched(self):
        r = self.run_script('launch.sh', *self.LAUNCH)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('nothing was launched', r.stdout)
        self.assertIn('--i-have-owner-approval', r.stdout)
        self.assertIn('MarketType=spot', r.stdout)
        self.assertEqual(self.real_launches(), [])
        self.assertFalse([c for c in self.calls() if ' create-' in c or ' put-' in c])
        self.assertNotIn(ACCOUNT, r.stdout + r.stderr)

    def test_with_the_flag_the_stub_is_asked_for_a_spot_instance_with_the_required_shape(self):
        r = self.run_script('launch.sh', *self.LAUNCH, '--i-have-owner-approval')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('launched i-0abc123', r.stdout)
        runs = self.real_launches()
        self.assertEqual(len(runs), 1)
        call = runs[0]
        for needle in ('MarketType=spot', 'InstanceInterruptionBehavior=terminate', 'MaxPrice=5.00',
                       '--instance-initiated-shutdown-behavior terminate', 'Name=duoforge-fuzz',
                       '--security-group-ids sg-0abc123', '--instance-type c7a.16xlarge', 'HttpTokens=required',
                       '--image-id ami-0abc123', 'ResourceType=instance,Tags=', 'ResourceType=volume,Tags=',
                       'ResourceType=spot-instances-request,Tags='):
            self.assertIn(needle, call)
        self.assertEqual(call.count('Key=project,Value=duoforge'), 3)
        self.assertEqual(call.count('Key=purpose,Value=fuzz'), 3)
        self.assertEqual(call.count('Key=campaign,Value=weather-sand-snow'), 3)
        self.assertNotIn('--key-name', call)
        self.assertNotIn('--associate', call)

    def test_any_group_but_duoforge_fuzz_is_refused(self):
        r = self.run_script('launch.sh', *self.LAUNCH, '--sg-name', 'default')
        self.assertEqual(r.returncode, 2)
        self.assertIn('only duoforge-fuzz is ever used', r.stderr)
        for env, text in (({'STUB_SG_INBOUND': '1'}, '1 inbound rule'), ({'STUB_SG_TAG': 'None'}, 'not tagged project=duoforge'),
                          ({'STUB_SG_COUNT': '0'}, 'not found exactly once'), ({'STUB_SG_COUNT': '2'}, 'not found exactly once')):
            with self.subTest(env=env):
                open(self.log, 'w').close()
                r = self.run_script('launch.sh', *self.LAUNCH, '--i-have-owner-approval', **env)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn(text, r.stderr)
                self.assertEqual(self.real_launches(), [])

    def test_max_hours_above_two_or_not_a_number_is_refused(self):
        for hours in ('3', '24', '0', '-1', '2.5', 'two', ''):
            with self.subTest(hours=hours):
                open(self.log, 'w').close()
                r = self.run_script('launch.sh', *self.LAUNCH, '--max-hours', hours, '--i-have-owner-approval')
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn('--max-hours', r.stderr)
                self.assertEqual(self.real_launches(), [])
        for hours in ('1', '2'):
            r = self.run_script('launch.sh', *self.LAUNCH, '--max-hours', hours)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('shutdown -h +%d' % (60 * int(hours)), r.stdout)

    def test_bad_values_are_refused(self):
        base = dict(zip(self.LAUNCH[::2], self.LAUNCH[1::2]))
        for flag, value in (('--commit', 'main'), ('--commit', 'a' * 39), ('--commit', 'A' * 40), ('--campaign', 'Bad_Id'),
                            ('--campaign', 'x; rm -rf /'), ('--campaign', ''), ('--bucket', 'UPPER'), ('--bucket', ''),
                            ('--types', 'c7a.large'), ('--types', 'c7a.16xlarge,p5.48xlarge'), ('--types', '')):
            with self.subTest(flag=flag, value=value):
                args = dict(base)
                args[flag] = value
                flat = [x for kv in args.items() for x in kv]
                open(self.log, 'w').close()
                r = self.run_script('launch.sh', *flat, '--i-have-owner-approval')
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(self.real_launches(), [])

    def test_the_commit_must_be_checked_against_origin_main_unless_that_is_switched_off_explicitly(self):
        r = self.run_script('launch.sh', *self.LAUNCH, DUOFORGE_FUZZ_NO_GIT_CHECK='')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('commit ' + SHA, r.stderr)
        self.assertEqual(self.real_launches(), [])

    def fresh_repo(self):
        """A repository of its own in the temporary directory: the tool in it, one commit, origin/main at that commit.
        What runs git on the tool's directory runs it here, never in the checkout that the tests happen to be in (a
        worktree whose .git file points to another system's path is no repository for this bash). Returns (the tool's
        directory in it, the sha)."""
        repo = os.path.join(self.tmp, 'repo')
        shutil.copytree(HERE, os.path.join(repo, 'tools', 'cloud', 'aws_fuzz'),
                        ignore=shutil.ignore_patterns('__pycache__'))
        git = ['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid']
        subprocess.run(git + ['init', '-q'], check=True, capture_output=True)
        subprocess.run(git + ['add', '-A'], check=True, capture_output=True)
        subprocess.run(git + ['commit', '-q', '-m', 'x'], check=True, capture_output=True)
        sha = subprocess.run(git + ['rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()
        subprocess.run(git + ['update-ref', 'refs/remotes/origin/main', sha], check=True)
        return os.path.join(repo, 'tools', 'cloud', 'aws_fuzz'), sha

    def test_df_init_does_not_export_the_path_conversion_switches(self):
        # Exported, MSYS_NO_PATHCONV made git -C "$DF_DIR" fail under Git Bash: only the aws call may have them.
        tool, _sha = self.fresh_repo()
        env = {k: v for k, v in self.env.items() if k not in SWITCHES}
        script = ('. "%s/lib.sh"; df_init; env | grep -c -E "^(MSYS_NO_PATHCONV|MSYS2_ARG_CONV_EXCL)=" || true; '
                  'git -C "$DF_DIR" rev-parse --show-toplevel') % posix(tool)
        r = subprocess.run([BASH, '-c', script], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[0], '0', r.stdout)
        self.assertNotIn('fatal', r.stderr)

    def test_the_conversion_switches_are_set_for_the_aws_call_alone(self):
        # a probe aws that prints what it sees
        probe_dir = os.path.join(self.tmp, 'probe')
        os.mkdir(probe_dir)
        probe = os.path.join(probe_dir, 'aws')
        with open(probe, 'w', newline=chr(10)) as f:
            f.write('#!/usr/bin/env bash' + chr(10) +
                    'echo "PATHCONV=${MSYS_NO_PATHCONV:-unset} EXCL=${MSYS2_ARG_CONV_EXCL:-unset}"' + chr(10))
        os.chmod(probe, 0o755)
        env = dict(self.env, PATH=probe_dir + os.pathsep + self.env['PATH'])
        env = {k: v for k, v in env.items() if k not in SWITCHES}
        script = '. "%s/lib.sh"; df_init; df_aws x; echo "after: ${MSYS_NO_PATHCONV:-unset}"' % posix(HERE)
        r = subprocess.run([BASH, '-c', script], env=env, capture_output=True, text=True)
        self.assertEqual(r.stdout.splitlines()[:2], ['PATHCONV=1 EXCL=*', 'after: unset'], r.stdout + r.stderr)

    def test_print_mode_reaches_the_request_with_a_commit_of_a_real_main(self):
        # a repository of its own with the tool in it and an origin/main: the real check (git -C on the script's
        # directory, merge-base, cat-file of the campaign) runs, as it does on the owner's machine
        tool, sha = self.fresh_repo()
        env = dict(self.env, DUOFORGE_FUZZ_NO_GIT_CHECK='')
        r = subprocess.run([BASH, posix(os.path.join(tool, 'launch.sh')), '--campaign', 'weather-sand-snow', '--commit',
                            sha, '--bucket', 'my-fuzz-bucket'], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('nothing was launched', r.stdout)
        self.assertIn(sha, r.stdout)
        self.assertNotIn('fatal', r.stderr)
        self.assertEqual(self.real_launches(), [])
        # and a campaign that this commit does not have is refused by the same check
        r = subprocess.run([BASH, posix(os.path.join(tool, 'launch.sh')), '--campaign', 'no-such-campaign', '--commit',
                            sha, '--bucket', 'my-fuzz-bucket'], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 2)
        self.assertIn('has no tools/cloud/aws_fuzz/campaigns/no-such-campaign/campaign.conf', r.stderr)

    def test_an_unknown_argument_and_a_missing_value_are_refused(self):
        self.assertEqual(self.run_script('launch.sh', '--nope').returncode, 2)
        self.assertEqual(self.run_script('launch.sh', '--campaign').returncode, 2)

    # ------------------------------------------------------------------ the user data
    def test_the_user_data_starts_with_the_watchdog_and_holds_no_secret(self):
        with open(os.path.join(HERE, 'user_data.sh'), encoding='utf-8') as f:
            raw = f.read().split('\n')
        self.assertEqual(raw[0], '#!/bin/bash')
        self.assertEqual(raw[1], 'shutdown -h +@MAX_MINUTES@ "duoforge fuzz watchdog: at most @MAX_MINUTES@ minutes"')
        text = '\n'.join(raw)
        self.assertEqual(sorted(set(re.findall(r'@[A-Z_]+@', text))), ['@BUCKET@', '@CAMPAIGN@', '@COMMIT@', '@MAX_MINUTES@'])
        for secret in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'aws configure', 'AKIA', 'ASIA'):
            self.assertNotIn(secret, text)
        for needle in ('b2cb775b0616115b775534eaeff50300e1fc81fc', 'npm ci --ignore-scripts --omit=dev', 'node build',
                       'DDUOFORGE_ENABLE_IPO=ON', '--no-lock', 'spot/instance-action', 'X-aws-ec2-metadata-token',
                       'done.txt', 'trap finish EXIT', 'shutdown -h now', 'DF_LOCAL_RATE=24', 'DF_MIN_FACTOR=2',
                       'DF_DEFAULT_CHUNK_BATTLES=2000', 'latest-v22.x', 'chunks.sh', 'run_chunks', 'bench_run.py', '/usr/bin/time'):
            self.assertIn(needle, text)

    def test_the_rendered_user_data_has_no_placeholder_left_and_the_watchdog_matches_max_hours(self):
        script = ('. "%s/lib.sh"; df_render_user_data weather-sand-snow %s my-fuzz-bucket 120' % (posix(HERE), SHA))
        r = subprocess.run([BASH, '-c', script], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.split('\n')
        self.assertEqual(lines[0], '#!/bin/bash')
        self.assertTrue(lines[1].startswith('shutdown -h +120 '), lines[1])
        self.assertIsNone(re.search(r'@[A-Z_]+@', r.stdout))
        self.assertIn("DF_COMMIT='%s'" % SHA, r.stdout)
        self.assertLess(len(r.stdout.encode()), 16000)  # the limit of EC2 user data is 16 KB

    # ------------------------------------------------------------------ check.sh
    def test_check_reports_a_pass_when_every_dry_run_would_have_succeeded(self):
        r = self.run_script('check.sh', '--bucket', 'my-fuzz-bucket')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('nothing is missing', r.stdout)
        for t in ('c7a.16xlarge', 'c6a.16xlarge', 'c7i.16xlarge', 'm7a.16xlarge'):
            self.assertIn('run-instances --dry-run %s' % t, r.stdout)
        dry = [c for c in self.calls() if ' run-instances ' in (' ' + c + ' ')]
        self.assertEqual(len(dry), 4)
        self.assertTrue(all('--dry-run' in c for c in dry))
        self.assertEqual(self.real_launches(), [])
        for c in dry:
            self.assertIn('Key=purpose,Value=fuzz', c)
            self.assertIn('--instance-initiated-shutdown-behavior terminate', c)

    def test_check_reports_what_is_missing_and_decodes_an_unauthorized_message(self):
        r = self.run_script('check.sh', '--bucket', 'my-fuzz-bucket', STUB_DRYRUN='unauth', STUB_S3='deny',
                            STUB_SG_INBOUND='2', STUB_DECODE='ok')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('missing (', r.stdout)
        self.assertIn('2 inbound rule(s)', r.stdout)
        self.assertIn('listing the prefix fuzz/ failed', r.stdout)
        self.assertIn('run-instances --dry-run c7a.16xlarge: UnauthorizedOperation', r.stdout)
        self.assertIn('ec2:RunInstances on instance', r.stdout)  # the decoded message
        self.assertTrue(any('decode-authorization-message' in c for c in self.calls()))
        self.assertNotIn(ACCOUNT, r.stdout + r.stderr)
        self.assertEqual(self.real_launches(), [])

    def test_check_prints_a_raw_unauthorized_message_when_it_cannot_be_decoded(self):
        r = self.run_script('check.sh', '--bucket', 'my-fuzz-bucket', STUB_DRYRUN='unauth')
        self.assertEqual(r.returncode, 1)
        self.assertIn('Encoded authorization failure message', r.stdout)
        self.assertIn('DecodeAuthorizationMessage is not allowed or failed', r.stdout)
        self.assertNotIn(ACCOUNT, r.stdout + r.stderr)

    def test_check_without_a_bucket_says_so(self):
        r = self.run_script('check.sh')
        self.assertEqual(r.returncode, 1)
        self.assertIn('no bucket given', r.stdout)

    # ------------------------------------------------------------------ the chunk scheduler (chunks.sh)
    HARNESS = r"""
set -euo pipefail
WORK=$1; EVENTS=$2; LOGF=$3; HERE=$4
mkdir -p "$WORK/out"
[ -f "$WORK/done.txt" ] || : > "$WORK/done.txt"
S3_BASE=s3://my-fuzz-bucket/fuzz/c
CHUNKS=${CHUNKS:-6}; PARALLEL=${PARALLEL:-2}; CHUNK_BATTLES=10; BASE_SEED=100; VCPUS=4
log() { printf '%s\n' "$*" >> "$LOGF"; }
fail() { log "FAILED: $*"; exit 1; }
node() { echo v1; }
run_driver() { # idx seed dir
    mkdir -p "$3/cases/x"
    echo '{}' > "$3/summary.json"; echo '{"node":"v1"}' > "$3/run.json"
    echo "S$1" >> "$EVENTS"; sleep 0.4
    echo "8 0.5" > "$3.time"
    echo "E$1" >> "$EVENTS"
    [ "$1" != "${FAIL_IDX:-none}" ]
}
. "$HERE/chunks.sh"
case ${MODE:-run} in
    run) run_chunks ;;
    partial) mkdir -p "$WORK/out/chunk-0003"; echo "0003 $WORK/out/chunk-0003" > "$WORK/inflight"; upload_partial ;;
esac
"""

    def run_harness(self, mode='run', **env):
        work = os.path.join(self.tmp, 'work')
        events = os.path.join(self.tmp, 'events.txt')
        logf = os.path.join(self.tmp, 'harness.log')
        for path in (events, logf):
            open(path, 'w').close()
        script = os.path.join(self.tmp, 'harness.sh')
        with open(script, 'w', newline=chr(10)) as f:
            f.write(self.HARNESS)
        e = dict(self.env, MODE=mode, **env)
        r = subprocess.run([BASH, posix(script), posix(work), posix(events), posix(logf), posix(HERE)], env=e,
                           capture_output=True, text=True, timeout=120)
        with open(events, encoding='utf-8') as f:
            ev = f.read().split()
        with open(logf, encoding='utf-8') as f:
            log = f.read()
        return r, ev, log, work

    def test_the_scheduler_runs_the_chunks_in_parallel_uploads_each_and_keeps_the_manifest_safe(self):
        os.makedirs(os.path.join(self.tmp, 'work'))
        with open(os.path.join(self.tmp, 'work', 'done.txt'), 'w', newline=chr(10)) as f:
            f.write('0001' + chr(10))  # finished by an earlier box
        r, ev, log, work = self.run_harness()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr + log)
        started = [e[1:] for e in ev if e[0] == 'S']
        self.assertEqual(sorted(started), ['0000', '0002', '0003', '0004', '0005'])  # 0001 is skipped
        self.assertIn('chunk 0001 is in the done-manifest: skipped', log)
        running = peak = 0
        for e in ev:
            running += 1 if e[0] == 'S' else -1
            peak = max(peak, running)
        self.assertEqual(peak, 2)  # PARALLEL, and the chunks do overlap
        with open(os.path.join(work, 'done.txt'), encoding='utf-8') as f:
            self.assertEqual(sorted(f.read().split()), ['0000', '0001', '0002', '0003', '0004', '0005'])
        calls = self.calls()
        # the manifest is written after the upload of the chunk it adds, every time
        uploaded = set()
        manifests = 0
        for c in calls:
            m = re.search(r'chunk-(\d{4})/summary.json', c)
            if m:
                uploaded.add(m.group(1))
            if c.startswith('MANIFEST'):
                manifests += 1
                listed = [x for x in c[len('MANIFEST '):].split(',') if x and x != '0001']
                self.assertTrue(set(listed) <= uploaded, (c, uploaded))
        self.assertEqual(manifests, 5)
        for idx in ('0000', '0002', '0003', '0004', '0005'):
            self.assertTrue(any('chunk-%s/summary.json' % idx in c for c in calls), idx)
            self.assertTrue(any('chunk-%s/cases' % idx in c and '--recursive' in c for c in calls), idx)
        self.assertFalse(any('chunk-0001/' in c for c in calls))
        with open(os.path.join(work, 'inflight'), encoding='utf-8') as f:
            self.assertEqual(f.read().strip(), '')
        self.assertRegex(log, r'chunk 0000: 10 battles in \d+ s \([0-9.]+ battles/s\), 8\.5 CPU-s, \d+% of the 4 vCPUs')

    def test_the_seed_of_a_chunk_is_the_base_seed_plus_its_index(self):
        r, _ev, log, _work = self.run_harness(CHUNKS='3', PARALLEL='1')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr + log)
        for idx, seed in (('0000', 100), ('0001', 101), ('0002', 102)):
            self.assertIn('chunk %s: seed %d, 10 battles, started' % (idx, seed), log)

    def test_a_failing_chunk_fails_the_campaign_and_is_not_in_the_manifest(self):
        r, _ev, log, work = self.run_harness(FAIL_IDX='0002')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('FAILED: chunk 0002', log)
        with open(os.path.join(work, 'done.txt'), encoding='utf-8') as f:
            self.assertNotIn('0002', f.read().split())

    def test_the_partial_results_of_every_chunk_in_flight_are_uploaded(self):
        r, _ev, log, work = self.run_harness(mode='partial')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr + log)
        self.assertTrue(any(c.startswith('s3 sync ') and c.endswith('s3://my-fuzz-bucket/fuzz/c/partial/chunk-0003/ --only-show-errors')
                            for c in self.calls()), self.calls())

    # ------------------------------------------------------------------ the benchmark step
    def fake_bench(self, fail=False):
        path = os.path.join(self.tmp, 'fake_bench.py')
        with open(path, 'w', newline=chr(10)) as f:
            f.write(FAKE_BENCH)
        return shlex.quote(posix(sys.executable)) + ' ' + shlex.quote(posix(path)) + (' --fail' if fail else '')

    def test_bench_run_reports_games_and_decisions_per_second_on_all_vcpus_and_on_16_threads(self):
        import bench_run
        out = os.path.join(self.tmp, 'bench.json')
        self.assertEqual(bench_run.main(['--bench', self.fake_bench(), '--vcpus', '64', '--seconds', '0.3', '--out', out,
                                         '--instance-type', 'c7a.16xlarge', '--campaign', 'weather-sand-snow',
                                         '--commit', SHA]), 0)
        with open(out, encoding='utf-8') as f:
            d = json.load(f)
        self.assertEqual((d['threads'], d['vcpus'], d['instance_type']), (64, 64, 'c7a.16xlarge'))
        self.assertEqual((d['games_per_second'], d['decisions_per_second']), (64000, 64 * 30000))
        self.assertEqual(d['threads_16']['threads'], 16)
        self.assertEqual(d['threads_16']['games_per_second'], 16000)
        self.assertGreaterEqual(len(d['runs']), 1)
        self.assertEqual((d['campaign'], d['commit']), ('weather-sand-snow', SHA))

    def test_bench_run_with_16_or_fewer_vcpus_has_no_comparison_and_a_failing_bench_fails(self):
        import bench_run
        out = os.path.join(self.tmp, 'bench2.json')
        self.assertEqual(bench_run.main(['--bench', self.fake_bench(), '--vcpus', '8', '--seconds', '0.1', '--out', out]), 0)
        with open(out, encoding='utf-8') as f:
            self.assertIsNone(json.load(f)['threads_16'])
        with self.assertRaises(Exception):
            bench_run.main(['--bench', self.fake_bench(fail=True), '--vcpus', '8', '--seconds', '0.1', '--out', out])

    # ------------------------------------------------------------------ the repository
    def test_no_account_id_and_no_access_key_anywhere_in_the_tool(self):
        for base, _dirs, files in os.walk(HERE):
            for name in files:
                if name.endswith(('.pyc',)) or '__pycache__' in base:
                    continue
                with open(os.path.join(base, name), encoding='utf-8', errors='replace') as f:
                    text = f.read()
                with self.subTest(file=name):
                    self.assertIsNone(re.search(r'(?<![0-9A-Za-z])[0-9]{12}(?![0-9A-Za-z])', text), 'a 12-digit number')
                    self.assertIsNone(re.search(r'\b(AKIA|ASIA)[0-9A-Z]{12,}', text), 'an access key id')

    def test_the_campaigns_are_well_formed(self):
        base = os.path.join(HERE, 'campaigns')
        found = sorted(os.listdir(base))
        self.assertTrue({'closure-mirror', 'team-c-mirror', 'weather-sand-snow'} <= set(found))
        for name in found:
            with self.subTest(campaign=name):
                self.assertRegex(name, r'^[a-z0-9][a-z0-9-]{0,39}$')
                keys = {}
                with open(os.path.join(base, name, 'campaign.conf'), encoding='utf-8') as f:
                    for line in f:
                        if line.strip() and not line.startswith('#'):
                            k, _, v = line.rstrip('\n').partition('=')
                            keys[k] = v
                self.assertTrue({'base_seed', 'chunks', 'pairings', 'teams'} <= set(keys), keys)
                self.assertLessEqual(set(keys), {'base_seed', 'chunks', 'pairings', 'teams', 'chunk_battles', 'parallel', 'bench'})
                if 'chunk_battles' in keys:
                    self.assertTrue(100 <= int(keys['chunk_battles']) <= 20000)
                if 'parallel' in keys:
                    self.assertRegex(keys['parallel'], r'^(auto|[0-9]{1,2})$')
                if 'bench' in keys:
                    self.assertIn(keys['bench'], ('0', '1'))
                self.assertRegex(keys['base_seed'], r'^[0-9]{1,12}$')
                self.assertRegex(keys['chunks'], r'^[0-9]{1,3}$')
                self.assertRegex(keys['pairings'], r'^[A-Za-z0-9,-]+$')
                for team in keys['teams'].split():
                    m = re.match(r'^[A-Z]=([A-Za-z0-9._-]+)$', team)
                    if m:
                        self.assertTrue(os.path.isfile(os.path.join(base, name, m.group(1))), team)

    def test_the_readme_policy_is_what_the_task_asks_for(self):
        with open(os.path.join(HERE, 'README.md'), encoding='utf-8') as f:
            readme = f.read()
        blocks = [textwrap.dedent(b) for b in re.findall(r'^[ ]*```json\n(.*?)\n[ ]*```', readme, re.S | re.M)]
        docs = [json.loads(b) for b in blocks]
        self.assertGreaterEqual(len(docs), 3)  # the trust policy, the role's permissions and the user's policy
        policy = next(d for d in docs if any(s.get('Sid') == 'ReadEc2' for s in d['Statement']))
        role = next(d for d in docs if any(s.get('Sid') == 'WriteResults' for s in d['Statement']))
        statements = {s['Sid']: s for s in policy['Statement']}
        self.assertTrue(all(s['Effect'] == 'Allow' for s in statements.values()))
        for sid, s in statements.items():  # every statement is held to the region
            self.assertEqual(s['Condition'].get('StringEquals', {}).get('aws:RequestedRegion'), 'eu-central-1', sid)
        actions = sorted(a for s in statements.values() for a in ([s['Action']] if isinstance(s['Action'], str) else s['Action']))
        self.assertFalse([a for a in actions if a.startswith('iam:') and a != 'iam:PassRole'], actions)
        self.assertEqual(sorted(set(actions)), ['ec2:CreateTags', 'ec2:Describe*', 'ec2:RunInstances', 'ec2:TerminateInstances',
                                                'iam:PassRole', 's3:GetObject', 's3:ListBucket', 'ssm:GetParameter'])
        self.assertTrue(statements['PassRole']['Resource'].endswith(':role/duoforge-fuzz'))
        self.assertEqual(statements['PassRole']['Condition']['StringEquals']['iam:PassedToService'], 'ec2.amazonaws.com')
        self.assertEqual(statements['CreateTagsOnLaunch']['Condition']['StringEquals']['ec2:CreateAction'], 'RunInstances')
        self.assertEqual(statements['Terminate']['Condition']['StringEquals']['aws:ResourceTag/project'], 'duoforge')
        tagged = statements['RunInstancesTagged']
        self.assertEqual(tagged['Condition']['StringEquals']['aws:RequestTag/project'], 'duoforge')
        self.assertEqual(sorted(r.split(':')[-1].split('/')[0] for r in tagged['Resource']),
                         ['instance', 'spot-instances-request', 'volume'])
        plain = statements['RunInstancesSupporting']
        self.assertNotIn('aws:RequestTag/project', plain['Condition']['StringEquals'])
        self.assertEqual(sorted(r.split(':')[-1].split('/')[0] for r in plain['Resource']),
                         ['image', 'network-interface', 'security-group', 'subnet'])
        self.assertIn('arn:aws:ssm:eu-central-1::parameter' + '/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id',
                      statements['ReadAmiParameter']['Resource'])
        self.assertEqual(statements['ListResultsBucket']['Condition']['StringLike']['s3:prefix'], ['fuzz/', 'fuzz/*'])
        for s in role['Statement']:
            self.assertTrue(all(r.endswith('/fuzz/*') or 'prefix' in json.dumps(s.get('Condition', {})) for r in
                                ([s['Resource']] if isinstance(s['Resource'], str) else s['Resource'])), s)

    # ------------------------------------------------------------------ shellcheck
    @unittest.skipIf(shutil.which('shellcheck') is None, 'shellcheck is not installed')
    def test_shellcheck_is_clean(self):
        scripts = [os.path.join(HERE, n) for n in ('lib.sh', 'check.sh', 'launch.sh', 'collect.sh', 'user_data.sh', 'chunks.sh')]
        r = subprocess.run(['shellcheck', '-x', '-S', 'warning', *[posix(s) for s in scripts]], capture_output=True, text=True,
                           cwd=HERE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == '__main__':
    unittest.main()
