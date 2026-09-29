"""Worker phases for review drafts ('draft') and exact-byte promotion ('promote').

Both run inside the shared supervised owner and reuse the final route's helpers; neither
adds a checking shortcut. A draft skips only the editorial/reference-capture work that a
draft by definition lacks; a promotion encodes nothing and still requires the final gates.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from audio.audio_mix_picture import observe_picture_source
from audio.program_audio_clock import exact_aac_audio_clock
from cut_preview_io import bound_json, write_new
from stage_timing import stage_span
from studio.native_short_delivery import clock, finish_dialogue, full_decode, native_srgb_delivery
from studio.native_short_draft import (DRAFT_MEDIA_STATUS, DRAFT_OUTPUT, admit_draft_launch,
                                       draft_media_result, read_draft_stage)
from studio.native_short_picture_reuse import copy_picture
from studio.native_stage_evidence import read_native_capture_receipt, require

DRAFT_PHASES = frozenset({'draft', 'promote'})
PICTURE_TIMEOUT_SECONDS = 480  # Same bound as the final picture render; a budget grants no more than it has left.
AUDIO_FILES = ('receipt.json', 'program-master.wav', 'candidate.mp4')


def render_draft_picture(request: dict, canvas: dict, timeout: float) -> None:
    """The review draft's one expensive full-picture generation (final SDR route, shared source frames)."""
    from studio.native_short_worker import render_command
    from studio.native_source_store import prepare_source_view
    if request.get('captureMode', 'sdk-streaming') == 'sdk-streaming':
        prepare_source_view(request)  # Leased shared frames; the SDK sees only this private view.
    subprocess.run(render_command(request, canvas), check=True, timeout=timeout)


def static_admission(request: dict) -> dict:
    """The conservative static package check before any picture or audio work (early pass reused)."""
    from studio.native_early_stage import worker_static_result
    root = Path(request['output'])
    with stage_span(str(root), 'native_static_preflight'):
        static = worker_static_result(request)
    require(static['status'] == 'static-checks-pass', 'Native static preflight blocked this export')
    return {'staticPreflight': static['status'], 'staticEvidence': static['evidenceDirectory']}


def playability(candidate: Path, canvas: dict) -> dict:
    """Exact frame count, AAC presentation clock and a complete audio/video decode."""
    timeline = clock(canvas)
    duration = canvas['totalFrames'] / float(timeline.fps.fraction)
    observed = observe_picture_source(str(candidate), duration)
    require(len(observed.packets) == canvas['totalFrames'], 'Review draft frame count differs from the authored clock')
    audio = exact_aac_audio_clock(str(candidate), 'ffprobe', timeline.sample_at_frame(canvas['totalFrames']))
    full_decode(candidate, timeout=max(180, duration * 2))
    return {'expectedFrames': canvas['totalFrames'], 'videoPackets': len(observed.packets),
            'durationSeconds': duration, 'audioClock': audio, 'fullAudioVideoDecodePassed': True}


def render_review_draft(request: dict, plan: dict) -> dict:
    """The whole authored timeline with final clocks, sources, geometry and SDR command."""
    from studio.native_motion_previews import prepare_audio
    from studio.native_short_worker import verify_files
    root, canvas = Path(request['output']), plan['canvas']
    technical = static_admission(request)
    with stage_span(str(root), 'native_dialogue_preparation'):
        prepared = prepare_audio(request, plan)
    verify_files(request)
    with stage_span(str(root), 'native_picture_render'):
        from studio.native_budget_clock import stage_allowance
        render_draft_picture(request, canvas, stage_allowance(request, PICTURE_TIMEOUT_SECONDS))
    verify_files(request)
    with stage_span(str(root), 'native_dialogue_delivery'):
        audio = finish_dialogue(request, canvas, plan.get('audioFinishing'), prepared)
    with stage_span(str(root), 'native_color_metadata'):
        color = native_srgb_delivery(root, audio, DRAFT_OUTPUT)
    with stage_span(str(root), 'native_draft_playability'):
        playable = playability(root / DRAFT_OUTPUT, canvas)
    return {'status': DRAFT_MEDIA_STATUS, 'reviewState': 'draft', 'output': color['output'],
            'sha256': color['sha256'], 'audioReceipt': str(root / 'audio/receipt.json'),
            'audioReviewRequired': audio['audioReviewRequired'], 'audioQuality': audio['audioQuality'],
            'color': color, 'playability': playable, 'technicalAdmission': technical,
            'editorialReview': 'pending', 'finalQc': 'not-run', 'humanApproved': False,
            'additionalPictureEncodes': 1, 'sourceCurrent': True, 'providerCalls': 0}


