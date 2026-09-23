"""Route native exports and enforce their shared supervised launch contract."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import bound_json
from studio.native_runtime import digest
from studio.native_stage_evidence import require

if TYPE_CHECKING:
    from studio.native_run_config import NativeRunConfig

HERE = Path(__file__).resolve().parent
REQUEST_ENV = 'SNIPER_NATIVE_EXPORT_REQUEST'
OWNER_ENV = 'SNIPER_NATIVE_EXPORT_OWNER'


def native_project(project: Path) -> bool:
    """Recognize authored native packages even when their plan is missing."""
    return any((project / name).exists() for name in
               ('index.html', 'LONG-PROJECT.json', 'SHORT-PROJECT.json'))


def export_adapter(project: Path) -> str:
    """Require one explicit contract; never reinterpret legacy or incomplete HTML."""
    plans = [name for name in ('LONG-PROJECT.json', 'SHORT-PROJECT.json')
             if (project / name).exists() or (project / name).is_symlink()]
    require(len(plans) == 1, 'Native export needs exactly one LONG-PROJECT.json or SHORT-PROJECT.json; '
            'use studio/native_export.py after declaring the project contract')
    require(not (project / plans[0]).is_symlink(), 'Native export plan cannot be a symlink')
    return 'native-long' if plans[0] == 'LONG-PROJECT.json' else 'native-short'


def validate_export_launch(settings: NativeRunConfig) -> dict | None:
    """Reject custom native render wrappers before resource admission or child launch."""
    if not native_project(settings.project):
        return None
    # Dedicated inspection/cache utilities are not master export entry points.
    file = settings.root / 'export-request.json'
    if not file.exists() and Path(settings.admission['output']).suffix.lower() not in {'.mp4', '.mov', '.webm', '.mkv'}:
        return None
    adapter = export_adapter(settings.project)
    require(file.is_file(), 'Native video work requires the shared exporter; use studio/native_export.py')
    request = bound_json(file)
    require(request.get('adapter', 'native-short') == adapter
            and request.get('project') == str(settings.project)
            and request.get('output') == str(settings.root)
            and Path(request['runtime']) / 'dist/cli.js' == settings.cli,
            'Native export request does not bind this project, output and runtime')
    phase, worker = admitted_worker(settings, request, file)
    from graphics.visual_source_project import admit_project_sources
    admit_project_sources(settings.project)
    require(settings.additional_pins.get(str(file)) == digest(file)
            and settings.additional_pins.get(str(worker)) == digest(worker), 'Native export worker/request is unpinned')
    if adapter == 'native-long' and phase in {'picture', 'render'}:
        require(bound_json(settings.root / 'sample-qc/result.json').get('passed') is True,
                'Long picture requires passed encoded seam samples')
    if phase in {'picture', 'render'} and not request.get('verifyStage'):
        from studio.native_motion_previews import require_motion_previews
        require_motion_previews(request)
    return request


def admitted_worker(settings: NativeRunConfig, request: dict, file: Path) -> tuple[str, Path]:
    """Close the command/phase/output vocabulary at the common launch boundary."""
    long = request.get('adapter') == 'native-long'
    short_capture = not long and settings.command[-1:] == [str(file)]
    phase = 'capture' if short_capture else settings.command[-1]
    worker = HERE / ('native_long_worker.py' if long else
                     'native_short_capture.mjs' if short_capture else 'native_short_worker.py')
    interpreter = request['tools']['node'] if short_capture else sys.executable
    child = [interpreter, str(worker), str(file), *([] if short_capture else [phase])]
    outputs = {'capture': 'native-frames.json', 'preview': 'motion-previews.json',
               'picture': 'picture.mp4', 'render': 'review.mp4', 'verify': 'checks.json'}
    from studio.native_preview_sections import section_phase, section_output
    if section_phase(phase):
        outputs[phase] = section_output(phase)
    require(phase in outputs and (long or phase != 'picture')
            and settings.command == ['/usr/bin/sandbox-exec', '-f', str(settings.sandbox), *child]
            and settings.admission['output'] == str(settings.root / outputs[phase]),
            'Native work must run through the shared export worker, not a custom wrapper')
    return phase, worker


def require_owned_worker(request: dict) -> None:
    """Direct worker CLIs cannot omit the live owner or substitute its request."""
    file = Path(request['output']) / 'export-request.json'
    require(os.environ.get(REQUEST_ENV) == str(file), 'Native worker requires the shared export supervisor')
    owner = active_owner_snapshot(Path(os.environ[OWNER_ENV]))
    require(owner.get('additionalFilePinsBefore', {}).get(str(file)) == digest(file)
            and owner.get('project') == request['project'] and not owner.get('completedAt'),
            'Native worker owner does not bind the current request')
    pid = int(os.environ.get('SNIPER_NATIVE_EXPORT_PID', '0'))
    require(pid > 1, 'Native worker has no live supervisor')
    os.kill(pid, 0)


def active_owner_snapshot(file: Path) -> dict:
    """Retry only an observed atomic owner replacement, never malformed or stale evidence."""
    for attempt in range(3):
        try:
            return bound_json(file)
        except RuntimeError as error:
            if attempt == 2 or 'artifact changed during read' not in str(error):
                raise
    raise RuntimeError('Native owner snapshot unavailable')


def worker_environment(settings: NativeRunConfig, owner_file: Path) -> dict[str, str]:
    """Bind SDK render admission to the live owner and its exact immutable request."""
    environment = dict(settings.environment)
    environment.pop(REQUEST_ENV, None)
    environment.pop(OWNER_ENV, None)
    environment.pop('SNIPER_NATIVE_EXPORT_PID', None)
    if validate_export_launch(settings) is not None:
        environment.update({REQUEST_ENV: str(settings.root / 'export-request.json'),
                            OWNER_ENV: str(owner_file), 'SNIPER_NATIVE_EXPORT_PID': str(os.getpid())})
    return environment


def main() -> None:
    """Forward adapter options unchanged; malformed/ambiguous projects never fall back."""
    if len(sys.argv) == 3 and sys.argv[1] == 'source-input':
        import json
        from graphics.visual_source_project import describe_project
        print(json.dumps(describe_project(Path(sys.argv[2]).resolve(strict=True)), indent=2))
        return
    if len(sys.argv) == 3 and sys.argv[1] == 'review-input':
        import json
        from studio.native_long_prebuild import prebuild_snapshot
        print(json.dumps(prebuild_snapshot(Path(sys.argv[2]).resolve(strict=True)), indent=2))
        return
    if len(sys.argv) < 3 or sys.argv[1] in ('-h', '--help'):
        print('Usage: native_export.py PROJECT NEW_ATTEMPT [adapter options]\n'
              'The project must declare LONG-PROJECT.json or SHORT-PROJECT.json.\n'
              'Use native_long_export.py --help or native_short_export.py --help for options.')
        raise SystemExit(0 if len(sys.argv) == 2 else 2)
    project = Path(sys.argv[1]).resolve(strict=True)
    if export_adapter(project) == 'native-long':
        from studio.native_long_export import main as export
    else:
        from studio.native_short_export import main as export
    export()


if __name__ == '__main__':
    main()
