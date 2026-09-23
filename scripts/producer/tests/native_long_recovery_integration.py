"""Exercise real picture-only and complete-media recovery through production owners."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import bound_json, write_new
from studio.native_long_export import prepare
from studio.native_long_recovery import ensure_picture
from studio.native_runtime import digest
from studio.native_short_pipeline import NativeShortPipeline


def settings(project: Path, output: Path, resume: Path | None = None,
             donor: Path | None = None) -> argparse.Namespace:
    """Use the public adapter's ordinary argument preparation and immutable inputs."""
    return argparse.Namespace(project=project, output=output, cache=None, resume_from=resume,
        prepared_master=None, audio_donor=donor, audio_profile='native-short-v1' if resume else 'default-v3')


def run(project: Path, output: Path, donor: Path | None = None) -> None:
    """Stop at a valid picture seal, then recover twice without picture encoding."""
    output.mkdir()
    partial, recovered, verified = [output / name for name in ('picture-only', 'picture-recovered', 'verification-recovered')]
    request, environment = prepare(settings(project, partial, donor=donor))
    pipeline = NativeShortPipeline(request, environment)
    pipeline.capture()
    ensure_picture(pipeline)
    assert (partial / 'picture-stage.json').is_file()
    assert not (partial / 'render-stage.json').exists()
    picture_sha = digest(partial / 'picture.mp4')
    write_new(partial / 'integration-stop.json', {
        'status': 'test-intentionally-stopped-after-complete-picture', 'productionDelivery': False,
        'pictureSha256': picture_sha, 'stages': pipeline.stages})
    request, environment = prepare(settings(project, recovered, partial))
    assert NativeShortPipeline(request, environment).execute(), 'Picture recovery failed'
    media = bound_json(recovered / 'render-result.json')
    assert media['additionalPictureEncodes'] == 0
    assert digest(recovered / 'picture.mp4') == picture_sha
    check_audio_reuse(partial, recovered, donor)
    request, environment = prepare(settings(project, verified, recovered))
    assert NativeShortPipeline(request, environment).execute(), 'Verification recovery failed'
    final = bound_json(verified / 'delivery.json')
    assert final['renderReused'] is True
    assert digest(verified / 'review.mp4') == digest(recovered / 'review.mp4')
    assert [stage['phase'] for stage in final['stages']] == ['capture-reused', 'verification']
    write_new(output / 'integration-result.json', {
        'status': 'real-picture-and-verification-recovery-passed', 'productionDelivery': False,
        'additionalPictureEncodesAfterStop': 0, 'additionalMasteringPassesAfterStop': 0,
        'recoveredVideoSha256': final['sha256'], 'pictureOnly': str(partial),
        'pictureRecovery': str(recovered), 'verificationRecovery': str(verified)})


def check_audio_reuse(partial: Path, recovered: Path, donor: Path | None) -> None:
    """Verify the actual reused float or AAC authority according to the initial route."""
    master = bound_json(recovered / 'audio-preparation/receipt.json')
    if donor:
        assert master['donorReceiptSha256'] == digest(donor)
        assert bound_json(recovered / 'audio/receipt.json')['additionalAacEncodes'] == 0
        return
    assert master['preparedMasterReceiptSha256'] == digest(partial / 'audio-preparation/receipt.json')
    assert master['masterSha256'] == digest(partial / 'audio-preparation/program-master.wav')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--audio-donor', type=Path)
    args = parser.parse_args()
    run(args.project.resolve(strict=True), args.output.absolute(), args.audio_donor)
