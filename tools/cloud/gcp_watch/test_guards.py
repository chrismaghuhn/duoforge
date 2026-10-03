#!/usr/bin/env python3
"""Offline tests of tools/cloud/gcp_watch: the guards of create.sh, start.sh, stop.sh and delete.sh with a stub `gcloud`
first on the PATH (nothing here reaches Google Cloud: the stub logs every call and answers from the environment), and the
round of round.sh with stand-ins for the network, the build and the diff driver.

 - the identity guard: any project but the watchdog's, or no active account, is refused before any other call;
 - the approval flag: without it nothing that creates, starts, stops or deletes is ever called (the request is printed);
 - the inspection: a wrong network (not custom), a wrong subnet range or network, a firewall rule, a missing service
   account, a machine type or zone that is not allowed, a bucket that is not private, are each refused, even with the flag;
 - the request: spot, STOP, the network and subnet, the service account, a shielded VM, no SSH key, the labels
   project=duoforge and purpose=watch, the bucket as metadata, no template and no instance group;
 - start, stop and delete touch only an instance that carries the labels, and say what they would call;
 - the startup script: its first command is the 120-minute watchdog, it holds no secret and no bucket name;
 - the bench round (start.sh --bench SHA1,SHA2): two commits of this repository only (a branch head is one, a commit of
   a fork or of nowhere is not), known families only, the approval flag, the metadata call before the start call;
 - the round: the campaigns of the rotation, fresh seeds, the object names, the rebuild rule, a campaign with its cap and
   its uploads, the heartbeat, the bench round (bench_ab.py with a fake duoforge_bench, the routing by the metadata);
 - the repository: no key, no token, no bucket name, the pin equal to the one of the CI, shellcheck when installed.
Needs bash on the PATH (Git Bash on Windows)."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ROOT = os.path.dirname(ROOT)
BASH = os.environ.get('DUOFORGE_BASH') or shutil.which('bash')
PROJECT = 'project-d498a888-995e-4142-82a'
SA = 'duoforge-watch@%s.iam.gserviceaccount.com' % PROJECT
BUCKET = 'bucket-for-tests-' + 'x1'  # a made-up name: the real one is a launch parameter and is not in the repository
SHA = 'b' * 40

STUB = r'''#!/usr/bin/env bash
# The stub gcloud of the tests: logs the call, answers from STUB_* variables.
printf '%s\n' "$*" >> "$STUB_LOG"
all="$*"
case "$all" in
    "config get project"*) printf '%s\n' "${STUB_PROJECT-project-d498a888-995e-4142-82a}" ;;
    "auth list"*) [ -z "${STUB_ACCOUNT-x}" ] || printf '%s\n' "${STUB_ACCOUNT-someone}" ;;
    *"networks subnets describe"*)
        [ "${STUB_SUBNET_MISSING:-}" != 1 ] || { echo "not found" >&2; exit 1; }
        case $all in
            *"value(ipCidrRange)"*) printf '%s\n' "${STUB_CIDR:-10.20.0.0/24}" ;;
            *"value(network)"*) printf '%s\n' "${STUB_SUBNET_NET:-https://www.googleapis.com/compute/v1/projects/p/global/networks/duoforge-net}" ;;
        esac ;;
    *"networks describe"*)
        [ "${STUB_NET_MISSING:-}" != 1 ] || { echo "not found" >&2; exit 1; }
        printf '%s\n' "${STUB_NET_AUTO:-False}" ;;
    *"firewall-rules list"*) [ -z "${STUB_FIREWALL:-}" ] || printf '%s\n' "$STUB_FIREWALL" ;;
    *"iam service-accounts describe"*)
        [ "${STUB_SA_MISSING:-}" != 1 ] || { echo "not found" >&2; exit 1; }
        for a in "$@"; do case $a in *@*.iam.gserviceaccount.com) echo "$a" ;; esac; done ;;
    *"machine-types list"*) [ "${STUB_MACHINE_NONE:-}" = 1 ] || echo europe-west4-a ;;
    *"storage buckets describe"*)
        [ "${STUB_BUCKET_MISSING:-}" != 1 ] || { echo "not found" >&2; exit 1; }
        printf '%b\n' "${STUB_BUCKET:-True\tenforced}" ;;
    *"instances describe"*)
        [ -n "${STUB_INSTANCE-}" ] || exit 1
        case $all in
            *"value(status)"*) printf '%s\n' "${STUB_INSTANCE-}" ;;
            *"value(labels.project,labels.purpose)"*) printf '%b\n' "${STUB_LABELS:-duoforge\twatch}" ;;
        esac ;;
    *"instances add-metadata"*)
        [ "${STUB_ADD_METADATA_FAIL:-}" != 1 ] || { echo "metadata refused" >&2; exit 1; }
        echo done ;;
    *"instances create"* | *"instances start"* | *"instances stop"* | *"instances delete"*) echo done ;;
    *) echo "UNEXPECTED CALL: $all" >&2; exit 9 ;;
esac
exit 0
'''

READ_ONLY = re.compile(r'^(config get|auth list|compute (networks|networks subnets|machine-types|firewall-rules|instances) '
                       r'(describe|list)|iam service-accounts describe|storage buckets describe)')


def wr(path, text):
    with open(path, 'w', encoding='utf-8', newline=chr(10)) as f:
        f.write(text)


def posix(path):
    return path.replace('\\', '/')


def rm_tree(path):
    """shutil.rmtree that also removes what git makes read-only on Windows."""
    def force(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=force)


@unittest.skipIf(BASH is None, 'bash is not on the PATH')
class Guards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gcp_watch_test_')
        self.addCleanup(rm_tree, self.tmp)
        self.stubdir = os.path.join(self.tmp, 'bin')
        os.mkdir(self.stubdir)
        stub = os.path.join(self.stubdir, 'gcloud')
        with open(stub, 'w', newline='\n') as f:
            f.write(STUB)
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self.log = os.path.join(self.tmp, 'calls.log')
        open(self.log, 'w').close()
        self.env = dict(os.environ, PATH=self.stubdir + os.pathsep + os.environ['PATH'], STUB_LOG=posix(self.log))
        for var in list(self.env):
            if var.startswith(('STUB_', 'CLOUDSDK_', 'GW_')) and var != 'STUB_LOG':
                self.env.pop(var)
        found = subprocess.run([BASH, '-c', 'command -v gcloud'], env=self.env, capture_output=True, text=True).stdout.strip()
        self.assertTrue('gcp_watch_test_' in found.lower(), found)  # the stub is what `gcloud` is

    def run_script(self, script, *args, **env):
        e = dict(self.env, **env)
        return subprocess.run([BASH, posix(os.path.join(HERE, script)), *args], env=e, capture_output=True, text=True,
                              timeout=120)

    def calls(self):
        with open(self.log, encoding='utf-8') as f:
            return [re.sub(r'^--project \S+ --quiet ', '', line.strip()) for line in f if line.strip()]

    def changes(self):
        return [c for c in self.calls() if re.search(r'instances (create|start|stop|delete|add-metadata)', c)]

    def assertRefused(self, r, text, changes=False):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn(text, r.stderr)
        if not changes:
            self.assertEqual(self.changes(), [])

    # ------------------------------------------------------------------------------------------ the identity guard
    def test_a_wrong_project_is_refused_before_any_other_call(self):
        for script, args in (('create.sh', ['--bucket', BUCKET]), ('start.sh', []), ('stop.sh', []), ('delete.sh', [])):
            open(self.log, 'w').close()
            r = self.run_script(script, *args, '--i-have-owner-approval', STUB_PROJECT='some-other-project')
            self.assertRefused(r, "not '%s'" % PROJECT)
            self.assertEqual(self.calls(), ['config get project'], script)

    def test_no_active_account_is_refused(self):
        r = self.run_script('create.sh', '--bucket', BUCKET, '--i-have-owner-approval', STUB_ACCOUNT='')
        self.assertRefused(r, 'no active gcloud account')

    def test_an_unreadable_project_is_refused(self):
        r = self.run_script('start.sh', STUB_PROJECT='')
        self.assertRefused(r, 'could not be read')

    # ------------------------------------------------------------------------------------------ the approval flag
    def test_create_without_the_flag_is_a_dry_run(self):
        r = self.run_script('create.sh', '--bucket', BUCKET)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('dry run', r.stderr)
        self.assertIn('instances create duoforge-watch', r.stdout)
        self.assertEqual(self.changes(), [])
        self.assertTrue(all(READ_ONLY.match(c) for c in self.calls()), self.calls())

    def test_start_stop_delete_without_the_flag_are_dry_runs(self):
        for script, status in (('start.sh', 'TERMINATED'), ('stop.sh', 'RUNNING'), ('delete.sh', 'TERMINATED')):
            open(self.log, 'w').close()
            r = self.run_script(script, STUB_INSTANCE=status)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('dry run', r.stderr)
            self.assertIn('instances %s duoforge-watch' % script[:-3], r.stdout)
            self.assertEqual(self.changes(), [], script)
            self.assertTrue(all(READ_ONLY.match(c) for c in self.calls()), self.calls())

    def test_the_flag_makes_the_real_call_and_only_that(self):
        r = self.run_script('create.sh', '--bucket', BUCKET, '--i-have-owner-approval', STUB_INSTANCE='')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.changes()), 1, self.calls())
        for script, status in (('start.sh', 'TERMINATED'), ('stop.sh', 'RUNNING'), ('delete.sh', 'RUNNING')):
            open(self.log, 'w').close()
            r = self.run_script(script, '--i-have-owner-approval', STUB_INSTANCE=status)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self.changes(), ['compute instances %s duoforge-watch --zone europe-west4-a' % script[:-3]])

    # ------------------------------------------------------------------------------------------ the inspection
    def refuse_create(self, text, **env):
        env.setdefault('STUB_INSTANCE', '')
        r = self.run_script('create.sh', '--bucket', BUCKET, '--i-have-owner-approval', **env)
        self.assertRefused(r, text)
        
    def test_a_network_that_is_not_custom_is_refused(self):
        self.refuse_create('is not a custom-mode network', STUB_NET_AUTO='True')

    def test_a_missing_network_is_refused(self):
        self.refuse_create("the network 'duoforge-net' was not found", STUB_NET_MISSING='1')

    def test_a_wrong_subnet_range_or_network_is_refused(self):
        self.refuse_create('has the range', STUB_CIDR='10.99.0.0/24')
        self.refuse_create("is not in the network 'duoforge-net'", STUB_SUBNET_NET='https://x/global/networks/default')
        self.refuse_create('was not found in europe-west4', STUB_SUBNET_MISSING='1')

    def test_a_firewall_rule_is_refused(self):
        self.refuse_create('firewall rule(s) (allow-ssh)', STUB_FIREWALL='allow-ssh')

    def test_a_missing_service_account_is_refused(self):
        self.refuse_create('service account %s was not found' % SA, STUB_SA_MISSING='1')

    def test_a_bucket_that_is_not_private_is_refused(self):
        self.refuse_create('the bucket is not private', STUB_BUCKET='False\\tenforced')
        self.refuse_create('the bucket is not private', STUB_BUCKET='True\\tinherited')
        self.refuse_create('was not found or cannot be read', STUB_BUCKET_MISSING='1')

    def test_a_machine_type_that_is_not_offered_is_refused(self):
        self.refuse_create('is not offered in europe-west4', STUB_MACHINE_NONE='1')

    def test_an_existing_instance_is_not_created_again(self):
        self.refuse_create("the instance 'duoforge-watch' already exists", STUB_INSTANCE='TERMINATED')

    def test_bad_values_are_refused_before_any_call(self):
        cases = (('--machine-type', 'n2-standard-64', 'machine type'), ('--zone', 'us-central1-a', 'the zone'),
                 ('--bucket', 'Bad Bucket', 'not a bucket name'))
        for flag, value, text in cases:
            open(self.log, 'w').close()
            args = ['--bucket', BUCKET, '--i-have-owner-approval', flag, value]
            r = self.run_script('create.sh', *args)
            self.assertRefused(r, text)
            self.assertEqual(self.calls(), [], flag)
        r = self.run_script('create.sh', '--i-have-owner-approval')
        self.assertRefused(r, '--bucket is required')
        r = self.run_script('create.sh', '--bucket', BUCKET, '--bogus')
        self.assertRefused(r, 'unknown argument')

    # ------------------------------------------------------------------------------------------ the request
    def test_the_request(self):
        r = self.run_script('create.sh', '--bucket', BUCKET, STUB_INSTANCE='')
        self.assertEqual(r.returncode, 0, r.stderr)
        req = r.stdout.replace(chr(92) + ',', ',')
        for part in ('--provisioning-model SPOT', '--instance-termination-action STOP', '--maintenance-policy TERMINATE',
                     '--machine-type t2d-standard-8', '--zone europe-west4-a', '--image-family ubuntu-2404-lts-amd64',
                     '--image-project ubuntu-os-cloud', '--network-interface network=duoforge-net,subnet=duoforge-subnet',
                     '--service-account ' + SA, '--scopes cloud-platform', '--shielded-secure-boot', '--shielded-vtpm',
                     '--shielded-integrity-monitoring', 'block-project-ssh-keys=TRUE', 'enable-oslogin=FALSE',
                     'duoforge-bucket=' + BUCKET, 'startup-script=', '--labels project=duoforge,purpose=watch',
                     '--boot-disk-size 60GB', '--project ' + PROJECT):
            self.assertIn(part, req)
        for part in ('--no-address', 'ssh-keys=', 'instance-templates', 'instance-groups', '--preemptible', 'default'):
            self.assertNotIn(part, req.replace('block-project-ssh-keys', ''))
        self.assertTrue(re.search(r'startup-script=\S*gcp_watch\S*startup\.sh', req.replace('\\', '/')), req)

    def test_the_machine_type_and_zone_can_be_chosen_from_the_lists(self):
        r = self.run_script('create.sh', '--bucket', BUCKET, '--machine-type', 't2d-standard-4', '--zone', 'europe-west4-b',
                            STUB_INSTANCE='')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('--machine-type t2d-standard-4', r.stdout)
        self.assertIn('--zone europe-west4-b', r.stdout)

    # ------------------------------------------------------------------------------------------ start, stop, delete
    def test_an_instance_without_the_labels_is_never_touched(self):
        for script, status in (('start.sh', 'TERMINATED'), ('stop.sh', 'RUNNING'), ('delete.sh', 'TERMINATED')):
            r = self.run_script(script, '--i-have-owner-approval', STUB_INSTANCE=status, STUB_LABELS='\\t')
            self.assertRefused(r, 'does not carry the labels')
            r = self.run_script(script, '--i-have-owner-approval', STUB_INSTANCE=status, STUB_LABELS='duoforge\\tfuzz')
            self.assertRefused(r, 'does not carry the labels')

    def test_state_checks(self):
        self.assertRefused(self.run_script('start.sh', '--i-have-owner-approval', STUB_INSTANCE='RUNNING'), 'already RUNNING')
        self.assertRefused(self.run_script('stop.sh', '--i-have-owner-approval', STUB_INSTANCE='TERMINATED'), 'nothing to stop')
        self.assertRefused(self.run_script('start.sh', '--i-have-owner-approval', STUB_INSTANCE=''), 'there is no instance')
        self.assertRefused(self.run_script('delete.sh', '--zone', 'asia-east1-a'), 'the zone')

    # ------------------------------------------------------------------------------------------ the bench round
    RUN = 'b20261003T120000Z'

    def make_repo(self, url='https://github.com/chrismaghuhn/duoforge.git', name='repo'):
        """A small repository: main (origin/main), a branch head that only a branch of origin has (origin/pr-branch, a
        pull request head of this repository), and a local commit that no ref of origin has."""
        repo = os.path.join(self.tmp, name)
        os.makedirs(repo)

        def git(*args):
            r = subprocess.run(['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@t', *args], capture_output=True,
                               text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout.strip()
        git('init', '-q')
        git('commit', '-q', '--allow-empty', '-m', 'main')
        main = git('rev-parse', 'HEAD')
        git('commit', '-q', '--allow-empty', '-m', 'pr head')
        pr = git('rev-parse', 'HEAD')
        git('commit', '-q', '--allow-empty', '-m', 'local only')
        local = git('rev-parse', 'HEAD')
        git('remote', 'add', 'origin', url)
        git('update-ref', 'refs/remotes/origin/main', main)
        git('update-ref', 'refs/remotes/origin/pr-branch', pr)
        return repo, main, pr, local

    def bench(self, refs, *args, **env):
        env.setdefault('STUB_INSTANCE', 'TERMINATED')
        env.setdefault('GW_BENCH_RUN', self.RUN)
        return self.run_script('start.sh', '--bench', refs, *args, **env)

    def test_a_bench_round_is_a_dry_run_without_the_flag(self):
        repo, main, pr, _ = self.make_repo()
        r = self.bench('%s,%s' % (main, pr), GW_REPO_DIR=posix(repo))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('dry run', r.stderr)
        self.assertEqual(self.changes(), [])
        self.assertTrue(all(READ_ONLY.match(c) for c in self.calls()), self.calls())
        meta = 'compute instances add-metadata duoforge-watch --zone europe-west4-a --metadata ' \
               '^:^bench_refs=%s,%s:bench_families=copy,codec,batch:bench_run=%s' % (main, pr, self.RUN)
        start = 'compute instances start duoforge-watch --zone europe-west4-a'
        lines = r.stdout.strip().splitlines()
        self.assertEqual([re.sub(r'^\S+ --project \S+ --quiet ', '', ln) for ln in lines], [meta, start])

    def test_the_flag_sets_the_metadata_and_then_starts(self):
        repo, main, pr, _ = self.make_repo()
        r = self.bench('%s,%s' % (main, pr), '--families', 'copy,codec', '--zone', 'europe-west4-b', '--i-have-owner-approval',
                       GW_REPO_DIR=posix(repo))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.changes(), [
            'compute instances add-metadata duoforge-watch --zone europe-west4-b --metadata '
            '^:^bench_refs=%s,%s:bench_families=copy,codec:bench_run=%s' % (main, pr, self.RUN),
            'compute instances start duoforge-watch --zone europe-west4-b'])

    def test_a_bench_run_id_is_made_when_none_is_given(self):
        repo, main, pr, _ = self.make_repo()
        r = self.bench('%s,%s' % (main, pr), GW_REPO_DIR=posix(repo), GW_BENCH_RUN='')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r'bench_run=b\d{8}T\d{6}Z')

    def test_a_failed_metadata_call_does_not_start_the_instance(self):
        repo, main, pr, _ = self.make_repo()
        r = self.bench('%s,%s' % (main, pr), '--i-have-owner-approval', GW_REPO_DIR=posix(repo), STUB_ADD_METADATA_FAIL='1')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('is not started', r.stderr)
        self.assertEqual(len(self.changes()), 1, self.calls())
        self.assertIn('add-metadata', self.changes()[0])

    def test_a_commit_that_is_not_of_this_repository_is_refused(self):
        repo, main, pr, local = self.make_repo()
        for sha, text in (('c' * 40, 'is not in this repository'),  # a commit nobody here has (a fork, or nowhere)
                          (local, 'is not reachable from any branch of origin')):  # here, but on no branch of origin
            for refs in ('%s,%s' % (main, sha), '%s,%s' % (sha, pr)):
                open(self.log, 'w').close()
                r = self.bench(refs, '--i-have-owner-approval', GW_REPO_DIR=posix(repo))
                self.assertRefused(r, text)
                self.assertIn(sha, r.stderr)
                self.assertEqual(self.calls(), [], refs)  # refused before any gcloud call

    def test_a_foreign_remote_is_refused(self):
        for i, url in enumerate(('https://github.com/someone-else/duoforge.git', 'https://example.com/chrismaghuhn/duoforge.git',
                                 'https://github.com/chrismaghuhn/duoforge-fork.git',
                                 'https://github.com/chrismaghuhn/duoforge.git.evil')):
            repo, main, pr, _ = self.make_repo(url, 'foreign%d' % i)
            open(self.log, 'w').close()
            r = self.bench('%s,%s' % (main, pr), '--i-have-owner-approval', GW_REPO_DIR=posix(repo))
            self.assertRefused(r, 'is not chrismaghuhn/duoforge')
            self.assertEqual(self.calls(), [], url)
        for i, url in enumerate(('git@github.com:chrismaghuhn/duoforge.git', 'https://github.com/chrismaghuhn/duoforge')):
            repo, main, pr, _ = self.make_repo(url, 'same%d' % i)  # the same repository, spelled otherwise
            r = self.bench('%s,%s' % (main, pr), GW_REPO_DIR=posix(repo))
            self.assertEqual(r.returncode, 0, (url, r.stderr))

    def test_a_directory_that_is_not_a_repository_is_refused(self):
        r = self.bench('%s,%s' % ('a' * 40, 'b' * 40), GW_REPO_DIR=posix(self.tmp))
        self.assertRefused(r, "no remote 'origin'")
        self.assertEqual(self.calls(), [])

    def test_bench_commits_must_be_two_full_shas(self):
        repo, main, pr, _ = self.make_repo()
        for refs, text in ((main, 'exactly two commits'), ('%s,%s,%s' % (main, pr, main), 'exactly two commits'),
                           ('%s,%s' % (main[:12], pr), 'is not a commit'), ('%s,%s' % (main, 'main'), 'is not a commit'),
                           ('%s,%s' % (main, pr.upper()), 'is not a commit'), (',', 'exactly two commits'), ('', 'exactly two commits'),
                           ('%s,%s,' % (main, pr), 'exactly two commits'), (',%s,%s' % (main, pr), 'exactly two commits')):
            open(self.log, 'w').close()
            r = self.bench(refs, '--i-have-owner-approval', GW_REPO_DIR=posix(repo))
            self.assertRefused(r, text)
            self.assertEqual(self.calls(), [], refs)

    def test_an_unknown_bench_family_is_refused(self):
        repo, main, pr, _ = self.make_repo()
        for families, text in (('copy,bogus', "unknown benchmark family 'bogus'"), ('copy,Codec', "unknown benchmark family 'Codec'"),
                               ('', 'is empty'), ('copy,,codec', 'has an empty name'), ('copy,codec,', 'has an empty name'),
                               (',copy', 'has an empty name'), ('copy,copy', "named twice"),
                               ('snapshot', "unknown benchmark family 'snapshot'")):
            open(self.log, 'w').close()
            r = self.bench('%s,%s' % (main, pr), '--families', families, '--i-have-owner-approval', GW_REPO_DIR=posix(repo))
            self.assertRefused(r, text)
            self.assertEqual(self.calls(), [], families)
        for families in ('step', 'events,request', 'copy,codec,batch', 'step,events,request,copy,codec,episode,batch'):
            r = self.bench('%s,%s' % (main, pr), '--families', families, GW_REPO_DIR=posix(repo))  # every real family is allowed
            self.assertEqual(r.returncode, 0, (families, r.stderr))
            self.assertIn('bench_families=%s:' % families, r.stdout)

    def test_the_bench_options_belong_to_start_only(self):
        repo, main, pr, _ = self.make_repo()
        r = self.run_script('start.sh', '--families', 'copy', STUB_INSTANCE='TERMINATED')
        self.assertRefused(r, '--families belongs to --bench')
        for script in ('stop.sh', 'delete.sh'):
            r = self.run_script(script, '--bench', '%s,%s' % (main, pr), STUB_INSTANCE='RUNNING', GW_REPO_DIR=posix(repo))
            self.assertRefused(r, "unknown argument '--bench'")
        self.assertRefused(self.run_script('start.sh', '--bench'), '--bench needs a value')
        self.assertEqual(self.calls(), [])

    def test_the_bench_round_keeps_the_other_guards(self):
        repo, main, pr, _ = self.make_repo()
        refs = '%s,%s' % (main, pr)
        r = self.bench(refs, '--i-have-owner-approval', GW_REPO_DIR=posix(repo), STUB_PROJECT='some-other-project')
        self.assertRefused(r, "not '%s'" % PROJECT)
        self.assertEqual(self.calls(), ['config get project'])
        open(self.log, 'w').close()
        self.assertRefused(self.bench(refs, '--i-have-owner-approval', GW_REPO_DIR=posix(repo), STUB_LABELS='duoforge\\tfuzz'),
                           'does not carry the labels')
        self.assertRefused(self.bench(refs, '--i-have-owner-approval', GW_REPO_DIR=posix(repo), STUB_INSTANCE='RUNNING'),
                           'already RUNNING')
        self.assertRefused(self.bench(refs, '--i-have-owner-approval', GW_REPO_DIR=posix(repo), STUB_INSTANCE=''),
                           'there is no instance')

    def test_the_bench_families_agree_with_the_bench(self):
        main_c = open(os.path.join(ROOT, 'bench', 'main.c'), encoding='utf-8').read()
        names = re.search(r'names\[\] = \{([^}]*)\}', main_c)
        self.assertIsNotNone(names)
        real = re.findall(r'"(\w+)"', names.group(1))
        lib = re.search(r"^GW_BENCH_FAMILIES='([^']*)'", open(os.path.join(HERE, 'lib.sh'), encoding='utf-8').read(), re.M)
        self.assertEqual(lib.group(1).split(), real)
        sys.path.insert(0, HERE)
        try:
            import bench_ab
        finally:
            sys.path.remove(HERE)
        self.assertEqual(list(bench_ab.FAMILIES), real)
        self.assertEqual(bench_ab.DEFAULT_FAMILIES, 'copy,codec,batch')

    # ------------------------------------------------------------------------------------------ the startup script
    def test_the_startup_script(self):
        text = open(os.path.join(HERE, 'startup.sh'), encoding='utf-8').read()
        lines = text.splitlines()
        self.assertEqual(lines[0], '#!/bin/bash')
        self.assertTrue(lines[1].startswith('shutdown -h +120'), lines[1])
        self.assertIn('exec bash "$REPO/tools/cloud/gcp_watch/round.sh"', text)
        self.assertNotIn('@', re.sub(r'#.*', '', text).replace('"$@"', ''))  # no placeholder to fill

    # ------------------------------------------------------------------------------------------ the repository
    def test_no_secret_no_key_no_bucket_name_in_the_tools(self):
        patterns = (r'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY', r'AIza[0-9A-Za-z_-]{20,}', r'ya29\.[0-9A-Za-z_-]{20,}',
                    r'"private_key"', r'duoforge-watch-[0-9a-f]{6}', r'gs://duoforge-watch', r'[0-9]{12}-compute@',
                    r'client_secret')
        for name in os.listdir(HERE):
            path = os.path.join(HERE, name)
            if not os.path.isfile(path) or name == 'test_guards.py' or name.endswith('.pyc'):
                continue
            text = open(path, encoding='utf-8').read()
            for pat in patterns:
                self.assertIsNone(re.search(pat, text), (name, pat))

    def test_the_pin_is_the_one_of_the_ci(self):
        ci = open(os.path.join(ROOT, '.github', 'workflows', 'ci.yml'), encoding='utf-8').read()
        pin = re.search(r'^RD_SHOWDOWN_PIN=([0-9a-f]{40})', open(os.path.join(HERE, 'round.sh'), encoding='utf-8').read(), re.M)
        self.assertIsNotNone(pin)
        self.assertIn('ref: ' + pin.group(1), ci)

    def test_the_readme_says_what_it_must(self):
        text = open(os.path.join(HERE, 'README.md'), encoding='utf-8').read()
        for part in ('--i-have-owner-approval', 'STOP', 't2d-standard-8', 'europe-west4', 'duoforge-net', 'duoforge-subnet',
                     'create.sh', 'start.sh', 'stop.sh', 'delete.sh', 'round.sh', 'Spot price', 'stopped', 'heartbeat',
                     '--bench', 'bench_refs', 'bench_run', 'bench.json', 'bench_ab.py', 'reachable from a branch of `origin`'):
            self.assertIn(part, text)

    def test_shellcheck(self):
        exe = shutil.which('shellcheck')
        if exe is None:
            self.skipTest('shellcheck is not installed')
        files = [os.path.join(HERE, n) for n in ('lib.sh', 'create.sh', 'start.sh', 'stop.sh', 'delete.sh', 'round.sh')]
        r = subprocess.run([exe, '-x', '-S', 'warning', *files], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)


ROUND_PRELUDE = r'''
set -euo pipefail
export RD_SOURCE_ONLY=1
export GW_WORK="$T/work" GW_REPO="$T/repo" GW_HEAD="%s" GW_BOOT_LOG="$T/boot.log"
mkdir -p "$GW_WORK/state"
source "%s/round.sh"
RD_BUCKET=testbucket
RD_PUT_LOG="$T/puts.log"
: > "$RD_PUT_LOG"
rd_gcs_put() {
    local body='(binary)'
    case "$2" in *.json | *.txt) body=$(tr '\n' ' ' < "$1") ;; esac
    printf '%%s\t%%s\n' "$2" "$body" >> "$RD_PUT_LOG"
}
''' % (SHA, '%(here)s')

FAKE_DRIVER = r'''
import json, os, sys, time
a = sys.argv
out = a[a.index('--out') + 1]
os.makedirs(os.path.join(out, 'cases', 'fz_1'), exist_ok=True)
json.dump({'argv': a[1:]}, open(os.path.join(os.path.dirname(out), 'argv-' + os.path.basename(out) + '.json'), 'w'))
if os.environ.get('FAKE_SLEEP'):
    time.sleep(float(os.environ['FAKE_SLEEP']))
if os.environ.get('FAKE_NO_CASES'):
    os.rmdir(os.path.join(out, 'cases', 'fz_1'))
json.dump({'buckets': {'PASS': 598, 'ORACLE_GAP': 2, 'DIVERGENCE': 0}}, open(os.path.join(out, 'summary.json'), 'w'))
json.dump({'seed': int(a[a.index('--seed') + 1])}, open(os.path.join(out, 'run.json'), 'w'))
'''


@unittest.skipIf(BASH is None, 'bash is not on the PATH')
class Round(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gcp_watch_round_')
        self.addCleanup(rm_tree, self.tmp)
        self.t = posix(self.tmp)
        # a small repository checkout: the real scheduler (chunks.sh), two campaigns, the fake driver
        repo = os.path.join(self.tmp, 'repo')
        camps = os.path.join(repo, 'tools', 'cloud', 'aws_fuzz', 'campaigns')
        os.makedirs(os.path.join(camps, 'alpha'))
        os.makedirs(os.path.join(camps, 'throughput-sweep'))
        os.makedirs(os.path.join(camps, 'swept'))
        os.makedirs(os.path.join(repo, 'tools', 'reference'))
        shutil.copy(os.path.join(ROOT, 'tools', 'cloud', 'aws_fuzz', 'chunks.sh'), os.path.join(repo, 'tools', 'cloud', 'aws_fuzz'))
        conf = 'pairings=AB,BA\nteams=A=A.txt PP_0123456789ABCDEF\nbase_seed=9300000\nchunks=2\nbench=0\n'
        wr(os.path.join(camps, 'alpha', 'campaign.conf'), conf)
        wr(os.path.join(camps, 'alpha', 'A.txt'), 'team\n')
        wr(os.path.join(camps, 'throughput-sweep', 'campaign.conf'), conf + 'sweep=5,7\n')
        wr(os.path.join(camps, 'swept', 'campaign.conf'), conf + 'sweep=5,7\n')
        wr(os.path.join(repo, 'tools', 'reference', 'diff_driver.py'), FAKE_DRIVER)
        runner = os.path.join(self.tmp, 'work', 'build', 'tools', 'difftest')
        os.makedirs(runner)
        self.runner = os.path.join(runner, 'duoforge_diff_runner')
        wr(self.runner, '#!/bin/sh\n')
        os.chmod(self.runner, 0o755)

    def sh(self, body, **env):
        script = ROUND_PRELUDE.replace('%(here)s', posix(HERE)) + body
        e = dict(os.environ, T=self.t, **env)
        return subprocess.run([BASH, '-c', script], env=e, capture_output=True, text=True, timeout=120)

    def puts(self):
        with open(os.path.join(self.tmp, 'puts.log'), encoding='utf-8', errors='replace') as f:
            return [line.rstrip('\n').split('\t', 1) for line in f if line.strip()]

    def test_the_rotation_is_the_campaigns_without_a_sweep(self):
        r = self.sh('rd_campaigns "$GW_REPO"')
        self.assertEqual(r.stdout.split(), ['alpha'], r.stderr)
        r = self.sh('rd_campaigns "%s"' % posix(ROOT))
        names = r.stdout.split()
        self.assertIn('registry-mix', names)
        self.assertIn('g13-moves', names)
        self.assertIn('weather-sand-snow', names)
        self.assertFalse([n for n in names if n.startswith('throughput-')], names)
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(names), 12)

    def test_the_seeds_are_fresh(self):
        seeds = []
        for now in (1790000040, 1790000099, 1790000100, 1790003640):
            r = self.sh('rd_seed 9300000', RD_NOW=str(now))
            seeds.append(int(r.stdout))
        self.assertEqual(seeds[0], seeds[1])  # the same minute
        self.assertEqual(len(set(seeds)), 3)  # a new minute is a new seed
        self.assertTrue(all(len(str(s)) <= 12 and s >= 9300000 + 10000000 for s in seeds))
        a, b = (int(self.sh('rd_seed %d' % base, RD_NOW='1790000000').stdout) for base in (9300000, 9310000))
        self.assertNotEqual(a, b)

    def test_the_object_names(self):
        r = self.sh('RD_ROUND_ID=r20261003T120000Z; rd_object alpha summary.json')
        self.assertEqual(r.stdout, 'watch/%s/r20261003T120000Z/alpha/summary.json' % SHA[:12])

    def test_a_rebuild_only_when_the_head_changed(self):
        os.makedirs(os.path.join(self.tmp, 'work', 'state'), exist_ok=True)
        wr(os.path.join(self.tmp, 'work', 'state', 'built-head'), SHA + '\n')
        self.assertEqual(self.sh('rd_needs_build %s' % SHA).returncode, 1)  # cached: no rebuild
        self.assertEqual(self.sh('rd_needs_build %s' % ('c' * 40)).returncode, 0)  # a new head
        os.remove(self.runner)
        self.assertEqual(self.sh('rd_needs_build %s' % SHA).returncode, 0)  # the runner is gone
        os.remove(os.path.join(self.tmp, 'work', 'state', 'built-head'))
        self.assertEqual(self.sh('rd_needs_build %s' % SHA).returncode, 0)  # nothing was ever built

    def test_a_campaign_is_played_capped_and_uploaded(self):
        r = self.sh('RD_ROUND_ID=r1; rd_run_campaign alpha; cat "$GW_WORK/out/alpha/status.json"', RD_NOW='1790000000',
                    RD_ROUND_BATTLES='600')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        argv = json.load(open(os.path.join(self.tmp, 'work', 'out', 'argv-alpha.json')))['argv']
        seed = 9300000 + 10000000 + 1790000000 // 60
        for pair in (('--battles', '600'), ('--seed', str(seed)), ('--pairings', 'AB,BA'), ('--checkout', self.t + '/work/pokemon-showdown')):
            self.assertEqual(argv[argv.index(pair[0]) + 1].replace('\\', '/'), pair[1], argv)
        self.assertIn('--no-lock', argv)
        self.assertIn('--workers', argv)
        self.assertEqual([a for a in argv if a == '--team'].__len__(), 2)
        self.assertIn('PP_0123456789ABCDEF', argv)
        self.assertTrue(any(a.replace('\\', '/').startswith('A=') and a.endswith('/campaigns/alpha/A.txt') for a in argv), argv)
        objects = [o for o, _ in self.puts()]
        base = 'watch/%s/r1/alpha/' % SHA[:12]
        self.assertEqual(objects, [base + 'summary.json', base + 'run.json', base + 'cases.tgz', base + 'status.json'])
        status = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual((status['campaign'], status['status'], status['exit'], status['seed']), ('alpha', 'ok', 0, seed))
        self.assertEqual(status['buckets'], {'ORACLE_GAP': 2, 'PASS': 598})

    def test_a_campaign_without_cases_uploads_no_archive(self):
        r = self.sh('RD_ROUND_ID=r1; rd_run_campaign alpha', FAKE_NO_CASES='1')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('cases.tgz', ' '.join(o for o, _ in self.puts()))

    def test_the_hard_cap_ends_a_campaign_and_the_round_goes_on(self):
        r = self.sh('RD_ROUND_ID=r1; rd_run_campaign alpha; cat "$GW_WORK/out/alpha/status.json"',
                    RD_CAMPAIGN_CAP_SECONDS='1', FAKE_SLEEP='30')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        status = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual((status['status'], status['exit']), ('capped', 124))
        self.assertLess(status['seconds'], 20)

    def test_the_heartbeat(self):
        r = self.sh('RD_ROUND_ID=r1; rd_set_state running alpha; rd_heartbeat')
        self.assertEqual(r.returncode, 0, r.stderr)
        (obj, body), = self.puts()
        self.assertEqual(obj, 'watch/heartbeat.json')
        hb = json.loads(body)
        self.assertEqual((hb['state'], hb['campaign'], hb['head'], hb['round']), ('running', 'alpha', SHA, 'r1'))
        self.assertRegex(hb['time'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')

    def test_leaving_uploads_the_log_and_powers_off_unless_told_not_to(self):
        wr(os.path.join(self.tmp, 'boot.log'), 'line\n')
        r = self.sh('RD_ROUND_ID=r1; shutdown() { echo "SHUTDOWN $*" >> "$T/shutdown.log"; }; rd_finish')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(open(os.path.join(self.tmp, 'shutdown.log')).read().strip(), 'SHUTDOWN -h now')
        objects = [o for o, _ in self.puts()]
        self.assertIn('watch/%s/r1/log.txt' % SHA[:12], objects)
        self.assertIn('watch/heartbeat.json', objects)
        hb = json.loads(dict(self.puts())['watch/heartbeat.json'])
        self.assertEqual(hb['state'], 'off')

    # ------------------------------------------------------------------------------------------ the bench round
    def bench_setup(self):
        """The repository gets bench_ab.py, and two fake builds (one fake duoforge_bench each) are what rd_bench_build
        would have produced: RD_BENCH_BIN of a sha is its fake."""
        tool = os.path.join(self.tmp, 'repo', 'tools', 'cloud', 'gcp_watch')
        os.makedirs(tool)
        shutil.copy(os.path.join(HERE, 'bench_ab.py'), tool)
        fake = os.path.join(self.tmp, 'fake_bench.py')
        wr(fake, FAKE_BENCH)
        self.fake_log = os.path.join(self.tmp, 'fake.log')
        self.cmd = '%s %s' % (posix(sys.executable), posix(fake))
        self.sha_a, self.sha_b = 'a' * 40, 'b' * 40
        return r'''
rd_ensure_build_tools() { :; }
rd_instance_type() { echo t2d-standard-8; }
rd_bench_build() {
    echo "build $1" >> "$T/builds.log"
    RD_BENCH_BIN="$FAKE_CMD --label ${1:0:1} --rev $1 --log $T/fake.log"
}
'''

    def test_a_bench_round_builds_runs_and_uploads_bench_json(self):
        stubs = self.bench_setup()
        r = self.sh(stubs + '''
rd_metadata() { case $1 in bench_families) echo copy,codec,batch ;; *) return 1 ;; esac; }
rd_bench_main "%s,%s" b20261003T120000Z
echo "state: $(cat "$RD_STATE/hb")"''' % (self.sha_a, self.sha_b), FAKE_CMD=self.cmd, RD_BENCH_ROUNDS='2', RD_BENCH_REPETITIONS='3')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(open(os.path.join(self.tmp, 'builds.log')).read().split('\n')[:2], ['build ' + 'a' * 40, 'build ' + 'b' * 40])
        (obj, body), = self.puts()
        self.assertEqual(obj, 'bench/b20261003T120000Z/bench.json')
        data = json.loads(body)
        self.assertEqual(data['run'], 'b20261003T120000Z')
        self.assertEqual(data['instance_type'], 't2d-standard-8')
        self.assertEqual(sorted(data['results']), ['batch/workers=1', 'codec', 'copy'])
        self.assertEqual((data['rounds'], data['repetitions'], data['workers']), (2, 3, [1]))
        self.assertIn('state: done', r.stdout)

    def test_a_bench_round_checks_before_it_builds(self):
        stubs = self.bench_setup()
        cases = (('%s,%s' % (self.sha_a, 'main'), 'copy', 'is not SHA1,SHA2'), (self.sha_a, 'copy', 'is not SHA1,SHA2'),
                 ('%s,%s' % (self.sha_a, self.sha_b), 'copy,bogus', 'bad commits or families'))
        for refs, families, text in cases:
            r = self.sh(stubs + 'rd_metadata() { case $1 in bench_families) echo %s ;; *) return 1 ;; esac; }\n'
                        'rd_bench_main "%s" b20261003T120000Z' % (families, refs), FAKE_CMD=self.cmd)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn(text, r.stdout + r.stderr)
            self.assertFalse(os.path.exists(os.path.join(self.tmp, 'builds.log')), 'a build was started')
            self.assertEqual(self.puts(), [])
        r = self.sh(stubs + 'rd_metadata() { return 1; }\nrd_bench_main "%s,%s" b20261003T120000Z' % (self.sha_a, self.sha_b),
                    FAKE_CMD=self.cmd)
        self.assertEqual(r.returncode, 1)
        self.assertIn('bench_families is not', r.stdout + r.stderr)

    def test_a_failed_measurement_is_uploaded_and_fails_the_round(self):
        stubs = self.bench_setup()
        r = self.sh(stubs + '''
rd_metadata() { case $1 in bench_families) echo copy,codec ;; *) return 1 ;; esac; }
rd_bench_main "%s,%s" b20261003T120000Z''' % (self.sha_a, self.sha_b), FAKE_CMD=self.cmd, FAKE_OMIT='codec', RD_BENCH_ROUNDS='1')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        (obj, body), = self.puts()
        self.assertEqual(obj, 'bench/b20261003T120000Z/bench.json')
        self.assertIn('did not report: codec', json.loads(body)['error'])
        self.assertIn('bench_ab.py failed', r.stdout + r.stderr)

    def boot(self, run, bench_last=None, refs=None):
        """rd_main with the metadata of the instance, stand-ins for the tools, and a logging rd_bench_main."""
        state = os.path.join(self.tmp, 'work', 'state')
        os.makedirs(state, exist_ok=True)
        if bench_last:
            wr(os.path.join(state, 'bench-last'), bench_last + '\n')
        wr(os.path.join(state, 'built-head'), SHA + '\n')
        return self.sh('''
node() { echo v22.0.0; }
rd_ensure_tools() { :; }
rd_heartbeat_loop() { :; }
rd_metadata() {
    case $1 in
        duoforge-bucket) echo testbucket ;;
        bench_refs) [ -z "${FAKE_REFS:-}" ] || echo "$FAKE_REFS" ;;
        bench_run) [ -z "${FAKE_RUN:-}" ] || echo "$FAKE_RUN" ;;
        *) return 1 ;;
    esac
}
rd_bench_main() { echo "BENCH $*" >> "$T/bench-main.log"; }
RD_BUCKET=''
RD_NO_SHUTDOWN=1
rd_main''', FAKE_REFS=refs or '', FAKE_RUN=run or '', RD_NO_SHUTDOWN='1', RD_NOW='1790000000')

    def test_the_metadata_decides_between_a_bench_round_and_a_fuzz_round(self):
        refs = '%s,%s' % ('a' * 40, 'b' * 40)
        # a new bench run id: the bench round, no campaign, and the id is remembered
        r = self.boot('b20261003T120000Z', refs=refs)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(open(os.path.join(self.tmp, 'bench-main.log')).read().strip(), 'BENCH %s b20261003T120000Z' % refs)
        self.assertEqual(open(os.path.join(self.tmp, 'work', 'state', 'bench-last')).read().strip(), 'b20261003T120000Z')
        self.assertFalse([o for o, _ in self.puts() if o.startswith('watch/%s/' % SHA[:12]) and 'alpha' in o])
        # the same id again (the metadata stays on the instance): a fuzz round
        os.remove(os.path.join(self.tmp, 'bench-main.log'))
        r = self.boot('b20261003T120000Z', bench_last='b20261003T120000Z', refs=refs)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('was played already', r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'bench-main.log')))
        self.assertIn('watch/%s/r%s/alpha/status.json' % (SHA[:12], re.search(r'round r(\S+) on', r.stdout).group(1)),
                      [o for o, _ in self.puts()])
        # no bench_refs at all: a fuzz round, as before
        r = self.boot('', refs='')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'bench-main.log')))

    def test_bench_refs_without_a_bench_run_id_fail_explicitly(self):
        refs = '%s,%s' % ('a' * 40, 'b' * 40)
        for run in ('', 'run-1', 'b2026'):
            r = self.boot(run, refs=refs)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn('bench_run is not a bench run id', r.stdout)
            self.assertFalse(os.path.exists(os.path.join(self.tmp, 'bench-main.log')))

    def test_a_bench_round_puts_its_log_under_the_bench_prefix(self):
        wr(os.path.join(self.tmp, 'boot.log'), 'line\n')
        r = self.sh('RD_BENCH_RUN=b20261003T120000Z; RD_ROUND_ID=r1; rd_finish', RD_NO_SHUTDOWN='1')
        self.assertEqual(r.returncode, 0, r.stderr)
        objects = [o for o, _ in self.puts()]
        self.assertIn('bench/b20261003T120000Z/log.txt', objects)
        self.assertNotIn('watch/%s/r1/log.txt' % SHA[:12], objects)


FAKE_BENCH = r'''
import json, os, sys
a = sys.argv[1:]
def opt(name, default=None):
    return a[a.index(name) + 1] if name in a else default
label, rev, log = opt('--label'), opt('--rev'), opt('--log')
out = opt('--out')
if log:
    with open(log, 'a') as f:
        f.write(label + '\n')
    count = sum(1 for line in open(log) if line.strip() == label)
else:
    count = 1
if os.environ.get('FAKE_FAIL') == label:
    sys.exit(3)
base = {'a': 1000000, 'b': 1100000}.get(label, 1000000)
fams = opt('--families').split(',')
workers = [int(w) for w in opt('--workers', '1').split(',')]
omit = os.environ.get('FAKE_OMIT', '')
errors = int(os.environ.get('FAKE_ERRORS', '0')) if os.environ.get('FAKE_ERRORS_LABEL', label) == label else 0
def entry(family, variant, w=1, calls=0, nbytes=0):
    wall = base + 1000 * count
    return {'family': family, 'variant': variant, 'workers': w, 'repetitions': 3, 'wall_ns': [wall] * 3, 'cpu_ns': [wall] * 3,
            'disturbed_repetitions': 0, 'median_wall_ns': wall, 'battles': 100, 'turns': 1, 'steps': 1, 'side_decisions': 1,
            'calls': calls, 'bytes': nbytes, 'truncations': 0, 'errors': 0,
            'per_second': {'battles': 5, 'turns': 1, 'steps': 1, 'side_decisions': 1, 'calls': 7 if calls else 0}}
results = []
table = {'step': ('STEP_CORE', 'plain'), 'events': ('STEP_CORE', 'events'), 'request': ('REQUEST', 'request+candidates+observe'),
         'copy': ('SNAPSHOT', 'copy'), 'codec': ('SNAPSHOT', 'codec'), 'episode': ('EPISODE_NATIVE', 'uniform-random')}
for f in fams:
    if f == omit:
        continue
    if f == 'batch':
        results += [entry('BATCH_NATIVE', 'workers=%d' % w, w) for w in workers]
    else:
        results.append(entry(*table[f], calls=1000 if f in ('copy', 'codec') else 0, nbytes=500 if f == 'codec' else 0))
json.dump({'manifest': {'engine': 'duoforge x', 'revision': rev, 'dirty': False,
                        'cpu': 'fake', 'context_fingerprint': 'fp', 'workload': 'closure-pairings-v1'},
           'results': results, 'errors': errors}, open(out, 'w'))
'''


@unittest.skipIf(BASH is None, 'bash is not on the PATH')
class BenchAB(unittest.TestCase):
    """bench_ab.py with a fake duoforge_bench: what it runs, in which order, and what it refuses."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='gcp_watch_bench_')
        self.addCleanup(rm_tree, self.tmp)
        sys.path.insert(0, HERE)
        self.addCleanup(sys.path.remove, HERE)
        import bench_ab
        self.mod = bench_ab
        self.fake = os.path.join(self.tmp, 'fake_bench.py')
        wr(self.fake, FAKE_BENCH)
        self.log = os.path.join(self.tmp, 'fake.log')
        self.out = os.path.join(self.tmp, 'bench.json')
        self.a, self.b = 'a' * 40, 'b' * 40

    def run_ab(self, *args, env=None, a_rev=None, b_rev=None):
        cmd = '%s %s' % (posix(sys.executable), posix(self.fake))
        argv = ['--a-bin', '%s --label a --rev %s --log %s' % (cmd, a_rev or self.a, posix(self.log)),
                '--b-bin', '%s --label b --rev %s --log %s' % (cmd, b_rev or self.b, posix(self.log)),
                '--a-sha', self.a, '--b-sha', self.b, '--out', self.out, '--repetitions', '3', *args]
        saved = {k: os.environ.get(k) for k in (env or {})}
        os.environ.update(env or {})
        try:
            status = self.mod.main(argv)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        with open(self.out, encoding='utf-8') as f:
            return status, json.load(f)

    def invocations(self):
        return open(self.log).read().split() if os.path.exists(self.log) else []

    def test_the_builds_alternate_and_the_result_has_median_and_spread(self):
        status, data = self.run_ab('--rounds', '4', '--families', 'copy,codec,batch', '--run', 'b1')
        self.assertEqual(status, 0, data)
        self.assertEqual(self.invocations(), list('abbaabba'))  # A B, B A, A B, B A
        self.assertEqual(data['rounds_order'], ['ab', 'ba', 'ab', 'ba'])
        self.assertEqual(list(data['results']), ['copy', 'codec', 'batch/workers=1'])
        for key, r in data['results'].items():
            for side in ('a', 'b'):
                w = r[side]['median_wall_ns']
                self.assertEqual(len(w['samples']), 4)
                self.assertTrue(w['min'] <= w['median'] <= w['max'])
                self.assertGreater(w['spread_percent'], 0)
            self.assertAlmostEqual(r['ratio_b_over_a']['of_medians'], 1.1, places=1)
            self.assertLessEqual(r['ratio_b_over_a']['paired_min'], r['ratio_b_over_a']['paired_max'])
        copy = data['results']['copy']['a']
        self.assertEqual(copy['calls_per_repetition'], 1000)
        self.assertAlmostEqual(copy['ns_per_call']['median'], copy['median_wall_ns']['median'] / 1000, places=2)
        self.assertEqual(data['results']['codec']['a']['bytes_per_state'], 500)
        self.assertNotIn('ns_per_call', data['results']['batch/workers=1']['a'])
        self.assertEqual((data['a']['revision'], data['b']['revision']), (self.a, self.b))
        self.assertTrue(data['same_workload_fingerprint'])
        self.assertEqual((data['run'], data['workers'], data['families']), ('b1', [1], ['copy', 'codec', 'batch']))

    def test_the_command_line_of_the_bench_is_one_thread_and_the_same_for_both_builds(self):
        calls = []
        orig = self.mod.run_invocation

        def spy(command, argv, out_path, timeout):
            calls.append(list(argv))
            return orig(command, argv, out_path, timeout)
        self.mod.run_invocation = spy
        try:
            status, _ = self.run_ab('--rounds', '2', '--families', 'copy,codec,batch')
        finally:
            self.mod.run_invocation = orig
        self.assertEqual(status, 0)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(c == calls[0] for c in calls), calls)
        argv = calls[0]
        self.assertEqual(argv[argv.index('--families') + 1], 'copy,codec,batch')
        self.assertEqual(argv[argv.index('--workers') + 1], '1')

    def test_an_unknown_family_is_refused_before_anything_runs(self):
        for families in ('copy,bogus', 'snapshot', '', 'copy,copy', 'copy,,codec'):
            status, data = self.run_ab('--families', families)
            self.assertEqual(status, 1, families)
            self.assertIn('error', data)
            self.assertEqual(self.invocations(), [], families)
        self.assertIn('unknown benchmark family bogus', self.run_ab('--families', 'copy,bogus')[1]['error'])

    def test_bad_commits_and_workers_are_refused(self):
        self.a = 'main'
        status, data = self.run_ab()
        self.assertEqual(status, 1)
        self.assertIn('is not a 40-digit commit', data['error'])
        self.a = 'a' * 40
        for workers in ('0', '1,1', 'x', '1,300'):
            status, data = self.run_ab('--families', 'batch', '--workers', workers)
            self.assertEqual(status, 1, workers)
        self.assertEqual(self.invocations(), [])

    def test_a_family_that_a_build_did_not_report_is_an_error(self):
        status, data = self.run_ab('--rounds', '1', '--families', 'copy,codec', env={'FAKE_OMIT': 'codec'})
        self.assertEqual(status, 1)
        self.assertIn('did not report: codec', data['error'])

    def test_a_binary_that_is_not_the_labelled_commit_is_an_error(self):
        status, data = self.run_ab('--rounds', '1', b_rev='c' * 40)
        self.assertEqual(status, 1)
        self.assertIn('is not the commit it is labelled with', data['error'])

    def test_errors_and_failures_of_the_bench_are_errors(self):
        status, data = self.run_ab('--rounds', '1', env={'FAKE_ERRORS': '2', 'FAKE_ERRORS_LABEL': 'a'})
        self.assertEqual(status, 1)
        self.assertIn('reported 2 error', data['error'])
        os.remove(self.log)
        status, data = self.run_ab('--rounds', '1', env={'FAKE_FAIL': 'b'})
        self.assertEqual(status, 1)
        self.assertIn('exited with status 3', data['error'])

    def test_validate_only_runs_nothing(self):
        out = self.out
        self.assertEqual(self.mod.main(['--validate-only', '--a-sha', self.a, '--b-sha', self.b, '--families', 'copy,codec',
                                        '--out', out]), 0)
        self.assertTrue(json.load(open(out))['validated'])
        self.assertEqual(self.mod.main(['--validate-only', '--a-sha', self.a, '--b-sha', self.b, '--families', 'nope',
                                        '--out', out]), 1)
        self.assertEqual(self.mod.main(['--a-sha', self.a, '--b-sha', self.b, '--out', out]), 1)  # no binaries given
        self.assertEqual(self.invocations(), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
