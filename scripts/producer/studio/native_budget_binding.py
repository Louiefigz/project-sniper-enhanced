"""Bind native Short and Long work to its original shared authority at every supported boundary."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from studio.native_budget_clock import ClockAnchor, MIN_STAGE_SECONDS, allocation, observe
from studio.native_budget_engine import engine_identity
from studio.native_budget_launch import LaunchRequest, admit_launch, charge_nested, own_identity, record_outcome
from studio.native_budget_policy import Decision, clip_record, phase_refusal
from studio.native_budget_registry import (
    PROJECT_ROW, BudgetRefused, active_binding, binding_refusal, owner_binding, project_identity,
    project_output_seconds, resolve_binding,
)
from studio.native_budget_schema import BOUNDS
from studio.production import outputs
from studio.production.claims import ClaimRef, LaunchCheck, check_launch
from studio.production.formats import clip_deadlines
from studio.production.queue_clock import task_deadline
from studio.production.lineage import project_format
from studio.production.host_contract import process_handle
from studio.production.settlement import DELIVERED, launch_outcome
from headless.durable_files import DurableFileError, read_private_file
from studio.native_budget_store import (
    AUTHORITY, MAX_RECORD_BYTES, BudgetAuthorityError, archived_directory, batch_directory, default_root,
    locked_batch, registry_lock,
)

__all__ = ['BudgetRefused', 'resolve_binding', 'active_binding', 'owner_binding', 'bind_project', 'reserve_launch',
           'reserve_task_launch', 'reserve_resolved', 'reserve_utility', 'charge_request', 'record_request_outcome',
           'require_budget_continuity', 'advance_clock']
REPO = Path(__file__).resolve().parents[3]
SUCCESS = (*DELIVERED, 'native-short-rendered-awaiting-qc', 'native-motion-previews-complete')
IDENTITY_FILES = {'short': ('PROJECT-MANIFEST.json', 'SHORT-PROJECT.json'),
                  'long': ('LONG-PROJECT.json', 'PREBUILD-REVIEW.json')}  # a Long's content is its reviewed plan


def advance_clock(record: dict) -> float:
    """Observe the batch clock and persist its high-water mark into the record."""
    anchor = observe(ClockAnchor.from_record(record['clock']), record['startEpoch'])
    record['clock'] = anchor.record()
    from studio.production.queue_clock import checkpoint
    checkpoint(record, anchor.elapsed)
    return anchor.elapsed


def bind_project(root: Path, batch_id: str, clip_id: str, project: Path) -> None:
    """Attach a (new revision) project to an output of the active batch; counters never reset.

    The registry lock serializes binds, batch creation and archiving, so two
    coordinators cannot bind one folder, copy or revision to two outputs at once. The
    project's format must be the output's; a Long's first project binds its lineage.
    """
    identity = project_identity(project)
    with registry_lock(root), locked_batch(root, batch_id) as session:
        record = session.read()
        elapsed = advance_clock(record)
        clip = clip_record(record, clip_id)
        refusal = phase_refusal(record, clip, elapsed) or outputs.format_refusal(record, clip_id, identity) \
            or binding_refusal(record, clip_id, identity) or outputs.binding_refusal(record, clip_id, identity)
        if refusal:
            raise BudgetRefused(refusal)
        lineage = outputs.bind_lineage(clip, identity)
        _attach(clip, identity)
        session.commit(record, {'event': 'project-bound', 'clipId': clip_id, 'project': str(project),
                                'format': identity['format'], 'lineageBound': lineage, 'elapsed': elapsed})


def _attach(clip: dict, identity: dict) -> None:
    """Record the folder identity, content hash and (a Short's) selection on the clip (bounded)."""
    if any(row['key'] == identity['key'] for row in clip['projects']):
        return
    if len(clip['projects']) >= BOUNDS['projects']:
        raise BudgetRefused('This clip already has the maximum number of project folders')
    clip['projects'].append({key: identity[key] for key in PROJECT_ROW})


def input_identity(project: Path, route: str, options: dict) -> str:
    """Pre-preparation identity: authored project bytes (by format), route, canonical options, engine."""
    digest = hashlib.sha256()
    for name in IDENTITY_FILES[project_format(project)]:
        digest.update(name.encode() + b'\0' + (project / name).read_bytes())
    digest.update(json.dumps({'route': route, 'options': options}, sort_keys=True).encode())
    digest.update(engine_identity(REPO)['identity'].encode())
    return digest.hexdigest()


def reserve_launch(project: Path, output: Path, route: str, options: dict) -> dict | None:
    """Reserve a budgeted launch before any preparation; None when unbudgeted."""
    root = default_root()
    binding = resolve_binding(root, project)
    if binding is None:
        return None
    return _reserve(root, binding, _launch_request(binding, (project, output), route, options), None)


@dataclass(frozen=True)
class TaskLaunch:
    """An exporter launch that belongs to one acknowledged media task claim of ``batch_id``."""

    project: Path
    output: Path
    route: str
    options: dict
    batch_id: str
    claim: ClaimRef
    request_sha256: str


def reserve_task_launch(launch: TaskLaunch) -> dict:
    """Reserve the acknowledged media task's single exact launch and debit atomically."""
    root = default_root()
    binding = resolve_binding(root, launch.project)
    if binding is None or binding['batchId'] != launch.batch_id:
        raise BudgetRefused(f'The project is not bound to batch {launch.batch_id}, which owns this task claim')
    request = _launch_request(binding, (launch.project, launch.output), launch.route, launch.options)
    return _reserve(root, binding, request, (launch.claim, launch.request_sha256))


def _launch_request(binding: dict, paths: tuple[Path, Path], route: str, options: dict) -> LaunchRequest:
    """The pre-preparation launch identity (authored bytes, route, options, engine)."""
    project, output = paths
    if project_format(project) == 'long':  # the Long public entry reserves with its own binding (D2)
        raise BudgetRefused('A Long launch reserves at the Long public entry (studio/native_export.py routes a Long '
                            'project to studio/native_long_export.py); this Short launch path does not admit it')
    return LaunchRequest(binding['clipId'], route, input_identity(project, route, options),
                         (str(project), str(output)), project_output_seconds(project))


def reserve_resolved(root: Path, binding: dict, launch: LaunchRequest) -> dict:
    """Reserve a launch whose request its format's public entry built for this resolved binding (the Long entry)."""
    return _reserve(root, binding, launch, None)


def _reserve(root: Path, binding: dict, launch: LaunchRequest, claim_context: tuple | None) -> dict:
    """One locked admission; with a task claim, the claim is checked first and bound to the attempt."""
    engine = engine_identity(REPO)
    claim, request_sha256 = claim_context or (None, None)
    with locked_batch(root, binding['batchId']) as session:
        record = session.read()
        elapsed = advance_clock(record)
        task = None if claim is None else check_launch(
            record, claim, LaunchCheck(launch.route, binding['clipId'], process_handle(**own_identity()),
                                       launch_fingerprint(request_sha256, launch.identity)))
        decision = _launch_decision(record, launch, (engine, elapsed))
        if decision.allowed and task is not None:
            attempt = decision.detail['attempt']
            attempt['grantedSeconds'] = min(attempt['grantedSeconds'], task_deadline(record, task) - elapsed)
            task['attempt'] = attempt['id']
        session.commit(record, {'event': 'launch-admitted' if decision.allowed else 'launch-refused',
                                'clipId': binding['clipId'], 'route': launch.route, 'output': launch.paths[1],
                                'elapsed': elapsed, 'reason': decision.reason,
                                'taskId': claim.task_id if claim else None})
    if not decision.allowed:
        raise BudgetRefused(decision.reason)
    attempt = decision.detail['attempt']
    return _grant(root, record, binding, (attempt['id'], launch.route, attempt['grantedSeconds']))


def launch_fingerprint(request_sha256: str, identity: str) -> str:
    """Bind the retained media task request to its exact project, route, options and engine identity."""
    from studio.native_budget_schema import SHA256
    if type(request_sha256) is not str or SHA256.fullmatch(request_sha256) is None:
        raise ValueError('A media task launch needs its retained request SHA-256')
    return hashlib.sha256(f'native-media-task-v1:{request_sha256}:{identity}'.encode()).hexdigest()


def _launch_decision(record: dict, launch: LaunchRequest, context: tuple) -> Decision:
    """Engine freeze first, then the launch rules."""
    engine, elapsed = context[:2]
    facts = context[2] if len(context) > 2 else None
    if facts is not None:
        facts.require_launch(record, launch)
    if record['engine'] and record['engine']['identity'] != engine['identity']:
        return Decision(False, 'The engine changed after this batch froze it '
                        f'({record["engine"]["identity"][:12]}… → {engine["identity"][:12]}…); run the '
                        'batch from its frozen snapshot or record an explicit migration')
    plan = {'format': facts.format if facts is not None else project_format(Path(launch.paths[0]))}
    refusal = outputs.format_refusal(record, launch.clip_id, plan)
    return Decision(False, refusal) if refusal else admit_launch(record, launch, elapsed, facts)


def _grant(root: Path, record: dict, binding: dict, attempt: tuple) -> dict:
    """The request binding every stage inherits: one allocation, never reset."""
    attempt_id, route, granted = attempt
    anchor = ClockAnchor.from_record(record['clock'])
    from studio.production.queue_authority import bind_allocation
    grant = bind_allocation(allocation(anchor, granted, record['deadlines']['cleanupReserveSeconds']), record,
                            {'authority': str(root), 'batchId': binding['batchId'], 'clipId': binding['clipId']})
    return {'schemaVersion': 1, 'authority': str(root), 'batchId': binding['batchId'],
            'clipId': binding['clipId'], 'attemptId': attempt_id, 'route': route,
            'allocation': grant}


def reserve_utility(root: Path, binding: dict, kind: str) -> dict:
    """Admit bounded supporting work for one bound clip by phase and deadline.

    Utilities consume the batch clock but no launch counter. They are refused
    for a closed batch, a handed-off clip, a passed deadline, when less than
    the cleanup reserve remains, or when the served folder's plan (``binding['format']``,
    from ``owner_binding``) is not its output's format.
    """
    with locked_batch(root, binding['batchId']) as session:
        record = session.read()
        elapsed = advance_clock(record)
        refusal, granted = _utility_refusal(record, binding, elapsed)
        session.commit(record, {'event': 'utility-refused' if refusal else 'utility-admitted', 'kind': kind,
                                'clipId': binding['clipId'], 'elapsed': elapsed, 'reason': refusal or 'admitted'})
    if refusal:
        raise BudgetRefused(refusal)
    return _grant(root, record, binding, (None, kind, granted))


def _utility_refusal(record: dict, binding: dict, elapsed: float) -> tuple[str | None, float]:
    """Phase refusal, or too little time left for the cleanup reserve.

    A clip with a delivery is in its hand-off: its supporting work (review bundle,
    Studio copies) may use the hand-off reserve up to the delivery deadline. Other
    clips stop supporting work where the hand-off reserve begins.
    """
    clip = clip_record(record, binding['clipId'])
    deadlines = clip_deadlines(record, clip)
    end = deadlines['deliverySeconds'] - (0 if clip['deliveries'] else deadlines['handoffReserveSeconds'])
    granted = end - elapsed
    refusal = phase_refusal(record, clip, elapsed) or outputs.format_refusal(record, binding['clipId'], binding)
    if refusal is None and granted < deadlines['cleanupReserveSeconds'] + MIN_STAGE_SECONDS:
        refusal = 'Less time remains than the cleanup reserve; start no new supporting work'
    return refusal, granted


def charge_request(request: dict, kind: str, audio_key: str | None = None) -> None:
    """Pre-charge nested work for a budgeted request; unbudgeted requests are unaffected."""
    binding = request.get('productionBudget')
    if binding and binding.get('continuationOf'):
        from studio.native_budget_continuation import charge_review_audio
        return charge_review_audio(request, kind, audio_key)
    if not binding or not binding.get('attemptId'):
        return
    with locked_batch(Path(binding['authority']), binding['batchId']) as session:
        record = session.read()
        elapsed = advance_clock(record)
        decision = charge_nested(record, binding, kind, audio_key)
        session.commit(record, {'event': 'nested-charged' if decision.allowed else 'nested-refused',
                                'clipId': binding['clipId'], 'attemptId': binding['attemptId'],
                                'kind': kind, 'elapsed': elapsed, 'reason': decision.reason})
    if not decision.allowed:
        raise BudgetRefused(decision.reason)


def record_request_outcome(request: dict, result: dict) -> None:
    """Close the reserved launch with the exporter's terminal receipt fields."""
    binding = request.get('productionBudget')
    if not binding or not binding.get('attemptId'):
        return
    outcome = launch_outcome(result, SUCCESS)       # bounded as the settlement room reserves it
    with locked_batch(Path(binding['authority']), binding['batchId']) as session:
        record = session.read()
        elapsed = advance_clock(record)
        attempt = record_outcome(record, binding, outcome, elapsed)
        session.commit(record, {'event': 'launch-completed', 'clipId': binding['clipId'],
                                'attemptId': attempt['id'], 'status': attempt['status'],
                                'resultStatus': attempt['resultStatus'], 'elapsed': elapsed})


def require_budget_continuity(request: dict) -> None:
    """An unbudgeted launch cannot follow budgeted history whose authority vanished."""
    from studio.native_export_history import candidate_attempts
    for attempt in candidate_attempts(request):
        file = attempt / 'export-request.json'
        prior = json.loads(file.read_text()) if file.is_file() else {}
        binding = prior.get('productionBudget')
        if binding and prior.get('project') == request['project']:
            _require_batch_present(binding)


def _require_batch_present(binding: dict) -> None:
    """Earlier budgeted work must still have readable authority, live or archived."""
    root, batch_id = Path(binding['authority']), binding['batchId']
    directory = batch_directory(root, batch_id)
    if not directory.is_dir():
        directory = archived_directory(root, batch_id)
    try:
        with locked_batch(root, batch_id, create=True, directory=directory) as session:
            _released_or_current(session, directory == archived_directory(root, batch_id))
    except BudgetAuthorityError as error:
        raise BudgetRefused(f'Earlier attempts of this project were budgeted by batch {batch_id}, '
                            f'whose authority is missing or unreadable ({error}). Restore it, or start '
                            'explicit new work with a new batch; losing history never resets a budget') from error


def _released_or_current(session: object, archived: bool) -> None:
    """A readable record of this engine, or an archived one of another engine version that was released."""
    try:
        session.read()
    except BudgetAuthorityError:
        if not (archived and _foreign_released(session)):
            raise


def _foreign_released(session: object) -> bool:
    """Whether the locked record is another engine version's released batch."""
    from studio.native_budget_batches import foreign_released
    try:
        raw = json.loads(read_private_file(session.dir_fd, AUTHORITY, MAX_RECORD_BYTES).decode('utf-8'))
    except (OSError, DurableFileError, UnicodeError, ValueError):
        return False
    return foreign_released(raw)
