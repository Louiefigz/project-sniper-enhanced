"""P3a coordination vocabulary (MASTER-PLAN M-080; P3a §4.0.1): a data catalog with one rule, ``reads`` (§4.0.6).

Every coordination module reads its names, kinds, bounds and derivation paths from here; nothing restates them.
Overrides in force: ``COORDINATION_LIMITS`` holds ``planning: 3`` only (X9, C-1): the specialist cap is P3b's
``team_catalog.SPECIALIST_CAP`` (M-088), the single source, never copied here. ``SHORT_DERIVATION`` is P3a's Short
derivation table as corrected by X201 (F-1..F-4, checked against the writer at stack 35eca01b):
- F-1: declared reveals are ``data-hf-reveal`` attributes in catalog composition files (L-B,
  ``native-reveal-declarations.ts:18``), not a native-plan field. A region entry digests its composition file's
  bytes, and compositions outside every region form one global entry (``UNMAPPED_COMPOSITIONS``).
- F-2: no music or sound-effect asset role exists (``native-short-strategy.ts:14``), so ``audio`` derives only
  ``audio-finishing`` and ``assets`` stays an unlisted, global key.
- F-3: ``native_short_regions.plan_projection(plan, local)`` is called with the region rows' files as ``local``.
- F-4: P2-08's ``speakerPictureDecisions`` lies outside ``plan_projection``; it is a global entry until L-R or
  M-073 places it.
- F-5 (lane, the same widening; for ruling): every native-plan key outside ``plan_projection`` is global too, except
  the generated bindings (``role_packet_native.GENERATED_BINDINGS``, which ``planHash`` also leaves out) and the
  derived ``PLAN_DERIVED`` paths. F-4 is one case of this rule.
Anything the table does not name is global: every projection path not in ``PROJECTION_DERIVED`` and every other plan
path not in ``PLAN_DERIVED`` becomes a ``key-<path>`` graphics entry with global isolation ("unproved isolation is
global"). A dict key mapped to () is derived whole; one mapped to names is derived only at those sub-keys.
"""
from __future__ import annotations

RESPONSIBILITIES = ('source-speaker-fidelity', 'graphics-motion', 'audio-dialogue', 'captions-timing',
                    'transitions', 'story-pacing')
ROLES = ('plan-integration', 'independent-review')
PHASES = {'proposal': ('specialist',), 'integration': ('author', 'planning'), 'execution': ('author', 'specialist'),
          'verification': ('check', 'specialist'), 'review': ('planReview', 'review'), 'repair': ('repairCycle',)}
PLAN_REVIEW_SUBJECT = 'plan'          # review phase: planReview iff the subject is the plan, else review
REVIEW_SUBJECTS = ('plan', 'preview', 'export', 'section', 'program')

# Plan section -> the responsibility owning its entries; `unresolved` rows name their own `responsibility`.
SECTION_OWNER = {'story': 'story-pacing', 'captions': 'captions-timing', 'graphics': 'graphics-motion',
                 'holds': 'graphics-motion', 'framing': 'source-speaker-fidelity',
                 'sourceFacts': 'source-speaker-fidelity', 'audio': 'audio-dialogue', 'transitions': 'transitions'}
CONTENT_SECTIONS = ('story', 'holds', 'framing', 'captions', 'graphics', 'transitions', 'audio', 'sourceFacts')
ENTRY_SECTIONS = (*CONTENT_SECTIONS, 'unresolved')

# Short derivation (P3a §4.0.2 table, X201): plan section -> the inputs its entries are derived from.
# Native-plan paths are dotted; `REVIEW-REGIONS.json`, `compositions/*.html` and the sealed shared-evidence record
# (`homes.sharedEvidence`) are project files, not plan keys. Provenance per row is in the lane HANDOVER.
SHORT_DERIVATION = {
    'clock': ('canvas.frameRate', 'canvas.totalFrames'),
    'speech': ('canvas.occurrences', 'canvas.cuts', 'canvas.segments'),
    'story': ('strategy.pacing.beats',),
    'holds': ('strategy.scenes',),
    'framing': ('canvas.pictureViews',),
    'captions': ('canvas.captionGroups', 'canvas.occurrences', 'canvas.captionCorrections', 'canvas.captionMode',
                 'canvas.captionViews', 'canvas.captionProtectedPhrases', 'canvas.captionSuppressions'),
    'graphics': ('REVIEW-REGIONS.json', 'compositions/*.html', 'canvas.titleCard', 'canvas.text', 'canvas.shapes',
                 'canvas.motion', 'visualSources.decisions'),
    'transitions': ('strategy.scenes',),
    'audio': ('audioFinishing',),
    'sourceFacts': ('homes.sharedEvidence', 'canvas.cuts', 'canvas.segments', 'assets'),
}
# `plan_projection` paths the derivation covers; every other projection path is a global `key-<path>` entry.
PROJECTION_DERIVED = {
    'canvas': ('frameRate', 'totalFrames', 'occurrences', 'cuts', 'segments', 'pictureViews', 'captionGroups',
               'captionCorrections', 'captionMode', 'captionViews', 'captionProtectedPhrases', 'captionSuppressions',
               'titleCard', 'text', 'shapes', 'motion'),
    'audioFinishing': (),
    'brief': ('visualSourceDecisions',),
}
# Native-plan keys outside plan_projection that the derivation covers (F-5); every other one is global (F-4, F-5).
PLAN_DERIVED = {'strategy': ('scenes',), 'visualSources': ('decisions',), 'sharedEvidence': ()}
UNMAPPED_COMPOSITIONS = 'compositions-unmapped'   # compositions no region row covers (F-1)
PROJECT_UNIT = 'project'                          # no REVIEW-REGIONS.json: one global graphics unit

