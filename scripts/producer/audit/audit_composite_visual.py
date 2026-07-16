#!/usr/bin/env python3
"""Fail-closed pixel QC for rendered graphics and transitions.

Graphic checks compare the finished composite with the graphics-free base at
the same output timestamps.  That makes the real footage the contrast
authority instead of assuming a template background.  Transition checks use
the already-extracted before/seam/after review frames and reject an absent or
accidentally flat seam.
"""
from __future__ import annotations

import math
import os
from collections import defaultdict

from PIL import Image, ImageFilter, ImageStat

from audit.audit_checks import CheckResult, FAIL, PASS
from audit.audit_frames import FrameRef, extract_review_frames
from brand import load_tokens
from producer_config import MOTION

_SAMPLE_WIDTH = 480
_DELTA_ACTIVE = 16
_MIN_ACTIVE_RATIO = 0.0008
_SOURCE_BG_DELTA_MAX = 22
_ACCENT_DISTANCE_MAX = 48
_ACCENT_PIXEL_DELTA_MIN = 5
_MIN_ACCENT_PIXELS_PER_TILE = 5
_TILE_COLUMNS = 12
_TILE_ROWS = 8
_MIN_TRANSITION_CHANGE = 2.0
_MIN_TRANSITION_STDDEV = 4.0
_UNIFORM_TRANSITIONS = frozenset({"white-flash"})
_DEFAULT_ACCENT_KINDS = frozenset({"glass-rail"})


def _rgb_image(path: str) -> Image.Image | None:
    try:
        with Image.open(path) as source:
            image = source.convert("RGB")
    except (OSError, ValueError):
        return None
    if image.width <= _SAMPLE_WIDTH:
        return image
    height = max(1, round(image.height * _SAMPLE_WIDTH / image.width))
    return image.resize((_SAMPLE_WIDTH, height), Image.Resampling.LANCZOS)


def _paired_images(final_path: str, base_path: str
                   ) -> tuple[Image.Image, Image.Image] | None:
    final, base = _rgb_image(final_path), _rgb_image(base_path)
    if final is None or base is None or final.size != base.size:
        return None
    return final, base


def _pixel_delta(left: tuple[int, int, int],
                 right: tuple[int, int, int]) -> int:
    return max(abs(left[index] - right[index]) for index in range(3))


def _pixels(image: Image.Image) -> tuple:
    """Decoded pixels without Pillow's deprecated ``getdata`` API."""
    return image.get_flattened_data()


def _active_ratio(images: tuple[Image.Image, Image.Image]) -> float:
    final, base = images
    active = sum(_pixel_delta(a, b) >= _DELTA_ACTIVE
                 for a, b in zip(_pixels(final), _pixels(base)))
    return active / (final.width * final.height)


def _hex_rgb(value: object) -> tuple[int, int, int] | None:
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(character * 2 for character in text)
    if len(text) != 6 or any(c not in "0123456789abcdefABCDEF" for c in text):
        return None
    return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))


