"""Public review-draft and promotion options, project admission and request selection."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from audio.mastering_profile import NATIVE_SHORT_MASTERING_PROFILE
from cut_preview_io import bound_json, real_directory
from studio.native_runtime import REPO, digest
from studio.native_short_draft import DRAFT_STATUS, read_draft_stage
from studio.native_stage_evidence import require

# The draft attempt's own keys; its audio stage is not the promotion's (a promotion encodes no audio).
DRAFT_ONLY = ('reviewDraft', 'draftAuthority', 'output', 'pins', 'previewOnly', 'audioStage')
FINDING_KEYS = {'code', 'severity', 'message', 'lane', 'evidence'}
SEVERITIES = {'info', 'minor', 'major', 'critical'}


def draft_options(parser: argparse.ArgumentParser, stage: argparse._MutuallyExclusiveGroup) -> None:
    """Add the explicit draft/promotion stages beside --render-only/--verify-from/--resume-from."""
    stage.add_argument('--review-draft', action='store_true',
                       help='Render the whole authored edit as a labeled review-draft.mp4; editorial review '
                            'stays pending, final QC is not run and the result is never final')
    stage.add_argument('--promote-draft', type=Path,
                       help='Promote the exact bytes of a final-eligible review-draft attempt after current '
                            '--preview-reviews, reference capture and full verification (no encode)')
    parser.add_argument('--draft-findings', type=Path,
                        help='JSON {"schemaVersion":1,"findings":[...]} of open findings shown with a review draft')


def validate_draft_options(args: argparse.Namespace) -> None:
    """Reject options that would change a draft's route or skip a promotion's editorial gate."""
    draft, promote = getattr(args, 'review_draft', False), getattr(args, 'promote_draft', None)
    if getattr(args, 'draft_findings', None) and not draft:
        raise ValueError('--draft-findings records open findings on a --review-draft export only')
    if not (draft or promote):
        return
    if args.audio_donor or args.picture_donor or getattr(args, 'preview_only', False) \
            or getattr(args, 'preview_from', None):
        raise ValueError('Review drafts and promotions accept no donors, --preview-only or --preview-from')
    if draft and getattr(args, 'preview_reviews', None):
        raise ValueError('--review-draft skips moving previews and their review gate; apply reviews with --promote-draft')
    if promote and not getattr(args, 'preview_reviews', None):
        raise ValueError('--promote-draft requires current --preview-reviews')
    if promote and getattr(args, 'audio_stage', None):
        raise ValueError('--promote-draft copies the draft\'s encoded audio; omit --audio-stage')
    if promote and (args.cache or args.cached_native_batches or getattr(args, 'sdk_streaming', False) or args.acquire_source_cache
                    or getattr(args, 'reference_map', None)
                    or args.audio_profile != NATIVE_SHORT_MASTERING_PROFILE.identity):
        raise ValueError('--promote-draft preserves the draft route, cache, audio policy and reference map; '
                         'omit render options')


def finding(row: object) -> dict:
    """One bounded open finding; findings describe a draft and never grant approval."""
    require(isinstance(row, dict) and {'code', 'severity', 'message'} <= set(row) <= FINDING_KEYS,
            'Draft finding needs code, severity and message (optional lane, evidence)')
    require(isinstance(row['code'], str) and re.fullmatch('[A-Z0-9][A-Z0-9_-]{1,63}', row['code']) is not None
            and row['severity'] in SEVERITIES and isinstance(row['message'], str)
            and 0 < len(row['message'].strip()) and len(row['message']) <= 2000, 'Invalid draft finding')
    evidence = row.get('evidence', [])
    require(isinstance(evidence, list) and len(evidence) <= 20
            and all(isinstance(item, str) and 0 < len(item) <= 1000 for item in evidence), 'Invalid finding evidence')
    require(isinstance(row.get('lane', ''), str) and len(row.get('lane', '')) <= 80, 'Invalid finding lane')
    return {**row, 'source': 'draft-findings'}


def supplied_findings(file: Path | None) -> tuple[list[dict], dict | None]:
    """Read explicit findings once; the immutable request retains their content and hash."""
    if file is None:
        return [], None
    path = file.resolve(strict=True)
    value = bound_json(path)
    require(set(value) == {'schemaVersion', 'findings'} and value['schemaVersion'] == 1
            and isinstance(value['findings'], list) and 1 <= len(value['findings']) <= 64,
            'Draft findings need schemaVersion 1 and 1-64 findings')
    rows = [finding(row) for row in value['findings']]
    require(len({row['code'] for row in rows}) == len(rows), 'Draft finding codes must be unique')
    return rows, {'path': str(path), 'sha256': digest(path)}


def project_admission(args: argparse.Namespace, project: Path, local: tuple[dict, dict], timeout: float) -> dict:
    """Draft-mode cold read for --review-draft; {} leaves the caller's strict final check-export.

    ``local`` is the (tools, environment) pair; ``timeout`` is the caller's budget-bounded allowance.
    """
    if not getattr(args, 'review_draft', False):
        return {}
    tools, environment = local
    completed = subprocess.run([tools['node'], '--import', 'tsx', str(REPO / 'scripts/producer/native-short.ts'),
                                'check-draft', str(project)], cwd=REPO, env=environment,
                               check=True, timeout=timeout, stdout=subprocess.PIPE, text=True)
    checked = json.loads(completed.stdout.strip().splitlines()[-1])
    require(checked.get('status') == 'project-current' and checked.get('humanApproved') is False
            and checked.get('reviewState') in {'draft', 'final-eligible'}, 'Unexpected draft-mode project admission')
    rows, binding = supplied_findings(getattr(args, 'draft_findings', None))
    return {'reviewDraft': True, 'draftAuthority': {
        'schemaVersion': 1, 'projectReviewState': checked['reviewState'], 'projectDraft': checked['draft'],
        'prebuildReview': checked['prebuildReview'], 'openFindings': [*checked['openFindings'], *rows],
        'suppliedFindings': binding, 'editorialReview': 'pending'}}


def draft_selection(args: argparse.Namespace, request: dict, reference_map: Path | None) -> dict | None:
    """Bind a review draft or promotion before publication; None selects the ordinary export."""
    if request.get('reviewDraft'):
        from studio.native_reference_reuse import bind_reference_map
        return {**bind_reference_map(request, reference_map), 'previewOnly': False}
    promote = getattr(args, 'promote_draft', None)
    return prepare_promotion(request, promote.absolute()) if promote else None


def draft_input_pins(draft: dict) -> dict[str, str]:
    """The draft's project-input pins: its request pins without the sealed audio stage it imported."""
    binding = draft.get('audioStage') or {}
    stage = set()
    if binding.get('mode') in ('discovered', 'explicit'):
        record = bound_json(Path(binding['seal']), binding['sealSha256'])
        stage = {binding['seal'], record['masterReceipt']['path']}
    return {file: sha for file, sha in draft['pins'].items() if file not in stage}


