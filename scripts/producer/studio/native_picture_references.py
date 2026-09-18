"""Exact native-reference identity, geometry and unchanged pixel thresholds."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import numpy as np
from PIL import Image

from cut_preview_io import file_hash, file_identity, read_bytes
from studio.native_runtime import digest
from studio.native_selected_frames import MAX_FRAME_BYTES
from studio.native_stage_evidence import MAX_NATIVE_FILE_BYTES


def require_reference_dimensions(image: Image.Image, shape: tuple[int, int, int] | None,
                                 message: str) -> None:
    """Share the exact unscaled reference-size guard across forward/reverse checks."""
    if shape and image.size != (shape[1], shape[0]):
        raise RuntimeError(message)


def picture_metrics(reference: Path, actual: np.ndarray,
                    shape: tuple[int, int, int] | None = None,
                    reference_sha256: str | None = None) -> dict:
    """Compare declared sRGB without fitted color, alignment or relaxed thresholds."""
    raw = read_bytes(reference, maximum=MAX_FRAME_BYTES + 1024 * 1024)
    if reference_sha256 is not None and hashlib.sha256(raw).hexdigest() != reference_sha256:
        raise RuntimeError('Native picture reference changed')
    with Image.open(io.BytesIO(raw)) as image:
        require_reference_dimensions(image, shape, 'Native reference/output dimensions differ')
        a, b = np.asarray(image.convert('RGB')), actual
    if a.shape != b.shape or len(a.shape) != 3 or a.shape[2] != 3 or (shape and a.shape != shape):
        raise RuntimeError('Native reference/output dimensions differ')
    delta = a.astype(np.float64) - b.astype(np.float64)
    mse, mae = float(np.mean(delta * delta)), float(np.mean(np.abs(delta)))
    psnr = float(10 * np.log10(255 * 255 / mse)) if mse else 100.0
    return {'mae': mae, 'psnrDb': psnr, 'passed': mae <= 2 and psnr >= 40}


def qualify_reverse_frames(native: dict, shape: tuple[int, int, int] | None = None) -> list[dict]:
    """Permit bounded browser edge antialiasing only after exact scene/source checks."""
    comparisons = []
    for row in (value for value in native['frames'] if value['repeat']):
        prior = next((value for value in native['frames']
                      if value['frame'] == row['frame'] and not value['repeat']), None)
        if prior is None:
            raise RuntimeError('Reverse-seek frame has no original forward reference')
        files = [Path(value['path']) for value in (prior, row)]
        if any(digest(file) != value['sha256'] for file, value in zip(files, (prior, row))):
            raise RuntimeError('Reverse-seek image changed after capture')
        if prior['visualState'] != row['visualState'] or prior['payload'] != row['payload']:
            raise RuntimeError('Reverse-seek scene/source state changed')
        raw = read_bytes(files[1], maximum=MAX_FRAME_BYTES + 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise RuntimeError('Reverse-seek image changed after capture')
        with Image.open(io.BytesIO(raw)) as image:
            require_reference_dimensions(image, shape, 'Reverse-seek reference dimensions differ')
            metrics = picture_metrics(files[0], np.asarray(image.convert('RGB')), shape, prior['sha256'])
        passed = metrics['mae'] <= .01 and metrics['psnrDb'] >= 60
        comparisons.append({'frame': row['frame'], **metrics, 'passed': passed,
                            'byteIdentical': prior['sha256'] == row['sha256']})
    if not comparisons or not all(row['passed'] for row in comparisons):
        raise RuntimeError(f'Reverse-seek pixel stability failed: {comparisons}')
    return comparisons


def reference_identities(native: dict) -> dict[Path, tuple[int, ...]]:
    """Remember every reference, including repeats, to reject later replacement."""
    return {Path(row['path']): file_identity(Path(row['path']).lstat()) for row in native['frames']}


def assert_picture_inputs(paths: dict[Path, tuple[int, ...]], candidate: tuple[Path, str],
                          receipt: tuple[Path, str]) -> None:
    """Keep checked media, capture schedule and retained reference identities bound."""
    if any(file_identity(path.lstat()) != expected for path, expected in paths.items()):
        raise RuntimeError('Native picture reference changed during verification')
    if any(file_hash(path, maximum=MAX_NATIVE_FILE_BYTES) != expected for path, expected in (candidate, receipt)):
        raise RuntimeError('Native picture candidate or capture receipt changed during verification')