def _luminance(pixel: tuple[int, int, int]) -> float:
    channels = []
    for value in pixel:
        channel = value / 255.0
        channels.append(channel / 12.92 if channel <= 0.03928
                        else ((channel + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(left: tuple[int, int, int],
              right: tuple[int, int, int]) -> float:
    first, second = _luminance(left), _luminance(right)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


def _accent_colors(graphic: dict) -> list[tuple[int, int, int]]:
    spec = graphic.get("spec") or {}
    values = [spec[key] for key in ("accent", "accentColor") if key in spec]
    if not values and str(graphic.get("kind", "")) in _DEFAULT_ACCENT_KINDS:
        values.append(load_tokens().get("accent"))
    colors = [_hex_rgb(value) for value in values]
    return [color for color in colors if color is not None]


def _local_delta(final: Image.Image, base: Image.Image) -> list[int]:
    values = [_pixel_delta(a, b)
              for a, b in zip(_pixels(final), _pixels(base))]
    mask = Image.new("L", final.size)
    mask.putdata(values)
    return list(_pixels(mask.filter(ImageFilter.BoxBlur(5))))


def _source_contrast_ratios(images: tuple[Image.Image, Image.Image],
                            accents: list[tuple[int, int, int]]) -> list[float]:
    final, base = images
    local = _local_delta(final, base)
    tiles: dict[tuple[int, int], list[float]] = defaultdict(list)
    for offset, (pixel, under) in enumerate(zip(_pixels(final), _pixels(base))):
        if _pixel_delta(pixel, under) < _ACCENT_PIXEL_DELTA_MIN:
            continue
        if local[offset] > _SOURCE_BG_DELTA_MAX:
            continue
        if min(math.dist(pixel, accent) for accent in accents) > _ACCENT_DISTANCE_MAX:
            continue
        x, y = offset % final.width, offset // final.width
        tile = (x * _TILE_COLUMNS // final.width,
                y * _TILE_ROWS // final.height)
        tiles[tile].append(_contrast(pixel, under))
    medians = []
    for values in tiles.values():
        if len(values) < _MIN_ACCENT_PIXELS_PER_TILE:
            continue
        ordered = sorted(values)
        medians.append(ordered[len(ordered) // 2])
    return medians


def _graphic_results(plan: dict, final_frames: dict[str, FrameRef],
                     base_frames: dict[str, FrameRef]) -> list[CheckResult]:
    results: list[CheckResult] = []
    floor = float(MOTION["contrast"]["min_ratio"])
    for index, graphic in enumerate(plan.get("graphicsTrack") or []):
        prefix = f"graphic{index}_"
        labels = sorted(label for label in final_frames if label.startswith(prefix))
        pairs = [_paired_images(final_frames[label].path, base_frames[label].path)
                 for label in labels if label in base_frames]
        valid = [pair for pair in pairs if pair is not None]
        peak = max((_active_ratio(pair) for pair in valid), default=0.0)
        status = PASS if valid and peak >= _MIN_ACTIVE_RATIO else FAIL
        results.append(CheckResult(
            f"graphic_composite_{index}_presence", status,
            f"peak changed-pixel ratio {peak:.4f}",
            f"requires >= {_MIN_ACTIVE_RATIO:.4f} against graphics-free footage"))
        accents = _accent_colors(graphic)
        if graphic.get("anchor") == "own-screen" or not accents or not valid:
            continue
        ratios = [ratio for pair in valid
                  for ratio in _source_contrast_ratios(pair, accents)]
        if not ratios:
            continue
        lowest = min(ratios)
        results.append(CheckResult(
            f"graphic_composite_{index}_contrast",
            PASS if lowest >= floor else FAIL,
            f"lowest source-exposed accent tile {lowest:.2f}:1",
            f"requires >= {floor:g}:1 against the actual footage"))
    return results


def _mean_distance(left: Image.Image, right: Image.Image) -> float:
    values = [_pixel_delta(a, b)
              for a, b in zip(_pixels(left), _pixels(right))]
    return sum(values) / len(values) if values else 0.0


def _transition_result(index: int, transition: dict,
                       frames: dict[str, FrameRef]) -> CheckResult:
    prefix = f"transition{index}_"
    images = {phase: _rgb_image(frames[f"{prefix}{phase}"].path)
              for phase in ("before", "seam", "after")
              if f"{prefix}{phase}" in frames}
    if any(images.get(phase) is None for phase in ("before", "seam", "after")):
        return CheckResult(f"transition_composite_{index}", FAIL,
                           "missing comparison frame",
                           "before/seam/after pixels are required")
    before, seam, after = images["before"], images["seam"], images["after"]
    if before.size != seam.size or seam.size != after.size:
        return CheckResult(f"transition_composite_{index}", FAIL,
                           "frame dimensions differ", "cannot compare transition")
    change = min(_mean_distance(before, seam), _mean_distance(seam, after))
    uniformity = ImageStat.Stat(seam.convert("L")).stddev[0]
    kind = str(transition.get("kind", ""))
    uniform_bad = uniformity < _MIN_TRANSITION_STDDEV \
        and kind not in _UNIFORM_TRANSITIONS
    empty_bad = change < _MIN_TRANSITION_CHANGE
    detail = (f"requires change >= {_MIN_TRANSITION_CHANGE:g} and seam stddev >= "
              f"{_MIN_TRANSITION_STDDEV:g} (uniform allowed: white-flash)")
    measured = f"change {change:.2f}; seam luma stddev {uniformity:.2f}"
    return CheckResult(f"transition_composite_{index}",
                       FAIL if uniform_bad or empty_bad else PASS,
                       measured, detail)


def _reference_path(out_dir: str) -> str | None:
    direct = os.path.join(out_dir, "base_final.mp4")
    if os.path.isfile(direct):
        return direct
    cursor = os.path.abspath(out_dir)
    while os.path.dirname(cursor) != cursor:
        if os.path.basename(cursor) == ".sniper-qc":
            candidate = os.path.join(os.path.dirname(cursor), "base_final.mp4")
            return candidate if os.path.isfile(candidate) else None
        cursor = os.path.dirname(cursor)
    return None


def check_composite_visuals(out_dir: str, plan: dict,
                            frames: list[FrameRef]) -> list[CheckResult]:
    """Measure rendered graphic/transition pixels using existing review stills."""
    final = {frame.label: frame for frame in frames if frame.path}
    graphics = plan.get("graphicsTrack") or []
    results: list[CheckResult] = []
    if graphics:
        reference = _reference_path(out_dir)
        if reference is None:
            results.append(CheckResult(
                "graphic_composite_reference", FAIL, "missing base_final.mp4",
                "cannot prove graphic visibility against the actual footage"))
        else:
            refs = [frame for frame in frames if frame.kind == "graphic"]
            base = extract_review_frames(
                reference, os.path.join(out_dir, "audit_reference"), refs)
            base_map = {frame.label: frame for frame in base if frame.path}
            results.append(CheckResult(
                "graphic_composite_reference",
                PASS if len(base_map) == len(refs) else FAIL,
                f"{len(base_map)}/{len(refs)} reference frame(s)",
                "graphics-free footage extracted at every graphic QC timestamp"))
            results.extend(_graphic_results(plan, final, base_map))
    results.extend(_transition_result(index, transition, final)
                   for index, transition in enumerate(plan.get("transitions") or []))
    return results
