"""Launch admission, nested charges and outcomes for budgeted native Short exports.

A launch is reserved in the authority BEFORE export checks, runtime
preparation or input hashing, so failures during preparation are charged.
Nested expensive work (full-picture generations, AAC candidates, preview
packages) is pre-charged when it starts and never refunded, so a crash,
interruption or resume cannot earn a fresh allowance.
"""
from __future__ import annotations

import os
import re
import subprocess
import uuid
from dataclasses import dataclass

from native_render_processes import ProcessIdentity, identity_matches, process_table
from studio.native_budget_forecast import launch_fits, service_allowance
from studio.native_budget_policy import Decision, charge, clip_record, phase_refusal
from studio.native_budget_schema import BOUNDS, NESTED, ROUTES
from studio.production.formats import (
    LONG_POLICY, clip_deadlines, clip_limits, long_latest_starts, output_format, preparation_passed,
)

# One retry per clip, shared: host conditions that can clear without changing inputs (a full disk
# included, so freeing space is not an 'unchanged deterministic failure').
TRANSIENT = frozenset({'host-memory-pressure', 'measurement-unavailable', 'cancelled',
                       'abandoned', 'capacity-timeout', 'disk-space', 'capacity-credit-unavailable'})
PS_ENVIRONMENT = {'TZ': 'UTC', 'LC_ALL': 'C', 'PATH': '/usr/bin:/bin'}
PS_TIMEOUT_SECONDS = 5  # one process-table read; a bound the queue clock's poll bound counts


@dataclass(frozen=True)
class LaunchRequest:
    """What an exporter asks to start; identity is cheap and computed pre-preparation."""

    clip_id: str
    route: str
    identity: str
    paths: tuple[str, str]  # (project, output)
    output_seconds: float
    window_seconds: float | None = None  # a Long preview: its region packet's summed window seconds (code, not a guess)
    family_members: int = 1  # frozen scoped previews and the final boundary-preview member

    following_members: int = 1  # the exact final inventory reserved after a grouped preview
    service_seconds: float = 0.0  # operational Long final-review work; never creative identity or capacity

    @property
    def family_work(self) -> float | tuple[float | None, int] | None:
        """The forecast's window total and exact repeated startup count."""
        return (self.window_seconds, self.family_members) if self.family_members > 1 else self.window_seconds

    @property
    def preview_work(self) -> float | tuple[float | None, int] | None:
        """Retain preview-specific callers while final families use the same grouped forecast."""
        return self.family_work if self.route == 'preview' else None


def launch_family(route: str) -> str:
    """Moving previews and full-program exports have separate launch counters."""
    return 'previewLaunch' if route == 'preview' else 'exportAttempt'


def _process_table() -> dict:
    """One process-table read with a fixed clock and locale, so identities compare exactly."""
    output = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,lstart='], env=PS_ENVIRONMENT,
                            check=True, capture_output=True, text=True, timeout=PS_TIMEOUT_SECONDS)
    return process_table(output.stdout)


def own_identity() -> dict:
    """The live supervisor's PID, group and exact start, for later liveness checks."""
    pid = os.getpid()
    row = _process_table().get(pid)
    if row is None:
        raise RuntimeError('Exporter cannot observe its own process identity')
    return {'pid': pid, 'pgid': row[1], 'started': row[2]}


def reconcile_running(record: dict, elapsed: float, table: dict | None = None) -> list[str]:
    """Mark launches whose supervisor is provably gone as abandoned (still charged)."""
    from studio.native_budget_family_state import active_family_attempts
    families = active_family_attempts(record, elapsed, table)
    running = [attempt for clip in record['clips'].values() for attempt in clip['attempts']
               if attempt['status'] == 'running' and attempt['id'] not in families]
    if not running:
        return []
    table = _process_table() if table is None else table
    gone = [attempt for attempt in running
            if not identity_matches(table, ProcessIdentity(**attempt['supervisor']))]
    for attempt in gone:
        attempt.update(status='abandoned', completedElapsed=elapsed,
                       failure={'category': 'abandoned', 'phase': None, 'errorType': None,
                                'signature': 'supervisor-exited-without-outcome'})
    return [attempt['id'] for attempt in gone]


