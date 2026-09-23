"""Fully decode a bounded review preview with the existing native media jail."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cut_preview_io import bound_json, file_hash
from headless.admission_receipt import validate_admission_receipt
from headless.external_media_probe import admit_external_media
from headless.external_media_probe_policy import MediaProbeLimits


def verify_preview(media: dict) -> None:
    """Revalidate retained native decode evidence and both copies of its bytes."""
    admission = media['admission']
    _limits, decoded = validate_admission_receipt(admission)
    facts, snapshot = decoded['facts'], admission['snapshot']
    if admission['policy'] != 'sniper-external-media-probe-v4-native' \
            or facts['mediaKind'] != 'timed-media' or facts['videoStreams'] != 1 \
            or not 2 <= facts['declaredFrames'] <= 1800 \
            or not 0 < facts['durationSeconds'] <= 30:
        raise ValueError('Readiness preview requires a bounded native moving-image decode')
    if snapshot['sha256'] != media['sha256'] \
            or snapshot['sizeBytes'] != facts['sizeBytes']:
        raise ValueError('Preview decode snapshot binding changed')
    for filename in (media['path'], snapshot['path']):
        if file_hash(Path(filename), 1024 ** 3) != media['sha256']:
            raise ValueError('Preview bytes changed after decode')


def observe_preview(source: Path, store: Path) -> dict:
    """Observe actual moving-image bytes without granting editorial approval.

    Args:
        source: A short current-candidate preview from an existing renderer.
        store: The project's immutable admitted-media snapshot store.

    Returns:
        Existing full-decode admission and the original preview byte binding.
    """
    before = file_hash(source, 1024 ** 3)
    store.mkdir(parents=True, exist_ok=True)
    limits = MediaProbeLimits(max_bytes=1024 ** 3, max_duration_seconds=30,
                             max_frames=1800, max_decode_seconds=90)
    admitted = admit_external_media(str(source), str(store), limits)
    facts = admitted['decoded']['facts']
    if facts['videoStreams'] != 1 or facts['declaredFrames'] < 2 \
            or not 0 < facts['durationSeconds'] <= 30:
        raise ValueError('Readiness preview needs a moving-image clip of at most 30 seconds')
    if file_hash(source, 1024 ** 3) != before or admitted['snapshot']['sha256'] != before:
        raise ValueError('Preview changed during its full decode')
    result = {'path': str(source), 'sha256': before, 'admission': admitted}
    verify_preview(result)
    return result


def main() -> int:
    """Print decoded evidence; never publish a successful receipt on failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('preview', nargs='?')
    parser.add_argument('store', nargs='?')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    try:
        if args.verify:
            paths = json.loads(sys.stdin.read(1024 * 1024 + 1))
            if not isinstance(paths, list) or not 1 <= len(paths) <= 1001:
                raise ValueError('Expected bounded preview receipt paths')
            for filename in paths:
                verify_preview(bound_json(Path(filename))['media'])
            print(json.dumps({'status': 'current-decoded-preview-evidence'}))
            return 0
        if not args.preview or not args.store:
            raise ValueError('Expected preview and snapshot store')
        result = observe_preview(Path(args.preview).absolute(), Path(args.store).absolute())
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        print(json.dumps({'error': str(error)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
