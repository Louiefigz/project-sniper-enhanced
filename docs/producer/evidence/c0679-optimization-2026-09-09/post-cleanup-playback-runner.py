"""Run one 0–65-second stock Studio observation under the shared native guard.

No render, source mutation, screenshots, audio remaster or additional preview
server is requested. The result preserves telemetry failures and child cleanup.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PREPARATION = Path(__file__).resolve().parent
RECOVERY = PREPARATION.parent
LIVE = Path('/Users/maintainer/ProjectSniperSource')
sys.path.insert(0, str(RECOVERY))
sys.path.insert(0, str(LIVE / 'scripts/producer'))

from native_bounded_config import CHROME, CLI, NODE, PROJECT, SANDBOX, digest, environment
from native_render_resources import ResourcePolicy
from render_native_bounded import NativeRun


def settings(label: str) -> dict:
    """Prepare metadata/config only; explicit execution owns the heavy lease."""
    if not re.fullmatch(r'[a-z0-9-]+', label):
        raise ValueError('Use a new lowercase attempt label')
    directory = PREPARATION / label
    directory.mkdir(mode=0o700, exist_ok=False)
    output = directory / 'playback.json'
    config = directory / 'config.json'
    config.write_text(json.dumps({'url':'http://127.0.0.1:41058/#project/native-presenter-v1',
        'chrome':str(CHROME), 'puppeteerDir':str(LIVE / 'templates/motion/node_modules/puppeteer-core'),
        'output':str(output)}, indent=2)+'\n')
    script = PREPARATION / 'observe-playback.cjs'
    pins = {str(path): digest(path) for path in (script, Path(__file__), config,
            RECOVERY / 'render_native_bounded.py', LIVE / 'scripts/producer/native_work_lease.py')}
    admission = {'output':str(output),'sdkSha256':digest(CLI),'sandboxSha256':digest(SANDBOX),
                 'sourceProgramDuration':683.7664166666667,'observationStart':0,'observationEnd':65,
                 'browserSha256':digest(CHROME),'jobKind':'studio-playback-observation'}
    return {'root':directory,'project':PROJECT,'cli':CLI,'deadline':135,
            'admission':admission,'additional_pins':pins,'environment':environment(),
            'policy':ResourcePolicy(maximum_owned_gib=4,maximum_process_gib=3,maximum_swap_growth_gib=1),
            'command':['/usr/bin/sandbox-exec','-f',str(SANDBOX),str(NODE),str(script),str(config)]}


def execute(label: str) -> dict:
    """Keep raw lifecycle receipts separate from observed playback quality."""
    values = settings(label)
    job = NativeRun(label, settings=values)
    job.path = values['root'] / 'supervisor.json'
    job.result.update(jobKind='studio-playback-observation',renderOnlyTiming=False,probeOnlyTiming=True)
    job.execute()
    raw_status = job.result['status']
    job.result['executionStatusBeforeProbeClassification'] = raw_status
    job.result['status'] = 'probe-completed-awaiting-review' if raw_status == 'rendered-awaiting-output-qc' else 'probe-failed'
    job.persist()
    return {'status':job.result['status'],'directory':str(values['root']),
            'cleanup':job.result.get('cleanup'),'elapsedSeconds':job.result['elapsedSeconds']}


def main() -> None:
    """Require an explicit run switch so preparation cannot accidentally launch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    parser.add_argument('--execute',action='store_true')
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'status':'prepared-not-started','seconds':65,'exclusiveHeavyLeaseRequired':True}))
        return
    print(json.dumps(execute(args.label)))


if __name__ == '__main__':
    main()
