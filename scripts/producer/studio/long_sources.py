"""Prepare a separate native long-form project without altering a working pipeline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import file_hash, real_directory
from edit.selected_sources import prepare, read_package
from studio.long_sources_project import check_project, project_inputs, selection, write_project
from studio.native_preflight import preflight
from studio.native_stage_evidence import require, verify_pins


def prepare_project(project: Path, destination: Path, reuse_stage: Path | None = None) -> dict:
    """Use existing static checks and supervised preparation, then verify the isolated copy."""
    project, destination = project.resolve(strict=True), destination.absolute()
    real_directory(destination.parent)
    require(not destination.exists() and not destination.is_symlink()
            and not destination.is_relative_to(project) and not project.is_relative_to(destination),
            'long-form preparation needs a new destination outside the working project')
    workspace = destination.with_name(destination.name + '.preparation')
    workspace.mkdir(mode=0o700)
    before = preflight(project, workspace / 'original-preflight')
    require(before['status'] == 'static-checks-pass', 'original long-form static checks failed; working project was not changed')
    inputs = project_inputs(project)
    if reuse_stage:
        receipt = reuse_stage.resolve(strict=True)
        binding = {'path': str(receipt), 'sha256': file_hash(receipt)}
        result, _pins = read_package(binding)
    else:
        prepared = prepare(selection(inputs), workspace / 'media')
        binding = {key: prepared[key] for key in ('path', 'sha256')}
        result = prepared['summary']
    record = write_project(inputs, binding, destination)
    after = preflight(destination, workspace / 'prepared-preflight')
    require(after['status'] == 'static-checks-pass', 'prepared long-form static checks failed; inspect the separate project')
    check_project(destination)
    verify_pins(inputs['pins'])
    return {'status': 'prepared-awaiting-native-qc', 'project': str(destination), 'package': binding,
            'sourceBytes': result['sourceBytes'], 'preparedBytes': result['preparedBytes'],
            'mediaReused': reuse_stage is not None, 'mappedElements': len(record['mappings']),
            'preservedProgramAudio': inputs['preservedProgramAudio'], 'originalProjectUnchanged': True,
            'scope': 'Selected media and static compatibility only; final native render/review checks remain required'}


def main() -> None:
    """Make preparation explicit; preview opens only a cold-verified isolated project."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'check', 'preview'))
    parser.add_argument('project', type=Path)
    parser.add_argument('destination', type=Path, nargs='?')
    parser.add_argument('--reuse-stage', type=Path)
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    if args.operation == 'prepare':
        require(args.destination is not None, 'prepare needs a new destination')
        print(json.dumps(prepare_project(project, args.destination, args.reuse_stage)))
        return
    require(args.destination is None and args.reuse_stage is None, 'check/preview accepts only a project')
    record = check_project(project)
    if args.operation == 'preview':
        from studio.managed_preview import open_preview
        print(json.dumps(open_preview(str(project)).to_json()))
        return
    print(json.dumps({'status': 'prepared-project-current', 'project': str(project),
                      'mappedElements': len(record['mappings']), 'scope': record['status']}))


if __name__ == '__main__':
    main()