# Packet role -> its assignment (the table P4-22 extends; P3b adds its specialist roles, P4 its Long roles).
PACKET_ROLES = {
    'clip-owner': {'format': 'short', 'phases': ('integration', 'repair'), 'kinds': ('author', 'repairCycle'),
                   'subject': None},
    'plan-critic': {'format': 'short', 'phases': ('review',), 'kinds': ('planReview',), 'subject': 'plan'},
    'motion-critic': {'format': 'short', 'phases': ('review',), 'kinds': ('review',), 'subject': 'preview'},
    'final-critic': {'format': 'short', 'phases': ('review',), 'kinds': ('review',), 'subject': 'export'},
}

# Always global; so is every entry whose `isolation` is `global`.
GLOBAL_SECTIONS = ('approvedContent', 'clock', 'speech', 'story', 'sections')
# A change to the key also affects the values (§4.0.1).
DEPENDS = {
    'source-speaker-fidelity': ('graphics-motion', 'captions-timing'),
    'graphics-motion': ('source-speaker-fidelity', 'transitions'),
    'transitions': ('graphics-motion', 'audio-dialogue'),
    'captions-timing': ('graphics-motion',),
    'audio-dialogue': ('transitions',),
    'story-pacing': ('source-speaker-fidelity', 'graphics-motion', 'audio-dialogue', 'captions-timing', 'transitions'),
}

# Per output, counted from charged ledger rows, never refunded (X9: planning only; specialists are P3b's).
COORDINATION_LIMITS = {'planning': 3}
SHORT_REPAIR_RESERVE = {'repairCycle': 1, 'planReview': 1, 'review': 2}
LONG_REPAIR_RESERVE = {'repairCycle': 1, 'review': 2}
WORK_COUNTERS = ('planning', 'author', 'specialist', 'planReview', 'review', 'repairCycle')

EVIDENCE_KINDS = ('plan-record', 'owned-artifacts', 'typed-review-record', 'source-playback', 'validator-receipt',
                  'decision')
# Decision kind -> the author roles allowed to record it (§4.0.5).
DECISION_KINDS = {
    'staffing': ('director',),
    'responsibility-assigned': ('director', 'integration-owner'),
    'plan-disposition': ('director', 'integration-owner'),
    'conflict-resolved': ('director', 'integration-owner'),
    'conflict-blocking': ('director', 'integration-owner'),
    'global-change': ('integration-owner',),
    'unresolved-evidence': ('integration-owner', 'specialist', 'critic', 'director'),
    'finding-routed': ('director',),
    'finding-deferred': ('director', 'operator'),
    'finding-obsolete': ('director',),
    'finding-resolved': ('director',),
    'operator-input-needed': ('director',),
    'operator-input-received': ('operator',),
    'operator-change': ('operator',),
    'coordinator-note': ('director', 'operator'),
}
OUTPUTLESS_DECISIONS = ('staffing', 'operator-input-needed', 'operator-input-received', 'coordinator-note')

# Record and artifact bounds (§4.0.1). The result document bound is section_results.MAX_RESULT_BYTES (4 MiB).
BOUNDS = {'planRecordBytes': 1_048_576, 'bindingBytes': 8_192, 'inputPinBytes': 256 * 1024 ** 2,
          'planVersions': 8, 'decisionsPerBatch': 1_024, 'decisionEventBytes': 2_048}
# Plan-record list bounds (§4.0.2). `framing` and `audio` have no stated bound; the lane chose 128 and 64 (U-T7).
PLAN_BOUNDS = {'story': 64, 'holds': 128, 'framing': 128, 'captions': 512, 'graphics': 128, 'transitions': 64,
               'audio': 64, 'sourceFacts': 128, 'unresolved': 64, 'ownership': 64, 'contributions': 32,
               'conflicts': 32, 'decisions': 128, 'sections': 3, 'inputs': 64, 'totalFrames': 54_000}
TEXT_BYTES = {'statement': 500, 'purpose': 500, 'speaker': 120, 'rule': 500, 'evidence': 500}


def reads(responsibilities: tuple[str, ...]) -> frozenset[str]:
    """What a task holding these responsibilities reads (§4.0.6): S plus every R' whose change affects S.

    The structural roles (``plan-integration``, ``independent-review``) read every responsibility. The rule is one
    step, exactly as written: ``S ∪ {R' : DEPENDS[R'] ∩ S ≠ ∅}``.

    Raises:
        ValueError: A name outside ``RESPONSIBILITIES`` and ``ROLES``.
    """
    held = set(responsibilities)
    unknown = held - set(RESPONSIBILITIES) - set(ROLES)
    if unknown:
        raise ValueError(f'Coordination plan: responsibilities: unknown names {sorted(unknown)}')
    if held & set(ROLES):
        return frozenset(RESPONSIBILITIES)
    return frozenset(held | {source for source, targets in DEPENDS.items() if held & set(targets)})
