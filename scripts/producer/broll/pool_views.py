"""Human-review and manifest projections for admitted b-roll catalogs."""
from __future__ import annotations

from pathlib import Path

MANIFEST_FIELDS = (
    "id", "path", "originalPath", "sourceSha256", "admissionReceiptPath",
    "admissionReceiptSha256", "kind", "duration", "resolution",
    "orientation", "category", "hasSpeech", "tags", "description",
)


def uncataloged_table(records: list[dict], broll_dir: Path) -> list[str]:
    """Return the human vision-review queue for uncataloged assets."""
    rows = [row for row in records if not row.get("cataloged")]
    if not rows:
        return ["", "All pool assets are cataloged."]
    lines = [
        "",
        f"UNCATALOGED ({len(rows)}) — LOOK at each asset's frames, then:",
        "  broll_pool.py annotate <broll_dir> <id> "
        "--manifest <asset_manifest.json> "
        "--tags \"tok,tok\" --description \"...\"",
    ]
    for row in rows:
        duration = (
            f"{row['duration']:.1f}s" if row.get("duration") else row["kind"]
        )
        lines.append(
            f"  {row['id']:<38} "
            f"{row.get('category') or '-':<20} {duration:>8}"
        )
        lines.extend(
            f"      {broll_dir / frame}"
            for frame in row.get("frames") or []
        )
    return lines


def manifest_entries(catalog: list[dict]) -> list[dict]:
    """Return cataloged rows in the strict executable manifest shape."""
    return [
        {key: row.get(key) for key in MANIFEST_FIELDS}
        for row in catalog if row.get("cataloged")
    ]
