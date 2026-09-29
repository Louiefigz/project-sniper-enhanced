"""Supported static project inputs for dependency tests; no media or editorial qualification."""
from __future__ import annotations

import json
from pathlib import Path

from studio.native_region_contract import derive_region_map


def write_static_project(project: Path, canvas: dict, texts: tuple[str, ...]) -> Path:
    """Write equal contiguous, frame-exact static template mounts on an immutable full canvas.

    Intended for small integer-FPS test canvases whose frame count divides evenly
    across the supplied section texts. All actual reviews/render owners remain
    the caller's responsibility.
    """
    from fractions import Fraction
    (project / 'compositions').mkdir(parents=True)
    (project / 'LONG-PROJECT.json').write_text(json.dumps({'canvas': canvas}))
    length = Fraction(canvas['totalFrames'], len(texts)) / Fraction(canvas['frameRate'])
    if length.denominator != 1:
        raise ValueError('Static TEST fixture requires whole-second sections')
    mounts = []
    for index, text in enumerate(texts):
        key = f'unit-{index}'
        (project / f'compositions/{key}.html').write_text(
            f'<template><div data-composition-id="{key}" data-duration="{length}"><p>{text}</p></div></template>')
        mounts.append(f'<div data-composition-src="compositions/{key}.html" data-composition-id="{key}" '
                      f'style="position:absolute" data-start="{index * length}" data-duration="{length}"></div>')
    (project / 'index.html').write_text('<html><body>' + ''.join(mounts) + '</body></html>')
    (project / 'REVIEW-REGIONS.json').write_text(json.dumps(derive_region_map(project, canvas)))
    return project
