"""Prepare and verify reusable selected media beneath the shared native owner."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import bound_json, file_hash, real_directory, write_new
from edit.selected_sources_contract import selection_request, source_pins, source_sections
from edit.selected_sources_media import SectionJob, media_info, prepare_section
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig, local_environment
from studio.native_runtime import install_runtime
from studio.native_stage_evidence import StageEvidence, read_stage, require, seal_stage

STATUS = 'selected-sources-prepared'


def inventory(result: dict) -> dict[str, Path]:
    """Include every derived asset in the immutable completion record."""
    assets = {}
    for index, section in enumerate(result['sections']):
        for kind in ('video', 'audio'):
            if section[kind]:
                assets[f'{kind}{index}'] = Path(section[kind]['path'])
    return assets


def read_package(binding: dict) -> tuple[dict, dict[str, str]]:
    """Require completed ownership and unchanged sources, tools, receipts and media."""
    require(type(binding) is dict and set(binding) == {'path', 'sha256'}, 'invalid selected-source binding')
    receipt = Path(binding['path'])
    record = bound_json(receipt, binding['sha256'])
    record, pins = read_stage(receipt, record['inputs'], 'selected-sources')
    result = bound_json(Path(record['artifacts']['result']['path']), record['artifacts']['result']['sha256'])
    expected = {'result': Path(record['artifacts']['result']['path']), **inventory(result)}
    require({key: str(value) for key, value in expected.items()}
            == {key: row['path'] for key, row in record['artifacts'].items()}, 'selected-source inventory differs')
    return result, pins


def worker(request_path: Path) -> None:
    """Run sequential bounded selection after host admission, without provider access."""
    started = time.monotonic()
    request = bound_json(request_path)
    selected = selection_request(request['selection'])
    sources = {row['file']: row for row in selected['sources']}
    info = {key: media_info(Path(row['path']), request['tools']) for key, row in sources.items()}
    sections = source_sections(selected, {key: row['duration'] for key, row in info.items()})
    root = Path(request['output'])
    estimated = estimate_bytes(sections, sources, info)
    require(shutil.disk_usage(root).free > 10 * 1024 ** 3 + estimated * 2,
            'selected-source workspace would consume the 10 GiB disk reserve')
    prepared = [prepare_section(SectionJob(sources[row['sourceFile']], row,
                root / f'section-{index:03d}', request['tools']), info[row['sourceFile']])
                for index, row in enumerate(sections)]
    result = {'schemaVersion': 1, 'selection': selected, 'sections': prepared,
              'sourceBytes': sum(Path(row['path']).stat().st_size for row in sources.values()),
              'preparedBytes': sum(row[kind]['bytes'] for row in prepared for kind in ('video', 'audio') if row[kind]),
              'elapsedSeconds': time.monotonic() - started, 'additionalPictureEncodes': 0}
    write_new(root / 'result.json', result)


def estimate_bytes(sections: list, sources: dict, info: dict) -> int:
    """Budget copied packets, keyframe handles and stereo float audio before writing."""
    from fractions import Fraction
    return sum(int((Fraction(row['end']) - Fraction(row['start']) + 30)
                   * (Path(sources[row['sourceFile']]['path']).stat().st_size
                      / float(Fraction(info[row['sourceFile']]['duration'])) + 48000 * 8)) for row in sections)


def prepare(value: dict, destination: Path) -> dict:
    """Create a new isolated attempt and seal it only after supervised success."""
    selected = selection_request(value)
    destination = destination.absolute()
    real_directory(destination.parent)
    destination.mkdir(mode=0o700)
    control, root = destination / 'control', destination / 'run'
    control.mkdir(); root.mkdir()
    write_new(control / 'selection.json', selected)
    tools, environment = local_environment()
    cli = install_runtime() / 'dist/cli.js'
    sandbox = Path(__file__).parents[1] / 'studio/native_localhost_only.sb'
    files = [*Path(__file__).parent.glob('selected_sources*.py'), Path(__file__).parents[1] / 'cut_preview_io.py',
             Path(__file__).parents[1] / 'studio/native_stage_evidence.py', Path(sys.executable).resolve(),
             *map(Path, tools.values())]
    pins = {**source_pins(selected), **{str(file): file_hash(file) for file in files}}
    request = {'project': str(control), 'output': str(root), 'selection': selected, 'tools': tools, 'pins': pins}
    request_path = root / 'request.json'
    write_new(request_path, request)
    settings = NativeRunConfig(project=control, root=root, cli=cli, environment=environment,
        command=['/usr/bin/sandbox-exec', '-f', str(sandbox), sys.executable, str(Path(__file__).resolve()),
                 'worker', str(request_path)],
        admission={'output': str(root / 'result.json'), 'sdkSha256': file_hash(cli), 'sandboxSha256': file_hash(sandbox)},
        additional_pins={**pins, str(request_path): file_hash(request_path)}, success_status=STATUS)
    owner = NativeRun('selected-sources', settings)
    require(owner.execute(), f'selected-source preparation failed; inspect {owner.path}')
    result = bound_json(root / 'result.json')
    seal_stage(StageEvidence('selected-sources', control, root, request_path, owner.path, pins,
                             {'result': root / 'result.json', **inventory(result)}, STATUS))
    receipt = root / 'selected-sources-stage.json'
    return {'path': str(receipt), 'sha256': file_hash(receipt), 'summary': result}


def main() -> None:
    """Expose explicit new preparation and read-only completed-package validation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'check', 'worker'))
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path, nargs='?')
    args = parser.parse_args()
    args.input = args.input.absolute()
    if args.operation == 'worker':
        worker(args.input)
        return
    if args.operation == 'check':
        result, pins = read_package({'path': str(args.input), 'sha256': file_hash(args.input)})
        print(json.dumps({'result': result, 'pins': pins}))
        return
    require(args.output is not None, 'preparation needs a new output directory')
    print(json.dumps(prepare(bound_json(args.input), args.output)))


if __name__ == '__main__':
    main()
