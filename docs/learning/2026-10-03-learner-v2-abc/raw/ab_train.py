"""Throughput A/B of the PPO update: `host` runs train with ppo._update_host
(every minibatch cut on the host, decision 0014), `scan` with ppo.update
(samples on the device once, one jitted scan). Everything else is the same
code. usage: python ab_train.py host|scan <train options...>"""
import sys

from duoforge_learn import ppo, train

arm = sys.argv[1]
if arm == "host":
    ppo.update = ppo._update_host
elif arm != "scan":
    raise SystemExit(f"arm {arm!r}: host or scan")
sys.exit(train.main(sys.argv[2:]))
