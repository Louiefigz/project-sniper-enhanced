"""The locked Python API for production tasks: what the coordinator commands (unit A3) call.

Each function holds the batch's kernel lock for one read-modify-write: it reads and
validates the record, advances the batch clock, applies one transition and commits
it with one event before returning. A refusal commits nothing (except a task that
reached its deadline at claim time, which is recorded failed and then refused), and a
repeated identical callback commits nothing and returns ``committed: False``.
``TaskRefused`` and its ``StaleClaim``/``TaskConflict`` are ``BudgetRefused``: do not
start the work (exit 3). ``BudgetAuthorityError`` means corrupt or unwritable
authority (exit 2). Nothing here launches a process or calls a host.
"""
from __future__ import annotations

from pathlib import Path

from studio.native_budget_launch import reconcile_running
from studio.native_budget_policy import close_refusal
from studio.production import callbacks, claims, lifecycle, outputs
from studio.native_budget_staging import staged_starts  # noqa: F401 - re-exported for the operator's listing
from studio.production.approvals import (  # noqa: F401 - re-exported: the approval API callers import from here
    AddedClip, ApprovalChange, add_clip, approval_for_project, read_approval, record_script_change,
)
from studio.production.authorization import discard_staged  # noqa: F401 - re-exported: the operator's discard
from studio.production.outputs import output_for_project, read_output  # noqa: F401 - re-exported (D2/D3 readers)
from studio.production.claims import ClaimRef, Enrollment, Outcome
from studio.production.dependencies import ready_order, refresh, supersede
from studio.production.host_contract import clip_text, parse_event
from studio.production.reconcile import apply_host_event, current_observation, reconcile_tasks
from studio.production.session import read_now, transact
from studio.production.tasks import TaskRefused, TaskSpec, enqueue, task_of
from studio.production.queue_clock import task_deadline


def enqueue_tasks(root: Path, batch_id: str, specs: tuple[TaskSpec, ...]) -> dict:
    """Add one submission of typed tasks atomically (identical replays are no-ops)."""
    def operation(record: dict, elapsed: float) -> Outcome:
        """Enqueue the submission and report what was new."""
        result = enqueue(record, tuple(specs), elapsed)
        return Outcome(bool(result['enqueued']), {'event': 'tasks-enqueued', 'taskIds': result['enqueued']}, result)
    return transact(root, batch_id, operation)


def authorize_output(root: Path, batch_id: str, request: outputs.OutputAuthorization) -> dict:
    """Authorize a Long (any time the run is active) or a Short on its own clock (a run holding a Long).

    The output's clock starts now under the run anchor and is never reset; the mixed forecast must fit
    every committed output, else the refusal names the conflict and nothing is recorded.
    """
    def operation(record: dict, elapsed: float) -> Outcome:
        """Record the authorization event, or recognise an identical repeat."""
        result = outputs.authorize_output(record, request, elapsed)
        row, approvals = result['output'], record['clips'][result['clipId']]['approvals']
        event = {'event': 'output-authorized', 'clipId': result['clipId'], 'format': row['format'],
                 'identity': row['identity'], 'authorizedElapsed': row['authorizedElapsed'],
                 'deadlineElapsed': row['deadlineElapsed'], 'derivedFrom': row['derivedFrom'],
                 'approval': approvals[0]['identity'] if approvals else None}  # read_approval checks the chain
        return Outcome(not result['replayed'], event, result)
    return transact(root, batch_id, operation)


def enroll_director(root: Path, batch_id: str, enrollment: Enrollment) -> dict:
    """Record the already-running director with its exact handle; returns its claim."""
    return transact(root, batch_id, lambda record, elapsed: claims.enroll_director(record, enrollment, elapsed))


def next_ready(root: Path, batch_id: str) -> list[dict]:
    """Ready tasks, least deadline first, each with whether it can be claimed now and why not."""
    record, elapsed = read_now(root, batch_id)
    return [{'taskId': task['id'], 'kind': task['kind'], 'clipId': task['clipId'], 'route': task['route'],
             'deadlineElapsed': task_deadline(record, task),
             'slackSeconds': round(task_deadline(record, task) - elapsed, 3),
             'refusal': claims.claim_refusal(record, task, elapsed)} for task in ready_order(record)]


def claim_task(root: Path, batch_id: str, task_id: str, claimer: dict) -> dict:
    """Commit launch intent (reserve before dispatch); returns the epoch, token and input receipts."""
    return transact(root, batch_id, lambda record, elapsed: claims.claim(record, task_id, claimer, elapsed))


def release_claim(root: Path, batch_id: str, ref: ClaimRef) -> dict:
    """The claim holder attests nothing was launched: the slot frees, the charge stays."""
    return transact(root, batch_id, lambda record, elapsed: claims.release(record, ref, elapsed))


def attach_task(root: Path, batch_id: str, ref: ClaimRef, handle: dict) -> dict:
    """The launched execution acknowledges its claim with its exact handle before any work."""
    return transact(root, batch_id, lambda record, elapsed: claims.attach(record, ref, handle, elapsed))


def complete_task(root: Path, batch_id: str, ref: ClaimRef, result: callbacks.TaskResult) -> dict:
    """Record the execution's artifact receipts (idempotent for the identical outcome)."""
    return transact(root, batch_id, lambda record, elapsed: callbacks.complete(record, ref, result, elapsed))


def record_section_review_progress(root: Path, batch_id: str, ref: ClaimRef, receipt: dict) -> dict:
    """Record one current chunk judgment without completing or recharging its assigned reviewer."""
    from studio.production.section_chunk_progress import record_progress
    return transact(root, batch_id, lambda record, elapsed: record_progress(record, ref, receipt))


