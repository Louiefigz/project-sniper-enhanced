"""Shared governed package context for P4 scene copy/timing cohorts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edit.exact_timing import PositiveRational
from graphics.scene_bundle import BundleSnapshot, promote_bundle
from graphics.scene_package_cli import run as run_scene_package
from planner.treatment_models import TreatmentState
from tests.p4_exit_media import write_canonical

FIXTURE = Path(__file__).parent / "fixtures" / "fire-sparkles-bundle-0831"  # declares the pinned SDK 0.8.31


@dataclass(frozen=True)
class SceneRunContext:
    """Shared durable bundle and output roots for repeated package revisions."""

    root: Path
    store: Path
    cache: Path
    bundle: BundleSnapshot


def create_context(root: Path) -> SceneRunContext:
    store, cache = root / "bundle-store", root / "scene-cache"
    store.mkdir()
    cache.mkdir()
    bundle = promote_bundle(
        str(FIXTURE.resolve()), str(store), select_current=False)
    return SceneRunContext(root, store, cache, bundle)


def _package(scene: dict) -> dict:
    return {
        "schemaVersion": 1,
        "scene": scene,
        "publicationContext": {
            "use": "commercial", "platform": "youtube",
            "evaluatedAt": "2026-07-30T12:00:00Z",
        },
        "assets": [],
        "readability": {
            "required": False, "sourceSha256": None, "receipt": None,
        },
    }


def render_package(
    context: SceneRunContext,
    scene: dict,
    label: str,
    cache: Path | None = None,
) -> dict:
    package_path = context.root / f"{label}-package.json"
    receipt_path = context.root / f"{label}-receipt.json"
    write_canonical(package_path, _package(scene))
    return run_scene_package([
        "render", str(package_path),
        "--bundle-store", str(context.store),
        "--cache-dir", str(cache or context.cache),
        "--workers", "2", "--receipt-out", str(receipt_path),
    ])


def receipt_map(receipt: dict) -> dict[str, dict]:
    return {row["unitId"]: row for row in receipt["renderReceipts"]}


def asset_hash(row: dict) -> str:
    return row["proof"]["asset"]["sha256"]


def scene_state(scene: dict) -> TreatmentState:
    plan = {
        "cutTrack": [{
            "sourceId": "source-main", "srcStart": 0.0, "srcEnd": 60.0,
        }],
        "transitions": [],
        "baselineLook": {
            "zoom": 1.0, "centerX": 0.5, "centerY": 0.5, "grade": "none",
        },
        "music": {"enabled": False},
    }
    return TreatmentState(
        plan, (scene,), PositiveRational(30, 1), 1800)


def clips(scene: dict, receipt: dict) -> list[dict]:
    timing = scene["timing"]
    rate = (
        int(timing["fps"]["numerator"])
        / int(timing["fps"]["denominator"]))
    start = timing["startFrame"] / rate
    end = timing["endFrameExclusive"] / rate
    indexed = receipt_map(receipt)
    return [{
        "path": indexed[row["unitId"]]["path"],
        "outStart": start, "outEnd": end, "anchor": "free-band",
        "x": 0, "y": 0,
    } for row in sorted(scene["renderUnits"], key=lambda item: item["zIndex"])]
