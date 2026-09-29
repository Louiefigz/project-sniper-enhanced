"""Cheap diagnostics on captured native references, before any preview or picture owner.

Reverse-seek stability reuses the exact final-gate comparison and thresholds
(``reverse_frame_comparisons``); phone-size text reads the rendered font size of
every visible leaf text element already recorded by the capture owner. Neither
replaces the final encoded checks, and small text is a review finding, not a
claim about readability or design quality.
"""
from __future__ import annotations

import re
from pathlib import Path

from cut_preview_io import bound_json
from studio.native_font_readiness import MIN_PHONE_TEXT_PX
from studio.native_stage_evidence import read_native_capture_receipt

MAX_ROWS = 64
FONT_SIZE = re.compile(r'(\d+(?:\.\d+)?)px')
REVERSE_THRESHOLDS = {'maeMaximum': .01, 'psnrMinimumDb': 60, 'exactSceneStateAndSourceFramesRequired': True}


def canvas_shape(project: Path) -> tuple[int, int, int]:
    """Return the captured reference shape (height, width, RGB) of a native Short."""
    canvas = bound_json(project / 'SHORT-PROJECT.json')['canvas']
    return canvas.get('height', 1920), canvas.get('width', 1080), 3


def reverse_seek_report(native: dict, shape: tuple[int, int, int]) -> dict:
    """Compare each reverse seek with its forward reference using the final-gate thresholds."""
    from studio.native_picture_references import reverse_frame_comparisons
    try:
        comparisons = reverse_frame_comparisons(native, shape)
    except (RuntimeError, OSError, KeyError, ValueError) as error:
        return {'status': 'reverse-seek-invalid', 'error': str(error), 'compared': 0, 'failed': []}
    failed = [{key: row[key] for key in ('frame', 'mae', 'psnrDb')} for row in comparisons if not row['passed']]
    status = 'reverse-seek-stable' if comparisons and not failed else 'reverse-seek-drift'
    return {'status': status, 'compared': len(comparisons), 'failed': failed[:MAX_ROWS],
            'failedCount': len(failed), 'thresholds': REVERSE_THRESHOLDS}


def font_px(font: object) -> float | None:
    """Read the font size from a computed CSS font shorthand (first px value)."""
    match = FONT_SIZE.search(font) if isinstance(font, str) else None
    return float(match.group(1)) if match else None


def small_text_report(native: dict, minimum: float = MIN_PHONE_TEXT_PX) -> dict:
    """List visible text rendered below the phone-size floor at the 1080-wide canvas."""
    found: dict[tuple[str, float], dict] = {}
    rows = [(frame['frame'], element) for frame in native['frames'] if not frame['repeat']
            for element in frame.get('visualState', [])]
    for frame, element in rows:
        size, text = font_px(element.get('font')), (element.get('text') or '').strip()
        if text and size is not None and size < minimum:
            found.setdefault((element['id'], size), {'id': element['id'], 'fontPx': size,
                                                     'text': text[:80], 'firstFrame': frame})
    elements = sorted(found.values(), key=lambda row: (row['firstFrame'], row['id']))
    return {'status': 'small-text-found' if elements else 'phone-text-ok', 'minimumPx': minimum,
            'elements': elements[:MAX_ROWS], 'elementCount': len(elements),
            'scope': 'rendered font size of captured elements that carry an id (native canvas text); '
                     'unidentified composition text is covered by declared-size scanning only'}


def capture_diagnostics(receipt: Path, project: Path) -> dict:
    """Run both diagnostics on one completed capture receipt."""
    native = read_native_capture_receipt(receipt)
    if native.get('status') != 'native-references-and-seek-states-pass':
        return {'status': 'capture-not-passed', 'receipt': str(receipt)}
    reverse = reverse_seek_report(native, canvas_shape(project))
    text = small_text_report(native)
    status = 'defects' if reverse['status'] != 'reverse-seek-stable' or text['elements'] else 'clean'
    return {'schemaVersion': 1, 'status': status, 'receipt': str(receipt), 'reverseSeek': reverse,
            'phoneText': text, 'finalGatesUnchanged': True}
