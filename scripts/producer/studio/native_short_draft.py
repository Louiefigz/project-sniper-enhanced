"""Full-program native Short review drafts: a distinct stage, file and status, never final media.

A review draft renders the whole authored timeline through the final media route and
technical/playability checks, but runs no reference capture, moving previews, editorial
preview-review gate or encoded-picture comparisons. Its `draft-stage.json` is refused by
--verify-from, --resume-from and automatic recovery; only --promote-draft can reuse its
exact bytes, and only after the current editorial gate, capture and full verification.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from cut_preview_io import bound_json, write_new
from studio.native_runtime import digest
from studio.native_stage_evidence import StageEvidence, read_stage, require, seal_stage

DRAFT_STATUS = 'native-short-review-draft'
DRAFT_OWNER_STATUS = 'native-short-review-draft-media-complete'
DRAFT_MEDIA_STATUS = 'review-draft-media-complete'
DRAFT_OUTPUT = 'review-draft.mp4'
DRAFT_LABEL = 'REVIEW DRAFT - editorial review pending; not final'
LAUNCH_OUTPUTS = {'draft': DRAFT_OUTPUT, 'promote': 'review.mp4'}
PROMOTION_PHASES = {'capture', 'preview', 'promote', 'verify'}
RECOVERY_REFUSAL = ('Native review drafts are never final media: --verify-from, --resume-from and automatic '
                    'recovery refuse draft-stage.json. Use --promote-draft ATTEMPT --preview-reviews BUNDLE '
                    '(final-eligible projects only).')
LIMITATIONS = (
    'Editorial review pending: no moving previews were rendered or reviewed for this draft.',
    'Final QC not run: no reference capture, reverse-seek or encoded-picture comparisons.',
    'Technical admission ran: static preflight before picture work, audio master/QC and AAC/mux checks.',
    'Playability verified: exact frame count, AAC audio clock and a full audio/video decode.',
    'Not human approved; no listening or viewing approval is implied.',
)


def project_is_draft(request: dict) -> bool:
    """Read the project's own draft authority, independently of what the request claims."""
    plan = Path(request['project']) / 'SHORT-PROJECT.json'
    return request.get('adapter', 'native-short') == 'native-short' and plan.is_file() and 'draft' in bound_json(plan)


def admit_draft_launch(request: dict, phase: str) -> None:
    """Close draft and promotion phases to their own requests at every owner launch."""
    draft, promotion = request.get('reviewDraft') is True, bool(request.get('promoteDraft'))
    require(not (draft and promotion), 'A request cannot be both a review draft and a promotion')
    require(draft or not project_is_draft(request),
            'A draft-built project launches only review-draft owners; final, preview and promotion phases refuse it')
    if draft or phase == 'draft':
        require(draft and phase == 'draft' and request.get('adapter', 'native-short') == 'native-short'
                and not request.get('verifyStage') and not request.get('previewReviews'),
                'Review-draft requests launch only the draft worker, and the draft phase needs a review-draft request')
        return
    if promotion or phase == 'promote':
        from studio.native_preview_sections import section_phase
        require(promotion and (phase in PROMOTION_PHASES or section_phase(phase) is not None),
                'Draft promotion copies sealed draft bytes; it launches no picture render')
        if phase == 'promote':
            require(not request.get('verifyStage'), 'Promotion cannot reuse another sealed render')
            from studio.native_motion_previews import require_motion_previews
            require_motion_previews(request)


def refuse_draft_media(record: dict | None, request: dict | None) -> None:
    """Ordinary final-media recovery never reads a review-draft seal or attempt."""
    require(not (record and record.get('stage') == 'draft') and not (request and request.get('reviewDraft')),
            RECOVERY_REFUSAL)


def draft_artifacts(root: Path) -> dict[str, Path]:
    """The complete draft inventory; the review MP4 has a draft-only name."""
    return {'picture': root / 'picture.mp4', 'draft': root / DRAFT_OUTPUT,
            'audio': root / 'audio/receipt.json', 'media': root / 'draft-result.json'}


