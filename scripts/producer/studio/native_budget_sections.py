"""Durable section launch charges inside the existing locked production-budget record.

The pool admits an owner first. Its pre-launch hook then records intent before
Popen, so contention never spends a launch and a crash never refunds one.
Picture generations and the one transient retry retain the Long's existing caps.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from native_render_processes import ProcessIdentity, identity_matches
from studio.native_budget_binding import advance_clock
from studio.native_budget_clock import BudgetExhausted, ClockAnchor, allocation, stage_allowance
from studio.native_budget_launch import TRANSIENT, _process_table, failure_signature, find_attempt, own_identity
from studio.native_budget_policy import charge, clip_record, phase_refusal
from studio.native_budget_registry import BudgetRefused
from studio.native_budget_section_schema import MAX_SECTION_OWNERS
from studio.native_budget_store import locked_batch
from studio.production.formats import clip_deadlines, clip_limits, output_format
from studio.production.settlement import launch_outcome


def section_identity(request: dict, phase: str) -> tuple[dict, str]:
    """Bind picture, global audio policy and source bytes without attempt-directory spellings."""
    if phase.startswith('review-package-'):
        from studio.native_segments.review_budget import package_identity
        return {}, package_identity(request, phase)
    if not phase.startswith('segment-picture-'):
        value = {'scope': request.get('sectionScope'), 'pins': request['pins'], 'phase': phase}
        return {}, hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    index = int(phase.split('-')[2])
    window = request['revision']['renderWindows'][index]
    project = Path(request['project'])
    audio = {str(Path(name).relative_to(project)): sha for name, sha in request['pins'].items()
             if Path(name).is_relative_to(project) and Path(name).suffix.lower() in {'.wav', '.mp3', '.aac'}}
    audio.update({key: request['pins'].get(request.get(key)) for key in ('audioDonor', 'preparedMaster')
                  if request.get(key)})
    value = {'window': window['inputIdentity'], 'audio': audio, 'profile': request.get('audioProfile')}
    return window, hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def inherited_allocation(record: dict, binding: dict, elapsed: float) -> dict:
    """Rebuild only the original durable grant's remaining time; never grant a fresh interval."""
    attempt = find_attempt(record, binding['clipId'], binding['attemptId'])
    clip = clip_record(record, binding['clipId'])
    deadlines = clip_deadlines(record, clip)
    end = min(attempt['admittedElapsed'] + attempt['grantedSeconds'],
              deadlines['deliverySeconds'] - deadlines['handoffReserveSeconds'])
    grant = allocation(ClockAnchor.from_record(record['clock']), end - elapsed,
                       deadlines['cleanupReserveSeconds'])
    original = binding.get('allocation', {})
    if original.get('boot') == grant['boot']:
        for key in ('continuousDeadline', 'epochDeadline', 'grantedSeconds'):
            grant[key] = min(grant[key], original[key])
    stage_allowance({'productionBudget': {'allocation': grant}}, 21600)
    return grant


def reconcile_owners(rows: list[dict], elapsed: float) -> None:
    """A proven exited supervisor leaves a charged abandoned row, never a reusable launch."""
    live = [row for row in rows if row['status'] == 'running']
    if not live:
        return
    table = _process_table()
    for row in live:
        if not identity_matches(table, ProcessIdentity(**row['supervisor'])):
            row.update(status='abandoned', completedElapsed=elapsed,
                       failure={'category': 'abandoned', 'phase': row['phase'], 'errorType': None,
                                'signature': 'section-supervisor-exited-without-outcome'})


def retry_section(clip: dict, context: tuple[dict, dict], previous: dict | None, limits: dict) -> str | None:
    """One shared transient retry; an exporter may already have debited that same retry."""
    if previous is None or previous['status'] == 'succeeded':
        return None
    failure = previous.get('failure') or {}
    if failure.get('category') not in TRANSIENT:
        raise BudgetRefused('Unchanged deterministic section failure: repair its inputs before retrying')
    attempt, request = context
    already = attempt['transientRetryOf'] == previous['attemptId'] or prepaid_family_retry(clip, request, previous)
    consumed = any(row['attemptId'] == attempt['id'] and row['retryOf'] for row in clip['sectionOwners'])
    if (already and consumed) or (not already and clip['counters']['transientRetry'] >= limits['transientRetry']):
        raise BudgetRefused('The Long already used its transient-failure retry')
    if not already:
        charge(clip, 'transientRetry')
    return previous['id']


