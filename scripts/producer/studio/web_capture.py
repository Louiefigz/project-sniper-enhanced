"""Supervise public website/repository B-roll acquisition separately from offline export."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_render_resources import ResourcePolicy
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig, local_environment
from studio.native_runtime import REPO, digest


def execute(args: argparse.Namespace) -> bool:
    """Use the same memory/ownership gates for a fresh public browser and encoder."""
    plan_path = args.plan.resolve(strict=True)
    plan = json.loads(plan_path.read_text())
    output = args.output.absolute()
    output.mkdir(mode=0o700)
    tools, environment = local_environment()
    request = output / 'request.json'
    request.write_text(json.dumps({'plan': plan, 'output': str(output), 'tools': tools}, indent=2))
    script = Path(__file__).with_suffix('.mjs')
    sandbox = Path(__file__).with_name('web_capture.sb')
    pins = [plan_path, request, script, sandbox, script.with_name('web_capture_policy.mjs')]
    pins += [Path(value) for value in tools.values()]
    policy = ResourcePolicy(maximum_owned_gib=4, maximum_process_gib=3, maximum_swap_growth_gib=1)
    settings = NativeRunConfig(REPO, output, script,
        ['/usr/bin/sandbox-exec', '-f', str(sandbox), tools['node'], str(script), str(request)], environment,
        {'output': str(output / 'capture.json'), 'sdkSha256': digest(script), 'sandboxSha256': digest(sandbox)},
        sandbox=sandbox, policy=policy, deadline=240, compressor_admission='short-headroom',
        additional_pins={str(file): digest(file) for file in pins},
        success_status='public-web-capture-awaiting-editorial-review', unused_ram_advisory=args.unused_ram_advisory)
    if not NativeRun('capture', settings).execute():
        return False
    if plan['mode'] == 'capture':
        write_binding(output, tools['node'])
    return True


def verified_binding(candidate: object, binding: dict, output: Path, node: str) -> dict:
    """Require exact adapter output and reread its immutable origin through shared TS validation."""
    if not isinstance(candidate, dict) or set(candidate) != set(binding) | {'origin'}:
        raise ValueError('Origin adapter returned an incomplete asset binding')
    origin = candidate['origin']
    if not isinstance(origin, dict) or set(origin) != {'path', 'sha256'} \
            or origin['path'] != str(output / 'ASSET-ORIGIN.json') \
            or any(candidate[key] != value for key, value in binding.items()):
        raise ValueError('Origin adapter changed the captured asset or requested origin path')
    reader = ("const { readFileSync } = require('node:fs');"
              "const { readNativeAssetOrigin } = require('./src/lib/server/native-short-asset-use-origins.ts');"
              "readNativeAssetOrigin(JSON.parse(readFileSync(0,'utf8')));")
    subprocess.run([node, '--import', 'tsx', '--eval', reader],
                   cwd=REPO, input=json.dumps(candidate), text=True,
                   capture_output=True, check=True, timeout=60)
    return candidate


def write_binding(output: Path, node: str) -> None:
    """Emit the exact frozen asset binding consumed by native Short assembly."""
    output = output.resolve(strict=True)
    receipt = output / 'capture.json'
    evidence = json.loads(receipt.read_text())
    if evidence['status'] != 'captured-for-review':
        raise ValueError('Cannot admit an incomplete web capture')
    video = output / 'capture.mp4'
    supervision = output / 'capture.render.json'
    binding = {'file': f'assets/{digest(video)}.mp4', 'path': str(video), 'sha256': digest(video),
               'role': 'supporting-video', 'webCapture': {'path': str(receipt), 'sha256': digest(receipt),
               'supervisionPath': str(supervision), 'supervisionSha256': digest(supervision)}}
    technical = output / 'CAPTURE-ASSET.json'
    technical.write_text(json.dumps(binding, indent=2))
    command = [node, '--import', 'tsx', str(REPO / 'scripts/producer/native-short.ts'),
               'origin-web', str(technical), str(output / 'ASSET-ORIGIN.json')]
    result = subprocess.run(command, cwd=REPO, text=True, capture_output=True, check=True, timeout=60)
    candidate = verified_binding(json.loads(result.stdout), binding, output, node)
    content = json.dumps(candidate, indent=2)
    with (output / 'ASSET.json').open('x') as handle:
        handle.write(content)


def main() -> None:
    """Run one bounded plan; inspect first, then capture into a fresh attempt folder."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--unused-ram-advisory', action='store_true')
    raise SystemExit(0 if execute(parser.parse_args()) else 1)


if __name__ == '__main__':
    main()
