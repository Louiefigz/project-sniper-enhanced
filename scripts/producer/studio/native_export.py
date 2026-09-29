"""Route native exports and enforce their shared supervised launch contract.

The same boundary binds the sealed audio stage's worker to its live owner: the
supervisor names the closed ``stage-request.json`` (never an export request) in
the child environment; the worker's side of that contract is
``native_audio_owner.require_owned_audio_worker``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import ArtifactReplaced, bound_json
from studio.native_runtime import digest
from studio.native_stage_evidence import require

if TYPE_CHECKING:
    from studio.native_run_config import NativeRunConfig

HERE = Path(__file__).resolve().parent
REQUEST_ENV = 'SNIPER_NATIVE_EXPORT_REQUEST'
OWNER_ENV = 'SNIPER_NATIVE_EXPORT_OWNER'
PID_ENV = 'SNIPER_NATIVE_EXPORT_PID'
AUDIO_REQUEST_ENV = 'SNIPER_NATIVE_AUDIO_REQUEST'
BINDING_ENV = (REQUEST_ENV, AUDIO_REQUEST_ENV, OWNER_ENV, PID_ENV)
AUDIO_WORKER = HERE / 'native_audio_stage.py'
AUDIO_SCOPE = 'native-short-audio-stage-request'
SANDBOX_PREFIX = ('/usr/bin/sandbox-exec', '-f')
OWNER_READ_ATTEMPTS = 5  # Each retry follows one completed owner publication.


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
    from studio.native_preview_sections import section_phase
    section = section_phase(phase)
    audio_package = adapter == 'native-short' and section and section[0] == 'package'
    require(settings.lane == ('audio' if audio_package else 'heavy'), 'Native worker resource class differs')
    if adapter == 'native-short':
        from studio.native_short_draft import admit_draft_launch
        admit_draft_launch(request, phase)
    if adapter == 'native-long':
        from studio.native_long_chunks import require_chunk_request
        require_chunk_request(request)
    from studio.native_long_scope import require_scope_request
    require_scope_request(request, phase)
    from graphics.visual_source_project import admit_project_sources
    admit_project_sources(settings.project)
    require(settings.additional_pins.get(str(file)) == digest(file)
            and settings.additional_pins.get(str(worker)) == digest(worker), 'Native export worker/request is unpinned')
    final_picture = phase in {'picture', 'render'} or phase.startswith('segment-picture-')
    if adapter == 'native-long' and final_picture:
        require(bound_json(settings.root / 'sample-qc/result.json').get('passed') is True,
                'Long picture requires passed encoded seam samples')
    if final_picture and not request.get('verifyStage'):
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
    if not long:
        from studio.native_short_draft import LAUNCH_OUTPUTS
        outputs.update(LAUNCH_OUTPUTS)
    from studio.native_preview_sections import section_phase, section_output
    if section_phase(phase):
        outputs[phase] = section_output(phase)
    from studio.native_segments.owners import segment_phase, segment_output
    if segment_phase(phase) is not None:
        require(long and request.get('revision', {}).get('mode') == 'initial-long',
                'segment workers require an admitted initial Long section plan')
        outputs[phase] = segment_output(phase)
    from studio.native_segments.review_scopes import package_phase, phase_scope
    if package_phase(phase):
        require(long and request.get('productionBudget', {}).get('familyInvocation'),
                'review package requires its original Long section family')
        phase_scope(request, phase)
        outputs[phase] = f'{phase}.json'
    require(phase in outputs and (long or phase != 'picture')
            and settings.command == ['/usr/bin/sandbox-exec', '-f', str(settings.sandbox), *child]
            and settings.admission['output'] == str(settings.root / outputs[phase]),
            'Native work must run through the shared export worker, not a custom wrapper')
    return phase, worker


def validate_audio_launch(settings: NativeRunConfig) -> Path | None:
    """Close the audio-stage worker's command, request, output, lane and pins before admission.

    Returns None for owners that do not run the audio worker; any launch naming it must
    match the one command ``native_audio_stage.owner_config`` builds for its own request.
    """
    if not any(Path(part).name == AUDIO_WORKER.name for part in settings.command):
        return None
    from studio.native_audio_seal import REQUEST_NAME, RESULT_NAME
    file = settings.root / REQUEST_NAME
    require(file.is_file() and not file.is_symlink(), 'Native audio worker requires its stage-request.json')
    request = bound_json(file)
    require(request.get('scope') == AUDIO_SCOPE and request.get('stageRoot') == str(settings.root)
            and request.get('project') == str(settings.project) and request.get('leaseClass') == settings.lane,
            'Native audio request does not bind this stage, project and pool class')
    require(settings.command == [*SANDBOX_PREFIX, str(settings.sandbox), sys.executable, str(AUDIO_WORKER),
                                 'worker', str(file)]
            and settings.admission['output'] == str(settings.root / RESULT_NAME),
            'Native audio work must run through the shared audio-stage worker, not a custom wrapper')
    pins = {**request['pins'], str(file): digest(file)}
    require(all(settings.additional_pins.get(path) == value for path, value in pins.items()),
            'Native audio worker/request is unpinned')
    return file


def launch_binding(settings: NativeRunConfig) -> tuple[str, Path] | None:
    """Validate one native launch and name the request variable its child must bind.

    Exports bind ``export-request.json``; the audio stage binds its closed audio request.
    Supporting utilities (review bundles, cache aliases) bind neither.
    """
    if validate_export_launch(settings) is not None:
        return REQUEST_ENV, settings.root / 'export-request.json'
    audio = validate_audio_launch(settings)
    return None if audio is None else (AUDIO_REQUEST_ENV, audio)


def require_owned_worker(request: dict) -> None:
    """Direct worker CLIs cannot omit the live owner or substitute its request."""
    file = Path(request['output']) / 'export-request.json'
    require(os.environ.get(REQUEST_ENV) == str(file), 'Native worker requires the shared export supervisor')
    owner = active_owner_snapshot(Path(os.environ[OWNER_ENV]))
    require(owner.get('additionalFilePinsBefore', {}).get(str(file)) == digest(file)
            and owner.get('project') == request['project'] and not owner.get('completedAt'),
            'Native worker owner does not bind the current request')
    pid = int(os.environ.get(PID_ENV, '0'))
    require(pid > 1, 'Native worker has no live supervisor')
    os.kill(pid, 0)


def active_owner_snapshot(file: Path) -> dict:
    """Reopen only when the owner renamed a new receipt over the one being read.

    ``NativeRun.persist`` publishes each complete snapshot by rename, so a worker that
    opened the previous receipt finds it unlinked. That read is discarded and the path
    reopened and fully revalidated, at most ``OWNER_READ_ATTEMPTS`` times in all. An
    in-place change, a missing, linked or malformed receipt fails at once, and bytes of
    a replaced receipt are never returned.
    """
    for _ in range(OWNER_READ_ATTEMPTS - 1):
        try:
            return bound_json(file)
        except ArtifactReplaced:
            continue
    return bound_json(file)


def worker_environment(settings: NativeRunConfig, owner_file: Path) -> dict[str, str]:
    """Bind the child to the live owner and its exact immutable request; never inherit a binding."""
    environment = {key: value for key, value in settings.environment.items() if key not in BINDING_ENV}
    binding = launch_binding(settings)
    if binding is not None:
        environment.update({binding[0]: str(binding[1]), OWNER_ENV: str(owner_file), PID_ENV: str(os.getpid())})
    return environment


def main() -> None:
    """Forward adapter options unchanged; malformed/ambiguous projects never fall back."""
    if len(sys.argv) == 3 and sys.argv[1] == 'source-input':
        import json
        from graphics.visual_source_project import describe_project
        print(json.dumps(describe_project(Path(sys.argv[2]).resolve(strict=True)), indent=2))
        return
    if len(sys.argv) == 5 and sys.argv[1] == 'section-review-input':
        import json
        from studio.native_long_scope import scope_for_project
        from studio.native_long_prebuild import prebuild_snapshot
        project = Path(sys.argv[2]).resolve(strict=True)
        scope = scope_for_project(project, Path(sys.argv[3]).resolve(strict=True), sys.argv[4])
        print(json.dumps({**prebuild_snapshot(project, scope), 'sectionScope': scope}, indent=2))
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
