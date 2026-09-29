"""Supervised whole-program audio preparation for a built native Short.

``prepare <project> <new-stage-dir>`` freezes the audio-input contract, runs the
shared dialogue premaster and float mastering (``prepare_dialogue``) as one
NativeRun owner with verified cleanup, resource sampling and a deadline, then
seals the result for identity-bound reuse by native exports. ``check <stage>``
re-verifies a seal. The internal ``worker`` starts no DSP unless the live, admitted
owner bound to its exact request launched it (``native_audio_owner.require_owned_audio_worker``),
and publishes no result once that supervisor is no longer its parent; a direct call is
refused with exit status 2 and writes nothing. No picture is rendered;
no editorial or listening approval is claimed. Exit status: 0 sealed/valid, 1 audio
stage failed, 2 invalid use or refused worker.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio.mastering_profile import MASTERING_PROFILE_IDENTITIES, NATIVE_SHORT_MASTERING_PROFILE
from audit.audit_checks import FAIL
from cut_preview_io import bound_json, real_directory, write_new
from studio.native_audio_contract import (
    CORE_IMPLEMENTATION, PRODUCER, audio_input_contract, audio_input_identity, executed_implementation,
)
from studio.native_audio_seal import (
    FAILED_NAME, OWNER_NAME, REQUEST_NAME, RESULT_NAME, STATUS_PREPARED, WORKER_FAILURE,
    read_sealed_stage, seal_stage,
)
from studio.native_audio_owner import (NativeOwnerRefused, refusal_line, require_live_supervisor,
                                        require_owned_audio_worker, worker_refusal)
from studio.native_runtime import digest
from studio.native_stage_evidence import require, verify_pins

STUDIO = Path(__file__).resolve().parent
LEASE_CLASS = 'audio'  # ffmpeg-only work; never waits behind browser renders in a qualified pool
DEFAULT_WORK_SECONDS = 300.0
DEFAULT_CAPACITY_WAIT_SECONDS = 600.0


class AudioStageFailure(RuntimeError):
    """The supervised audio stage failed; its failure record stays in the stage root."""

    def __init__(self, record: dict) -> None:
        """Carry the stage failure for export receipts without implying picture failure.

        A host condition (a capacity wait, memory pressure, cancellation) keeps the owner's
        own category, so the budget treats it as transient rather than as a failed check; a
        worker refused by the owner gate keeps its refusal category for every reader.
        """
        from studio.native_budget_launch import TRANSIENT
        owner = record.get('failureCategory')
        self.phase, self.record = 'audio-stage', record
        self.category = owner if owner in TRANSIENT or record.get('workerRefused') else 'audio-stage-failure'
        super().__init__(f"Native audio stage failed before any picture work: {record.get('error')}")


@dataclass(frozen=True)
class AudioStagePlan:
    """One explicit audio stage; bounds come from the caller and, inside an export, its budget."""

    project: Path
    root: Path
    profile: str = NATIVE_SHORT_MASTERING_PROFILE.identity
    work_seconds: float = DEFAULT_WORK_SECONDS
    capacity_wait_seconds: float = DEFAULT_CAPACITY_WAIT_SECONDS
    runtime: Path | None = None
    export_request: dict | None = None  # the export this stage runs inside; None when standalone


def audio_stage_lease_class() -> str:
    """Return the lease class for audio-only owners (the single POOL wiring point)."""
    return LEASE_CLASS


def input_pins(project: Path, tools: dict[str, str]) -> dict[str, str]:
    """Pin every project, tool and implementation file the audio worker reads."""
    plan = bound_json(project / 'SHORT-PROJECT.json')
    manifest = bound_json(project / 'PROJECT-MANIFEST.json')
    names = {'SHORT-PROJECT.json', 'PROJECT-MANIFEST.json'}
    names.update(row['file'] for row in manifest['files'] if row['file'].endswith('.wav'))
    if plan.get('preparedSources'):
        names.add('PREPARED-SOURCES.json')
    else:
        names.add(plan['canvas']['sourceFile'])
    files = [project / name for name in names]
    files += [Path(tools['ffmpeg']).resolve(), Path(tools['ffprobe']).resolve(), Path(sys.executable).resolve()]
    files += [PRODUCER / name for name in CORE_IMPLEMENTATION]
    return {str(file): digest(file) for file in sorted(set(files))}


def stage_request(plan: AudioStagePlan, project: Path, tools: dict[str, str]) -> dict:
    """Freeze the exact contract, tools, bounds and lease class before the owner starts."""
    contract = audio_input_contract(project, plan.profile, tools)
    return {'schemaVersion': 1, 'scope': 'native-short-audio-stage-request', 'project': str(project),
            'stageRoot': str(plan.root), 'output': str(plan.root / 'work'), 'tools': tools,
            'audioProfile': plan.profile, 'audioInput': contract,
            'audioInputSha256': audio_input_identity(contract), 'leaseClass': audio_stage_lease_class(),
            'workSeconds': plan.work_seconds, 'capacityWaitSeconds': plan.capacity_wait_seconds,
            'pins': input_pins(project, tools)}


def owner_config(plan: AudioStagePlan, request_file: Path, environment: dict[str, str], runtime: Path) -> object:
    """Build the one audio owner configuration in the pool's audio class.

    Inside an export the owner inherits that launch's budget exactly like the
    export's other owners; a standalone stage is budgeted by its project folder.
    """
    from studio.native_budget_owner import budget_owner_settings
    from studio.native_run_config import NativeRunConfig
    cli, sandbox = runtime / 'dist/cli.js', STUDIO / 'native_localhost_only.sb'
    command = ['/usr/bin/sandbox-exec', '-f', str(sandbox), sys.executable, str(Path(__file__).resolve()),
               'worker', str(request_file)]
    request = bound_json(request_file)
    pins = {**request['pins'], str(request_file): digest(request_file)}
    admission = {'output': str(plan.root / RESULT_NAME), 'sdkSha256': digest(cli),
                 'sandboxSha256': digest(sandbox), 'scope': 'audio-only whole-program preparation; no picture'}
    settings = NativeRunConfig(Path(request['project']), plan.root, cli, command, environment, admission,
                               sandbox=sandbox,
                               deadline=plan.work_seconds + plan.capacity_wait_seconds, additional_pins=pins,
                               success_status=STATUS_PREPARED, capacity_wait_seconds=plan.capacity_wait_seconds,
                               lane=audio_stage_lease_class())
    return settings if plan.export_request is None else budget_owner_settings(plan.export_request, settings)


def failure_diagnostics(root: Path) -> dict:
    """Name the failed shared checks and step receipts retained by the worker."""
    work, rows = root / 'work', {}
    for name, file in (('master', 'audio-preparation/receipt.json'), ('channel', 'channel-normalization.json'),
                       ('cleanup', 'dialogue-cleanup/receipt.json')):
        rows[name] = bound_json(work / file) if (work / file).is_file() else {}
    failed = [{key: row.get(key) for key in ('name', 'measured', 'detail')}
              for row in rows['master'].get('audioQuality') or [] if row.get('status') == FAIL]
    steps = {name: {'status': rows[name].get('status'), 'error': rows[name].get('error')}
             for name in ('channel', 'cleanup') if rows[name]}
    return {'failedChecks': failed, 'steps': steps}


def record_failure(root: Path, owner: dict) -> dict:
    """Publish the terminal failure with its failed checks; a failed stage is never sealed.

    A worker refused by the owner gate wrote nothing; its logged refusal names the cause.
    """
    worker = root / WORKER_FAILURE
    refusal = worker_refusal(root, owner)
    detail = refusal or (bound_json(worker) if worker.is_file() else {})
    diagnostics = failure_diagnostics(root)
    reason = detail.get('error') or owner.get('abortReason') or 'audio worker failed'
    named = '; '.join(f"{row['name']}: {row['measured']}" for row in diagnostics['failedChecks'])
    record = {'schemaVersion': 1, 'status': 'failed', 'phase': 'audio-stage', 'reusable': False,
              'ownerStatus': owner.get('status'), 'abortReason': owner.get('abortReason'),
              'failureCategory': refusal['category'] if refusal else owner.get('failureCategory'),
              'workerRefused': refusal is not None, 'cleanup': owner.get('cleanup'),
              'error': f'{reason} ({named})' if named else reason,
              'errorType': NativeOwnerRefused.__name__ if refusal else detail.get('errorType'),
              'diagnostics': diagnostics, 'ownerReceipt': str(root / OWNER_NAME)}
    write_new(root / FAILED_NAME, record)
    return record


def stage_owner_settings(plan: AudioStagePlan, environment: dict[str, str] | None = None) -> object:
    """Create the new stage directory and its frozen request; return its one owner's settings.

    Args:
        plan: Project, new stage directory, profile and explicit time bounds.
        environment: Closed child environment; defaults to the shared local one.

    Returns:
        The NativeRunConfig whose owner alone may launch this stage's worker.
    """
    from studio.native_run_config import local_environment
    from studio.native_runtime import install_runtime
    project = plan.project.resolve(strict=True)
    real_directory(plan.root.parent)
    require(not plan.root.exists() and not plan.root.is_relative_to(project) and not project.is_relative_to(plan.root),
            'audio stage needs a new directory outside the project')
    tools, local = local_environment()
    runtime = plan.runtime or install_runtime()
    request = stage_request(plan, project, tools)
    plan.root.mkdir(mode=0o700)
    (plan.root / 'work').mkdir()
    write_new(plan.root / REQUEST_NAME, request)
    return owner_config(plan, plan.root / REQUEST_NAME, environment or local, runtime)


def prepare_stage(plan: AudioStagePlan, environment: dict[str, str] | None = None) -> dict:
    """Run and seal one audio stage, or raise AudioStageFailure with its retained record.

    Args:
        plan: Project, new stage directory, profile and explicit time bounds.
        environment: Closed child environment; defaults to the shared local one.

    Returns:
        The verified seal record.
    """
    from studio.native_run import NativeRun
    owner = NativeRun('audio-stage', stage_owner_settings(plan, environment))
    if not owner.execute():
        raise AudioStageFailure(record_failure(plan.root, owner.result))
    return seal_stage(plan.root, bound_json(plan.root / REQUEST_NAME)['leaseClass'])


def require_tool_resolution(tools: dict[str, str]) -> None:
    """Bare ``ffmpeg``/``ffprobe`` calls in the audio path must reach the admitted tools."""
    for name in ('ffmpeg', 'ffprobe'):
        found = shutil.which(name)
        require(found is not None and digest(Path(found).resolve()) == digest(Path(tools[name]).resolve()),
                f'{name} on the owned PATH differs from the admitted tool')


def checked_preparation(request: dict) -> dict:
    """Recheck inputs, then prepare the premaster and float master only while the supervisor lives."""
    from studio.native_short_delivery import prepare_dialogue
    project = Path(request['project'])
    verify_pins(request['pins'])
    require_tool_resolution(request['tools'])
    require(audio_input_contract(project, request['audioProfile'], request['tools']) == request['audioInput'],
            'audio inputs changed before preparation')
    plan = bound_json(project / 'SHORT-PROJECT.json')
    require_live_supervisor()
    prepared = prepare_dialogue({'output': request['output'], 'project': str(project), 'tools': request['tools'],
                                 'audioProfile': request['audioProfile'], 'preparedMaster': None,
                                 'audioDonor': None, 'pins': {}}, plan['canvas'], plan.get('audioFinishing'))
    verify_pins(request['pins'])
    require_live_supervisor()  # an orphan of a killed supervisor never publishes its result
    return prepared


def worker(request_file: Path) -> None:
    """Owned child: bind the live owner, recheck inputs, prepare the float master, record closure.

    Raises:
        NativeOwnerRefused: No live admitted owner bound to this exact request launched it,
            or its supervisor stopped being its parent; nothing is written into the stage.
    """
    request = require_owned_audio_worker(request_file)
    started, root = time.monotonic(), Path(request['stageRoot'])
    try:
        prepared = checked_preparation(request)
    except NativeOwnerRefused:
        raise
    except Exception as error:
        write_new(root / WORKER_FAILURE, {'status': 'failed', 'errorType': type(error).__name__,
                                          'error': str(error), 'elapsedSeconds': time.monotonic() - started})
        raise
    write_new(root / RESULT_NAME, {'schemaVersion': 1, 'status': STATUS_PREPARED, 'prepared': prepared,
        'audioInputSha256': request['audioInputSha256'], 'implementation': executed_implementation(),
        'elapsedSeconds': time.monotonic() - started, 'pictureWork': False, 'humanListeningApproved': False})
    print(json.dumps({'status': STATUS_PREPARED}), flush=True)


def summary(record: dict) -> dict:
    """Compact CLI view of a sealed stage."""
    return {'status': record['status'], 'audioInputSha256': record['audioInputSha256'],
            'seal': str(Path(record['stageRoot']) / 'audio-stage.json'), 'masterSha256': record['master']['sha256'],
            'premasterSha256': record['premaster']['sha256'], 'ownerElapsedSeconds': record['ownerElapsedSeconds'],
            'audioReviewRequired': record['audioReviewRequired'], 'humanListeningApproved': False}


def main() -> None:
    """Dispatch prepare/check/worker; failures stay on disk for diagnosis."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'check', 'worker'))
    parser.add_argument('paths', nargs='+', type=Path)
    parser.add_argument('--audio-profile', choices=MASTERING_PROFILE_IDENTITIES,
                        default=NATIVE_SHORT_MASTERING_PROFILE.identity)
    parser.add_argument('--work-seconds', type=float, default=DEFAULT_WORK_SECONDS)
    parser.add_argument('--capacity-wait-seconds', type=float, default=DEFAULT_CAPACITY_WAIT_SECONDS)
    args = parser.parse_args()
    if args.operation == 'worker':
        try:
            worker(args.paths[0].resolve(strict=True))
        except NativeOwnerRefused as error:
            print(refusal_line(error), flush=True)
            raise SystemExit(2) from error
        return
    try:
        if args.operation == 'check':
            report = summary(read_sealed_stage(args.paths[0].resolve(strict=True) / 'audio-stage.json'))
        else:
            report = summary(prepare_stage(AudioStagePlan(args.paths[0], args.paths[1].absolute(),
                args.audio_profile, args.work_seconds, args.capacity_wait_seconds)))
    except AudioStageFailure as error:
        print(json.dumps({'status': 'failed', 'phase': 'audio-stage', **error.record}), flush=True)
        raise SystemExit(1) from error
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print(json.dumps({'status': 'error', 'error': str(error)}), flush=True)
        raise SystemExit(2) from error
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
