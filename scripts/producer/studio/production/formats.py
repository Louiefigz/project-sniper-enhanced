"""Format identity and policy: every output of a run is a Short or a Long, with its own clock and limits.

Identity. A clip of a schema-5 run may carry an ``output`` row: its explicit format, when it was
authorized (its own clock start under the run anchor), its immutable deadlines, the policy copy that
governs it (Longs) and, for a Short, the Long it was derived from. A clip without one is a Short on the
batch clock with exactly today's policy (``native_budget_schema`` LIMITS/DEADLINES/PROVISIONAL_RATES):
every Short declared at ``start`` or added with ``add-clip`` (and every clip of a lifted closed schema-3
batch). Schema 4 was pre-release and is refused by version. The
row is written only by an explicit authorization (``production.outputs``) and never changes afterwards,
except that a Long's lineage is bound once, by its first project (``production.lineage``).

Policy. A Short's deadline is minute 40 of its clock and never a Long's; a Long's is 180 minutes from its
own authorization and never lengthens a Short's. Each output's limits, deadlines and forecast rates come
from its format (``clip_limits``/``clip_deadlines``/``clip_rates``, absolute run-elapsed seconds, in the
keys of ``record['deadlines']``). Run-scoped work ends with the latest output deadline
(``run_deadlines``). The run's aggregate caps (clips, AI slots and reservations) are unchanged.

Every number in ``LONG_POLICY`` names its evidence. Where no measurement exists (every 10-minute Long,
real-footage 15-minute Longs, Long moving previews, any Long running beside other work) the rate is
derived from recorded evidence and says so; ``LONG_DURATION_EVIDENCE`` states what was measured per
output duration and ``LONG_RISKS`` what the rates do not cover (graphics-dense pictures).
"""
from __future__ import annotations

import hashlib
import json
import math

from studio.native_budget_schema import BOUNDS, SHA256

FORMATS = ('short', 'long')
TIMED = ('preparationSeconds', 'draftDecisionSeconds', 'deliverySeconds')  # offsets from an output's clock start
OUTPUT_KEYS = {'format', 'authorizedElapsed', 'deadlineElapsed', 'preparationElapsed', 'outputSeconds', 'derivedFrom',
               'lineage', 'recordedBy', 'policy', 'identity'}
