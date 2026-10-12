#!/usr/bin/env python3
"""Offline tests of tools/cloud/p1_pilot: the guards of launch.sh and check.sh with a stub `aws` first on the PATH
(nothing here reaches AWS: the stub logs every call and answers from the environment), and the user data run with
stand-ins for shutdown, aws, git, curl and the workload.

 - the identity guard: a caller that is not ':user/pokeengine' is refused before any other call;
 - launch.sh: the instance type allow-list (g6.4xlarge, g5.4xlarge, in that order), --max-hours 1..4, --max-price
   0.10..1.50 and the cost cap hours x price, the commit (40 hex digits, on origin/main, with run.sh at it), the
   security group, one box at a time, the image behind the parameter, no launch without the approval flag;
 - the request: one one-time spot instance with the price ceiling, interruption and shutdown behaviour terminate, the
   instance profile, IMDSv2, the 150 GB gp3 root volume, the tags on instance, volume and spot request, no key pair;
 - the three self-termination mechanisms: the watchdog is the first command of the user data, the exit trap uploads
   and powers off (run for real with stand-ins: success, failure, no run.sh, interruption notice, soft deadline), and
   the request's shutdown and interruption behaviour terminate;
 - no secret, account id or bucket name in the user data or the directory;
 - check.sh: DryRunOperation is a pass, what is missing is reported, the role statement for p1/ is always printed;
 - shellcheck over the scripts when it is installed.
Needs bash on the PATH (Git Bash on Windows)."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BASH = os.environ.get('DUOFORGE_BASH') or shutil.which('bash')
ACCOUNT = '%012d' % 7  # a made-up account id, built here so that no number of that shape is in the repository
SHA = 'b' * 40
SWITCHES = ('MSYS_NO_PATHCONV', 'MSYS2_ARG_CONV_EXCL')
DLAMI_PARAM = '/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-24.04/latest/ami-id'
DLAMI_NAME = 'Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04) 20261006'
RUN_ID_RE = re.compile(r'^[0-9a-f]{12}-[0-9]{8}T[0-9]{6}Z$')

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
    "ec2 describe-subnets") echo subnet-0abc123 ;;
    "ec2 describe-instances")
        if [ "${STUB_DESCRIBE_INSTANCES:-ok}" = deny ]; then echo "An error occurred (UnauthorizedOperation)" >&2; exit 254; fi
        echo "${STUB_ACTIVE:-}" ;;
    "ec2 describe-images")
        case $all in
            *RootDeviceName*) printf '%s%s\n' "${STUB_ROOT_DEV:-/dev/sda1}" "${STUB_CR:-}" ;;
            *BlockDeviceMappings*) printf '%s\t%s%s\n/dev/sdb\tNone%s\n' "${STUB_ROOT_DEV:-/dev/sda1}" "${STUB_ROOT_GB:-75}" \
                "${STUB_CR:-}" "${STUB_CR:-}" ;;
            *"Images[0].Name"*) echo "${STUB_AMI_NAME:-Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04) 20261006}" ;;
        esac ;;
    "ssm get-parameter")
        if [ "${STUB_SSM:-ok}" = deny ]; then
            echo "An error occurred (AccessDeniedException) when calling the GetParameter operation: User: arn:aws:iam::$STUB_ACCOUNT:user/pokeengine is not authorized" >&2; exit 254; fi
        echo "${STUB_AMI:-ami-0abc123}" ;;
    "s3api list-objects-v2")
        if [ "${STUB_S3:-ok}" = deny ]; then echo "An error occurred (AccessDenied) when calling the ListObjectsV2 operation" >&2; exit 254; fi
        echo "${STUB_KEYS:-0}" ;;
    "service-quotas get-service-quota")
        if [ "${STUB_QUOTA:-16}" = deny ]; then echo "An error occurred (AccessDeniedException)" >&2; exit 254; fi
        echo "${STUB_QUOTA:-16.0}" ;;
    "ec2 run-instances")
        case $all in
            *--dry-run*)
                if [ "${STUB_DRYRUN:-pass}" = pass ]; then
                    echo "An error occurred (DryRunOperation) when calling the RunInstances operation: Request would have succeeded, but DryRun flag is set." >&2
                else
                    echo "An error occurred (UnauthorizedOperation) when calling the RunInstances operation: You are not authorized to perform this operation. User: arn:aws:iam::$STUB_ACCOUNT:user/pokeengine is not authorized to perform: ec2:RunInstances on resource: arn:aws:ec2:eu-central-1:$STUB_ACCOUNT:instance/* Encoded authorization failure message: AbC123-xyz_9" >&2
                fi
                exit 254 ;;
            *)
                for t in $(printf '%s' "${STUB_NO_CAPACITY:-}" | tr ',' ' '); do
                    case $all in *"--instance-type $t "*)
                        echo "An error occurred (InsufficientInstanceCapacity) when calling the RunInstances operation" >&2; exit 254 ;; esac
                done
                echo i-0abc123 ;;
        esac ;;
esac
exit 0
'''

# The stand-ins of the user data's run: every command the box would use that is not a shell builtin or coreutils.
BOX_STUBS = {
    'shutdown': 'echo "SHUTDOWN $*" >> "$EVENTS"\n',
    'aws': ('case "$1 $2" in\n'
            '    "s3 sync") echo "AWS s3 sync $3 $4 [$(cd "$3" && ls | sort | tr \'\\n\' \' \')]" >> "$EVENTS" ;;\n'
            '    "s3 cp") echo "AWS s3 cp $3 $4" >> "$EVENTS" ;;\n'
            '    *) echo "AWS $*" >> "$EVENTS" ;;\n'
            'esac\n'),
    'git': ('[ "$1" = -C ] && { dir=$2; shift 2; }\n'
            'case $1 in\n'
            '    checkout) if [ -n "${STUB_RUN_SH:-}" ]; then mkdir -p "$dir/tools/cloud/p1_pilot";'
            ' cp "$STUB_RUN_SH" "$dir/tools/cloud/p1_pilot/run.sh"; fi ;;\n'
            '    rev-parse) echo "$STUB_COMMIT" ;;\n'
            'esac\n'),
    'curl': ('case "$*" in\n'
             '    *api/token*) echo token ;;\n'
             '    *instance-action*) if [ -f "$STUB_SPOT_FLAG" ]; then printf 200; else printf 404; fi ;;\n'
             '    *) exit 22 ;;\n'
             'esac\n'),
    'nvidia-smi': 'echo "GPU 0: NVIDIA L4 (stand-in)"\n',
    'setsid': 'exec "$@"\n',
}

RUN_SH = {
    'success': ('echo "BUCKET=$BUCKET RUN_PREFIX=$RUN_PREFIX RUN_ID=$RUN_ID COMMIT=$COMMIT" > "$OUT_DIR/env.txt"\n'
                'echo result > "$OUT_DIR/result.txt"\nexit 0\n'),
    'failure': 'echo partial > "$OUT_DIR/partial.txt"\necho "the workload fails" >&2\nexit 3\n',
    'interrupt': ('if [ "${1:-}" = --on-interrupt ]; then echo hook > "$OUT_DIR/hook.txt"; exit 0; fi\n'
                  'echo started > "$OUT_DIR/started.txt"\ntouch "$STUB_SPOT_FLAG"\nsleep 60\n'),
    'slow': 'echo started > "$OUT_DIR/started.txt"\nsleep 60\n',
}


def posix(path):
    return path.replace('\\', '/')


def write_exe(path, text):
    with open(path, 'w', newline='\n') as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@unittest.skipIf(BASH is None, 'bash is not on the PATH')
class Guards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='p1_pilot_test_')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.stubdir = os.path.join(self.tmp, 'bin')
        os.mkdir(self.stubdir)
        write_exe(os.path.join(self.stubdir, 'aws'), STUB)
        self.log = os.path.join(self.tmp, 'calls.log')
        open(self.log, 'w').close()
        self.env = dict(os.environ, PATH=self.stubdir + os.pathsep + os.environ['PATH'], STUB_LOG=posix(self.log),
                        STUB_ARN='arn:aws:iam::%s:user/pokeengine' % ACCOUNT, STUB_ACCOUNT=ACCOUNT,
                        DUOFORGE_P1_NO_GIT_CHECK='1', AWS_CONFIG_FILE=posix(os.path.join(self.tmp, 'none')),
                        AWS_SHARED_CREDENTIALS_FILE=posix(os.path.join(self.tmp, 'none')))
        for var in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'DUOFORGE_P1_BUCKET'):
            self.env.pop(var, None)
        # the stub must be what `aws` is, or a test would reach the real thing
        found = subprocess.run([BASH, '-c', 'command -v aws'], env=self.env, capture_output=True, text=True).stdout.strip()
        self.assertTrue(found.replace('\\', '/').lower().endswith('/bin/aws') and 'p1_pilot_test_' in found.lower(), found)

    def run_script(self, script, *args, **env):
        e = dict(self.env, **env)
        return subprocess.run([BASH, posix(os.path.join(HERE, script)), *args], env=e, capture_output=True, text=True,
                              timeout=120)

    def calls(self):
        with open(self.log, encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]

    def real_launches(self):
        return [c for c in self.calls() if ' run-instances ' in (' ' + c + ' ') and '--dry-run' not in c]

    def render(self, minutes=180, commit=SHA, bucket='my-p1-bucket', run_id='b' * 12 + '-20261009T120000Z', pilot='',
               part='', preset=''):
        script = '. "%s/lib.sh"; df_render_user_data %s %s %s %s "%s" "%s" "%s"' % (
            posix(HERE), commit, bucket, minutes, run_id, pilot, part, preset)
        r = subprocess.run([BASH, '-c', script], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    LAUNCH = ('--commit', SHA, '--bucket', 'my-p1-bucket')

    # ------------------------------------------------------------------ the identity guard
    def test_a_caller_that_is_not_pokeengine_is_refused_before_anything_else(self):
        for arn in ('arn:aws:iam::%s:user/someone-else' % ACCOUNT, 'arn:aws:iam::%s:root' % ACCOUNT,
                    'arn:aws:sts::%s:assumed-role/admin/x' % ACCOUNT, 'arn:aws:iam::%s:user/pokeengine2' % ACCOUNT,
                    'arn:aws:iam::%s:user/path/notpokeengine' % ACCOUNT, ''):
            for script, args in (('launch.sh', self.LAUNCH + ('--i-have-owner-approval',)),
                                 ('check.sh', ('--bucket', 'my-p1-bucket'))):
                with self.subTest(arn=arn, script=script):
                    open(self.log, 'w').close()
                    r = self.run_script(script, *args, STUB_ARN=arn)
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    self.assertNotIn(ACCOUNT, r.stdout + r.stderr)  # the account id is masked
                    self.assertEqual(len(self.calls()), 1, self.calls())
                    self.assertIn('sts get-caller-identity', self.calls()[0])
                    if arn:
                        self.assertIn("not a ':user/pokeengine'", r.stderr)

    def test_the_identity_call_comes_first_with_the_region_and_the_default_profile(self):
        env = {k: v for k, v in self.env.items() if k != 'AWS_PROFILE'}
        probe = os.path.join(self.tmp, 'probe')
        os.mkdir(probe)
        write_exe(os.path.join(probe, 'aws'), '#!/usr/bin/env bash\necho "PROFILE=$AWS_PROFILE $*" >> "$STUB_LOG"\n'
                                              'echo arn:aws:iam::%s:user/someone\n' % ACCOUNT)
        env['PATH'] = probe + os.pathsep + env['PATH']
        subprocess.run([BASH, posix(os.path.join(HERE, 'launch.sh')), *self.LAUNCH], env=env, capture_output=True, text=True)
        first = self.calls()[0]
        self.assertTrue(first.startswith('PROFILE=pokeengine --region eu-central-1 sts get-caller-identity'), first)

    # ------------------------------------------------------------------ launch.sh
    def test_without_the_approval_flag_the_request_is_printed_and_nothing_is_launched(self):
        r = self.run_script('launch.sh', *self.LAUNCH)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('nothing was launched', r.stdout)
        self.assertIn('MarketType=spot', r.stdout)
        self.assertIn('<user data>', r.stdout)
        self.assertEqual(self.real_launches(), [])
        self.assertFalse([c for c in self.calls() if ' create-' in c or ' put-' in c or ' delete-' in c])
        self.assertNotIn(ACCOUNT, r.stdout + r.stderr)
        run_id = re.search(r'^run id +(\S+)', r.stdout, re.M).group(1)
        self.assertRegex(run_id, RUN_ID_RE)
        self.assertTrue(run_id.startswith(SHA[:12]))
        self.assertIn('s3://my-p1-bucket/p1/%s/' % run_id, r.stdout)
        self.assertIn('cost cap      $4.50', r.stdout)  # 3 h x $1.50, the defaults

    def test_a_fresh_run_can_take_the_pilot_of_an_earlier_run(self):
        # option A of 2026-10-09: a new run (new run id) whose run.sh reads the pilot artefacts of an earlier run, read
        # only (PILOT_RUN_ID); the earlier run must have finished its generation and distillation
        old = 'aaaaaaaaaaaa-20261009T172944Z'
        r = self.run_script('launch.sh', *self.LAUNCH, '--from-run', old, STUB_KEYS='1')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run_id = re.search(r'^run id +(\S+)', r.stdout, re.M).group(1)
        self.assertNotEqual(run_id, old)
        self.assertIn('pilot from    s3://my-p1-bucket/p1/%s/ (read only)' % old, r.stdout)
        for marker in ('collect-production.done', 'distill.done'):
            self.assertTrue(any('--prefix p1/%s/markers/%s' % (old, marker) in c for c in self.calls()), marker)
        r = self.run_script('launch.sh', *self.LAUNCH, '--from-run', old, STUB_KEYS='0')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('collect-production.done', r.stderr)
        r = self.run_script('launch.sh', *self.LAUNCH, '--from-run', old, '--resume', old, STUB_KEYS='1')
        self.assertNotEqual(r.returncode, 0)
        r = self.run_script('launch.sh', *self.LAUNCH, '--from-run', 'not-a-run')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.real_launches(), [])
        self.assertIn("DF_PILOT_RUN_ID='%s'" % old, self.render(pilot=old))
        self.assertIn("DF_PILOT_RUN_ID=''", self.render())

    def test_a_c2_run_takes_only_the_generation_of_an_earlier_run_and_names_its_distill_preset(self):
        # option C2 of 2026-10-10: the new run reads only the generation of the earlier run (PILOT_PART=generation) and
        # distils again with the preset c2 (DISTILL_PRESET); the earlier run needs its generation, not its distillation
        old = 'aaaaaaaaaaaa-20261009T172944Z'
        c2 = ('--from-run', old, '--pilot-part', 'generation', '--distill-preset', 'c2')
        r = self.run_script('launch.sh', *self.LAUNCH, *c2, STUB_KEYS='1')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('pilot part    generation (run.sh distils again)', r.stdout)
        self.assertIn('distill       c2', r.stdout)
        self.assertTrue(any('--prefix p1/%s/markers/collect-production.done' % old in c for c in self.calls()))
        self.assertFalse(any('markers/distill.done' in c for c in self.calls()))
        for bad, why in ((('--pilot-part', 'generation'), 'needs --from-run'),  # the generation of which run?
                         (('--from-run', old, '--distill-preset', 'c2'), 'needs --pilot-part generation'),
                         (('--from-run', old, '--pilot-part', 'distill', '--distill-preset', 'c2'),
                          'needs --pilot-part generation'),  # the distillation of the earlier run is reused
                         (('--from-run', old, '--pilot-part', 'generation', '--distill-preset', 'big'), 'p1 or c2'),
                         (('--from-run', old, '--pilot-part', 'all'), 'distill or generation'),
                         (('--from-run', old, '--pilot-part', 'generation', '--distill-preset', 'c2', '--resume', old),
                          'exclude each other'),
                         (('--resume', old, '--pilot-part', 'generation'), 'needs --from-run'),
                         (('--pilot-part',), 'needs a value')):
            r = self.run_script('launch.sh', *self.LAUNCH, *bad, STUB_KEYS='1')
            self.assertEqual(r.returncode, 2, bad)
            self.assertIn(why, r.stderr, bad)
        self.assertEqual(self.real_launches(), [])
        text = self.render(pilot=old, part='generation', preset='c2')
        self.assertIn("DF_PILOT_PART='generation'", text)
        self.assertIn("DF_DISTILL_PRESET='c2'", text)
        text = self.render(pilot=old)
        self.assertIn("DF_PILOT_PART=''", text)
        self.assertIn("DF_DISTILL_PRESET=''", text)

    def test_a_resume_keeps_the_run_id_of_an_existing_run(self):
        # run.sh resumes from the markers under p1/<run id>/ (EXIT 33 of the first AWS pilot, 2026-10-09): a resume keeps
        # that run id (the commit may be newer); a malformed id or a run without markers is refused before anything else
        old = 'aaaaaaaaaaaa-20261009T172944Z'
        r = self.run_script('launch.sh', *self.LAUNCH, '--resume', old, STUB_KEYS='1')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(re.search(r'^run id +(\S+)', r.stdout, re.M).group(1), old)
        self.assertIn('s3://my-p1-bucket/p1/%s/' % old, r.stdout)
        self.assertTrue(any('list-objects-v2' in c and '--prefix p1/%s/markers/' % old in c for c in self.calls()))
        r = self.run_script('launch.sh', *self.LAUNCH, '--resume', old, STUB_KEYS='0')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('no markers', r.stderr)
        r = self.run_script('launch.sh', *self.LAUNCH, '--resume', 'inputs')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.real_launches(), [])

    def test_with_the_flag_one_spot_instance_of_the_required_shape_is_requested(self):
        r = self.run_script('launch.sh', *self.LAUNCH, '--i-have-owner-approval')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('launched i-0abc123 (g6.4xlarge', r.stdout)
        runs = self.real_launches()
        self.assertEqual(len(runs), 1)
        call = runs[0]
        for needle in ('--count 1 ', '--instance-type g6.4xlarge ', '--image-id ami-0abc123 ',
                       'MarketType=spot,SpotOptions={SpotInstanceType=one-time,MaxPrice=1.50,InstanceInterruptionBehavior=terminate}',
                       '--instance-initiated-shutdown-behavior terminate', '--iam-instance-profile Name=duoforge-fuzz',
                       '--security-group-ids sg-0abc123', 'HttpTokens=required,HttpEndpoint=enabled,HttpPutResponseHopLimit=1',
                       'DeviceName=/dev/sda1,Ebs={VolumeSize=150,VolumeType=gp3,DeleteOnTermination=true}',
                       'ResourceType=instance,Tags=', 'ResourceType=volume,Tags=', 'ResourceType=spot-instances-request,Tags='):
            self.assertIn(needle, call)
        self.assertEqual(call.count('Key=project,Value=duoforge'), 3)
        self.assertEqual(call.count('Key=purpose,Value=p1-pilot'), 3)
        self.assertEqual(len(re.findall(r'Key=run-id,Value=b{12}-[0-9]{8}T[0-9]{6}Z', call)), 3)
        for absent in ('--key-name', '--associate', 'MarketType=on-demand', 'persistent', '--count 2'):
            self.assertNotIn(absent, call)

    def test_the_types_are_tried_in_order_and_only_one_instance_is_ever_launched(self):
        r = self.run_script('launch.sh', *self.LAUNCH, '--i-have-owner-approval', STUB_NO_CAPACITY='g6.4xlarge')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('launched i-0abc123 (g5.4xlarge', r.stdout)
        runs = self.real_launches()
        self.assertEqual([re.search(r'--instance-type (\S+)', c).group(1) for c in runs], ['g6.4xlarge', 'g5.4xlarge'])
        open(self.log, 'w').close()
        r = self.run_script('launch.sh', *self.LAUNCH, '--i-have-owner-approval', STUB_NO_CAPACITY='g6.4xlarge,g5.4xlarge')
        self.assertEqual(r.returncode, 2)
        self.assertIn('no candidate type could be launched', r.stderr)

    def test_only_the_allow_listed_types(self):
        for types in ('g6.8xlarge', 'g6.12xlarge', 'p5.48xlarge', 'c7a.16xlarge', 'g6.4xlarge,g6.12xlarge', '', 'G6.4XLARGE'):
            with self.subTest(types=types):
                open(self.log, 'w').close()
                r = self.run_script('launch.sh', *self.LAUNCH, '--types', types, '--i-have-owner-approval')
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(self.real_launches(), [])
                r = self.run_script('check.sh', '--bucket', 'my-p1-bucket', '--types', types)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        r = self.run_script('launch.sh', *self.LAUNCH, '--types', 'g5.4xlarge', '--i-have-owner-approval')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('--instance-type g5.4xlarge ', self.real_launches()[0])

    def test_max_hours_is_a_whole_number_from_one_to_four(self):
        for hours in ('0', '5', '24', '-1', '2.5', 'three', '', '04x'):
            with self.subTest(hours=hours):
                open(self.log, 'w').close()
                r = self.run_script('launch.sh', *self.LAUNCH, '--max-hours', hours, '--i-have-owner-approval')
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn('--max-hours', r.stderr)
                self.assertEqual(self.real_launches(), [])
        for hours in (1, 2, 3, 4):
            r = self.run_script('launch.sh', *self.LAUNCH, '--max-hours', str(hours))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('shutdown -h +%d' % (60 * hours), r.stdout)

    def test_the_price_ceiling_is_bounded_and_the_cost_cap_is_hours_times_price(self):
        for price in ('1.51', '2', '10', '0.09', '0', '-1', 'abc', '1.555', '', '1,50', '.5'):
            with self.subTest(price=price):
                open(self.log, 'w').close()
                r = self.run_script('launch.sh', *self.LAUNCH, '--max-price', price, '--i-have-owner-approval')
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn('--max-price', r.stderr)
                self.assertEqual(self.real_launches(), [])
        for hours, price, ceiling, cap in (('4', '1.5', '1.50', '6.00'), ('1', '0.10', '0.10', '0.10'),
                                           ('3', '0.8', '0.80', '2.40'), ('2', '1', '1.00', '2.00')):
            with self.subTest(hours=hours, price=price):
                open(self.log, 'w').close()
                r = self.run_script('launch.sh', *self.LAUNCH, '--max-hours', hours, '--max-price', price,
                                    '--i-have-owner-approval')
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn('cost cap      $%s' % cap, r.stdout)
                self.assertIn('MaxPrice=%s,' % ceiling, self.real_launches()[0])

    def test_bad_values_are_refused(self):
        base = dict(zip(self.LAUNCH[::2], self.LAUNCH[1::2]))
        for flag, value in (('--commit', 'main'), ('--commit', 'b' * 39), ('--commit', 'B' * 40), ('--commit', ''),
                            ('--commit', SHA + 'b'), ('--commit', 'b' * 39 + ';'), ('--bucket', 'UPPER'),
                            ('--bucket', ''), ('--bucket', 'a|b-bucket'), ('--bucket', 'x' * 64)):
            with self.subTest(flag=flag, value=value):
                args = dict(base)
                args[flag] = value
                flat = [x for kv in args.items() for x in kv]
                open(self.log, 'w').close()
                r = self.run_script('launch.sh', *flat, '--i-have-owner-approval')
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(self.real_launches(), [])
        self.assertEqual(self.run_script('launch.sh', '--nope').returncode, 2)
        self.assertEqual(self.run_script('launch.sh', '--commit').returncode, 2)

    def test_any_group_but_duoforge_fuzz_is_refused(self):
        r = self.run_script('launch.sh', *self.LAUNCH, '--sg-name', 'default', '--i-have-owner-approval')
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

    def test_a_pilot_box_that_still_exists_blocks_a_second_one(self):
        for env, text in (({'STUB_ACTIVE': 'i-0running1'}, 'a pilot box still exists (i-0running1'),
                          ({'STUB_DESCRIBE_INSTANCES': 'deny'}, 'cannot tell whether a pilot box is still up')):
            with self.subTest(env=env):
                open(self.log, 'w').close()
                r = self.run_script('launch.sh', *self.LAUNCH, '--i-have-owner-approval', **env)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn(text, r.stderr)
                self.assertEqual(self.real_launches(), [])
        lookups = [c for c in self.calls() if 'describe-instances' in c]
        self.assertTrue(lookups and 'Name=tag:purpose,Values=p1-pilot' in lookups[0], lookups)

    def test_the_image_must_be_the_dlami_and_its_root_device_gets_the_volume(self):
        for env, text in (({'STUB_AMI_NAME': 'ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-20261001'},
                           'not a \'Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04)\''),
                          ({'STUB_ROOT_GB': '200'}, 'more than the 150 GB volume'),
                          ({'STUB_ROOT_DEV': 'None'}, 'no readable root device name'),
                          ({'STUB_AMI': 'not-an-ami'}, 'not an AMI id')):
            with self.subTest(env=env):
                open(self.log, 'w').close()
                r = self.run_script('launch.sh', *self.LAUNCH, '--i-have-owner-approval', **env)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn(text, r.stderr)
                self.assertEqual(self.real_launches(), [])
        open(self.log, 'w').close()
        r = self.run_script('launch.sh', *self.LAUNCH, '--i-have-owner-approval', STUB_ROOT_DEV='/dev/xvda')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('DeviceName=/dev/xvda,Ebs={VolumeSize=150,', self.real_launches()[0])
        self.assertTrue(any(DLAMI_PARAM in c for c in self.calls() if 'ssm get-parameter' in c))

    # ------------------------------------------------------------------ the commit and run.sh
    def test_the_commit_must_be_checked_against_origin_main_unless_that_is_switched_off_explicitly(self):
        r = self.run_script('launch.sh', *self.LAUNCH, DUOFORGE_P1_NO_GIT_CHECK='')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('commit ' + SHA, r.stderr)
        self.assertEqual(self.real_launches(), [])

    def fresh_repo(self):
        """A repository of its own in the temporary directory: the tool in it (without run.sh), one commit, then a
        second commit that adds run.sh, and a third one off main. What runs git on the tool's directory runs it here,
        never in the checkout the tests happen to be in. Returns (the tool's directory, the sha without run.sh, the sha
        with run.sh, the sha off main)."""
        repo = os.path.join(self.tmp, 'repo')
        tool = os.path.join(repo, 'tools', 'cloud', 'p1_pilot')
        shutil.copytree(HERE, tool, ignore=shutil.ignore_patterns('__pycache__', 'run.sh'))
        git = ['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid']

        def commit(msg):
            subprocess.run(git + ['add', '-A'], check=True, capture_output=True)
            subprocess.run(git + ['commit', '-q', '-m', msg], check=True, capture_output=True)
            return subprocess.run(git + ['rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()

        subprocess.run(git + ['init', '-q'], check=True, capture_output=True)
        without = commit('without run.sh')
        with open(os.path.join(tool, 'run.sh'), 'w', newline='\n') as f:
            f.write('#!/bin/bash\nexit 0\n')
        with_run = commit('with run.sh')
        subprocess.run(git + ['update-ref', 'refs/remotes/origin/main', with_run], check=True)
        with open(os.path.join(tool, 'extra.txt'), 'w') as f:
            f.write('x\n')
        off_main = commit('not on main')
        return tool, without, with_run, off_main

    def test_the_commit_must_be_on_origin_main_and_have_run_sh(self):
        tool, without, with_run, off_main = self.fresh_repo()
        env = dict(self.env, DUOFORGE_P1_NO_GIT_CHECK='')

        def launch(sha):
            open(self.log, 'w').close()
            return subprocess.run([BASH, posix(os.path.join(tool, 'launch.sh')), '--commit', sha, '--bucket', 'my-p1-bucket',
                                   '--i-have-owner-approval'], env=env, capture_output=True, text=True, timeout=120)

        r = launch(without)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('has no tools/cloud/p1_pilot/run.sh', r.stderr)
        self.assertEqual(self.real_launches(), [])
        r = launch(off_main)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('is not on origin/main', r.stderr)
        self.assertEqual(self.real_launches(), [])
        r = launch('c' * 40)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('is not in this repository', r.stderr)
        r = launch(with_run)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('fatal', r.stderr)
        self.assertEqual(len(self.real_launches()), 1)

    def test_the_c2_options_need_a_run_sh_that_reads_them(self):
        # a run.sh from before #321 ignores PILOT_PART and DISTILL_PRESET: the box would rerun the whole earlier pilot
        # with the p1 settings under a C2 label, so the launcher refuses such a commit
        tool, _, with_run, _ = self.fresh_repo()
        env = dict(self.env, DUOFORGE_P1_NO_GIT_CHECK='', STUB_KEYS='1')
        old = 'aaaaaaaaaaaa-20261009T172944Z'

        def launch(sha):
            open(self.log, 'w').close()
            return subprocess.run([BASH, posix(os.path.join(tool, 'launch.sh')), '--commit', sha, '--bucket', 'my-p1-bucket',
                                   '--from-run', old, '--pilot-part', 'generation', '--distill-preset', 'c2',
                                   '--i-have-owner-approval'], env=env, capture_output=True, text=True, timeout=120)

        r = launch(with_run)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('does not read PILOT_PART and DISTILL_PRESET', r.stderr)
        self.assertEqual(self.real_launches(), [])
        repo = os.path.dirname(os.path.dirname(os.path.dirname(tool)))
        git = ['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid']
        with open(os.path.join(tool, 'run.sh'), 'w', newline='\n') as f:
            f.write('#!/bin/bash\nPILOT_PART=${PILOT_PART:-distill}\nDISTILL_PRESET=${DISTILL_PRESET:-p1}\n')
        subprocess.run(git + ['commit', '-q', '-am', 'run.sh reads the C2 values'], check=True, capture_output=True)
        reads = subprocess.run(git + ['rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()
        subprocess.run(git + ['update-ref', 'refs/remotes/origin/main', reads], check=True)
        r = launch(reads)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.real_launches()), 1)

    def test_lib_does_not_export_the_path_conversion_switches(self):
        probe_dir = os.path.join(self.tmp, 'probe')
        os.mkdir(probe_dir)
        write_exe(os.path.join(probe_dir, 'aws'), '#!/usr/bin/env bash\n'
                  'echo "PATHCONV=${MSYS_NO_PATHCONV:-unset} EXCL=${MSYS2_ARG_CONV_EXCL:-unset}"\n')
        env = dict(self.env, PATH=probe_dir + os.pathsep + self.env['PATH'])
        env = {k: v for k, v in env.items() if k not in SWITCHES}
        script = '. "%s/lib.sh"; df_init; df_aws x; echo "after: ${MSYS_NO_PATHCONV:-unset}"' % posix(HERE)
        r = subprocess.run([BASH, '-c', script], env=env, capture_output=True, text=True)
        self.assertEqual(r.stdout.splitlines()[:2], ['PATHCONV=1 EXCL=*', 'after: unset'], r.stdout + r.stderr)

    # ------------------------------------------------------------------ the three self-termination mechanisms
    def test_the_three_self_termination_mechanisms_are_in_the_request_and_the_user_data(self):
        # (1) the hard wall cap is the first command of the user data, with the launch's max-hours
        for hours in (1, 3, 4):
            r = self.run_script('launch.sh', *self.LAUNCH, '--max-hours', str(hours), '--i-have-owner-approval')
            self.assertEqual(r.returncode, 0, r.stderr)
            call = self.real_launches()[-1]
            text = self.render(minutes=60 * hours)
            lines = text.split('\n')
            self.assertEqual(lines[0], '#!/bin/bash')
            self.assertEqual(lines[1], 'shutdown -h +%d "duoforge p1 watchdog: at most %d minutes"' % (60 * hours, 60 * hours))
            # (3) shutdown behaviour terminate, one-time spot, interruption behaviour terminate
            self.assertIn('--instance-initiated-shutdown-behavior terminate', call)
            self.assertIn('SpotInstanceType=one-time', call)
            self.assertIn('InstanceInterruptionBehavior=terminate', call)
        # (2) every way out of the script goes through the exit trap, which uploads and powers off
        self.assertIn('\ntrap finish EXIT\n', text)
        self.assertIn("\ntrap 'exit 143' TERM INT", text)
        finish = re.search(r'\nfinish\(\) \{\n(.*?)\n\}\n', text, re.S).group(1)
        steps = [s.strip() for s in finish.split('\n')]
        self.assertEqual(steps[-3:], ['sync_out', 'sync_log', 'shutdown -h now'])
        self.assertIn('/out/', re.search(r'\nsync_out\(\) \{\n(.*?)\n\}\n', text, re.S).group(1).replace('"${S3_BASE}out/"', '/out/'))
        # the check script's dry runs carry the same three
        r = self.run_script('check.sh', '--bucket', 'my-p1-bucket')
        for c in [c for c in self.calls() if '--dry-run' in c]:
            self.assertIn('--instance-initiated-shutdown-behavior terminate', c)
            self.assertIn('SpotInstanceType=one-time', c)
            self.assertIn('InstanceInterruptionBehavior=terminate', c)

    def test_the_rendered_user_data_has_no_placeholder_no_secret_and_fits(self):
        text = self.render()
        self.assertIsNone(re.search(r'@[A-Z_]+@', text))
        self.assertIn("DF_COMMIT='%s'" % SHA, text)
        self.assertIn("DF_BUCKET='my-p1-bucket'", text)
        self.assertIn('RUN_PREFIX="p1/$DF_RUN_ID/"', text)
        for secret in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'aws configure', 'AKIA', 'ASIA',
                       'BEGIN RSA', 'PRIVATE KEY', 'password', 'arn:aws:iam::'):
            self.assertNotIn(secret, text)
        self.assertIsNone(re.search(r'(?<![0-9])[0-9]{12}(?![0-9])', text))
        self.assertEqual(text.count('my-p1-bucket'), 1)  # the bucket is only the one value the launch gave
        self.assertIn('https://github.com/chrismaghuhn/duoforge.git', text)  # the public repository, no token
        self.assertLess(len(text.encode()), 16000)  # the limit of EC2 user data is 16 KB
        with open(os.path.join(HERE, 'user_data.sh'), encoding='utf-8') as f:
            raw = f.read()
        self.assertEqual(sorted(set(re.findall(r'@[A-Z_]+@', raw))),
                         ['@BUCKET@', '@COMMIT@', '@DISTILL_PRESET@', '@MAX_MINUTES@', '@PILOT_PART@',
                          '@PILOT_RUN_ID@', '@RUN_ID@'])

    # ------------------------------------------------------------------ the user data, run with stand-ins
    def run_box(self, workload, soft_deadline_seconds=30, minutes=180):
        """Runs the rendered user data with stand-ins for shutdown, aws, git, curl, nvidia-smi and setsid, its paths
        moved into the temporary directory and its intervals shortened. Returns (exit status, events, log, seconds).
        Not on Windows: there `shutdown -h` is the system's own command (hibernate), and a stand-in that is not found
        first would put the developer's machine to sleep. The Linux jobs run these tests (no root: a real shutdown
        fails there)."""
        if os.name == 'nt':
            self.skipTest("the user data's run powers off: never on a Windows developer machine")
        box = os.path.join(self.tmp, 'box')
        os.makedirs(os.path.join(box, 'bin'))
        for name, body in BOX_STUBS.items():
            write_exe(os.path.join(box, 'bin', name), '#!/usr/bin/env bash\n' + body)
        events = os.path.join(box, 'events.txt')
        open(events, 'w').close()
        text = self.render(minutes=minutes)
        for old, new in (('WORK=/opt/duoforge-p1\n', 'WORK=%s\n' % posix(os.path.join(box, 'work'))),
                         ('LOG=/var/log/duoforge-p1.log\n', 'LOG=%s\n' % posix(os.path.join(box, 'box.log'))),
                         ('DF_LOG_EVERY=60 ', 'DF_LOG_EVERY=1 '), ('DF_POLL_EVERY=5 ', 'DF_POLL_EVERY=1 '),
                         ('DF_SOFT_DEADLINE_SECONDS=$(((DF_MAX_MINUTES - DF_SOFT_MARGIN_MINUTES) * 60))\n',
                          'DF_SOFT_DEADLINE_SECONDS=%d\n' % soft_deadline_seconds)):
            self.assertEqual(text.count(old), 1, old)
            text = text.replace(old, new)
        script = os.path.join(box, 'user-data')
        with open(script, 'w', newline='\n') as f:
            f.write(text)
        env = dict(self.env, PATH=os.path.join(box, 'bin') + os.pathsep + self.env['PATH'], EVENTS=posix(events),
                   STUB_COMMIT=SHA, STUB_SPOT_FLAG=posix(os.path.join(box, 'spot-notice')))
        if workload is not None:
            run_sh = os.path.join(box, 'run.sh')
            with open(run_sh, 'w', newline='\n') as f:
                f.write('#!/bin/bash\n' + RUN_SH[workload])
            env['STUB_RUN_SH'] = posix(run_sh)
        # Git for Windows' bin/bash.exe (what CTest finds) puts /mingw64/bin and /usr/bin in front of the PATH it is
        # given, and the real git, curl or (on Windows, in System32) shutdown must never run here: the stand-ins are
        # put first inside bash, every one is checked to resolve to them, and only then is the user data started.
        start_sh = os.path.join(box, 'start.sh')
        with open(start_sh, 'w', newline='\n') as f:
            f.write('#!/bin/bash\n'
                    'BIN=$(cd "$(dirname "$0")/bin" && pwd) || exit 97\n'
                    'export PATH="$BIN:$PATH"\n'
                    'for c in %s; do\n'
                    '    p=$(command -v "$c") || { echo "STAND-IN MISSING: $c"; exit 97; }\n'
                    '    [ "$p" = "$BIN/$c" ] || { echo "STAND-IN NOT FIRST: $c is $p"; exit 97; }\n'
                    'done\n'
                    'exec bash "$1"\n' % ' '.join(sorted(BOX_STUBS)))
        start = time.monotonic()
        # the output goes to a file: a background sleep that outlives the script must not hold a pipe of this test
        stdout = os.path.join(box, 'stdout.txt')
        with open(stdout, 'w') as out:
            r = subprocess.run([BASH, posix(start_sh), posix(script)], env=env, stdout=out, stderr=subprocess.STDOUT,
                               timeout=120)
        seconds = time.monotonic() - start
        if r.returncode == 97:
            with open(stdout, encoding='utf-8') as f:
                self.fail('the stand-ins are not what the user data would run: ' + f.read())
        with open(events, encoding='utf-8') as f:
            ev = [line.rstrip('\n') for line in f if line.strip()]
        with open(os.path.join(box, 'box.log'), encoding='utf-8') as f:
            log = f.read()
        return r.returncode, ev, log, seconds

    def assert_ends_with_upload_and_power_off(self, ev, out_files):
        self.assertTrue(ev[0].startswith('SHUTDOWN -h +180 '), ev)  # (1) the watchdog came first
        self.assertEqual(ev[-1], 'SHUTDOWN -h now', ev)            # (2) and the end powers off
        self.assertEqual(sum(1 for e in ev if e == 'SHUTDOWN -h now'), 1, ev)
        syncs = [e for e in ev if e.startswith('AWS s3 sync ')]
        self.assertTrue(syncs, ev)
        last_sync = syncs[-1]
        self.assertRegex(last_sync, r' s3://my-p1-bucket/p1/b{12}-20261009T120000Z/out/ ')
        for name in out_files:
            self.assertIn(name, last_sync)
        logs = [i for i, e in enumerate(ev) if e.startswith('AWS s3 cp ') and '/p1/b' in e and '/log/' in e]
        self.assertTrue(logs, ev)
        self.assertLess(ev.index(last_sync), len(ev) - 1)
        self.assertLess(logs[-1], len(ev) - 1)
        for e in ev:  # nothing is ever written outside p1/<run id>/
            if e.startswith('AWS s3 '):
                self.assertIn(' s3://my-p1-bucket/p1/b' + 'b' * 11 + '-20261009T120000Z/', e)

    def test_the_box_runs_the_workload_with_its_environment_then_uploads_and_powers_off(self):
        rc, ev, log, _ = self.run_box('success')
        self.assertEqual(rc, 0, log)
        self.assert_ends_with_upload_and_power_off(ev, ('result.txt', 'env.txt', 'launcher.json'))
        with open(os.path.join(self.tmp, 'box', 'work', 'out', 'env.txt'), encoding='utf-8') as f:
            self.assertEqual(f.read().strip(), 'BUCKET=my-p1-bucket RUN_PREFIX=p1/%s/ RUN_ID=%s COMMIT=%s' % (
                'b' * 12 + '-20261009T120000Z', 'b' * 12 + '-20261009T120000Z', SHA))
        self.assertIn('run.sh exited with status 0', log)
        self.assertIn('interruption hook: no', log)

    def test_a_failing_workload_still_uploads_what_exists_and_powers_off(self):
        rc, ev, log, _ = self.run_box('failure')
        self.assertEqual(rc, 3, log)
        self.assert_ends_with_upload_and_power_off(ev, ('partial.txt',))
        self.assertIn('run.sh exited with status 3', log)
        self.assertIn('the workload fails', log)

    def test_a_commit_without_run_sh_fails_on_the_box_and_still_powers_off(self):
        rc, ev, log, _ = self.run_box(None)
        self.assertEqual(rc, 1, log)
        self.assertIn('has no tools/cloud/p1_pilot/run.sh', log)
        self.assert_ends_with_upload_and_power_off(ev, ())

    def test_a_spot_interruption_notice_runs_the_hook_then_uploads_and_powers_off(self):
        rc, ev, log, seconds = self.run_box('interrupt')
        self.assertEqual(rc, 143, log)
        self.assertIn('interruption hook: yes', log)
        self.assertIn('spot interruption notice', log)
        self.assertIn('running run.sh --on-interrupt', log)
        self.assert_ends_with_upload_and_power_off(ev, ('hook.txt', 'started.txt'))
        self.assertLess(seconds, 50)  # the workload's sleep 60 was cut short

    def test_the_soft_deadline_stops_the_workload_before_the_wall_cap(self):
        rc, ev, log, seconds = self.run_box('slow', soft_deadline_seconds=3)
        self.assertEqual(rc, 143, log)
        self.assertIn('soft deadline: 5 minutes before the wall cap of 180 minutes', log)
        self.assertIn('interruption hook: no', log)
        self.assert_ends_with_upload_and_power_off(ev, ('started.txt',))
        self.assertLess(seconds, 50)

    # ------------------------------------------------------------------ check.sh
    def test_check_reports_a_pass_and_always_prints_the_role_statement(self):
        r = self.run_script('check.sh', '--bucket', 'my-p1-bucket')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('nothing is missing', r.stdout)
        for t in ('g6.4xlarge', 'g5.4xlarge'):
            self.assertIn('run-instances --dry-run %s' % t, r.stdout)
        dry = [c for c in self.calls() if ' run-instances ' in (' ' + c + ' ')]
        self.assertEqual(len(dry), 2)
        self.assertTrue(all('--dry-run' in c for c in dry))
        self.assertEqual(self.real_launches(), [])
        for c in dry:
            self.assertEqual(c.count('Key=purpose,Value=p1-pilot'), 3)
            self.assertEqual(c.count('Key=project,Value=duoforge'), 3)
            self.assertIn('VolumeSize=150,VolumeType=gp3', c)
            self.assertIn('MaxPrice=1.50', c)
            self.assertIn('Name=duoforge-fuzz', c)
        self.assertTrue(any('list-objects-v2' in c and '--prefix p1/' in c for c in self.calls()))
        self.assertTrue(any('ssm get-parameter' in c and DLAMI_PARAM in c for c in self.calls()))
        self.assertIn('UNVERIFIED', r.stdout)
        self.assertIn('"Resource": "arn:aws:s3:::<BUCKET>/p1/*"', r.stdout)
        self.assertIn('"s3:prefix": ["p1/", "p1/*"]', r.stdout)
        self.assertNotIn(ACCOUNT, r.stdout + r.stderr)
        self.assertFalse([c for c in self.calls() if ' create-' in c or ' put-' in c or ' delete-' in c or 'iam ' in c])

    def test_the_windows_cli_s_carriage_returns_are_no_part_of_a_value(self):
        # aws.exe on Windows ends its text output with CRLF: the root device size read as "75\r" was "no EBS size"
        # (check.sh on the owner's machine, 2026-10-09)
        r = self.run_script('check.sh', '--bucket', 'my-p1-bucket', STUB_CR='\r')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('no EBS size', r.stdout)
        self.assertIn('nothing is missing', r.stdout)

    def test_check_reports_what_is_missing_and_what_the_user_policy_lacks(self):
        r = self.run_script('check.sh', '--bucket', 'my-p1-bucket', STUB_DRYRUN='unauth', STUB_S3='deny', STUB_SSM='deny',
                            STUB_SG_INBOUND='2', STUB_DECODE='ok', STUB_ACTIVE='i-0still', STUB_QUOTA='8')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        for text in ('2 inbound rule(s)', 'listing the prefix p1/ failed', 'ssm get-parameter %s failed' % DLAMI_PARAM,
                     'run-instances --dry-run g6.4xlarge: UnauthorizedOperation', 'ec2:RunInstances on instance',
                     'a pilot box still exists: i-0still', 'spot quota L-3819A6DF (All G and VT Spot Instance Requests): 8 vCPUs',
                     'ssm:GetParameter on arn:aws:ssm:eu-central-1::parameter' + DLAMI_PARAM,
                     's3:GetObject on arn:aws:s3:::<BUCKET>/p1/*', 'UNVERIFIED'):
            self.assertIn(text, r.stdout)
        self.assertNotIn(ACCOUNT, r.stdout + r.stderr)
        self.assertEqual(self.real_launches(), [])

    def test_check_takes_an_unreadable_quota_as_a_note_and_needs_a_bucket(self):
        r = self.run_script('check.sh', '--bucket', 'my-p1-bucket', STUB_QUOTA='deny')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('NOTE     the spot quota L-3819A6DF could not be read', r.stdout)
        r = self.run_script('check.sh')
        self.assertEqual(r.returncode, 1)
        self.assertIn('no bucket given', r.stdout)

    # ------------------------------------------------------------------ the repository
    def test_no_account_id_no_access_key_and_no_bucket_name_anywhere_in_the_tool(self):
        for base, _dirs, files in os.walk(HERE):
            if '__pycache__' in base:
                continue
            for name in files:
                with open(os.path.join(base, name), encoding='utf-8', errors='replace') as f:
                    text = f.read()
                with self.subTest(file=name):
                    self.assertIsNone(re.search(r'(?<![0-9A-Za-z])[0-9]{12}(?![0-9A-Za-z])', text), 'a 12-digit number')
                    self.assertIsNone(re.search(r'\b(AKIA|ASIA)[0-9A-Z]{12,}', text), 'an access key id')
                    for bucket in re.findall(r's3://([^/\s"\'`)]+)', text):
                        if name == 'test_guards.py' and bucket in ('my-p1-bucket', '([^'):
                            continue  # the made-up bucket of these tests, and this scan's own pattern
                        self.assertTrue(bucket.startswith(('<', '$')), bucket)
                    for arn_bucket in re.findall(r'arn:aws:s3:::([^/\s"\'`]+)', text):
                        if name == 'test_guards.py' and arn_bucket == '([^':
                            continue
                        self.assertTrue(arn_bucket.startswith('<'), arn_bucket)

    def test_the_readme_has_the_role_statement_of_check_sh_and_the_users_additions(self):
        with open(os.path.join(HERE, 'README.md'), encoding='utf-8') as f:
            readme = f.read()
        blocks = re.findall(r'^[ ]*```json\n(.*?)\n[ ]*```', readme, re.S | re.M)
        docs = [json.loads(textwrap.dedent(b)) for b in blocks]
        self.assertEqual(len(docs), 2)  # the role's statements and the user's additions
        r = subprocess.run([BASH, '-c', '. "%s/lib.sh"; df_role_statement' % posix(HERE)], env=self.env,
                           capture_output=True, text=True)
        printed = json.loads('[' + r.stdout + ']')
        role = next(d for d in docs if any(s.get('Sid') == 'P1PilotResults' for s in d['Statement']))
        self.assertEqual(role['Statement'], printed)
        for s in printed:
            resources = [s['Resource']] if isinstance(s['Resource'], str) else s['Resource']
            for res in resources:
                self.assertTrue(res.endswith('/p1/*') or 'p1/' in json.dumps(s.get('Condition', {})), s)
        user = next(d for d in docs if any(s.get('Sid') == 'ReadDlamiParameter' for s in d['Statement']))
        statements = {s['Sid']: s for s in user['Statement']}
        for sid, s in statements.items():
            self.assertEqual(s['Effect'], 'Allow')
            self.assertEqual(s['Condition']['StringEquals']['aws:RequestedRegion'], 'eu-central-1', sid)
        self.assertEqual(statements['ReadDlamiParameter']['Resource'],
                         'arn:aws:ssm:eu-central-1::parameter' + DLAMI_PARAM)
        self.assertEqual(statements['ListP1Results']['Condition']['StringLike']['s3:prefix'], ['p1/', 'p1/*'])
        self.assertEqual(statements['ReadP1Results']['Resource'], 'arn:aws:s3:::<BUCKET>/p1/*')
        actions = sorted({a for s in statements.values() for a in ([s['Action']] if isinstance(s['Action'], str) else s['Action'])})
        self.assertEqual(actions, ['s3:GetObject', 's3:ListBucket', 'servicequotas:GetServiceQuota', 'ssm:GetParameter'])
        self.assertIn(DLAMI_PARAM, readme)
        with open(os.path.join(HERE, 'lib.sh'), encoding='utf-8') as f:
            self.assertIn('DF_AMI_PARAM=' + DLAMI_PARAM + '\n', f.read())

    # ------------------------------------------------------------------ shellcheck
    @unittest.skipIf(shutil.which('shellcheck') is None, 'shellcheck is not installed')
    def test_shellcheck_is_clean(self):
        scripts = [os.path.join(HERE, n) for n in ('lib.sh', 'check.sh', 'launch.sh', 'user_data.sh')]
        r = subprocess.run(['shellcheck', '-x', '-S', 'warning', *[posix(s) for s in scripts]], capture_output=True, text=True,
                           cwd=HERE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == '__main__':
    unittest.main()