def prepare_promotion(current: dict, attempt: Path) -> dict:
    """Admit only an exact completed draft of a final-eligible project whose inputs are unchanged."""
    from studio.native_reference_reuse import bind_reference_map
    real_directory(attempt)
    draft = bound_json(attempt / 'export-request.json')
    require(draft.get('reviewDraft') is True and draft.get('output') == str(attempt), 'Promotion needs a review-draft attempt')
    require(draft['draftAuthority'].get('projectReviewState') == 'final-eligible',
            'A draft-built project can never be promoted; rebuild the corrected plan with a passing independent review')
    delivery_file = attempt / 'delivery.json'
    delivery = bound_json(delivery_file)
    require(delivery.get('status') == DRAFT_STATUS and delivery.get('promotable') is True,
            'Promotion needs a completed promotable review draft')
    for key in ('project', 'runtime', 'tools'):
        require(draft.get(key) == current.get(key), f'current {key} differs from the review draft')
    mapping = draft.get('referenceMap')
    current = bind_reference_map(current, Path(mapping) if mapping else None)
    require(current['pins'] == draft_input_pins(draft),
            'Current inputs differ from the sealed draft inputs; export a new draft or final')
    receipt = attempt / 'draft-stage.json'
    record, evidence = read_draft_stage(receipt, draft['pins'])
    draft_bytes = record['artifacts']['draft']
    require(delivery.get('draftStage') == str(receipt) and delivery.get('sha256') == draft_bytes['sha256'],
            'Review-draft delivery differs from its sealed bytes')
    output = Path(current['output'])
    require(output != attempt and not output.is_relative_to(attempt) and not attempt.is_relative_to(output),
            'Promotion output must preserve the draft attempt')
    promotion = {'schemaVersion': 1, 'attempt': str(attempt), 'draftStage': str(receipt),
                 'draftStageSha256': evidence[str(receipt)], 'draftSha256': draft_bytes['sha256'],
                 'draftDelivery': str(delivery_file), 'draftDeliverySha256': digest(delivery_file)}
    base = {key: value for key, value in draft.items() if key not in DRAFT_ONLY}
    pins = {**draft['pins'], **evidence, str(delivery_file): promotion['draftDeliverySha256']}
    return {**base, 'output': str(output), 'promoteDraft': promotion, 'pins': pins}