def fail_task(root: Path, batch_id: str, ref: ClaimRef, failure: callbacks.TaskFailure) -> dict:
    """Record the execution's failure category; dependents become failed with the reason."""
    return transact(root, batch_id, lambda record, elapsed: callbacks.fail(record, ref, failure, elapsed))


def confirm_cancelled(root: Path, batch_id: str, ref: ClaimRef, usage: dict | None = None) -> dict:
    """The execution confirms it stopped: its slot frees."""
    return transact(root, batch_id, lambda record, elapsed: callbacks.confirm_cancelled(record, ref, usage, elapsed))


def request_cancel(root: Path, batch_id: str, task_id: str, reason: str) -> dict:
    """Cancel unlaunched work, or ask live work to stop; returns the exact handle to interrupt."""
    return transact(root, batch_id, lambda record, elapsed: callbacks.request_cancel(record, task_id, reason, elapsed))


def record_usage(root: Path, batch_id: str, ref: ClaimRef, usage: dict) -> dict:
    """Merge a cumulative (possibly delayed) host usage report."""
    return transact(root, batch_id, lambda record, elapsed: callbacks.record_usage(record, ref, usage, elapsed))


def supersede_task(root: Path, batch_id: str, task_id: str, reason: str) -> dict:
    """Revoke the right to publish of a task and everything computed from it (processes are not stopped)."""
    def operation(record: dict, elapsed: float) -> Outcome:
        """Supersede the task and everything computed from it."""
        if record['status'] == 'closed' or type(reason) is not str or not reason.strip():
            raise TaskRefused('Supersede a task of an open batch, with a reason')
        task = task_of(record, task_id)
        changed = supersede(record, task_id, (clip_text(reason), None), elapsed)
        from studio.production.section_chunk_reuse_history import withdraw_chunk_carry
        if withdraw_chunk_carry(task, elapsed, reason) and task_id not in changed:
            changed.append(task_id)
        refresh(record, elapsed)
        return Outcome(bool(changed), {'event': 'task-superseded', 'taskIds': changed, 'reason': clip_text(reason)},
                       {'superseded': changed})
    return transact(root, batch_id, operation)


def host_event(root: Path, batch_id: str, raw: object) -> dict:
    """Apply one host event after validating it against the closed host contract."""
    event = parse_event(raw)
    return transact(root, batch_id, lambda record, elapsed: apply_host_event(record, event, elapsed))


def reconcile(root: Path, batch_id: str, host: dict | None = None) -> dict:
    """Reconcile launches and tasks against one process-table read and the host's turn states.

    The table is read while the batch lock is held, so no acknowledgement can land between the
    read and the transitions it decides (a table read before a child acknowledged would abandon it).
    """
    def operation(record: dict, elapsed: float) -> Outcome:
        """Reconcile launches and tasks against the same evidence, observed under the lock."""
        observation = current_observation(host)
        abandoned = reconcile_running(record, elapsed)
        changes = reconcile_tasks(record, observation, elapsed)
        expired = outputs.freeze_expired(record, elapsed)  # a Long never keeps another output's work alive
        detail = {'abandonedLaunches': abandoned, 'changes': changes, 'expiredFrozen': expired}
        return Outcome(bool(abandoned or changes or expired), {'event': 'tasks-reconciled', **detail}, detail)
    return transact(root, batch_id, operation)


def drain(root: Path, batch_id: str, reason: str) -> dict:
    """Begin shutdown once the batch may close: freeze all work, keep every reservation."""
    def operation(record: dict, elapsed: float) -> Outcome:
        """Freeze the run once it may close."""
        refusal = close_refusal(record, elapsed)
        if refusal or type(reason) is not str or not reason.strip():
            raise TaskRefused(refusal or 'Draining a batch records its reason')
        frozen = lifecycle.begin_drain(record, reason, elapsed)
        return Outcome(True, {'event': 'batch-draining', 'frozen': frozen, 'reason': clip_text(reason)},
                       {'status': record['status'], 'frozen': frozen, 'unsettled': lifecycle.unsettled(record)})
    return transact(root, batch_id, operation)


def close(root: Path, batch_id: str, host: dict | None = None) -> dict:
    """Close when everything owned has settled, otherwise drain (the same path as ``native_batch.py close``)."""
    def operation(record: dict, elapsed: float) -> Outcome:
        """Close, or drain until owned work settles (the process table is read under the lock)."""
        observation = current_observation(host)
        reconcile_running(record, elapsed)
        refusal = close_refusal(record, elapsed)
        if refusal:
            raise TaskRefused(refusal)
        result = lifecycle.close_or_drain(record, elapsed, observation)
        event = 'batch-closed' if result['status'] == 'closed' else 'batch-draining'
        return Outcome(True, {'event': event, 'unsettled': result['unsettled'],
                              'runningAttempts': result['runningAttempts']}, result)
    return transact(root, batch_id, operation)


def settle_resource(root: Path, batch_id: str, task_id: str, reason: str) -> dict:
    """While draining, record the operator's evidence that an unresolved slot has ended."""
    return transact(root, batch_id, lambda record, elapsed: callbacks.settle_resource(record, task_id, reason, elapsed))


def task_status(root: Path, batch_id: str) -> dict:
    """Counts, AI reservations and usage coverage, and what still holds the run open (read only)."""
    record, elapsed = read_now(root, batch_id)
    return {'batchId': batch_id, 'status': record['status'], 'elapsedSeconds': round(elapsed, 1),
            **lifecycle.task_summary(record, elapsed)}
