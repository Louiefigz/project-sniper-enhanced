"""Visual source admission for complete native projects and export reuse."""
from __future__ import annotations

import json
from pathlib import Path

from graphics.visual_source_policy import policy
from graphics.visual_source_receipt import require, subject_hash, validate_visual_sources


def native_short_subject(plan: dict) -> tuple[dict, list[str]]:
    """Mirror the typed author's subject, including every generated visual lane."""
    canvas = plan["canvas"]
    targets = [row["id"] for row in canvas["text"] + canvas["shapes"]]
    if canvas.get("titleCard"):
        targets.append("native-title-card")
    if canvas.get("captionViews"):
        targets.append("caption-presentation")
    if any(str(value).strip() for value in (plan.get("extension") or {}).values()):
        targets.append("scene-extension")
    targets.extend(row["file"] for row in plan.get("catalogFiles", []))
    return {"canvas": canvas, "extension": plan.get("extension"),
            "catalogFiles": plan.get("catalogFiles", []), "catalogTitle": plan.get("catalogTitle")}, sorted(set(targets))


def project_subject(project: Path) -> tuple[dict, list[str]]:
    """Bind Long decisions to all executable visual files in the admitted inventory."""
    from studio.native_preflight_inputs import inventory
    from studio.native_runtime import digest

    files, _directories = inventory(project)
    code = {str(file.relative_to(project)): digest(file) for file in files
            if file.suffix.lower() in {".html", ".css", ".js", ".mjs", ".cjs"}}
    require(code and "index.html" in code, "project has no native entry")
    require(not set(code.values()).intersection(policy()["retired"].values()),
            "retired template bytes exist in the executable project")
    targets = sorted(name for name in code if name.lower().endswith(".html"))
    return {"files": code}, targets


def admit_project_sources(project: Path) -> dict:
    """Recheck current policy before native export, including recovered attempts."""
    short = project / "SHORT-PROJECT.json"
    if short.exists():
        plan = json.loads(short.read_text())
        if plan.get("requestPacket"):
            require((plan.get("visualSources") or {}).get("request") == plan["requestPacket"],
                    "visual source decisions must bind the current project request")
        subject, targets = native_short_subject(plan)
        return validate_visual_sources(plan.get("visualSources"), subject, targets)
    subject, targets = project_subject(project)
    file = project / "VISUAL-SOURCES.json"
    require(file.is_file() and not file.is_symlink(),
            "VISUAL-SOURCES.json is required before native Long execution")
    return validate_visual_sources(json.loads(file.read_text()), subject, targets)


def describe_project(project: Path) -> dict:
    """Expose exact decision targets without inventing source choices or approval."""
    short = project / "SHORT-PROJECT.json"
    subject, targets = native_short_subject(json.loads(short.read_text())) if short.exists() else project_subject(project)
    return {"schemaVersion": 1, "policyVersion": policy()["policyVersion"],
            "subjectSha256": subject_hash(subject), "targets": targets,
            "request": None, "decisions": [], "sourceEvidenceChecked": False}


def source_implementation_files() -> list[Path]:
    """Pin the offline source authority used by native export and recovery."""
    from graphics.visual_source_policy import ROOT
    paths = [ROOT / 'schemas/producer/visual-source-policy-v1.json',
             ROOT / 'vendor/hyperframes-catalog/catalog-index.json']
    paths.extend((ROOT / 'scripts/producer/graphics').glob('visual_source_*.py'))
    paths.extend((ROOT / 'vendor/hyperframes-catalog').rglob('*.html'))
    return paths
