"""Synthetic source evidence for static fixtures, never production design approval.

The request explicitly selects a local TEST reference. Rebinding is deliberate
at fixture-authoring boundaries; tests that exercise stale evidence must not
call the binder after mutation. No validator is patched or bypassed.
"""
from __future__ import annotations

import json
from pathlib import Path

from graphics.visual_source_project import admit_project_sources, describe_project
from studio.native_runtime import digest


def write_test_json(file: Path, value: dict) -> None:
    """Persist explicitly synthetic test data without producing runtime approval."""
    file.write_text(json.dumps(value), encoding='utf-8')


def test_source_request(project: Path) -> tuple[dict, dict]:
    """Keep selected reference/request outside the subject inventory and unchanged."""
    directory = project.parent / f'TEST-source-evidence-{project.name}'
    directory.mkdir(exist_ok=True)
    reference, request = directory / 'reference.json', directory / 'request.json'
    if not reference.exists():
        write_test_json(reference, {
            'TEST_ONLY': 'Synthetic static dependency fixture; not rendered artwork.',
            'design': 'Inert test text, local assets and explicit timeline declarations.',
            'scope': 'Exercise source identity and SDK rejection of deliberate mutations.',
            'visualQualityApproved': False,
        })
    pin = {'path': str(reference), 'sha256': digest(reference)}
    if not request.exists():
        write_test_json(request, {
            'TEST_ONLY': 'This isolated test explicitly selects its synthetic reference.',
            'selectedReferences': [pin], 'project': str(project),
        })
    return {'path': str(request), 'sha256': digest(request)}, pin


def bind_test_project_sources(project: Path) -> dict:
    """Record an explicit TEST source choice for the current authored static bytes."""
    request, reference = test_source_request(project)
    receipt = describe_project(project)
    receipt['request'] = request
    receipt['decisions'] = [{
        'route': 'reference', 'targets': receipt['targets'], 'reference': reference,
        'reason': 'The TEST request explicitly selects this inert dependency fixture.',
        'adaptation': 'Apply only this test case’s authored dependency mutations; '
                      'no real media, editorial review or production quality is asserted.',
    }]
    receipt.pop('sourceEvidenceChecked')
    write_test_json(project / 'VISUAL-SOURCES.json', receipt)
    result = admit_project_sources(project)
    if result['visualQualityApproved'] is not False:
        raise AssertionError('TEST source admission must never grant quality approval')
    return result


def test_motion_review(request: dict, preview: Path, packet: dict) -> Path:
    """Model only review-schema admission, with explicit no-playback TEST evidence."""
    root = Path(request['output'])
    evidence = root / 'TEST-no-playback.txt'
    evidence.write_text('TEST structural fixture only. Nobody viewed these synthetic bytes.')
    coverage = ('briefAndRetainedMessage', 'assetsAndSourceEvidence', 'cuesAndSceneCoverage',
                'layoutCropAndText', 'motionAndTransitions', 'pacingAndAudio', 'feasibility',
                'visualSourceSelection')
    review = {
        'reviewer': {'identity': 'TEST synthetic reviewer', 'sessionId': 'TEST-review',
                     'plannerSessionId': 'TEST-author', 'independent': True},
        'coverage': {key: 'TEST structural assessment; no playback or real review occurred' for key in coverage},
        'evidence': [{'path': str(evidence), 'sha256': digest(evidence)}],
        'review': {'schemaVersion': 1, 'stage': 'plan', 'verdict': 'pass',
                   'summary': 'TEST validator fixture only', 'materialIssues': [], 'findings': []},
        'units': {row['id']: row['hash'] for row in packet['units']},
        'preview': {'path': str(preview), 'sha256': digest(preview)},
        'assessment': 'TEST fixture, not production approval; no media was played or reviewed.',
    }
    file = root / 'TEST-motion-reviews.json'
    write_test_json(file, {'schemaVersion': 1, 'reviews': [review]})
    request['previewReviews'] = str(file)
    request['pins'].update({str(path): digest(path) for path in (file, preview, evidence)})
    return file


def bind_test_motion_previews(request: dict) -> Path:
    """Exercise the real review gate using structurally valid inert TEST artifacts."""
    from studio.native_review_regions import region_packet, preview_windows
    root = Path(request['output'])
    packet = region_packet(request)
    clips = []
    for index, window in enumerate(preview_windows(packet)):
        media = root / f'TEST-preview-{index}.bin'
        media.write_bytes(b'TEST bytes only, not encoded media or playback proof')
        clips.append({'path': str(media), 'sha256': digest(media),
                      'absoluteFrameRange': [window['startFrame'], window['endFrame']]})
    file = root / 'motion-previews.json'
    write_test_json(file, {'status': 'native-motion-previews-complete', 'packet': packet,
                          'clips': clips, 'TEST_ONLY': 'Structural gate fixture; not production evidence'})
    return test_motion_review(request, file, packet)