def copy_draft_media(record: dict, root: Path) -> None:
    """Exact byte copies into the new attempt; the draft attempt is never written."""
    artifacts = record['artifacts']
    copy_picture(Path(artifacts['draft']['path']), root / 'review.mp4', artifacts['draft']['sha256'])
    copy_picture(Path(artifacts['picture']['path']), root / 'picture.mp4', artifacts['picture']['sha256'])
    audio = bound_json(Path(artifacts['audio']['path']), artifacts['audio']['sha256'])
    hashes = {'receipt.json': artifacts['audio']['sha256'], 'program-master.wav': audio['masterSha256'],
              'candidate.mp4': audio['candidateSha256']}
    (root / 'audio').mkdir()
    for name in AUDIO_FILES:
        copy_picture(Path(artifacts['audio']['path']).parent / name, root / 'audio' / name, hashes[name])


def promote_review_draft(request: dict, plan: dict) -> dict:
    """Final gates on the exact draft bytes: editorial gate at launch, capture proof, no encode."""
    root, promotion = Path(request['output']), request['promoteDraft']
    native = read_native_capture_receipt(root / 'native-frames.json')
    require(native.get('status') == 'native-references-and-seek-states-pass', 'Promotion requires passed reference checks')
    from studio.native_picture_references import check_samples
    check_samples(request, {**plan, 'canvas': {'width': 1080, 'height': 1920, **plan['canvas']}})
    technical = static_admission(request)
    receipt = Path(promotion['draftStage'])
    sealed = bound_json(receipt, promotion['draftStageSha256'])
    record, pins = read_draft_stage(receipt, sealed['inputs'])
    require(record['artifacts']['draft']['sha256'] == promotion['draftSha256']
            and all(request['pins'].get(file) == sha for file, sha in pins.items()), 'Promotion evidence was not pinned')
    media = draft_media_result(record)
    with stage_span(str(root), 'native_draft_promotion_copy'):
        copy_draft_media(record, root)
    output = root / 'review.mp4'
    return {'status': 'media-complete-awaiting-qc', 'output': str(output), 'sha256': media['sha256'],
            'audioReceipt': str(root / 'audio/receipt.json'), 'audioReviewRequired': media['audioReviewRequired'],
            'audioQuality': media['audioQuality'], 'color': {**media['color'], 'output': str(output)},
            'humanApproved': False, 'additionalPictureEncodes': 0, 'additionalAudioEncodes': 0,
            'sourceCurrent': True, 'providerCalls': 0,
            'promotion': {**promotion, 'bytesIdentical': True, 'draftOutput': media['output'],
                          'draftPlayability': media['playability'], 'staticAdmission': technical}}


def execute_draft_phase(request: dict, phase: str) -> dict:
    """Dispatch the closed draft/promotion phases after the same input and vocabulary checks."""
    from studio.native_short_worker import verify_files
    require(phase in DRAFT_PHASES, 'Unsupported review-draft phase')
    root = Path(request['output'])
    plan = bound_json(Path(request['project']) / 'SHORT-PROJECT.json')
    verify_files(request)
    admit_draft_launch(request, phase)
    if phase == 'draft':
        result = render_review_draft(request, plan)
        write_new(root / 'draft-result.json', result)
    else:
        result = promote_review_draft(request, plan)
        write_new(root / 'render-result.json', result)
    verify_files(request)
    return result
