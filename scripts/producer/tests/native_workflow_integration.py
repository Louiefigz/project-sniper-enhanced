"""Real short native lifecycle through mandatory entry, automatic recovery and review admission.

The review record is explicitly synthetic TEST data for validator qualification.
It makes no independent editorial/human approval claim about production footage.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import bound_json, write_new
from studio.native_long_export import prepare
from studio.native_long_prebuild import prebuild_snapshot
from studio.native_long_recovery import ensure_picture
from studio.native_review_contract import read_composition
from studio.native_review_bundle import prepare as prepare_bundle, supervise, publish, read_bundle
from studio.native_runtime import REPO, digest
from studio.native_short_pipeline import NativeShortPipeline


def synthetic_review(project: Path, root: Path) -> None:
    """Retain a clearly labeled schema fixture; this is not an actual critic verdict."""
    evidence = root / 'TEST-review-evidence.txt'
    evidence.write_text('Synthetic receipt for workflow mechanics. No human or editorial approval is claimed.\n')
    coverage = ('briefAndRetainedMessage', 'assetsAndSourceEvidence', 'cuesAndSceneCoverage',
                'layoutCropAndText', 'motionAndTransitions', 'pacingAndAudio', 'feasibility')
    write_new(project / 'PREBUILD-REVIEW.json', {'schemaVersion': 1,
        'scope': 'native-long-full-project', 'planHash': prebuild_snapshot(project)['planHash'],
        'reviewer': {'identity': 'TEST synthetic validator fixture', 'sessionId': 'TEST-reviewer',
                     'plannerSessionId': 'TEST-planner', 'independent': True},
        'coverage': {key: 'TEST synthetic assessment; validates admission mechanics only.' for key in coverage},
        'evidence': [{'path': str(evidence), 'sha256': digest(evidence)}],
        'review': {'schemaVersion': 1, 'stage': 'plan', 'verdict': 'pass',
                   'summary': 'TEST schema fixture; not editorial approval', 'materialIssues': [], 'findings': []}})


def cli(project: Path, output: Path) -> dict:
    """Use the actual public adapter selector with no resume flag."""
    log = output.parent / f'{output.name}.log'
    with log.open('xb') as handle:
        result = subprocess.run([sys.executable, str(REPO / 'scripts/producer/studio/native_export.py'),
            str(project), str(output), '--audio-profile', 'default-v3'],
            cwd=REPO, stdout=handle, stderr=subprocess.STDOUT, timeout=1200)
    if result.returncode:
        raise RuntimeError(f'Public native export failed; inspect {log}')
    return bound_json(output / 'delivery.json')


def settings(project: Path, output: Path) -> argparse.Namespace:
    """Use the production defaults apart from this fixture's established audio profile."""
    return argparse.Namespace(project=project, output=output, cache=None, resume_from=None,
        prepared_master=None, audio_donor=None, audio_profile='default-v3')


def review_bundle(root: Path, expected_sha: str) -> None:
    """Publish and re-read the real local-MP4/editable-Studio package without claiming playback."""
    manifest = root / 'review-manifest.json'
    write_new(manifest, {'schemaVersion': 1, 'compositions': [
        {'id': 'TechnicalFixture', 'title': 'TEST workflow fixture', 'export': str(root / 'verified')} ]})
    request, file = prepare_bundle(manifest, root / 'review-bundle')
    publish(request, supervise(request, file))
    bundle = read_bundle(root / 'review-bundle')
    row = bundle['compositions'][0]
    assert row['localVideoSha256'] == expected_sha
    assert row['audio']['additionalAudioEncodes'] == 0
    assert row['studioState']['status'] == 'prepared-files-unchanged'
    assert bundle['browserPlaybackVerified'] is False


def run(source: Path, root: Path) -> None:
    """Stop after real sealed picture, then recover across output roots and admit review."""
    root.mkdir()
    project = root / 'project'; shutil.copytree(source, project)
    if (project / 'PREBUILD-REVIEW.json').exists():
        raise ValueError('Integration source must be an unreviewed technical fixture')
    synthetic_review(project, root)
    partial = root / 'partial'
    request, environment = prepare(settings(project, partial))
    pipeline = NativeShortPipeline(request, environment)
    def stop_after_picture() -> None:
        """Exercise the ordinary failure handler after the real picture owner finishes."""
        ensure_picture(pipeline)
        raise RuntimeError('TEST intentional failure after completed picture')
    with patch.object(pipeline, 'render', side_effect=stop_after_picture):
        assert pipeline.execute() is False
    assert (partial / 'picture-stage.json').is_file(), 'Picture did not complete before test interruption'
    elsewhere = root / 'elsewhere'; elsewhere.mkdir()
    recovered = elsewhere / 'recovered'
    first = cli(project, recovered)
    assert first['status'] == 'native-long-checked-for-review'
    assert bound_json(recovered / 'render-result.json')['additionalPictureEncodes'] == 0
    assert bound_json(recovered / 'export-request.json')['recoverySelection']['mode'] == 'automatic'
    final = cli(project, root / 'verified')
    assert final['renderReused'] is True and final['sha256'] == first['sha256']
    assert [row['phase'] for row in final['stages']] == ['capture-reused', 'verification']
    review = read_composition({'id': 'TechnicalFixture', 'title': 'TEST workflow fixture', 'export': str(root / 'verified')})
    assert review.video_sha256 == final['sha256']
    review_bundle(root, final['sha256'])
    write_new(root / 'integration-result.json', {'status': 'workflow-enforcement-integration-passed',
        'productionDelivery': False, 'humanApproved': False, 'syntheticReview': True,
        'automaticPictureRecovery': True, 'automaticFinalVerificationRecovery': True,
        'longReviewBundleAdmission': True, 'longReviewBundlePublished': True,
        'additionalPictureEncodesAfterFailure': 0,
        'videoSha256': final['sha256']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_fixture', type=Path)
    parser.add_argument('new_output', type=Path)
    arguments = parser.parse_args()
    run(arguments.source_fixture.resolve(strict=True), arguments.new_output.absolute())
