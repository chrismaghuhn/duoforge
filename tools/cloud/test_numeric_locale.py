#!/usr/bin/env python3
"""The cloud launch scripts print decimals with a dot under any locale (tools/cloud/aws_fuzz, tools/cloud/p1_pilot).

printf and awk format decimals after LC_NUMERIC: under de_DE.UTF-8 they print 1,50, and a spot request with
MaxPrice=1,50 is wrong or refused. aws_fuzz/lib.sh, p1_pilot/lib.sh and aws_fuzz/chunks.sh set LC_NUMERIC=C when they
are sourced (and hand a set LC_ALL to the other categories, which LC_NUMERIC alone could not override). Here, offline:

 - the price, cost cap and request of both script sets read the same under de_DE.UTF-8 as under C.UTF-8, with a dot;
 - sourcing a lib changes LC_NUMERIC only: the other categories keep the caller's locale;
 - the guard suites of both script sets pass under LC_ALL=de_DE.UTF-8 (CTest runs them under the runner's locale).

Needs bash and the locales de_DE.UTF-8 and C.UTF-8; without them it reports itself skipped (DUOFORGE_SKIP), never
passed. To install the German one: sudo locale-gen de_DE.UTF-8."""
import os
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BASH = os.environ.get('DUOFORGE_BASH') or shutil.which('bash')
GERMAN = 'de_DE.UTF-8'
REFERENCE = 'C.UTF-8'
CATEGORIES = ('LC_CTYPE', 'LC_COLLATE', 'LC_MESSAGES', 'LC_MONETARY', 'LC_TIME', 'LC_PAPER', 'LC_NAME', 'LC_ADDRESS',
              'LC_TELEPHONE', 'LC_MEASUREMENT', 'LC_IDENTIFICATION')
LIBS = ('aws_fuzz/lib.sh', 'p1_pilot/lib.sh', 'aws_fuzz/chunks.sh')


def environment(**changes):
    env = {k: v for k, v in os.environ.items() if not (k.startswith('LC_') or k in ('LANG', 'LANGUAGE'))}
    env.update(changes)
    return env


def bash(script, **changes):
    r = subprocess.run([BASH, '-c', script], env=environment(**changes), capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise AssertionError('bash failed (%d): %s\n%s' % (r.returncode, script, r.stderr))
    return r.stdout


def lib(name):
    return '. "%s"' % os.path.join(HERE, name)


def missing_locales():
    """The locales the test needs that are not installed: glibc falls back to C silently for an unknown one."""
    missing = []
    if BASH is None:
        return ['bash']
    # bash's printf reads and writes decimals after the locale: 1,5 is a number under de_DE only
    probe = subprocess.run([BASH, '-c', 'printf %.2f 1,5'], env=environment(LC_ALL=GERMAN), capture_output=True, text=True)
    if probe.stdout != '1,50':
        missing.append(GERMAN)
    if bash('locale charmap', LC_ALL=REFERENCE).strip() != 'UTF-8':
        missing.append(REFERENCE)
    return missing


# Each prints what reaches the request or the summary of the launch: price, cost cap, the spot options.
AWS_FUZZ = lib('aws_fuzz/lib.sh') + r'''
df_max_price 2; echo
df_max_price 6; echo
df_max_price 12 24; echo
df_build_run_args ami-0 c7a.16xlarge subnet-0 sg-0 weather-sand-snow 2 '#!/bin/bash'
printf '%s\n' "${DF_RUN_ARGS[@]}" | grep MaxPrice
'''
P1_PILOT = lib('p1_pilot/lib.sh') + r'''
df_price2 1.5; echo
df_cost_cap 3 1.50; echo
df_cost_cap 4 0.37; echo
df_valid_price 1.50 && echo valid-1.50
df_valid_price 1.51 || echo refused-1.51
df_build_run_args ami-0 g6.4xlarge subnet-0 sg-0 run-0 "$(df_price2 1.5)" /dev/sda1 '#!/bin/bash'
printf '%s\n' "${DF_RUN_ARGS[@]}" | grep MaxPrice
'''


class NumericLocale(unittest.TestCase):
    def test_the_prices_and_cost_caps_have_a_dot_under_a_german_locale(self):
        expected = {
            'aws_fuzz': ['5.00', '1.67', '2.00',
                         'MarketType=spot,SpotOptions={SpotInstanceType=one-time,MaxPrice=5.00,'
                         'InstanceInterruptionBehavior=terminate}'],
            'p1_pilot': ['1.50', '4.50', '1.48', 'valid-1.50', 'refused-1.51',
                         'MarketType=spot,SpotOptions={SpotInstanceType=one-time,MaxPrice=1.50,'
                         'InstanceInterruptionBehavior=terminate}'],
        }
        for name, script in (('aws_fuzz', AWS_FUZZ), ('p1_pilot', P1_PILOT)):
            # LC_ALL as in the CTest, LANG alone as on the owner's machine, LC_NUMERIC alone as a mixed setup
            for how in ({'LC_ALL': GERMAN}, {'LANG': GERMAN}, {'LANG': REFERENCE, 'LC_NUMERIC': GERMAN}, {'LC_ALL': REFERENCE}):
                with self.subTest(scripts=name, locale=how):
                    self.assertEqual(bash(script, **how).splitlines(), expected[name])

    def test_sourcing_a_lib_changes_the_numbers_only(self):
        report = '; locale; printf "%.1f\\n" 2.5; awk "BEGIN { printf \\"%.1f\\n\\", 5 / 2 }"'
        for name in LIBS:
            for how in ({'LC_ALL': GERMAN}, {'LANG': GERMAN}):
                with self.subTest(lib=name, locale=how):
                    out = bash(lib(name) + report, **how).splitlines()
                    values = dict(line.split('=', 1) for line in out if '=' in line)
                    self.assertEqual(values['LC_NUMERIC'].strip('"'), 'C')
                    self.assertEqual(values['LC_ALL'], '')
                    for category in CATEGORIES:
                        self.assertEqual(values[category].strip('"'), GERMAN, category)
                    self.assertEqual(out[-2:], ['2.5', '2.5'])

    def test_the_guard_suites_pass_under_a_german_locale(self):
        for suite in ('aws_fuzz/test_guards.py', 'p1_pilot/tests/test_guards.py'):
            with self.subTest(suite=suite):
                r = subprocess.run([sys.executable, os.path.join(HERE, suite)], capture_output=True, text=True,
                                   timeout=500, env=environment(LC_ALL=GERMAN))
                self.assertEqual(r.returncode, 0, '%s under LC_ALL=%s:\n%s' % (suite, GERMAN, r.stderr[-6000:]))


if __name__ == '__main__':
    absent = missing_locales()
    if absent:
        print('DUOFORGE_SKIP: not installed: %s (locale -a; sudo locale-gen de_DE.UTF-8)' % ', '.join(absent))
        sys.exit(0)
    unittest.main()