def _retry_decision(clip: dict, launch: LaunchRequest) -> Decision | None:
    """Unchanged deterministic failures get zero retries; transient ones share one per clip."""
    family = launch_family(launch.route)
    previous = [row for row in clip['attempts']
                if launch_family(row['route']) == family and row['status'] in ('failed', 'abandoned')]
    if not previous or previous[-1]['identity'] != launch.identity:
        return None
    failure = previous[-1]['failure'] or {}
    if failure.get('category') not in TRANSIENT:
        return Decision(False, 'Unchanged deterministic failure: the same inputs already failed '
                        f'({failure.get("category")}: {failure.get("signature")}). Change the inputs '
                        'or report the diagnostic; retries of unchanged deterministic errors are 0')
    if clip['counters']['transientRetry'] >= 1:
        return Decision(False, 'The clip already used its one transient-failure retry')
    return Decision(True, 'transient-retry', {'transientRetryOf': previous[-1]['id']})


def admit_launch(record: dict, launch: LaunchRequest, elapsed: float, facts: object | None = None) -> Decision:
    """Decide and, when allowed, charge a launch in the caller's locked record."""
    if launch.route not in ROUTES:
        raise ValueError(f'Unknown launch route: {launch.route}')
    clip = clip_record(record, launch.clip_id)
    if facts is not None:
        facts.require_launch(record, launch)
    reconcile_running(record, elapsed, facts.processes if facts is not None else None)
    refusal = phase_refusal(record, clip, elapsed) or _launch_refusal(record, clip, launch, elapsed)
    if refusal:
        return Decision(False, refusal)
    retry = _retry_decision(clip, launch)
    if retry is not None and not retry.allowed:
        return retry
    fit = launch_fits(record, (launch.clip_id, launch.route, launch.output_seconds, launch.paths[0],
                               launch.window_seconds, launch.family_members, launch.following_members,
                               launch.service_seconds), elapsed, facts.forecast if facts is not None else None)
    if not fit['fits']:
        advice = ' Select --review-draft now.' if launch.route in ('preview', 'final') else ''
        if output_format(clip) == 'long':
            advice = f' A Long has no draft route: report the SLA risk now. {long_latest_start(record, clip, launch)}'
        return Decision(False, 'Forecast misses the handoff deadline (queue + own run + '
                        f'following export end at {fit["forecastFinishElapsed"]:.0f}s > '
                        f'{fit["latestFinishElapsed"]:.0f}s).{advice}', fit)
    deferral = _long_deferral(record, launch, elapsed, facts)
    if deferral:
        return Decision(False, deferral, fit)
    return _charge_launch(record, clip, launch, (elapsed, retry, fit, facts.supervisor if facts is not None else None))


def _long_deferral(record: dict, launch: LaunchRequest, elapsed: float, facts: object | None = None) -> str | None:
    """A Long launch waits while holding a slot now would make a committed Short newly miss (never preempted)."""
    clip = record['clips'][launch.clip_id]
    if output_format(clip) != 'long':
        return None
    from studio.production.mixed_forecast import long_launch_refusal
    inputs = facts.mixed_inputs(record, elapsed) if facts is not None else None
    refusal = long_launch_refusal(record, launch, elapsed, inputs)
    return f'{refusal} {long_latest_start(record, clip, launch)}' if refusal else None


