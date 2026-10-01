"""P3a coordination vocabulary (MASTER-PLAN M-080; P3a §4.0.1): a data catalog with one rule, ``reads`` (§4.0.6).

Every coordination module reads its names, kinds, bounds and derivation paths from here; nothing restates them.
Overrides in force: ``COORDINATION_LIMITS`` holds ``planning: 3`` only (X9, C-1): the specialist cap is P3b's
``team_catalog.SPECIALIST_CAP`` (M-088), the single source, never copied here. ``SHORT_DERIVATION`` is P3a's Short
derivation table as the rulings correct it (checked against the writer at stack 35eca01b). The governing rule
(X211): no plan input change may move no slice, and a derived summary never makes everything global.
- X201 F-1: declared reveals are ``data-hf-reveal`` attributes in catalog composition files (L-B,
  ``native-reveal-declarations.ts:18``). A region entry digests its composition's bytes; compositions outside every
  region form one global entry (``UNMAPPED_COMPOSITIONS``).
- X201 F-2: no music or sound-effect asset role exists (``native-short-strategy.ts:14``): ``audio`` derives
  ``audio-finishing`` only, and ``assets`` is a global key.
- X201 F-3: ``native_short_regions.plan_projection(plan, local)`` gets the region rows' files as ``local``.
- X201 F-4, X205 F-5: every native-plan path neither derived nor generated is a global ``key-<path>`` entry.
- L-R 4f1f4704 (its HANDOVER Interfaces table; coordinator, X211 round): ``speakerPictureDecisions`` is a top-level,
  author-written list that only P2-08 reads (``native-short-speaker-picture.ts``: over whole speaker intervals, exit
  runs, and the visual windows a supporting-visual decision needs). It is the whole-output framing entry
  ``SPEAKER_DECISIONS`` (source-speaker-fidelity) instead of F-4's global entry, pending L-R's review.
- X211(1): only ``GENERATED_EXEMPT`` is skipped; ``preparedSources`` is an input its ``PREPARED_READERS`` digest.
- X211(2): row fields ``plan_projection`` drops are digested (global for assets, the region's own entry for a
  region-bound catalog file, else global); only a row's ``path`` (a location its sha256 pins) is not.
- X211(3): the sealed record's people with a face region on this source, its speaker observations and its
  intervals on this source form the ``speaker-evidence`` framing entry.
- X211(4): the writer-verified summaries in ``SUMMARY_SOURCES`` are derived paths; each source they cover moves
  its own slice (``test_coordination_writer_plan`` proves it per source).
- X211 minor (W3-D8), X232 D-3 (accepted as a P3a S2 amendment): a top-level or canvas key outside
  ``WRITER_KEYS``/``CANVAS_KEYS`` stops the derivation by name, so a renamed P2 field never passes as a new global key;
  a change that adds a writer key updates these tuples and the derivation table in the same change.
- X232 D-1: ``strategy.visualPlanApplication`` is not a summary. Only its writer-verified hashes are derived
  (``visualPlanSha256`` and the ``APPLICATION_HASHES`` leaves); each decision's authored execution mapping is a scoped
  graphics entry over its window.
- X232 D-2: Short section bounds come from the writer's own limits (``SHORT_DERIVED_MAXIMA``); global keys are one
  entry per top-level root, so their count is bounded by the closed vocabulary (``KEY_ROOT_BOUND``).
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
    'framing': ('canvas.pictureViews', 'preparedSources', 'homes.sharedEvidence', 'speakerPictureDecisions'),
    'captions': ('canvas.captionGroups', 'canvas.occurrences', 'canvas.captionCorrections', 'canvas.captionMode',
                 'canvas.captionViews', 'canvas.captionProtectedPhrases', 'canvas.captionSuppressions',
                 'preparedSources'),
    'graphics': ('REVIEW-REGIONS.json', 'compositions/*.html', 'canvas.titleCard', 'canvas.text', 'canvas.shapes',
                 'canvas.motion', 'visualSources.decisions', 'catalogFiles', 'strategy.visualPlanApplication.decisions'),
    'transitions': ('strategy.scenes',),
    'audio': ('audioFinishing', 'preparedSources'),
    'sourceFacts': ('homes.sharedEvidence', 'canvas.cuts', 'canvas.segments', 'assets'),
}
# X211(1)/(3) inputs folded into existing entries: preparedSources (audio, captions, framing) and the sealed record's
# people, observations and intervals (the framing entry SPEAKER_EVIDENCE).
# `plan_projection` paths the derivation covers (dotted); every other projection path is a global `key-<path>` entry.
PROJECTION_DERIVED = ('canvas.frameRate', 'canvas.totalFrames', 'canvas.occurrences', 'canvas.cuts', 'canvas.segments',
                      'canvas.pictureViews', 'canvas.captionGroups', 'canvas.captionCorrections', 'canvas.captionMode',
                      'canvas.captionViews', 'canvas.captionProtectedPhrases', 'canvas.captionSuppressions',
                      'canvas.titleCard', 'canvas.text', 'canvas.shapes', 'canvas.motion', 'audioFinishing',
                      'brief.visualSourceDecisions')
# Bindings the engine generates from plan fields that already move slices (X211(1)); the TS plan hash leaves them out
# too (native-short-prebuild-review.ts:40-42), as it does preparedSources, which X211(1) rules is a real input.
GENERATED_EXEMPT = ('prebuildReview', 'guidedBinding', 'draft')
# The prepared working media (native-short-project.ts:47; native-selected-sources.ts:9-17: per-source video and audio):
# its sha256 joins audio-finishing, caption-style and every picture view.
PREPARED_READERS = ('audio', 'captions', 'framing')
LOCATION_KEYS = ('path',)   # a row's location; the row's own sha256 pins its bytes (X211(2))
# Writer-verified summaries (X211(4)) -> the plan paths each covers, per the writer at stack 35eca01b.
SUMMARY_SOURCES = {
    'strategy.pacing.timingHash': ('canvas.sourceFile', 'canvas.cuts', 'canvas.segments', 'canvas.frameRate',
                                   'canvas.totalFrames', 'canvas.occurrences', 'canvas.captionGroups'),
    'strategy.pacing.visualHash': ('canvas.pictureViews', 'canvas.captionViews', 'canvas.captionMode',
                                   'canvas.captionCorrections', 'canvas.captionSuppressions', 'canvas.text',
                                   'canvas.shapes', 'canvas.motion', 'canvas.titleCard', 'extension', 'strategy.scenes',
                                   'strategy.supportingSearch', 'assets'),
    'visualSources.subjectSha256': ('canvas', 'extension', 'catalogFiles', 'catalogTitle'),
    'strategy.assetUse.revisionHash': ('request', 'requestPacket', 'canvas', 'extension', 'assets', 'strategy.scenes',
                                       'strategy.supportingSearch'),
    'strategy.story.revisionHash': ('strategy.assetUse', 'strategy.pacing', 'strategy.viewerBenefit',
                                    'strategy.hookReasonToWatch', 'strategy.payoff', 'expectations', 'request',
                                    'requestPacket', 'canvas', 'extension', 'assets', 'strategy.scenes',
                                    'strategy.supportingSearch'),
    'strategy.visualPlanApplication.visualPlanSha256': ('visualPlan',),
}
SUMMARY_WRITERS = {   # where the writer computes each summary (file:line at stack 35eca01b)
    'strategy.pacing.timingHash': 'native-short-pacing-observations.ts:20-21',
    'strategy.pacing.visualHash': 'native-short-pacing-observations.ts:22-29',
    'visualSources.subjectSha256': 'visual-source-admission.ts:15-16, 30-32',
    'strategy.assetUse.revisionHash': 'native-short-asset-use.ts:13-18, 42',
    'strategy.story.revisionHash': 'native-short-story.ts:27-31, 51',
    'strategy.visualPlanApplication.visualPlanSha256': 'native-visual-plan-application.ts:206 (equals the visualPlan pin)',
}
# Hash leaves inside a visual-plan decision (X232 D-1): each is the sha256 of executable bytes the writer derives from
# plan inputs that move their own slices, and the writer refuses any other value (native-visual-plan-application.ts:124;
# native-visual-execution-binding.ts:103-144, :176-182). Every other decision leaf is authored or copied: digested.
APPLICATION_HASHES = ('implementationSha256', 'elementSha256', 'contentSha256', 'configurationSha256')
# Native-plan paths outside plan_projection the derivation covers; every other one is global (F-4, F-5).
PLAN_DERIVED = ('strategy.scenes', 'visualSources.decisions', 'sharedEvidence', 'preparedSources', 'speakerPictureDecisions',
                'strategy.visualPlanApplication.decisions', *SUMMARY_SOURCES)
# The writer's key vocabulary at stack 35eca01b plus P2's fields (native-short-project.ts:34-55,
# native-short-composition.ts:33-47; P2-05 P2-EARLY-CHECKS:590, P2-08 :721-722). Anything else stops by name.
WRITER_KEYS = ('visualSources', 'catalogFiles', 'catalogTitle', 'schemaVersion', 'request', 'strategy', 'canvas',
               'assets', 'requestPacket', 'visualPlan', 'prebuildReview', 'draft', 'preparedSources', 'guidedBinding',
               'audioFinishing', 'extension', 'expectations', 'sharedEvidence', 'speakerPictureDecisions')
CANVAS_KEYS = ('title', 'frameRate', 'totalFrames', 'background', 'sourceSize', 'sourceFile', 'cuts', 'segments',
               'occurrences', 'captionGroups', 'captionCorrections', 'captionMode', 'captionSuppressions',
               'pictureViews', 'captionViews', 'text', 'shapes', 'motion', 'titleCard', 'captionProtectedPhrases')
P2_FIELDS = ('canvas.captionProtectedPhrases', 'sharedEvidence', 'speakerPictureDecisions')   # not yet integrated
SPEAKER_EVIDENCE = 'speaker-evidence'             # the sealed record's picture-relevant facts (X211(3))
SPEAKER_DECISIONS = 'speaker-picture-decisions'   # the plan's answers to those facts (P2-08; L-R 4f1f4704)
FRAMING_EVIDENCE = (SPEAKER_EVIDENCE, SPEAKER_DECISIONS)   # whole-output framing entries beside the picture views
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

# The writer's own list limits at stack 35eca01b (X232 D-2), and the most entries each Short section can derive.
WRITER_LIMITS = {'pictureViews': 128, 'cues': 128, 'motion': 128,      # native-short-composition.ts:125-127
                 'regions': 128,                                        # native_short_regions.py:119 (REVIEW-REGIONS)
                 'beats': 128,                                          # native-short-pacing.ts:41
                 'scenes': 64,                                          # native-short-strategy.ts:90
                 'visualPlanDecisions': 256}                            # planner/visual_plan_fields.py:178
KEY_ROOT_BOUND = len(WRITER_KEYS) + 1      # one key-<root> per top-level writer key, plus plan_projection's `brief`
SHORT_DERIVED_MAXIMA = {
    'story': WRITER_LIMITS['beats'],
    'holds': WRITER_LIMITS['scenes'],
    'transitions': WRITER_LIMITS['scenes'] - 1,
    'framing': WRITER_LIMITS['pictureViews'] + len(FRAMING_EVIDENCE),
    'graphics': (WRITER_LIMITS['regions'] + 1 + 1 + WRITER_LIMITS['cues'] + WRITER_LIMITS['motion'] + 1
                 + WRITER_LIMITS['visualPlanDecisions'] + KEY_ROOT_BOUND),   # +1 unmapped/project, title card, sources
    'audio': 1,
}
# Record and artifact bounds (§4.0.1). The result document bound is section_results.MAX_RESULT_BYTES (4 MiB).
BOUNDS = {'planRecordBytes': 1_048_576, 'bindingBytes': 8_192, 'inputPinBytes': 256 * 1024 ** 2,
          'planVersions': 8, 'decisionsPerBatch': 1_024, 'decisionEventBytes': 2_048,
          'planDepth': 32}   # JSON nesting; the lane's bound (X211 minor), far above a record's real depth
# Plan-record list bounds (§4.0.2). `framing` and `audio` have no stated bound: framing is the writer's views plus the
# evidence entries (X232 D-2), audio the lane's 64 (U-T7).
PLAN_BOUNDS = {'story': 64, 'holds': 128, 'framing': SHORT_DERIVED_MAXIMA['framing'], 'captions': 512, 'graphics': 128,
               'transitions': 64, 'audio': 64, 'sourceFacts': 128, 'unresolved': 64, 'ownership': 64, 'contributions': 32,
               'conflicts': 32, 'decisions': 128, 'sections': 3, 'inputs': 64, 'totalFrames': 54_000}
# A Short's derived sections are bounded by what the writer admits (X232 D-2); a Long's authored ones by P3a.
SHORT_PLAN_BOUNDS = {**PLAN_BOUNDS, **{key: max(PLAN_BOUNDS[key], value) for key, value in SHORT_DERIVED_MAXIMA.items()}}
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
