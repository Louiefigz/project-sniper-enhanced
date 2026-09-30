"""The Long output policy as versioned data: each Long output row freezes one version when it is authorized.

``LONG_POLICY_V1`` is, byte for byte, the policy every Long authorized before P4 froze (it was
``formats.LONG_POLICY``). ``CURRENT_LONG_POLICY`` is the policy a new Long authorization freezes: version 2 with its
late-delivery mode (``LATE_LONG_DELIVERY``, one line of policy data; a row without the key, every v1 row, refuses late
work). An output row is readable only while its copy is a version this engine knows (``known_long_policy``): exactly
v1, or exactly v2 plus a valid late mode. Historical authorizations keep the policy they froze and are verified with
it; only new authorizations get the current one. Nothing here is a runtime switch: changing a value is an engine
change, which only new authorizations see.

Every number names its evidence. ``LONG_DURATION_EVIDENCE`` states what was measured per output duration and
``LONG_RISKS`` what the rates do not cover (graphics-dense pictures). This is a data catalog: it imports nothing from
``production.formats``, which reads it (MASTER-PLAN M-122; P4-LONG P4-02).
"""
from __future__ import annotations

import json

LONG_POLICY_V1 = {
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
# Version 2 until M-123 gives it P4-03's calibrated value: version 1's numbers with its version, so this step changes
# no number while the version logic is already in force (P4-02 "Behaviour").
LONG_POLICY_V2 = {**LONG_POLICY_V1, 'version': 2}
# Operator decision pending (P4 section 9 D1; P4-24). The alternative is {'mode': 'labeled', 'graceSeconds': N}.
LATE_LONG_DELIVERY = {'mode': 'refuse'}
CURRENT_LONG_POLICY = {**LONG_POLICY_V2, 'lateDelivery': LATE_LONG_DELIVERY}
MAX_LATE_GRACE_SECONDS = 10800   # a labeled late Long works at most another 180 minutes past its deadline
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


def valid_late_delivery(value: object) -> bool:
    """True for exactly ``{'mode': 'refuse'}`` or ``{'mode': 'labeled', 'graceSeconds': g}`` with an int g in
    (0, 10800]; a bool, a float or any other key is refused."""
    if type(value) is not dict:
        return False
    if _exact(value, {'mode': 'refuse'}):
        return True
    grace = value.get('graceSeconds')
    return set(value) == {'mode', 'graceSeconds'} and value['mode'] == 'labeled' and type(grace) is int \
        and 0 < grace <= MAX_LATE_GRACE_SECONDS


def known_long_policy(policy: object) -> str | None:
    """'v1' or 'v2' when an output row's policy copy is exactly a version this engine knows, else None.

    v1 is ``LONG_POLICY_V1`` with no other key (so no late mode: it refuses late work). v2 is ``LONG_POLICY_V2`` plus
    a valid ``lateDelivery``. Equality is exact in value and JSON type: ``True`` or ``1.0`` never stands in for ``1``.
    """
    if _exact(policy, LONG_POLICY_V1):
        return 'v1'
    if type(policy) is not dict or not valid_late_delivery(policy.get('lateDelivery')):
        return None
    rest = {key: value for key, value in policy.items() if key != 'lateDelivery'}
    return 'v2' if _exact(rest, LONG_POLICY_V2) else None


def _exact(value: object, expected: dict) -> bool:
    """Equal to ``expected`` with the same JSON types throughout (an int is not a float or a bool)."""
    return value == expected and _canonical(value) == _canonical(expected)


def _canonical(value: object) -> str:
    """The sorted, compact JSON text of a policy value."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'))
