"""Batch record creation and agent-dispatch admission for native Short production.

The defaults (``native_budget_schema.LIMITS``/``DEADLINES``) are the owner's
per-Short limits for the initial delivery (REMEDIATION-PLAN.md, "Enforced
limits"). Per-stage limits are ceilings under the shared batch deadline,
never allowances that multiply. Counters live in the per-user authority keyed
by batch and logical clip, so a rename, a new folder, a new agent, an engine
rebuild or a restart cannot clear them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from studio.native_budget_clock import ClockAnchor
from studio.native_budget_schema import (
    AI_POLICY, BOUNDS, COUNTERS, DEADLINES, DISPATCH_KINDS, LIMITS, PROVISIONAL_RATES, SCHEMA_VERSION, valid_title,
)
from studio.native_budget_selection import (
    approval_identity, compare_titles, script_identity, script_problem, title_identity, title_problem,
)
from studio.native_budget_store import require_batch_id, require_clip_id
from studio.native_budget_transcript import transcript_problem
from studio.production.formats import clip_deadlines, clip_limits, output_format, preparation_passed
from studio.production.authorization_record import new_authorization

CREATIVE_KINDS = ('author', 'planReview', 'repairCycle')


@dataclass(frozen=True)
class Decision:
    """An admission outcome; refusals carry the reason the coordinator must surface."""

    allowed: bool
    reason: str
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BatchSpec:
    """What the coordinator declares when a batch starts.

    ``ai_slots`` is the host's concurrent AI capacity, director included;
    ``ai_reservations`` the run's total AI tasks (None derives it from the per-clip
    dispatch ceilings plus the run-scoped allowance). ``approvals`` maps every clip
    to its ``Approval``: a Short's clock starts at the approved title and script.
    """

    batch_id: str
    clip_ids: tuple[str, ...]
    claims: tuple[str, ...]
    pool_slots: int
    ai_slots: int = AI_POLICY['defaultSlots']
    ai_reservations: int | None = None
    approvals: dict | None = None


@dataclass(frozen=True)
class Approval:
    """A clip's approved title and script as handed over at start, and who or what recorded it.

    ``title`` is the operator's exact text, always given (a missing title is refused). The script is the
    ordered, non-overlapping inclusive ``word_ranges`` of the admitted transcript (``transcript_sha256``,
    ``transcript_words`` long) on ``source_sha256``, the text of every kept word, and one derived
    [start, end] source-second range per word range. Binding reads the transcript at
    ``transcript_path`` and refuses one whose raw word numbering differs from the writer's
    (``native_budget_transcript``; ``source_seconds`` is the source's duration). Nothing is normalized.
    """

    title: str
    source_sha256: str
    transcript_sha256: str
    transcript_words: int
    transcript_path: str
    source_seconds: float
    word_ranges: tuple[tuple[int, int], ...]
    word_texts: tuple[str, ...]
    ranges: tuple[tuple[float, float], ...]
    recorded_by: str


def approval_row(approval: Approval, elapsed: float, epoch: float, reason: str) -> dict:
    """The durable approval: exact title, script fields and identities, time and recorder (validated)."""
    recorder = approval.recorded_by
    script = {'sourceSha256': approval.source_sha256, 'transcriptSha256': approval.transcript_sha256,
              'transcriptWords': approval.transcript_words, 'wordRanges': [list(row) for row in approval.word_ranges],
              'wordTexts': list(approval.word_texts),
              'ranges': [[float(start), float(end)] for start, end in approval.ranges]}
    problem = title_problem(approval.title) or script_problem(script) \
        or transcript_problem(approval.transcript_path, script, approval.source_seconds)
    if problem is None and (not valid_title(recorder) or len(recorder) > 128 or '\n' in recorder):
        problem = 'an approval names who or what recorded it (one line, at most 128 characters)'
    if problem:
        raise ValueError(f'Approval refused: {problem}')
    identity = script_identity(script)
    return {'title': approval.title, 'titleSha256': title_identity(approval.title), 'source': script['sourceSha256'],
            'transcript': script['transcriptSha256'], 'transcriptWords': script['transcriptWords'],
            'wordRanges': script['wordRanges'], 'wordTexts': script['wordTexts'], 'ranges': script['ranges'],
            'script': identity, 'identity': approval_identity(approval.title, identity),
            'wordCount': len(script['wordTexts']), 'sourceSeconds': float(approval.source_seconds),
            'elapsed': elapsed, 'epoch': epoch, 'recordedBy': recorder, 'reason': reason, 'previous': None}


def _initial_approvals(spec: BatchSpec, clips: list[str], epoch: float) -> dict:
    """The approvals bound when the clock starts: none, or exactly one per declared clip."""
    if spec.approvals is None:
        return {clip: [] for clip in clips}
    if type(spec.approvals) is not dict or set(spec.approvals) != set(clips):
        raise ValueError('Approvals, when given, name every declared clip exactly once')
    reason = 'approved title and script handed over at start: the clock starts here'
    return {clip: [approval_row(spec.approvals[clip], 0.0, epoch, reason)] for clip in clips}


def current_approval(record: dict, clip_id: str) -> dict | None:
    """The clip's latest recorded approval, or None when none is recorded."""
    approvals = clip_record(record, clip_id)['approvals']
    return approvals[-1] if approvals else None


def approval_differences(record: dict, clip_id: str, approval: Approval) -> list[str]:
    """What differs from the clip's current approval: 'title' (material), 'title-normalization' (NFC or
    whitespace only; not material) and 'script'. Everything differs when none is recorded."""
    current = current_approval(record, clip_id)
    if current is None:
        return ['title', 'script']
    candidate = approval_row(approval, 0.0, 0.0, 'comparison')
    title = compare_titles(current['title'], candidate['title'])
    names = {'exact': [], 'normalization-only': ['title-normalization'], 'different': ['title']}[title]
    return names + (['script'] if candidate['script'] != current['script'] else [])


def ai_allowance(spec: BatchSpec, clips: int) -> dict:
    """The run's declared AI slots and reservations, within the policy ceilings."""
    per_clip = sum(LIMITS[kind] for kind in DISPATCH_KINDS)
    reservations = spec.ai_reservations
    if reservations is None:
        reservations = min(AI_POLICY['reservationsCeiling'], per_clip * clips + AI_POLICY['runScopedAllowance'])
    if type(spec.ai_slots) is not int or not 1 <= spec.ai_slots <= AI_POLICY['slotsCeiling'] \
            or type(reservations) is not int or not 1 <= reservations <= AI_POLICY['reservationsCeiling']:
        raise ValueError(f'AI slots must be 1-{AI_POLICY["slotsCeiling"]} and reservations '
                         f'1-{AI_POLICY["reservationsCeiling"]}')
    return {'slots': spec.ai_slots, 'reservations': reservations, 'charged': 0}


def new_clip(reason: str, added_after_start: bool, approvals: list | None = None) -> dict:
    """A logical clip starts with zero counters, no bound projects and its bound approval (if given)."""
    from studio.production.queue_clock import new_clock
    return {'capacityClock': new_clock(), 'addedAfterStart': added_after_start, 'reason': reason, 'state': 'active',
            'outputSeconds': None, 'projects': [],
            'counters': {name: 0 for name in COUNTERS}, 'aacByAudio': {},
            'attempts': [], 'dispatches': [], 'deliveries': [], 'approvals': list(approvals or [])}


def new_batch_record(spec: BatchSpec, anchor: ClockAnchor) -> dict:
    """Create the authoritative record; the clock starts now and never restarts."""
    require_batch_id(spec.batch_id)
    clips = [require_clip_id(clip) for clip in spec.clip_ids]
    if not clips or len(set(clips)) != len(clips) or len(clips) > BOUNDS['clips']:
        raise ValueError(f'A batch needs 1-{BOUNDS["clips"]} unique clip ids')
    if type(spec.pool_slots) is not int or not 1 <= spec.pool_slots <= 16:
        raise ValueError('Pool slots must be an integer from 1 to 16')
    approvals = _initial_approvals(spec, clips, anchor.epoch)
    record = {'schemaVersion': SCHEMA_VERSION, 'batchId': spec.batch_id, 'status': 'active', 'startEpoch': anchor.epoch,
              'clock': anchor.record(), 'limits': dict(LIMITS), 'deadlines': dict(DEADLINES),
              'rates': PROVISIONAL_RATES, 'poolSlots': spec.pool_slots, 'engine': None, 'holds': [],
              'claims': sorted(set(spec.claims)),
              'clips': {clip: new_clip('declared at batch start', False, approvals[clip]) for clip in clips},
              'closedAtElapsed': None,
              'production': {'ai': ai_allowance(spec, len(clips)), 'drain': None, 'tasks': {}, 'governance': None,
                             'authorization': None}}
    record['production']['authorization'] = new_authorization(record)
    return record


def clip_record(record: dict, clip_id: str) -> dict:
    """Return a declared clip; unknown clips are refused, never created implicitly."""
    clip = record['clips'].get(require_clip_id(clip_id))
    if clip is None:
        raise ValueError(f'Clip {clip_id} is not part of batch {record["batchId"]}; '
                         'add it explicitly with native_batch.py add-clip')
    return clip


def phase_refusal(record: dict, clip: dict | None, elapsed: float) -> str | None:
    """Batch-level refusals shared by every kind of new work (clip None for run-scoped work)."""
    if record['status'] == 'draining':
        return (f'Batch {record["batchId"]} is draining: no new work is admitted while its unresolved work '
                'settles; it cannot be replaced by a new batch until it closes')
    if record['status'] != 'active':
        return f'Batch {record["batchId"]} is closed; new work needs an explicit new user request'
    if record['production']['authorization']['setup'] != 'complete':
        return (f'Batch {record["batchId"]} is authorized and its clock is running, but its setup (capacity, source '
                'hashes, engine freeze) has not completed; rerun start to finish it')
    if clip is not None and clip['state'] == 'handed-off':
        return 'Clip was handed off; unrequested polishing after handoff is not admitted'
    if elapsed >= clip_deadlines(record, clip)['deliverySeconds']:  # each output's own; the run's latest for run work
        clock = 'Long\'s 180-minute' if clip is not None and output_format(clip) == 'long' else '40-minute'
        return f'The {clock} delivery deadline has passed; report the SLA miss instead of continuing'
    return None


def admit_dispatch(record: dict, clip_id: str, kind: str, elapsed: float) -> Decision:
    """Admit one agent dispatch against the clip's counters and the batch phase."""
    if kind not in DISPATCH_KINDS:
        raise ValueError(f'Unknown dispatch kind: {kind}')
    clip = clip_record(record, clip_id)
    refusal = phase_refusal(record, clip, elapsed)
    if refusal:
        return Decision(False, refusal)
    if kind in CREATIVE_KINDS and elapsed >= clip_deadlines(record, clip)['preparationSeconds']:
        return Decision(False, f'{preparation_passed(clip)}: no further creative authoring, plan review or '
                               'repair is admitted for the initial delivery; keep the best complete candidate')
    limit, used = clip_limits(record, clip)[kind], clip['counters'][kind]
    if used >= limit:
        return Decision(False, f'{kind} limit reached for clip {clip_id} ({used}/{limit}); '
                               'collect remaining findings for the user\'s next revision')
    if len(clip['dispatches']) >= BOUNDS['dispatches']:
        return Decision(False, 'Dispatch history for this clip is full')
    return Decision(True, 'admitted', {'counter': kind, 'used': used + 1, 'limit': limit})


def admit_new_clip(record: dict, clip_id: str, elapsed: float) -> Decision:
    """A clip added after start is explicit, visible work; never after minute 25."""
    require_clip_id(clip_id)
    if record['status'] != 'active':
        return Decision(False, f'The batch is {record["status"]}')
    if clip_id in record['clips']:
        return Decision(False, f'Clip {clip_id} already exists')
    if elapsed >= record['deadlines']['preparationSeconds']:
        return Decision(False, 'Minute 25 has passed: new clips cannot be added to this batch')
    if len(record['clips']) >= BOUNDS['clips']:
        return Decision(False, 'The batch already has the maximum number of clips')
    return Decision(True, 'admitted')


def close_refusal(record: dict, elapsed: float) -> str | None:
    """Closing never releases budgets early: every clip handed off, or the deadline passed.

    A draining batch may be asked again: it closes once its owned work has settled
    (``production.lifecycle.close_or_drain``).
    """
    if record['status'] == 'closed':
        return 'The batch is already closed'
    open_clips = [clip_id for clip_id, clip in record['clips'].items() if clip['state'] != 'handed-off'
                  and elapsed < clip_deadlines(record, clip)['deliverySeconds']]  # an open Long keeps its run open
    if open_clips:
        return (f'Clips {", ".join(open_clips)} are not handed off and the delivery deadline has not '
                'passed; a batch cannot be closed to reset its budgets')
    return None


def change_approval(record: dict, clip_id: str, approval: Approval, elapsed: float) -> dict:
    """Record the operator's typed change of a clip's approved title or script; the clock is unchanged.

    The approval bound at start (or when the clip was added) stays as history. Returns the change
    {'row', 'changed', 'material', 'from', 'to'}, or {'refusal': reason}.
    """
    clip = clip_record(record, clip_id)
    refusal = phase_refusal(record, clip, elapsed)
    if refusal is None and not clip['approvals']:
        refusal = f'Clip {clip_id} has no approved title and script bound at start; nothing can change'
    changed = approval_differences(record, clip_id, approval) if refusal is None else []
    if refusal is None and not changed:
        refusal = f'Clip {clip_id} already has this exact approved title and script'
    if refusal is None and len(clip['approvals']) >= BOUNDS['approvals']:
        refusal = f'Clip {clip_id} already has {BOUNDS["approvals"]} recorded approvals'
    if refusal:
        return {'refusal': refusal}
    before = clip['approvals'][-1]['identity']
    row = approval_row(approval, elapsed, record['clock']['epoch'],
                       'operator changed the approved title or script; the clock is unchanged')
    row['previous'] = before
    clip['approvals'].append(row)
    return {'row': row, 'changed': changed, 'material': bool({'title', 'script'} & set(changed)),
            'from': before, 'to': row['identity']}


def charge(clip: dict, counter: str, amount: int = 1) -> None:
    """Consume a counter; charges are never refunded by a later failure or restart."""
    if counter not in COUNTERS or type(amount) is not int or amount < 1:
        raise ValueError('Invalid budget charge')
    clip['counters'][counter] += amount


def approved_seconds(record: dict, clip_id: str) -> float | None:
    """Seconds of the clip's current approved script: the sum of its derived source-second ranges.

    The row is the one ``production.api.read_approval`` returns as ``current``. It is the output's
    known duration before its project is built (``sourceSeconds`` is the recording's length, not
    this). None when no approval is recorded.
    """
    approval = current_approval(record, clip_id)
    return sum(end - start for start, end in approval['ranges']) if approval else None
