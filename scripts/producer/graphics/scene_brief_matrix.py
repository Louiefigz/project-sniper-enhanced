"""Release gate ensuring P4 exercises materially different scene briefs."""
from __future__ import annotations

_REQUIRED_TAGS = {
    "overlay", "takeover", "presenter-hole", "mask", "blend", "particles",
    "real-copy-overflow", "own-screen-geometry", "footage-contrast",
    "unit-repair", "timing-move", "short", "longform",
}


def validate_brief_matrix(value: object) -> dict:
    """Require twelve unique briefs spanning the P4 risk surface."""
    if not isinstance(value, list) or len(value) < 12:
        raise ValueError("P4 brief matrix requires at least 12 briefs")
    ids: set[str] = set()
    tags: set[str] = set()
    aspects: set[str] = set()
    rates: set[tuple[int, int]] = set()
    for index, row in enumerate(value):
        if not isinstance(row, dict) or set(row) != {
                "briefId", "tags", "aspect", "fps"}:
            raise ValueError(f"P4 brief {index} has an invalid field set")
        ident = row["briefId"]
        if not isinstance(ident, str) or not ident or ident in ids:
            raise ValueError(f"P4 brief {index} has a duplicate/invalid id")
        ids.add(ident)
        if not isinstance(row["tags"], list) or not row["tags"] \
                or not all(isinstance(tag, str) for tag in row["tags"]):
            raise ValueError(f"P4 brief {index} tags are invalid")
        tags.update(row["tags"])
        if row["aspect"] not in {"9:16", "16:9"}:
            raise ValueError(f"P4 brief {index} aspect is unsupported")
        aspects.add(row["aspect"])
        fps = row["fps"]
        if not isinstance(fps, dict) or set(fps) != {
                "numerator", "denominator"}:
            raise ValueError(f"P4 brief {index} FPS is invalid")
        pair = fps["numerator"], fps["denominator"]
        if not all(type(item) is int and item > 0 for item in pair):
            raise ValueError(f"P4 brief {index} FPS is invalid")
        rates.add(pair)
    missing = sorted(_REQUIRED_TAGS - tags)
    if missing:
        raise ValueError(f"P4 brief matrix lacks coverage: {missing}")
    if aspects != {"9:16", "16:9"} or len(rates) < 2:
        raise ValueError("P4 briefs need both aspects and multiple exact FPS")
    return {
        "briefCount": len(value),
        "tags": sorted(tags),
        "aspects": sorted(aspects),
        "fps": [{"numerator": top, "denominator": bottom}
                for top, bottom in sorted(rates)],
    }
