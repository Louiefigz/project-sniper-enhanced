"""Supervise exact cache-directory aliases without changing sealed native inputs."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import bound_json, real_directory, write_new
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig, local_environment
from studio.native_runtime import digest
from studio.native_short_resume import media_result
from studio.native_short_sdk_picture_reuse import sdk_picture_reuse_pins
from studio.native_stage_evidence import read_stage, require, verify_pins

HERE = Path(__file__).resolve().parent
WORKER = HERE / 'source_cache_alias.mjs'
STATUS = 'source-cache-aliases-prepared'


def verify_alias_links(result: dict) -> None:
    """Reobserve actual link identity after the worker and owned cleanup finish."""
    for row in result['aliases']:
        target, source = Path(row['targetEntry']), Path(row['sourceEntry'])
        stat = target.lstat()
        require({'device': str(stat.st_dev), 'inode': str(stat.st_ino)} == row['linkIdentity'],
                'cache alias identity changed after owned preparation')
        require(target.resolve(strict=True) == source and source.resolve(strict=True) == source,
                'cache alias target changed after preparation')
        require(target == source or (target.is_symlink() and target.readlink() == source),
                'cache alias was replaced by other content')


def prepare(receipt: Path, output: Path) -> tuple[dict, Path]:
    """Bind a completed audio/video seal plus the original validated SDK donor."""
    receipt = receipt.resolve(strict=True)
    sealed = bound_json(receipt)
    record, pins = read_stage(receipt, sealed['inputs'], 'render')
    media_result(record)
    original = bound_json(Path(record['request']['path']), record['request']['sha256'])
    require(original.get('captureMode') == 'sdk-streaming' and bool(original.get('pictureDonor')),
            'cache aliases require completed SDK donor recovery')
    project, donor = Path(original['project']), Path(original['pictureDonor'])
    previous = bound_json(donor / 'export-request.json')
    pins.update(sdk_picture_reuse_pins(project, donor))
    require(record['artifacts']['picture']['sha256'] == pins[str(donor / 'picture.mp4')],
            'completed recovery picture differs from its donor')
    real_directory(output.parent)
    roots = [project, donor, Path(record['root']), Path(previous['project'])]
    require(not output.exists() and not output.is_symlink()
            and all(output != root and not output.is_relative_to(root) and not root.is_relative_to(output) for root in roots),
            'alias evidence needs a fresh disjoint directory')
    cache, donor_cache = Path(original['cache']), Path(previous['cache'])
    real_directory(cache); real_directory(donor_cache)
    output.mkdir(mode=0o700)
    request = {'schemaVersion': 1, 'root': str(output), 'project': str(project),
               'donorProject': previous['project'], 'cache': str(cache), 'donorCache': str(donor_cache),
               'runtime': original['runtime'], 'renderStage': str(receipt), 'pins': pins}
    file = output / 'request.json'
    write_new(file, request)
    return request, file


def execute(receipt: Path, output: Path) -> dict:
    """Use the existing exclusive heavy-work owner; no media extraction or encoding."""
    request, file = prepare(receipt, output)
    tools, environment = local_environment()
    original = bound_json(Path(bound_json(receipt)['request']['path']))
    require(tools == original['tools'], 'cache alias tools differ from the sealed runtime')
    cli, sandbox = Path(request['runtime']) / 'dist/cli.js', HERE / 'native_localhost_only.sb'
    pins = {**request['pins'], **{str(path): digest(path) for path in (Path(__file__), WORKER, file)}}
    settings = NativeRunConfig(Path(request['project']), output, cli,
        ['/usr/bin/sandbox-exec', '-f', str(sandbox), tools['node'], str(WORKER), str(file)], environment,
        {'output': str(output / 'result.json'), 'sdkSha256': digest(cli), 'sandboxSha256': digest(sandbox)},
        additional_pins=pins, deadline=300, success_status=STATUS)
    owner = NativeRun('source-cache-alias', settings)
    require(owner.execute(), 'cache alias owner failed; preserve the attempt')
    result = bound_json(output / 'result.json')
    require(owner.result.get('cleanup', {}).get('verified') is True
            and owner.result.get('leaseCleanupVerified') is True and result.get('status') == STATUS,
            'cache alias preparation or cleanup is incomplete')
    verify_pins(pins)
    require(digest(output / 'alias-plan.json') == result['aliasPlanSha256'], 'alias plan changed after preparation')
    verify_alias_links(result)
    record = {**result, 'ownerReceipt': str(owner.path), 'ownerSha256': digest(owner.path),
              'request': str(file), 'requestSha256': digest(file), 'renderStage': str(receipt),
              'renderStageUnchanged': digest(receipt) == request['pins'][str(receipt)],
              'scope': 'Only cache-directory links were added. Full native/encoded QC remains required.'}
    write_new(output / 'completion.json', record)
    return record


def main() -> None:
    """Prepare cache aliases before unchanged --verify-from resumes the checked media."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('render_stage', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = execute(args.render_stage.resolve(strict=True), args.output.absolute())
    print({'status': result['status'], 'aliases': len(result['aliases']), 'completion': str(args.output / 'completion.json')})


if __name__ == '__main__':
    main()