def long_latest_start(record: dict, clip: dict, launch: LaunchRequest) -> str:
    """A refused Long launch's latest start (``formats.long_latest_starts``, queue excluded) and its grant end."""
    members = launch.following_members if launch.route == 'preview' else launch.family_members
    starts = long_latest_starts(clip_deadlines(record, clip), launch.output_seconds, launch.family_work, members)
    service = service_allowance(clip, launch.route, launch.service_seconds)
    starts['latestPreviewStart'] -= service
    starts['latestFinalStart'] -= service
    key = 'latestPreviewStart' if launch.route == 'preview' else 'latestFinalStart'
    minute = (starts[key] - clip['output']['authorizedElapsed']) / 60
    return (f'Its latest {launch.route} start is {starts[key]:.0f}s (minute {minute:.1f} of this Long\'s own clock, '
            f'queue excluded; {starts["previewBasis"]}); its grant ends at {starts["grantEnd"]:.0f}s and is never '
            'extended.')


def _launch_refusal(record: dict, clip: dict, launch: LaunchRequest, elapsed: float) -> str | None:
    """Route-specific counter, phase and concurrency refusals.

    A clip runs at most one launch per family at a time: its moving preview may run beside its
    review draft (different counters, identities and retry histories), never two of either.
    """
    family, limits = launch_family(launch.route), clip_limits(record, clip)
    long = output_format(clip) == 'long'
    if long and launch.route not in LONG_POLICY['routes']:
        return f'A Long export has no {launch.route} route (only {", ".join(LONG_POLICY["routes"])})'
    if any(row['status'] == 'running' and launch_family(row['route']) == family for row in clip['attempts']):
        return f'Clip {launch.clip_id} already has a running {family} launch; wait for its outcome'
    # A Short's previews stop at minute 25; a Long's launches are admitted by their own forecast (no draft route).
    if launch.route == 'preview' and not long and elapsed >= clip_deadlines(record, clip)['preparationSeconds']:
        return f'{preparation_passed(clip)}: no new moving previews; export the best complete candidate'
    if clip['counters'][family] >= limits[family]:
        return (f'{family} limit reached for clip {launch.clip_id} '
                f'({clip["counters"][family]}/{limits[family]}), failed launches included')
    if len(clip['attempts']) >= BOUNDS['attempts']:
        return 'Launch history for this clip is full'
    return None


def _charge_launch(record: dict, clip: dict, launch: LaunchRequest, context: tuple) -> Decision:
    """Record the running attempt and its grant; the charge is permanent."""
    elapsed, retry, fit, supervisor = (*context, None)[:4]
    deadlines = clip_deadlines(record, clip)  # the output's own: a Short never inherits a Long deadline
    grant_end = deadlines['deliverySeconds'] - deadlines['handoffReserveSeconds']
    if launch.route == 'preview':
        grant_end -= fit['followingExportSeconds']
    attempt = {'id': uuid.uuid4().hex, 'route': launch.route, 'project': launch.paths[0],
               'output': launch.paths[1], 'identity': launch.identity, 'admittedElapsed': elapsed,
               'outputSeconds': launch.output_seconds, 'grantedSeconds': round(grant_end - elapsed, 3),
               'supervisor': own_identity() if supervisor is None else supervisor,
               'status': 'running', 'resultStatus': None, 'failure': None,
               'completedElapsed': None, 'stages': [], 'nested': {},
               'transientRetryOf': retry.detail['transientRetryOf'] if retry else None}
    charge(clip, launch_family(launch.route))
    if retry is not None:
        charge(clip, 'transientRetry')
    clip['attempts'].append(attempt)
    clip['outputSeconds'] = launch.output_seconds
    return Decision(True, 'admitted', {'attempt': attempt, 'forecast': fit})


def find_attempt(record: dict, clip_id: str, attempt_id: str) -> dict:
    """Return the exact reserved attempt; an unknown id is corrupt budget binding."""
    for attempt in clip_record(record, clip_id)['attempts']:
        if attempt['id'] == attempt_id:
            return attempt
    raise ValueError(f'Budget attempt {attempt_id} is not reserved for clip {clip_id}')


