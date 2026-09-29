"""Policy and shape data of the production-budget record (a data catalog: literals only, no logic).

``native_budget_schema`` re-exports every name here, so importers keep importing from it. These values
are the policy one ``SCHEMA_VERSION`` governs with: changing one needs a new schema version and its pinned
policy digest (``native_budget_schema.policy_digest``). ``SCHEMA_VERSION``, the compiled patterns and the
``ROWS`` check table stay in ``native_budget_schema``.
"""
from __future__ import annotations

PRE_RELEASE = (4,)          # development-only shapes: refused by name, never read (5 adds production.formats)

LIMITS = {
    'repairCycle': 2,        # consolidated correction sets, across all stages
    'author': 3,             # initial candidate + at most 2 focused repair assignments
    'review': 8,             # independent reviewer assignments incl. rechecks
    'planReview': 2,         # initial consolidated round + 1 corrected round
    'previewLaunch': 2,      # moving-preview launches, failed ones included
    'exportAttempt': 2,      # full-program launches: drafts, finals, verify/resume/promote, failures
    'pictureGeneration': 2,  # expensive full-picture renders, distinct from AAC/mux candidates
    'aacCandidate': 6,       # final-delivery AAC/master candidates per clip
    'aacPerAudio': 3,        # ... and per exact audio-input revision (includes the first)
    'transientRetry': 1,     # demonstrably transient failure retries across the whole clip
}
DEADLINES = {
    'preparationSeconds': 1500,   # minute 25: no creative polish admitted afterwards
    'draftDecisionSeconds': 1200,  # minute 20: at-risk clips must choose the review draft
    'deliverySeconds': 2400,      # minute 40: visible complete MP4 handoff
    'handoffReserveSeconds': 120,  # playback check + opening MP4/Studio before minute 40
    'cleanupReserveSeconds': 45,   # owned cleanup inside every granted allocation
}
# Seconds of wall time per second of authored output plus a fixed part (native_budget_forecast).
# Measured one at a time on the integrated engine (dense 45.6 s TEST clip: preview 370 s, draft 317 s,
# promotion 52 s, final reusing the preview's capture 361 s), times 1.21 for the qualified three-way
# pool (each concurrent final ran 1.21x its serial time). Verify/resume keep the earlier receipts.
PROVISIONAL_RATES = {
    'source': 'integrated engine 3b367f6, serial calibration outputs/shorts-sla-qualification/calibration/'
              'cal-3b367f6 x1.21 for 3 heavy slots (pool-qualification run-n3); verify/resume from the '
              'IMG_5954 receipts (outputs/shorts-delay-audit-2026-09-26)',
    'safetyFactor': 1.25,
    'routes': {
        'preview': {'perOutputSecond': 6.1, 'fixedSeconds': 170.0},
        'final': {'perOutputSecond': 8.9, 'fixedSeconds': 30.0},
        'draft': {'perOutputSecond': 8.0, 'fixedSeconds': 20.0},
        'promote': {'perOutputSecond': 1.1, 'fixedSeconds': 15.0},
        'verify': {'perOutputSecond': 5.3, 'fixedSeconds': 15.0},
    },
}
COUNTERS = ('author', 'review', 'planReview', 'repairCycle', 'previewLaunch', 'exportAttempt',
            'pictureGeneration', 'previewPackage', 'aacCandidate', 'transientRetry')
CLIP_STATES = ('active', 'handed-off')
ATTEMPT_STATES = ('running', 'succeeded', 'failed', 'abandoned')
ROUTES = ('preview', 'final', 'draft', 'verify', 'resume', 'promote')
NESTED = ('pictureGeneration', 'aacCandidate', 'previewPackage')
DISPATCH_KINDS = ('author', 'review', 'planReview', 'repairCycle')
BOUNDS = {'clips': 32, 'projects': 64, 'attempts': 64, 'dispatches': 256, 'deliveries': 64,
          'holds': 64, 'claims': 64, 'ranges': 512, 'stages': 64, 'tasks': 256, 'prerequisites': 16,
          'approvals': 4, 'approvalWords': 1024, 'approvalRanges': 128}
# Run-scoped AI work (director, shared planning/review, specialists and every descendant). The run
# declares its host slots and total reservations at start (``production.ai``); these are ceilings.
# Default slots: the audited host exposes four collaboration slots including its coordinator
# (ORCHESTRATION-DESIGN-REVIEW §9); a qualified host record replaces that default when it exists.
AI_POLICY = {
    'slotsCeiling': 16,         # concurrent AI reservations a run may declare
    'reservationsCeiling': 256,  # AI tasks a run may ever charge (one per task, never refunded)
    'runScopedAllowance': 8,    # default run-scoped reservations beside the per-clip dispatch ceilings
    'defaultSlots': 4,
    'depth': 3,                 # director -> task -> child -> grandchild
}
RECORD_KEYS = {'schemaVersion', 'batchId', 'status', 'startEpoch', 'clock', 'limits', 'deadlines',
               'rates', 'poolSlots', 'engine', 'holds', 'claims', 'clips', 'closedAtElapsed', 'production'}
BATCH_STATES = ('active', 'draining', 'closed')
CLIP_ROWS = {'projects': 'project', 'attempts': 'attempt', 'dispatches': 'dispatch', 'deliveries': 'delivery',
             'approvals': 'approval'}
CLIP_KEYS = {'addedAfterStart', 'reason', 'state', 'outputSeconds', 'counters', 'aacByAudio', *CLIP_ROWS}