def prepaid_family_retry(clip: dict, request: dict, previous: dict) -> bool:
    """Recognize the exact failed child whose new invocation already spent the shared retry."""
    binding = request['productionBudget']
    if not binding.get('familyInvocation'):
        return False
    from studio.native_budget_family_state import family_of, invocation_of
    family = family_of(clip, binding['familyId'])
    current = invocation_of(family, binding['familyInvocation'])
    earlier = family['invocations'][:family['invocations'].index(current)]
    prior = next((row for row in reversed(earlier) if row['sectionId'] == current['sectionId']), None)
    return bool(prior and prior['status'] in ('failed', 'abandoned')
        and (prior.get('failure') or {}).get('category') in TRANSIENT
        and previous['attemptId'] == family['id'] and previous['output'] == prior['output']
        and current['output'] == request['output']
        and prior['planSha256'] == current['planSha256'] and prior['scopeSha256'] == current['scopeSha256']
        and clip['counters']['transientRetry'] == 1)


def admit_section(record: dict, request: dict, owner: dict, elapsed: float) -> dict:
    """Validate and debit one pool-admitted owner in the caller's authority transaction."""
    binding = request['productionBudget']
    clip = clip_record(record, binding['clipId'])
    attempt = find_attempt(record, binding['clipId'], binding['attemptId'])
    if binding.get('familyInvocation'):
        from studio.native_budget_family import verify_family_request
        verify_family_request(record, request, owner['phase'])
    elif (attempt['project'], attempt['output']) != (request['project'], request['output']):
        raise BudgetRefused('Section owner does not belong to this reserved export attempt')
    rows = clip.setdefault('sectionOwners', [])
    reconcile_owners(rows, elapsed)
    elapsed = advance_clock(record)
    grant = inherited_allocation(record, binding, elapsed)
    refusal = phase_refusal(record, clip, elapsed)
    if refusal or output_format(clip) != 'long' or attempt['status'] != 'running':
        raise BudgetRefused(refusal or 'Section owner requires a running Long export allocation')
    existing = next((row for row in rows if row['id'] == owner['id']), None)
    if existing is not None:
        if existing != owner:
            raise BudgetRefused('Section launch token was reused with different owner evidence')
        return inherited_allocation(record, binding, elapsed)
    if any(row['phase'] == owner['phase'] and row['status'] == 'running' for row in rows):
        raise BudgetRefused('This section already has a live owned launch')
    if len(rows) >= MAX_SECTION_OWNERS:
        raise BudgetRefused('Section owner history reached its bound; no new work admitted')
    from studio.native_segments.review_budget import previous_owner
    previous = previous_owner(rows, owner)
    limits = clip_limits(record, clip)
    new_picture = requires_picture_generation(rows, owner, (attempt, previous))
    if new_picture and clip['counters']['pictureGeneration'] >= limits['pictureGeneration']:
        raise BudgetRefused('Long picture-generation limit reached; preserved sections remain available')
    owner['retryOf'] = retry_section(clip, (attempt, request), previous, limits)
    if new_picture:
        charge(clip, 'pictureGeneration')
        attempt['nested']['pictureGeneration'] = attempt['nested'].get('pictureGeneration', 0) + 1
    owner['admittedElapsed'] = elapsed
    rows.append(owner)
    return grant


def requires_picture_generation(rows: list[dict], owner: dict, history: tuple) -> bool:
    """Charge one plan generation, or one new attempt that actually repeats completed picture work."""
    if not owner['picture']:
        return False
    attempt, previous = history
    first = not any(row['picture'] and row['planIdentity'] == owner['planIdentity'] for row in rows)
    repeated = previous is not None and previous['status'] == 'succeeded' and previous['attemptId'] != attempt['id']
    return first or (repeated and not attempt['nested'].get('pictureGeneration'))


