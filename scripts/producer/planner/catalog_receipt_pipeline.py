"""Installed code identity for agent-facing catalog receipt issuance."""
from __future__ import annotations

import hashlib
from pathlib import Path

from planner.visual_plan_fields import canonical_hash
from planner.visual_plan_receipts import MAX_ARTIFACT_BYTES, read_exact

PRODUCER = Path(__file__).resolve().parents[1]
PIPELINE_FILES = (
    "cross_runtime_canonical_json.py",
    "graphics/catalog_receipt_runner.py",
    "graphics/comp_capability_artifact.py",
    "planner/catalog_receipt_issuer.py",
    "planner/catalog_receipt_issuer_cli.py",
    "planner/catalog_receipt_pipeline.py",
    "planner/visual_plan_admission.py",
    "planner/visual_plan_authority_admission.py",
    "planner/visual_plan_catalog_authority.py",
    "planner/visual_plan_contract.py",
    "planner/visual_plan_fields.py",
    "planner/visual_plan_layering.py",
    "planner/visual_plan_receipts.py",
    "planner/visual_plan_validation.py",
)


def catalog_receipt_pipeline_authority() -> dict:
    """Hash the fixed installed issuer/validator closure without caller input."""
    files = []
    for relative in PIPELINE_FILES:
        path = (PRODUCER / relative).resolve(strict=True)
        data = read_exact(str(path), f"catalog receipt pipeline {relative}",
                          MAX_ARTIFACT_BYTES)
        files.append({"path": relative,
                      "sha256": hashlib.sha256(data).hexdigest()})
    core = {"schemaVersion": 1,
            "kind": "installed-catalog-receipt-pipeline-authority",
            "files": files}
    return {**core, "sha256": canonical_hash(core)}


def catalog_receipt_pipeline_sha256() -> str:
    """Return the installed issuer/validator closure digest."""
    return catalog_receipt_pipeline_authority()["sha256"]
