"""Decoded local text/backing screening within the existing composite audit.

This is not OCR or whole-video approval. Only exact source-qualified opaque
plates are supported. Color pairs must occur on opposite sides of decoded
glyph-core pixels; unrelated original footage is never used as their backing.
Missing/ambiguous role evidence fails, and partial-opacity phases are disclosed
instead of being mislabeled full-opacity contrast passes.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable

import numpy as np
from PIL import Image, ImageFilter

from audit.audit_checks import CheckResult, FAIL, PASS, WARN
from audit.audit_text_placement import PlateContext, cropped_samples
from graphics.template_text_contrast import (
    effective_text_roles, text_plate_contract, text_treatment,
)
from producer_config import MOTION

_COLOR_TOLERANCE = 16
_NEIGHBOR_RADIUS = 8
_MIN_GLYPH_CORES = 24
_MAX_ROW_GAP = 8


def _rgb(text: str) -> tuple[int, int, int]:
    return tuple(int(text[offset:offset + 2], 16) for offset in (1, 3, 5))


def _shift(mask: np.ndarray, dx: int, dy: int) -> np.ndarray:
    moved = np.roll(mask, (dy, dx), axis=(0, 1))
    if dx > 0:
        moved[:, :dx] = False
    if dx < 0:
        moved[:, dx:] = False
    if dy > 0:
        moved[:dy, :] = False
    if dy < 0:
        moved[dy:, :] = False
    return moved


def _candidate_pixels(images: tuple[Image.Image, Image.Image], colors: tuple) -> tuple:
    final, base = (np.asarray(image, dtype=np.int16) for image in images)
    foreground, background = colors
    cores = np.max(np.abs(final - foreground), axis=2) <= _COLOR_TOLERANCE
    backing = np.max(np.abs(final - background), axis=2) <= _COLOR_TOLERANCE
    directions = [np.zeros(cores.shape, dtype=bool) for _ in range(4)]
    for distance in range(1, _NEIGHBOR_RADIUS + 1):
        for index, (dx, dy) in enumerate(((distance, 0), (-distance, 0), (0, distance), (0, -distance))):
            directions[index] |= _shift(backing, dx, dy)
    opposite = (directions[0] & directions[1]) | (directions[2] & directions[3])
    delta = np.max(np.abs(final - base), axis=2).astype(np.uint8)
    changed = np.asarray(Image.fromarray(delta).filter(ImageFilter.BoxBlur(3))) >= 5
    points = np.argwhere(cores & opposite & changed)
    return final, backing, points


def _neighbors(point: np.ndarray, data: tuple) -> list[tuple]:
    final, backing = data
    y, x = (int(value) for value in point)
    coordinates = ((x + dx * distance, y + dy * distance)
        for distance in range(1, _NEIGHBOR_RADIUS + 1)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
    return [tuple(int(value) for value in final[yy, xx]) for xx, yy in coordinates
            if 0 <= yy < backing.shape[0] and 0 <= xx < backing.shape[1] and backing[yy, xx]]


def _bands(points: np.ndarray) -> list[np.ndarray]:
    if not len(points):
        return []
    bands, start = [], 0
    rows = points[:, 0]
    for index in range(1, len(points)):
        if rows[index] - rows[index - 1] > _MAX_ROW_GAP:
            bands.append(points[start:index])
            start = index
    bands.append(points[start:])
    return [band for band in bands if len(band) >= _MIN_GLYPH_CORES]


def _measure_group(images: tuple, group: list[dict], contrast: Callable) -> dict:
    colors = (_rgb(group[0]["foreground"]), _rgb(group[0]["background"]))
    final, backing, points = _candidate_pixels(images, colors)
    bands = _bands(points)
    if len(group) == 1 and bands:
        bands = [np.concatenate(bands)]  # a qualified single role may wrap
    if len(bands) != len(group):
        raise ValueError(f"expected {len(group)} distinct text role band(s), observed {len(bands)}")
    result = {}
    for role, band in zip(group, bands):
        ratios = [min(contrast(tuple(int(v) for v in final[y, x]), other)
                      for other in _neighbors(np.array((y, x)), (final, backing)))
                  for y, x in band]
        # Every selected core is already close to the intended opaque color.
        # Do not discard low-ratio samples as compression outliers.
        result[role["id"]] = (min(ratios), len(ratios))
    return result


def _measure(images: tuple, roles: list[dict], contrast: Callable) -> dict:
    groups: dict[tuple, list] = defaultdict(list)
    for role in roles:
        groups[(role["foreground"], role["background"])].append(role)
    result = {}
    for group in groups.values():
        result.update(_measure_group(images, group, contrast))
    return result


def _plate_checks(index: int, graphic: dict, context: tuple, contrast: Callable) -> list:
    contract, samples = context
    roles = effective_text_roles(graphic, contract)
    if not roles:
        raise ValueError("no intended text roles to measure")
    start, end = float(graphic["outStart"]), float(graphic["outEnd"])
    exit_row = contract["exit"]
    tail = min(exit_row["maximumSeconds"], (end - start) * exit_row["durationFraction"])
    last_full = end - tail - exit_row["frameReserveSeconds"]
    first_full = start + max(role["fullOpacityAt"] for role in roles)
    full = [(label, pair) for label, timestamp, pair in samples if first_full <= timestamp <= last_full]
    if not full:
        raise ValueError("no sampled phase contains all intended fully visible text roles")
    readings: dict[str, list] = defaultdict(list)
    for label, pair in full:
        for role_id, reading in _measure(pair, roles, contrast).items():
            readings[role_id].append((label, *reading))
    floor = float(MOTION["contrast"]["min_ratio"])
    checks = []
    for role in roles:
        rows = readings[role["id"]]
        lowest = min(row[1] for row in rows)
        checks.append(CheckResult(f"graphic_composite_{index}_contrast_{role['id']}",
            PASS if lowest >= floor else FAIL,
            f"decoded local plate {lowest:.2f}:1; {sum(row[2] for row in rows)} glyph-core pairs",
            f"requires >= {floor:g}:1; full-opacity phases {', '.join(row[0] for row in rows)}; "
            f"template {contract['templateSha256']}"))
    partial = [label for label, timestamp, _ in samples if not first_full <= timestamp <= last_full]
    if partial:
        checks.append(CheckResult(f"graphic_composite_{index}_contrast_animation", WARN,
            "partial-opacity phase contrast not scored: " + ", ".join(partial),
            "intentional entrance/exit is not a full-opacity pass; plateau role evidence is required"))
    return checks


def text_plate_results(index: int, graphic: dict, evidence: PlateContext, contrast: Callable) -> list | None:
    """Return source-bound coverage, or None for other existing graphic kinds."""
    try:
        contract = text_plate_contract(str(graphic.get("kind", "")))
        if contract is None:
            return None
        if text_treatment(graphic, contract) == "scrim":
            return [CheckResult(f"graphic_composite_{index}_contrast", WARN,
                "legacy scrim: text-role contrast is unmeasured, not passed",
                "translucent backing depends on footage; explicit plates provide checked local text backing")]
        return _plate_checks(index, graphic, (contract, cropped_samples(index, evidence)), contrast)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return [CheckResult(f"graphic_composite_{index}_contrast", FAIL,
            "text-role contrast evidence unavailable", str(error))]
