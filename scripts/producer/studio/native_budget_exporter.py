"""Exporter-side budget boundary: route naming, reservation and early-failure closure.

Arguments are validated before anything is charged. The reservation then
happens before check-export, runtime installation or input hashing; if
preparation fails, the reserved launch is closed as a failed launch at once
(it stays charged), so an unpublished attempt can never leave free budget
behind or look like it is still running.

A Long reserves here too, at its own public entry (``native_long_export.execute``), never
through the Short launch path: ``reserve_long_launch`` charges the launch to the project's
own Long output (its identity is the reviewed plan, its duration the canvas, its deadline,
limits and rates the output row's) and returns the grant with the immutable Long binding
(``production.outputs.long_launch_binding``), which ``bind_long_budget`` checks against the
exact plan the request pins before it is written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from studio.native_budget_binding import (
    BudgetRefused, input_identity, record_request_outcome, require_budget_continuity, reserve_launch,
    reserve_resolved, resolve_binding, reserve_task_launch, TaskLaunch,
)
from studio.native_budget_clock import BudgetClockError, BudgetExhausted
from studio.native_budget_launch import LaunchRequest
from studio.native_budget_registry import project_identity
from studio.native_budget_store import BudgetAuthorityError, default_root
from studio.production.outputs import long_launch_binding

VALUE_KEYS = ('render_only', 'cached_native_batches', 'sdk_streaming', 'acquire_source_cache', 'audio_profile',
              'preview_only', 'review_draft')
# Content inputs. The frame cache location is an optimization, not an input, and paths never count:
# a copy of the same evidence or a new empty cache is the same launch for the zero-retry rule.
PATH_KEYS = ('audio_donor', 'picture_donor', 'preview_reviews', 'preview_from', 'reference_map',
             'verify_from', 'resume_from', 'promote_draft', 'audio_stage', 'draft_findings', 'prepared_master')
DIRECTORY_EVIDENCE = ('export-request.json', 'delivery.json', 'render-stage.json', 'draft-stage.json')
BUDGET_ERRORS = (BudgetRefused, BudgetAuthorityError, BudgetExhausted, BudgetClockError)


def launch_route(args: argparse.Namespace) -> str:
    """Name the launch kind the budget charges; previews and full programs differ."""
    if getattr(args, 'promote_draft', None):
        return 'promote'
    if getattr(args, 'review_draft', False):
        return 'draft'
    if getattr(args, 'verify_from', None):
        return 'verify'
    if getattr(args, 'resume_from', None):
        return 'resume'
    if getattr(args, 'preview_only', False) or not getattr(args, 'preview_reviews', None):
        return 'preview'
    return 'final'


def _path_evidence(value: Path) -> dict:
    """The digest of what a path option names (a file, or an attempt's evidence files)."""
    path = value.resolve()
    if path.is_file():
        return {'sha256': _file_digest(path)}
    return {'contents': {name: _file_digest(path / name) for name in DIRECTORY_EVIDENCE if (path / name).is_file()}}


def _file_digest(path: Path) -> str:
    """SHA-256 of one file."""
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def launch_options(args: argparse.Namespace) -> dict:
    """Route-shaping options, canonicalized and content-bound, for the unchanged-input identity."""
    values = {key: getattr(args, key) for key in VALUE_KEYS if getattr(args, key, None) not in (None, False)}
    for key in PATH_KEYS:
        value = getattr(args, key, None)
        if value is not None:
            values[key] = _path_evidence(Path(value))
    return values


def reserve_for_args(args: argparse.Namespace) -> tuple[bool, dict | None]:
    """Reserve before preparation; a refusal is reported and nothing starts."""
    try:
        budget = reserve_launch(args.project.resolve(strict=True), args.output.absolute(),
                                launch_route(args), launch_options(args))
    except BUDGET_ERRORS as error:
        print(json.dumps({'status': 'refused-by-production-budget', 'reason': str(error),
                          'childLaunched': False}), flush=True)
        return False, None
    return True, budget


def reserve_long_launch(project: Path, output: Path, route: str, options: dict) -> dict | None:
    """Reserve one Long launch on the project's own Long output before preparation; None when unbudgeted.

    The launch is admitted by the Long output's own forecast (``native_budget_launch.admit_launch``: its rates,
    limits and grant end, one heavy slot unless a Long profile is qualified); a preview is forecast over its
    windows (``native_long_contract.preview_window_seconds``, never fewer than it renders). The grant carries
    ``longOutput``: the plan pin, lineage and duration this launch reserved, and its output row's authorized duration
    and identity.
    """
    from studio.native_long_contract import preview_window_seconds  # the Long contract, only for a Long launch
    root = default_root()
    found = resolve_binding(root, project)
    if found is None:
        return None
    long_output = long_launch_binding(root, found, project_identity(project))
    windows = preview_window_seconds(project) if route == 'preview' else None
    launch = LaunchRequest(found['clipId'], route, input_identity(project, route, options),
                           (str(project), str(output)), long_output['outputSeconds'], windows)
    return {**reserve_resolved(root, found, launch), 'longOutput': long_output}


def reserve_long_for_args(args: argparse.Namespace) -> tuple[bool, dict | None]:
    """The Long public entry's reservation; a refusal is reported by name and nothing starts."""
    try:
        budget = reserve_long_launch(args.project.resolve(strict=True), args.output.absolute(),
                                     launch_route(args), launch_options(args))
    except BUDGET_ERRORS as error:
        print(json.dumps({'status': 'refused-by-production-budget', 'reason': str(error),
                          'childLaunched': False}), flush=True)
        return False, None
    return True, budget


def bind_long_budget(request: dict, budget: dict | None) -> dict:
    """Bind only this launch's reservation, and only to the exact plan it reserved (a resume's donor binding goes).

    A plan edited between the reservation and export pinning is refused; the caller closes the reserved launch as a
    failed preparation (it stays charged).
    """
    request = bind_current_budget(request, budget)
    if not budget:
        return request
    plan, reserved = str(Path(request['project']) / 'LONG-PROJECT.json'), budget['longOutput']
    if reserved['project'] != request['project'] or request['pins'].get(plan) != reserved['planSha256']:
        raise BudgetRefused('The Long plan changed between its reservation and export pinning; this launch is '
                            'charged as a failed preparation, and a new launch reserves the current plan')
    return request


def refuse_if_budgeted(project: Path) -> None:
    """Direct prepare() callers without a reservation are refused before any chargeable work."""
    if resolve_binding(default_root(), project) is not None:
        raise BudgetRefused('This project belongs to a production batch; launch it through '
                            'studio/native_export.py so the budget admits the work first')


def close_unpublished_launch(budget: dict | None, error: BaseException) -> None:
    """Charge and close a launch whose preparation failed before any request existed."""
    if not budget:
        return
    category = 'cancelled' if isinstance(error, KeyboardInterrupt) else (
        'budget-exhausted' if isinstance(error, BudgetExhausted) else 'preparation-failure')
    result = {'status': 'failed', 'failureCategory': category, 'failedPhase': 'preparation',
              'errorType': type(error).__name__, 'error': str(error)}
    if budget.get('familyId'):
        from studio.native_budget_family import record_family_outcome
        request = unpublished_family_request(budget)
        record_family_outcome(request, result)
    elif budget.get('continuationOf'):
        from studio.native_budget_continuation import record_review_outcome
        record_review_outcome({'productionBudget': budget, 'output': budget['continuationOutput']}, result)
    else:
        record_request_outcome({'productionBudget': budget}, result)


def bind_current_budget(request: dict, budget: dict | None) -> dict:
    """A reused donor's old binding never survives; only this launch's reservation does."""
    request.pop('productionBudget', None)
    if budget:
        request['productionBudget'] = budget
        return request
    refuse_if_budgeted(Path(request['project']))
    require_budget_continuity(request)
    return request


def unpublished_family_request(budget: dict) -> dict:
    """Close preparation after immutable publication too, only for the exact reserved invocation."""
    from cut_preview_io import bound_json
    request = {'productionBudget': budget, 'project': budget['longOutput']['project'], 'output': budget['familyOutput']}
    file = Path(budget['familyOutput']) / 'export-request.json'
    if file.exists():
        published = bound_json(file)
        if published.get('productionBudget') != budget:
            raise BudgetRefused('Published failed preparation belongs to another family reservation')
        return published
    return request


FAMILY_WAIT_POLL_SECONDS = 1.0

def reserve_for_task(args: argparse.Namespace, task: object) -> tuple[bool, dict | None]:
    """Reserve a claimed media task's single launch before preparation; a refusal is reported, nothing starts.

    ``task`` is the acknowledged ``production.process.TaskClaim``; the exporter process that
    acknowledged it is the only one the authority lets reserve its launch, and only for the inputs
    the task was enqueued with. A launch of the same family still running for the clip (a direct
    export, or a task's launch not yet reconciled) is waited for within the batch deadline first.
    The refusal goes to the watchdog, which settles the task (``process.publish_refusal``).
    """
    from studio.production.process import publish_refusal
    try:
        project = args.project.resolve(strict=True)
        _wait_for_family(project, launch_route(args), task.task_id)
        budget = reserve_task_launch(TaskLaunch(project, args.output.absolute(), launch_route(args),
                                                launch_options(args), task.batch_id, task.ref(), task.request_sha256))
    except BUDGET_ERRORS as error:
        print(json.dumps({'status': 'refused-by-production-budget', 'reason': str(error), 'childLaunched': False,
                          'taskId': task.task_id}), flush=True)
        publish_refusal(f'{type(error).__name__}: {error}')
        return False, None
    return True, budget


def _wait_for_family(project: Path, route: str, task_id: str) -> None:
    """Wait (never past the hand-off reserve) while the clip runs another launch of this route's family.

    A task that already launched does not wait: the reservation refuses its second launch.
    """
    from studio.native_budget_binding import advance_clock
    from studio.native_budget_launch import launch_family, reconcile_running
    from studio.native_budget_store import read_batch
    binding = resolve_binding(default_root(), project)
    while binding is not None:
        record = read_batch(default_root(), binding['batchId'])
        task = record['production']['tasks'].get(task_id)
        if task is None or task['attempt'] is not None:
            return
        from studio.production.formats import clip_deadlines
        elapsed = advance_clock(record)
        deadlines = clip_deadlines(record, record['clips'][binding['clipId']])
        reconcile_running(record, elapsed)  # in this read only: a launch whose supervisor is gone is not waited for
        running = [row for row in record['clips'][binding['clipId']]['attempts']
                   if row['status'] == 'running' and launch_family(row['route']) == launch_family(route)]
        if not running or elapsed >= deadlines['deliverySeconds'] - deadlines['handoffReserveSeconds']:
            return
        time.sleep(FAMILY_WAIT_POLL_SECONDS)