LONG_POLICY = {
    # The operator's Long target: a 15-minute cut from raw footage delivered within three hours of that Long's
    # own authorization (FULL-AUDIT-REQUIREMENTS "Longs use their own policy"; design review section 9). No
    # separate 10-minute target was given, so a 10-minute Long has the same ceiling, never a shorter invented one.
    'deliverySeconds': 10800,
    'maxOutputSeconds': 900,  # native_workload.workload_budget admits native Longs up to 15 minutes
    # Inside the 180 minutes (the coordinator's default for design question Q4), from its parts:
    # - one normal-speed playback of the whole program ("for a 15-minute Long, mandatory full playback alone takes
    #   15 minutes", RISK-EVIDENCE-AND-MITIGATIONS); listening overlaps it (B2 counts max(playback, listening)
    #   per artifact, D3-LONG-PACKET-CONTRACT section 5.2);
    # - review notes: ESTIMATE, the high end of D3 section 5.4's 5-10 minutes of notes beside that playback;
    # - hand-off open and confirm: ESTIMATE, the high end of D3 section 5.4's 2-5 minutes for a Long (identity
    #   hashing and Studio load are unmeasured for a Long; B3 measured 2.94 s per warm Short, WAVES.md:68);
    # - a stated margin: the Short's own 120 s hand-off reserve.
    'handoffReserve': {'playbackPerOutputSecond': 1.0, 'reviewNotesSeconds': 600, 'openConfirmSeconds': 300,
                       'marginSeconds': 120},
    'cleanupReserveSeconds': 45,  # owned cleanup inside every grant, as for Shorts
    'routes': ['preview', 'final', 'resume'],  # native_long_export.py has no draft, promote or verify route
    # The owner's per-output initial-delivery limits (REMEDIATION-PLAN "Enforced limits"). No Long-specific
    # authoring, review or launch evidence exists, so a Long gets the same ceilings, not larger invented ones.
    'limits': {'repairCycle': 2, 'author': 3, 'review': 8, 'planReview': 2, 'previewLaunch': 2, 'exportAttempt': 2,
               'pictureGeneration': 2, 'aacCandidate': 6, 'aacPerAudio': 3, 'transientRetry': 1},
    'rates': {
        'source': 'Long: one 4K-source 145.933 s (4,378-frame, 30 fps) program, supervised export 408.707 s of '
                  'which streaming capture/encode 344.926 s (youtube-automation/docs/findings/'
                  'TREVOR_LONG_FORM_PRODUCTION_AUDIT_2026-09-16.md, lines 3 and 36-45: 2.364 s per output second), '
                  'x1.21 (the qualified three-way pool slowdown, measured on Shorts; no Long or mixed concurrency was '
                  'measured). A moving preview is the 15-minute technical fixture early gates (162.231 s / 900 s, '
                  'docs/producer/NATIVE_LONG_RELIABILITY_2026-09-16.md) over the whole program plus that picture rate '
                  'over its windows: the preview packet\'s summed window seconds when given, else the whole program '
                  '(a bound). Resume can re-render a missing picture, so it carries the final rate. No 10- or '
                  '15-minute real-footage Long export was measured.',
        'safetyFactor': 1.25,
        'routes': {'preview': {'perOutputSecond': 0.22, 'perWindowSecond': 2.9, 'fixedSeconds': 80.0},  # 0.180 x1.21
                   'final': {'perOutputSecond': 2.9, 'fixedSeconds': 80.0},    # 2.364 x1.21 = 2.86; 63.8 x1.21 = 77
                   'verify': {'perOutputSecond': 2.9, 'fixedSeconds': 80.0}},  # a Long resume (forecast as verify)
    },
}
# Named risks, not rates to tune: they are reported with every Long's demand.
LONG_RISKS = {
    'denseGraphics': 'A graphics-dense composition renders far slower than the footage-led Trevor program: the dense '
                     'calibration Short cal-3b367f6 took 0.222-0.242 s per frame (outputs/shorts-sla-qualification/'
                     'calibration/cal-3b367f6/clip: draft 314.66 s and final pipeline 331.12 s for 1,369 frames). At '
                     'that rate a 27,000-frame (15-minute, 30 fps) Long picture takes about 100-109 minutes, not the '
                     'forecast 56; such a Long can miss its 180 minutes. Measure it; do not lower the forecast to fit.',
}
LONG_DURATION_EVIDENCE = {
    600: 'no measurement: no 10-minute Long export has been recorded; its demand is derived from the Long rates',
    900: 'technical fixture only (NATIVE_LONG_RELIABILITY_2026-09-16 stress-v4, 1920x1080 30 fps simple '
         'solid-colour source: early gates 162.231 s, picture 1213.295 s, assembly 52.801 s, resume verification '
         '136.013 s, all serial); no real-footage 15-minute export was measured',
}


def output_row(clip: dict) -> dict | None:
    """The clip's own authorization row, or None for a Short on the batch clock."""
    return clip.get('output')


def output_format(clip: dict) -> str:
    """'short' or 'long'; a clip without an output row is a Short."""
    row = clip.get('output')
    return 'short' if row is None else row['format']


def preparation_passed(clip: dict | None) -> str:
    """How a refusal names the output's preparation deadline."""
    if clip is not None and output_format(clip) == 'long':
        return 'This Long\'s preparation deadline has passed (its final export must start)'
    return 'Minute 25 has passed'


def is_mixed(record: dict) -> bool:
    """Whether the run holds a Long output."""
    return any(output_format(clip) == 'long' for clip in record['clips'].values())


def clip_limits(record: dict, clip: dict) -> dict:
    """The attempt and dispatch limits that govern this output."""
    return clip['output']['policy']['limits'] if output_format(clip) == 'long' else record['limits']


def clip_rates(record: dict, clip: dict) -> dict:
    """The forecast rates for this output's launches."""
    return clip['output']['policy']['rates'] if output_format(clip) == 'long' else record['rates']


def long_handoff_seconds(output_seconds: float) -> float:
    """A Long's hand-off reserve: whole-program playback (listening overlaps it), notes, open/confirm and margin."""
    reserve = LONG_POLICY['handoffReserve']
    return reserve['playbackPerOutputSecond'] * output_seconds + reserve['reviewNotesSeconds'] \
        + reserve['openConfirmSeconds'] + reserve['marginSeconds']


def long_one_output_seconds(output_seconds: float) -> float:
    """An unbound Long export's declared one-output run (A4's rule): the Long policy's grant end from its start."""
    return LONG_POLICY['deliverySeconds'] - long_handoff_seconds(output_seconds)