def draft_media_result(record: dict) -> dict:
    """Require the complete audio/color/playability proof bound by the draft owner."""
    artifacts = record['artifacts']
    require(set(artifacts) == set(draft_artifacts(Path('/'))), 'incomplete review-draft artifact inventory')
    media = bound_json(Path(artifacts['media']['path']), artifacts['media']['sha256'])
    audio = bound_json(Path(artifacts['audio']['path']), artifacts['audio']['sha256'])
    draft, color = artifacts['draft'], media.get('color', {})
    require(media.get('status') == DRAFT_MEDIA_STATUS and media.get('reviewState') == 'draft'
            and media.get('sha256') == draft['sha256'] == color.get('sha256')
            and media.get('output') == draft['path'] == color.get('output')
            and media.get('audioReceipt') == artifacts['audio']['path'], 'review-draft media proof differs from its seal')
    require(color.get('aacPacketsIdentical') is True and color.get('additionalPictureEncodes') == 0
            and color.get('additionalAudioEncodes') == 0
            and media.get('playability', {}).get('fullAudioVideoDecodePassed') is True,
            'review-draft color or playability proof is incomplete')
    require(audio.get('status') == 'audio-qualified' and isinstance(audio.get('audioQuality'), list)
            and media.get('audioQuality') == audio['audioQuality']
            and type(media.get('audioReviewRequired')) is bool
            and media['audioReviewRequired'] == audio.get('audioReviewRequired'),
            'review-draft audio qualification is incomplete')
    return media


def read_draft_stage(receipt: Path, inputs: dict[str, str]) -> tuple[dict, dict[str, str]]:
    """Revalidate a sealed draft and every current byte it depends on."""
    record, pins = read_stage(receipt, inputs, 'draft')
    require(record['successStatus'] == DRAFT_OWNER_STATUS, 'review-draft owner status differs')
    draft_media_result(record)
    return record, pins


def seal_draft(pipeline: object) -> tuple[dict, Path]:
    """Seal the completed draft owner as the distinct 'draft' stage, never 'render'."""
    root, request = pipeline.root, pipeline.request
    spec = StageEvidence('draft', Path(request['project']), root, root / 'export-request.json',
                         root / 'draft.render.json', request['pins'], draft_artifacts(root), DRAFT_OWNER_STATUS)
    seal_stage(spec)
    receipt = root / 'draft-stage.json'
    record, pins = read_draft_stage(receipt, request['pins'])
    pipeline.evidence.update(pins)
    return record, receipt


def draft_delivery(request: dict, record: dict, receipt: Path) -> dict:
    """Visible review-draft status fields; they never claim editorial or final approval."""
    media = draft_media_result(record)
    authority = request['draftAuthority']
    limitations = list(LIMITATIONS)
    if authority['projectReviewState'] == 'draft':
        limitations.append('Draft-built project (prebuild review not passed): never promotable; '
                           'rebuild the corrected plan with a passing independent review.')
    return {'output': media['output'], 'sha256': media['sha256'], 'draftStage': str(receipt),
            'draftStageSha256': digest(receipt), 'reviewState': 'draft', 'label': DRAFT_LABEL,
            'editorialReview': 'pending', 'finalQc': 'not-run', 'humanApproved': False,
            'projectReviewState': authority['projectReviewState'],
            'promotable': authority['projectReviewState'] == 'final-eligible',
            'prebuildReview': authority['prebuildReview'], 'openFindings': authority['openFindings'],
            'limitations': limitations, 'playability': media['playability'],
            'technicalAdmission': media['technicalAdmission'], 'audioQuality': media['audioQuality'],
            'audioReviewRequired': media['audioReviewRequired'], 'additionalPictureEncodes': 1}


