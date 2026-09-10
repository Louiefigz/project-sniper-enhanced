"""Deterministic, tags-only b-roll receipt resolution."""
from __future__ import annotations

import json
import re
from pathlib import Path

from broll.pool_admission import PoolAuthority
from ingest_probe import status
from ingest_scan import atomic_write_json

RECEIPT_PREFIX = "receipt: "
RESOLVED_SUFFIX = " — resolved from pool"


def _entity_tokens(note: str) -> frozenset:
    if not note.startswith(RECEIPT_PREFIX):
        return frozenset()
    raw = re.split(r"[^a-z0-9]+", note[len(RECEIPT_PREFIX):].lower())
    return frozenset(token for token in raw if token)


def _resolve_row(row: dict, tagged: list[tuple]) -> dict:
    if row.get("assetId") is not None:
        return row
    tokens = _entity_tokens(row.get("note") or "")
    if not tokens:
        return row
    hits = [asset_id for asset_id, tags in tagged if tokens <= tags]
    if len(hits) != 1:
        return row
    return {
        **row,
        "assetId": hits[0],
        "needsOperator": False,
        "note": f"{row['note']}{RESOLVED_SUFFIX}",
    }


def resolve_receipts(proposals: dict, catalog: list[dict]) -> dict:
    """Resolve exact all-token matches against cataloged vision tags."""
    tagged = [
        (row["id"], frozenset(tag.lower() for tag in row.get("tags") or []))
        for row in catalog if row.get("cataloged")
    ]
    output = dict(proposals)
    output["brollReceipts"] = [
        _resolve_row(row, tagged)
        for row in proposals.get("brollReceipts") or []
    ]
    return output


def _emit_outcomes(before: list[dict], after: list[dict]) -> None:
    for old, new in zip(before, after):
        if old.get("assetId") is None and new.get("assetId") is not None:
            status(
                status="receipt_resolved",
                assetId=new["assetId"],
                note=old.get("note"),
            )
            continue
        if new.get("assetId") is None:
            status(
                status="receipt_unresolved",
                note=new.get("note"),
                needsOperator=True,
            )


def resolve_file(
    authority: PoolAuthority,
    proposal_path: Path,
    output_path: Path | None,
    catalog: list[dict],
) -> None:
    """Resolve one proposal and atomically publish the resulting JSON."""
    try:
        proposals = json.loads(proposal_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("b-roll receipt proposal is malformed") from exc
    if type(proposals) is not dict:
        raise RuntimeError("b-roll receipt proposal is not an object")
    resolved = resolve_receipts(proposals, catalog)
    before = proposals.get("brollReceipts") or []
    after = resolved.get("brollReceipts") or []
    _emit_outcomes(before, after)
    destination = output_path or proposal_path
    atomic_write_json(destination, resolved)
    status(
        status="pool_resolve_done",
        out=str(destination),
        resolved=sum(
            1 for old, new in zip(before, after)
            if old.get("assetId") is None and new.get("assetId")
        ),
        unresolved=sum(1 for row in after if row.get("assetId") is None),
        sourceSetManifest=str(authority.manifest_path),
    )