def long_latest_starts(deadlines: dict, output_seconds: float, window_seconds: object = None,
                       final_members: int | None = None) -> dict:
    """A Long's grant end and the latest moments its final and (before it) its preview can start, queue excluded.

    A render ending at the grant end still leaves the whole hand-off reserve before the delivery deadline.
    """
    demand = long_demand(output_seconds, window_seconds, final_members)
    grant_end = deadlines['deliverySeconds'] - deadlines['handoffReserveSeconds']
    final = grant_end - demand['finalSeconds']
    return {'grantEnd': grant_end, 'latestFinalStart': final, 'latestPreviewStart': final - demand['previewSeconds'],
            'previewBasis': demand['previewBasis']}


def preview_basis(window_seconds: float | None) -> str:
    """How a Long's moving preview is forecast: from its preview packet's window seconds, or the whole-program bound."""
    if type(window_seconds) is tuple:
        return f'family preview windows ({window_seconds[0]} s across {window_seconds[1]} members)'
    return 'whole-program bound (no preview packet yet)' if window_seconds is None \
        else f'preview packet windows ({window_seconds:.1f} s)'


def long_demand(output_seconds: float, window_seconds: object = None, final_members: int | None = None) -> dict:
    """Forecast seconds of a Long's required launches and its hand-off reserve (a model, not a measurement)."""
    from studio.native_budget_forecast import route_seconds
    rates = LONG_POLICY['rates']
    members = final_members if final_members is not None else window_seconds[1] if type(window_seconds) is tuple else 1
    return {'previewSeconds': route_seconds(rates, 'preview', output_seconds, window_seconds),
            'previewBasis': preview_basis(window_seconds),
            'finalSeconds': route_seconds(rates, 'final', output_seconds,
                (None, members) if members > 1 else None),
            'handoffReserveSeconds': long_handoff_seconds(output_seconds),
            'evidence': LONG_DURATION_EVIDENCE.get(int(output_seconds), 'no measurement at this duration'),
            'risks': LONG_RISKS}


def expected_deadlines(fmt: str, authorized: float, output_seconds: float | None) -> tuple[float, float]:
    """(preparation, delivery) in run-elapsed seconds for an output authorized at ``authorized``.

    A Short keeps its minute 25 and 40 on its own clock. A Long's delivery is 180 minutes after its
    authorization; its preparation deadline is the latest start of its final for the declared duration
    (delivery less the hand-off reserve and the forecast final: minute 92 of a 15-minute Long). Creative work
    ends there; its launches are admitted by their own forecast (a shorter actual cut fits later), and a Long
    that can no longer reach a final is reported as a miss at once instead of rendering late.
    """
    from studio.native_budget_schema import DEADLINES
    if fmt == 'short':
        return authorized + DEADLINES['preparationSeconds'], authorized + DEADLINES['deliverySeconds']
    delivery = authorized + LONG_POLICY['deliverySeconds']
    demand = long_demand(output_seconds)
    return round(delivery - demand['handoffReserveSeconds'] - demand['finalSeconds'], 3), float(delivery)


def clip_deadlines(record: dict, clip: dict | None) -> dict:
    """Absolute run-elapsed deadlines of one output (None: the run), keyed like ``record['deadlines']``."""
    if clip is None:
        return run_deadlines(record)
    row = clip.get('output')
    base = record['deadlines']
    if row is None or row['format'] == 'short':
        from studio.production.queue_clock import excluded
        offset = (row['authorizedElapsed'] if row else 0.0) + excluded(clip)
        return {key: value + offset if key in TIMED else value for key, value in base.items()}
    return {'preparationSeconds': row['preparationElapsed'], 'draftDecisionSeconds': row['preparationElapsed'],
            'deliverySeconds': row['deadlineElapsed'], 'handoffReserveSeconds': long_handoff_seconds(row['outputSeconds']),
            'cleanupReserveSeconds': LONG_POLICY['cleanupReserveSeconds']}


def run_deadlines(record: dict) -> dict:
    """The run's deadlines: run-scoped work ends with the latest output's milestones.

    A Shorts-only run gets its Shorts' latest own deadlines, which added Shorts and credit move (M-052, X217 n2).
    """
    rows = [clip_deadlines(record, clip) for clip in record['clips'].values()]
    return {**record['deadlines'], **{key: max(row[key] for row in rows) for key in TIMED}}


