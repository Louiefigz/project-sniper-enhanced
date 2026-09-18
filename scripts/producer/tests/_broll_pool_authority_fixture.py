"""Shared admitted-manifest fixture for b-roll pool tests."""
from __future__ import annotations

import json
from pathlib import Path

from _ingest_admission_fixture import runner as admission_runner
from broll.pool_admission import PoolAuthority, open_pool
from ingest_admission import admit_ingest_candidates, collect_ingest_candidates


def _manifest_row(index: int, media: object) -> dict:
    return {
        "id": f"broll-{index}",
        "path": media.snapshot_path,
        "originalPath": media.original_path,
        "sourceSha256": media.sha256,
        "admissionReceiptPath": media.receipt_path,
        "admissionReceiptSha256": media.receipt_sha256,
        "kind": "video",
    }


def build_pool_authority(pool: Path) -> tuple[Path, PoolAuthority]:
    """Admit every current pool file and write a strict manifest."""
    authority_dir = pool.parent / "admission"
    admission = admit_ingest_candidates(
        collect_ingest_candidates([], pool, None),
        authority_dir,
        admission_runner,
    )
    rows = [
        _manifest_row(index, media)
        for index, media in enumerate(
            admission.media_by_original.values(), start=1)
    ]
    manifest_path = authority_dir / "asset_manifest.json"
    manifest_path.write_text(json.dumps({
        "sources": [],
        "broll": rows,
        "music": [],
        "sourceSetAdmission": admission.binding,
    }))
    return manifest_path, open_pool(pool, manifest_path)
