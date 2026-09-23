"""Current catalog authority; file presence never registers a visual design.

Shared policy data also feeds the TypeScript menu and saved-run admission.
Reference/custom work belongs to a source-bound project, never this registry.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = ROOT / "schemas/producer/visual-source-policy-v1.json"


def policy() -> dict:
    """Read the versioned source policy without an environment override."""
    value = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if value.get("schemaVersion") != 1 or not value.get("integrated"):
        raise ValueError("Missing HyperFrames visual source policy")
    return value


def integrated_kinds() -> set[str]:
    """Return only explicitly registered upstream ports."""
    return set(policy()["integrated"])


def require_integrated(kind: str, source: str | None = None) -> dict:
    """Reject retired, unknown or changed templates before cache/render use."""
    row = policy()["integrated"].get(kind)
    if row is None:
        raise ValueError(
            f"Visual source {kind!r} is retired or is not an upstream catalog port. "
            "Select the HyperFrames catalog; use a source-bound native project "
            "for a current-job reference or justified custom design.")
    file = ROOT / row["path"]
    if file.is_symlink() or not file.is_file():
        raise ValueError(f"Registered catalog source is unavailable: {kind}")
    actual = file.read_bytes() if source is None else source.encode("utf-8")
    if hashlib.sha256(actual).hexdigest() != row["sha256"]:
        raise ValueError(f"Registered catalog source changed: {kind}")
    upstream = ROOT / row["upstreamPath"]
    if upstream.is_symlink() or not upstream.is_file() or hashlib.sha256(upstream.read_bytes()).hexdigest() != row["upstreamSha256"]:
        raise ValueError(f"Upstream catalog source changed: {kind}")
    return row


def target_source_errors(target: dict | None) -> list[str]:
    """Accept the catalog default only; present invalid styles never default."""
    if target is None:
        return []
    if not isinstance(target, dict):
        return ["Invalid visual target; use graphicsStyle=catalog-first."]
    if ("style" in target or "visualProfile" in target
            or ("graphicsStyle" in target and target["graphicsStyle"] != "catalog-first")):
        return ["Legacy or unknown visual styles are retired; use "
                "graphicsStyle=catalog-first and current-job source evidence."]
    return []


def plan_source_errors(plan: dict) -> list[str]:
    """Reject retired designs on raw plans, including their non-HTML lanes."""
    errors = []
    for row in plan.get("graphicsTrack") or []:
        try:
            require_integrated(str(row.get("kind", "")))
        except ValueError as error:
            errors.append(str(error))
    if plan.get("titleCards"):
        errors.append("Legacy titleCards are retired; author the title with an "
                      "upstream catalog component in the native project.")
    if plan.get("transitions"):
        errors.append("Legacy transition presets are retired; select a HyperFrames "
                      "catalog transition in the native project.")
    errors.extend(target_source_errors(plan.get("target")))
    return errors


def require_plan_sources(plan: dict) -> None:
    """Enforce source policy before downstream execution or cache reuse."""
    errors = plan_source_errors(plan)
    if errors:
        raise ValueError("; ".join(errors))


def require_scene_sources(scene: dict) -> None:
    """Apply shared source admission while preserving the scene API's error type."""
    from graphics.scene_contract import SceneContractError
    from graphics.visual_source_receipt import validate_visual_sources
    try:
        if scene["composition"]["type"] == "catalog":
            require_integrated(scene["composition"]["kind"])
            return
        validate_visual_sources(scene.get("visualSources"),
                                {key: value for key, value in scene.items() if key != "visualSources"},
                                [element["elementId"] for element in scene["elements"]])
    except ValueError as error:
        raise SceneContractError(str(error)) from error