def output_identity(batch_id: str, clip_id: str, row: dict, clip: dict) -> str:
    """SHA-256 of what was authorized: batch, output, format, duration, derivation, recorder and first approval.

    Time is not part of it, so a repeated authorization after a lost acknowledgement is recognisable.
    """
    approval = clip['approvals'][0]['identity'] if clip['approvals'] else None
    body = {'batchId': batch_id, 'clipId': clip_id, 'format': row['format'], 'outputSeconds': row['outputSeconds'],
            'derivedFrom': row['derivedFrom'], 'recordedBy': row['recordedBy'], 'approval': approval}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def valid_lineage(value: object) -> bool:
    """A Long lineage: the prepared request's SHA-256 and 1-64 sorted unique source recording digests."""
    if type(value) is not dict or set(value) != {'request', 'sources'} or not _digest(value['request']):
        return False
    sources = value['sources']
    return type(sources) is list and 0 < len(sources) <= BOUNDS['claims'] and all(map(_digest, sources)) \
        and sources == sorted(set(sources))


def _digest(value: object) -> bool:
    """A lowercase SHA-256 hex digest."""
    return type(value) is str and SHA256.fullmatch(value) is not None


def outputs_problem(record: dict) -> str | None:
    """The first violation in any clip's format identity, or None (called on every authority read)."""
    for clip_id, clip in record['clips'].items():
        problem = _projects_problem(clip) or _output_problem(record, clip_id, clip)
        if problem:
            return f'clip {clip_id}: {problem}'
    return None


def _projects_problem(clip: dict) -> str | None:
    """A Short's projects carry their cut selection; a Long's carry none (its lineage is on its output row)."""
    long = output_format(clip) == 'long'
    if any((row['selection'] is None) != long for row in clip['projects']):
        return 'project rows do not match the output format'
    return None


def _output_problem(record: dict, clip_id: str, clip: dict) -> str | None:
    """An output row's shape, format rules, deadlines and identity."""
    row = clip.get('output')
    if row is None:
        return None
    if type(row) is not dict or set(row) != OUTPUT_KEYS or row['format'] not in FORMATS \
            or not clip['addedAfterStart'] or not _seconds(row['authorizedElapsed']) \
            or type(row['recordedBy']) is not str or not 0 < len(row['recordedBy'].strip()) <= 128:
        return 'output row fields'
    problem = _long_problem(row, clip) if row['format'] == 'long' else _short_problem(record, row, clip)
    if problem:
        return problem
    preparation, delivery = expected_deadlines(row['format'], row['authorizedElapsed'], row['outputSeconds'])
    if (row['preparationElapsed'], row['deadlineElapsed']) != (preparation, delivery):
        return 'output deadlines do not match its format and authorization time'
    if row['identity'] != output_identity(record['batchId'], clip_id, row, clip):
        return 'output identity does not match what was authorized'
    return None


def _seconds(value: object) -> bool:
    """A finite nonnegative number of seconds."""
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _long_problem(row: dict, clip: dict) -> str | None:
    """A Long: declared duration within policy, its policy copy, no Short approval, lineage bound once."""
    seconds = row['outputSeconds']
    if type(seconds) not in (int, float) or not 0 < seconds <= LONG_POLICY['maxOutputSeconds']:
        return f'a Long declares its output duration (at most {LONG_POLICY["maxOutputSeconds"]} seconds)'
    if row['policy'] != LONG_POLICY:
        return 'Long policy differs from this engine\'s policy'
    if clip['approvals'] or row['derivedFrom'] is not None:
        return 'a Long has no Short approval and derives from nothing'
    if row['lineage'] is not None and not valid_lineage(row['lineage']):
        return 'Long lineage'
    return None


def _short_problem(record: dict, row: dict, clip: dict) -> str | None:
    """A Short on its own clock: an approval, no Long fields, and a derivation (if any) from a Long of this run."""
    if row['outputSeconds'] is not None or row['policy'] is not None or row['lineage'] is not None:
        return 'a Short output row carries no duration, policy copy or lineage'
    if not clip['approvals']:
        return 'a Short on its own clock starts from its approved title and script'
    source = row['derivedFrom']
    if source is not None and (source not in record['clips'] or output_format(record['clips'][source]) != 'long'):
        return 'a derived Short names a Long output of this run'
    return None