def charge_nested(record: dict, binding: dict, kind: str, audio_key: str | None = None) -> Decision:
    """Pre-charge one nested expensive operation inside a running launch."""
    if kind not in NESTED:
        raise ValueError(f'Unknown nested charge: {kind}')
    clip = clip_record(record, binding['clipId'])
    attempt = find_attempt(record, binding['clipId'], binding['attemptId'])
    if attempt['status'] != 'running':
        return Decision(False, 'The budget attempt is no longer running')
    return charge_admitted_nested(record, binding, kind, audio_key)


def charge_admitted_nested(record: dict, binding: dict, kind: str, audio_key: str | None) -> Decision:
    """Charge a caller-admitted original attempt; launch state/deadline proof belongs to the caller."""
    clip = clip_record(record, binding['clipId'])
    attempt = find_attempt(record, binding['clipId'], binding['attemptId'])
    refusal = _nested_refusal(clip_limits(record, clip), clip, kind, audio_key)
    if refusal:
        return Decision(False, refusal)
    if kind == 'aacCandidate':
        clip['aacByAudio'][audio_key] = clip['aacByAudio'].get(audio_key, 0) + 1
    charge(clip, kind)
    attempt['nested'][kind] = attempt['nested'].get(kind, 0) + 1
    return Decision(True, 'charged', {kind: clip['counters'][kind]})


def _nested_refusal(limits: dict, clip: dict, kind: str, audio_key: str | None) -> str | None:
    """Per-kind ceilings for nested work, under the output's own limits."""
    used = clip['counters']
    if kind == 'pictureGeneration' and used['pictureGeneration'] >= limits['pictureGeneration']:
        return 'Expensive full-picture generation limit reached for this clip'
    if kind != 'aacCandidate':
        return None
    if type(audio_key) is not str or len(audio_key) != 64:
        raise ValueError('An AAC candidate charge needs its exact audio-input key')
    per_audio = clip['aacByAudio'].get(audio_key, 0)
    if used['aacCandidate'] >= limits['aacCandidate'] or per_audio >= limits['aacPerAudio']:
        return ('Final-delivery AAC candidate limit reached '
                f'({per_audio}/{limits["aacPerAudio"]} for this audio, '
                f'{used["aacCandidate"]}/{limits["aacCandidate"]} for the clip)')
    return None


def failure_signature(error_type: str | None, message: str | None) -> str:
    """Normalize volatile numbers, digests and paths so an unchanged error compares equal."""
    text = f'{error_type or "error"}: {message or ""}'
    text = re.sub(r'/[^\s:\'",)]+', '<path>', text)
    text = re.sub(r'\b[0-9a-f]{12,}\b', '<hex>', text)
    return re.sub(r'\d+(\.\d+)?', '#', text)[:240]


def record_outcome(record: dict, binding: dict, outcome: dict, elapsed: float) -> dict:
    """Close a launch exactly once with its receipt status and failure classification."""
    attempt = find_attempt(record, binding['clipId'], binding['attemptId'])
    if attempt['status'] not in ('running', 'abandoned'):
        raise ValueError('Budget attempt outcome was already recorded')
    succeeded = outcome['status'] in outcome['successStatuses']
    attempt.update(status='succeeded' if succeeded else 'failed', resultStatus=outcome['status'],
                   completedElapsed=elapsed, stages=outcome.get('stages', []))
    if not succeeded:
        attempt['failure'] = {'category': outcome.get('failureCategory') or 'renderer-failure',
                              'phase': outcome.get('failedPhase'), 'errorType': outcome.get('errorType'),
                              'signature': failure_signature(outcome.get('errorType'), outcome.get('error'))}
    delivery = outcome.get('delivery')
    if succeeded and delivery:
        from studio.production.queue_clock import record_delivery
        record_delivery(clip_record(record, binding['clipId']), attempt['id'])
        clip_record(record, binding['clipId'])['deliveries'].append(
            {**delivery, 'attemptId': attempt['id'], 'elapsed': elapsed})
    return attempt