class SectionBudgetOwner:
    """One callback token and terminal writer for a technical section owner."""

    def __init__(self, request: dict, phase: str, terminal: tuple[str, str] | None = None) -> None:
        """Prepare identity only; no debit before the shared pool admits this owner."""
        self.request, self.phase = request, phase
        self.output, self.success = terminal or (f'{phase}.json', 'native-segment-window-complete')
        self.owner: dict | None = None
        self.identity = uuid.uuid4().hex

    def plan_identity(self, binding: dict) -> str:
        """Charge the full frozen family generation once across distinct immutable snapshot paths."""
        from studio.native_segments.long_plan import identity
        return identity({'sectionFamily': binding['familyId']}) if binding.get('familyId') else self.request['revision']['identity']

    def stored_phase(self) -> str:
        """Namespace supporting owners without changing the canonical worker launch binding."""
        token = self.request.get('productionBudget', {}).get('familyInvocation')
        if token and not self.phase.startswith('segment-picture-'):
            return f'family-{token}-{self.phase}'
        return self.phase

    @property
    def launch_binding(self) -> dict:
        """Let NativeRun compare this callback with its pinned worker request and exact phase/output."""
        from studio.native_runtime import digest
        root = Path(self.request['output'])
        file = root / 'export-request.json'
        return {'request': str(file), 'requestSha256': digest(file), 'phase': self.phase,
                'output': str(root / self.output), 'owner': self.identity}

    def before_launch(self) -> dict | None:
        """Atomically pre-charge this owner and return its original remaining allocation."""
        binding = self.request.get('productionBudget')
        if not binding:
            return None
        from studio.native_segments.review_budget import require_package_family
        require_package_family(self.request, self.phase)
        _window, identity = section_identity(self.request, self.phase)
        if self.owner is None:
            self.owner = {'id': self.identity, 'phase': self.stored_phase(), 'inputIdentity': identity,
                          'planIdentity': self.plan_identity(binding), 'attemptId': binding['attemptId'],
                          'output': self.request['output'], 'supervisor': own_identity(), 'admittedElapsed': 0.0,
                          'completedElapsed': None, 'status': 'running', 'failure': None, 'retryOf': None,
                          'picture': self.phase.startswith('segment-picture-')
                          and self.phase not in self.request['revision'].get('windowDonors', {})}
        with locked_batch(Path(binding['authority']), binding['batchId']) as session:
            record = session.read()
            elapsed = advance_clock(record)
            try:
                grant = admit_section(record, self.request, self.owner, elapsed)
            except (BudgetRefused, BudgetExhausted) as error:
                session.commit(record, {'event': 'section-owner-refused', 'phase': self.phase,
                                        'elapsed': elapsed, 'reason': str(error)})
                raise
            session.commit(record, {'event': 'section-owner-launching', 'phase': self.phase,
                                    'owner': self.identity, 'elapsed': elapsed,
                                    'checkedElapsed': self.owner['admittedElapsed']})
        return grant

    def complete(self, result: dict) -> None:
        """Keep every launched outcome in authority; a prelaunch refusal has no debit to close."""
        if self.owner is None:
            return
        binding = self.request['productionBudget']
        with locked_batch(Path(binding['authority']), binding['batchId']) as session:
            record = session.read()
            clip = clip_record(record, binding['clipId'])
            row = next((row for row in clip.get('sectionOwners', []) if row['id'] == self.identity), None)
            if row is None:
                return
            if row['status'] != 'running':
                raise BudgetRefused('Section owner outcome was already recorded')
            elapsed = advance_clock(record)
            passed = result.get('status') == self.success
            row.update(status='succeeded' if passed else 'failed', completedElapsed=elapsed)
            if not passed:
                bounded = launch_outcome(result, ())
                row['failure'] = {'category': bounded.get('failureCategory') or 'renderer-failure',
                                  'phase': row['phase'], 'errorType': bounded.get('errorType'),
                                  'signature': failure_signature(result.get('errorType'), result.get('abortReason'))}
            session.commit(record, {'event': 'launch-completed', 'sectionOwner': self.identity,
                                    'status': row['status'], 'elapsed': elapsed})


def section_retry_allowed(request: dict, phase: str, error: BaseException) -> bool:
    """Inspect the original shared retry allowance; the actual pool launch alone debits it."""
    binding = request.get('productionBudget')
    if not binding or getattr(error, 'category', None) not in TRANSIENT:
        return False
    with locked_batch(Path(binding['authority']), binding['batchId']) as session:
        record = session.read()
        elapsed = advance_clock(record)
        inherited_allocation(record, binding, elapsed)
        clip = clip_record(record, binding['clipId'])
        limits = clip_limits(record, clip)
        allowed = clip['counters']['transientRetry'] < limits['transientRetry']
        session.commit(record, {'event': 'section-retry-inspected', 'phase': phase, 'elapsed': elapsed,
                                'allowed': allowed})
    return allowed