def execute_review_draft(pipeline: object, invocation: tuple[float, str] | None) -> bool:
    """One supervised draft owner, a distinct seal and exactly one terminal receipt."""
    from studio.native_run import utc
    started, began = invocation or (time.monotonic(), utc())
    root = pipeline.root
    result = {'status': 'failed', 'startedAt': began, 'output': str(root / DRAFT_OUTPUT),
              'reviewState': 'draft', 'label': DRAFT_LABEL, 'editorialReview': 'pending',
              'finalQc': 'not-run', 'humanApproved': False, 'renderReused': False,
              'preparationSeconds': time.monotonic() - started,
              'timingScope': 'This review-draft invocation including preparation and its owner; authoring is separate.'}
    try:
        from studio.native_budget_binding import charge_request
        from studio.native_early_stage import run_early_checks
        run_early_checks(pipeline)  # the same static gate and sealed audio stage as the final route
        charge_request(pipeline.request, 'pictureGeneration')  # the draft's one full picture, before its owner
        pipeline.supervise('draft', pipeline.worker('draft'), DRAFT_OUTPUT, DRAFT_OWNER_STATUS)
        record, receipt = seal_draft(pipeline)
        result.update(draft_delivery(pipeline.request, record, receipt), status=DRAFT_STATUS)
    except (Exception, KeyboardInterrupt) as error:
        result.update(status='failed', errorType=type(error).__name__, error=str(error),
                      failureCategory='cancelled' if isinstance(error, KeyboardInterrupt)
                      else getattr(error, 'category', 'renderer-failure'), failedPhase=getattr(error, 'phase', None))
    result.update(completedAt=utc(), elapsedSeconds=time.monotonic() - started, stages=pipeline.stages)
    write_new(root / 'delivery.json', result)
    from studio.native_budget_owner import record_budget_outcome
    budget_error = record_budget_outcome(pipeline.request, result)  # a delivered draft is a batch delivery
    if budget_error:
        print(json.dumps({**result, 'status': 'failed', 'failureCategory': 'budget-authority',
                          'budgetRecordError': budget_error}), flush=True)
        return False
    print(json.dumps(result), flush=True)
    return result['status'] == DRAFT_STATUS


def review_draft_delivery(export: Path, layout: dict | None = None) -> tuple[dict, dict, dict]:
    """Admit a sealed, playable review draft to review bundles; it stays labeled and never final."""
    from cut_preview_io import real_directory
    real_directory(export)
    request_file, delivery_file, video = export / 'export-request.json', export / 'delivery.json', export / DRAFT_OUTPUT
    request, delivery = bound_json(request_file), bound_json(delivery_file)
    require(request.get('reviewDraft') is True and request.get('output') == str(export)
            and (not layout or (layout.get('plan'), layout.get('entry')) == ('SHORT-PROJECT.json', 'index.html')),
            'review-draft bundle entry needs its own Short draft attempt and default layout')
    require(delivery.get('status') == DRAFT_STATUS and delivery.get('output') == str(video)
            and delivery.get('sha256') == digest(video) and delivery.get('humanApproved') is False
            and delivery.get('draftStage') == str(export / 'draft-stage.json'), 'incomplete review-draft delivery')
    record, pins = read_draft_stage(export / 'draft-stage.json', request['pins'])
    require(record['artifacts']['draft']['sha256'] == delivery['sha256'], 'review-draft bytes differ from their seal')
    pins.update({str(file): digest(file) for file in (request_file, delivery_file, video)})
    return delivery, request, pins


def project_review_label(project: Path) -> dict:
    """Studio/preview label from the project's own review state; never alters the composition."""
    manifest, plan = project / 'PROJECT-MANIFEST.json', project / 'SHORT-PROJECT.json'
    if not manifest.is_file() or not plan.is_file():
        return {}
    draft = bound_json(manifest).get('reviewState') == 'draft' or 'draft' in bound_json(plan)
    if not draft:
        return {'reviewState': 'not-draft', 'label': None}
    return {'reviewState': 'draft', 'label': DRAFT_LABEL, 'finalEligible': False,
            'note': 'Draft-built project: never promotable; exports must use --review-draft.'}


def review_state_notice(directory: str) -> dict:
    """Label a review-draft project in a Studio open result; the composition is never altered."""
    import sys
    notice = project_review_label(Path(directory).resolve(strict=True))
    if notice.get('label'):
        print(f"{notice['label']}: {directory}", file=sys.stderr, flush=True)
    return notice
