#!/usr/bin/env python3
"""broll_pool — the operator's b-roll ASSET POOL: vision cataloging + receipt resolution.

R17 receipts need ground truth: graphics_planner_receipts proposes
``{assetId: null, needsOperator: true, note: "receipt: <entity>"}`` rows and
nothing resolves them until the pool is cataloged (assess-pool-FIRST doctrine,
SKILL.md). This module owns that lane, on top of ingest_scan's probe + cache
machinery (same ``broll_catalog.json``, path+mtime keyed):

* ``scan <broll_dir>``      — walk the pool; every NEW/CHANGED video gets a stable
  id + vision fields and 3 representative frames (15%/50%/85% of duration — off
  the fade-prone edges) in ``<broll_dir>/.frames/``; images are their own frame.
  Idempotent: unchanged records keep their vision fields; an mtime change
  re-extracts frames and resets ``cataloged`` to false (stale tags never feed
  renders). Prints NDJSON + a human UNCATALOGED table — the list a Claude
  vision pass (the BRAIN, not a paid API) reviews to fill tags/description.
* ``annotate <broll_dir> <id> --tags .. --description ..`` — the brain writes
  what it SAW; sets ``cataloged: true``. The tool never invents tags.
* ``manifest <broll_dir>``  — emit the ``manifest["broll"]`` array (cataloged
  assets only) in the shape ``plan_lint._check_broll`` (needs ``id``) and
  ``broll_insert.resolve_assets`` (needs ``id``/``path``/``kind``) consume.
* ``resolve <broll_dir> <proposal.json>`` — fill brollReceipts assetIds by
  case-insensitive EXACT token match against catalog TAGS ONLY; a multi-token
  entity needs ALL tokens. Exactly one hit resolves; zero or MANY stays
  ``needsOperator`` untouched (feedback-no-fallbacks: no fuzzy match, no
  popularity ranking). ``brollConcept`` rows are never auto-resolved (R24:
  concept stock stays operator-choice).

NAMING IS NEVER LOAD-BEARING: filenames and folder names seed nothing — only
brain-confirmed tags resolve receipts (the vision catalog is source of truth).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingest_probe import MEDIA_EXTS, probe_media, run_command, status, warn  # noqa: E402
from ingest_scan import (BROLL_CATALOG_NAME, _category_tag,  # noqa: E402
                         _load_broll_cache, _write_broll_cache, broll_fields)

FRAMES_DIR_NAME = ".frames"
# Representative sample points: off the edges, so intros/fades/outros don't
# masquerade as the asset's content (the "settled" positions).
FRAME_POSITIONS = (0.15, 0.50, 0.85)
RECEIPT_PREFIX = "receipt: "
RESOLVED_SUFFIX = " — resolved from pool"
# The manifest["broll"] row contract: plan_lint._check_broll keys on "id";
# broll_insert.resolve_assets keys on "id"/"path"/"kind" (and probes the file).
MANIFEST_FIELDS = ("id", "path", "kind", "duration", "resolution",
                   "orientation", "category", "hasSpeech", "tags", "description")


def vision_defaults() -> dict:
    """The vision-catalog fields a fresh (un-reviewed) pool record carries."""
    return {"frames": [], "tags": [], "description": "", "cataloged": False}


def _asset_id(rel: str) -> str:
    """Stable pool id from the broll-relative path (an opaque HANDLE — never
    matched against; resolution is tags-only)."""
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", rel)
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return slug or hashlib.sha1(rel.encode()).hexdigest()[:10]


def _claim_id(existing: Optional[str], rel: str, used: dict) -> str:
    """Keep a record's existing id; slug new ones; de-collide deterministically."""
    cand = existing or _asset_id(rel)
    if used.get(cand, rel) != rel:
        cand = f"{cand}-{hashlib.sha1(rel.encode()).hexdigest()[:6]}"
    used[cand] = rel
    return cand


def _pool_files(broll_dir: Path) -> list[Path]:
    """Media files under the pool, skipping dot-dirs (``.frames`` is machinery)."""
    return sorted(
        p for p in broll_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in MEDIA_EXTS
        and not any(part.startswith(".")
                    for part in p.relative_to(broll_dir).parts))


def _pool_record(path: Path, broll_dir: Path, fresh: Optional[dict],
                 stale: Optional[dict]) -> tuple[Optional[dict], str]:
    """(record, how) for one pool file.

    ``fresh`` = cache hit whose mtime matched (kept verbatim, vision fields and
    all); ``stale`` = a cached record whose mtime CHANGED — its tags/description
    survive as hints but ``cataloged`` resets to false (the content moved under
    the annotation; the brain must look again). New files probe from scratch.
    """
    if fresh is not None:
        rec = {k: v for k, v in fresh.items() if k != "mtime"}
        if "cataloged" not in rec:              # pre-pool record: init vision
            rec.update(vision_defaults())
        return rec, "cached"
    try:
        probe = probe_media(str(path))
    except (RuntimeError, ValueError) as exc:
        warn(f"pool probe failed, skipping {path}: {exc}")
        status(status="pool_probe_failed", path=str(path))
        return None, "failed"
    rec = {**broll_fields(path, probe, _category_tag(path, broll_dir)),
           **vision_defaults()}
    if stale is not None:
        rec.update(id=stale.get("id"), tags=stale.get("tags", []),
                   description=stale.get("description", ""))
    return rec, ("updated" if stale is not None else "new")


def _extract_frames(path: Path, rec: dict, broll_dir: Path) -> list[str]:
    """3 representative JPGs into ``.frames/<id>_N.jpg`` (broll-relative paths).

    Images ARE their single frame. A video with unknown duration gets one
    frame at t=0 (flagged loud — still reviewable, never silently skipped).
    """
    if rec["kind"] == "image":
        return [str(path.relative_to(broll_dir))]
    dur = rec.get("duration")
    if not dur:
        warn(f"no duration for {path}; extracting a single t=0 frame")
    times = [dur * f for f in FRAME_POSITIONS] if dur else [0.0]
    frames_dir = broll_dir / FRAMES_DIR_NAME
    frames_dir.mkdir(exist_ok=True)
    rels: list[str] = []
    for n, t in enumerate(times, start=1):
        out = frames_dir / f"{rec['id']}_{n}.jpg"
        run_command(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                     "-ss", f"{t:.3f}", "-i", str(path),
                     "-frames:v", "1", "-q:v", "2", str(out)])
        rels.append(str(out.relative_to(broll_dir)))
    return rels


def _frames_current(rec: dict, broll_dir: Path) -> bool:
    """True when the record's frame files all still exist on disk."""
    frames = rec.get("frames") or []
    return bool(frames) and all((broll_dir / f).exists() for f in frames)


def scan_pool(broll_dir: Path) -> list[dict]:
    """Catalog the pool (idempotent), extracting frames for new/changed assets."""
    cache_path = broll_dir / BROLL_CATALOG_NAME
    cache = _load_broll_cache(cache_path)
    used: dict = {}
    records, cache_rows = [], []
    for path in _pool_files(broll_dir):
        mtime = path.stat().st_mtime
        stale = cache.get(str(path))
        fresh = stale if (stale and stale.get("mtime") == mtime) else None
        rec, how = _pool_record(path, broll_dir, fresh, stale)
        if rec is None:
            continue
        rel = str(path.relative_to(broll_dir))
        rec["id"] = _claim_id(rec.get("id"), rel, used)
        if how != "cached" or not _frames_current(rec, broll_dir):
            try:
                rec["frames"] = _extract_frames(path, rec, broll_dir)
            except RuntimeError as exc:
                warn(f"frame extraction failed for {path}: {exc}")
                rec["frames"] = []
        status(status=f"pool_{how}", id=rec["id"], path=rel,
               cataloged=rec["cataloged"], frames=len(rec["frames"]))
        records.append(rec)
        cache_rows.append({**rec, "mtime": mtime})
    _write_broll_cache(cache_path, cache_rows)
    status(status="pool_scan_done", assets=len(records),
           cataloged=sum(1 for r in records if r["cataloged"]),
           uncataloged=sum(1 for r in records if not r["cataloged"]))
    return records


def uncataloged_table(records: list[dict], broll_dir: Path) -> list[str]:
    """The human review queue: what the brain must LOOK at, with frame paths."""
    rows = [r for r in records if not r.get("cataloged")]
    if not rows:
        return ["", "All pool assets are cataloged."]
    lines = ["", f"UNCATALOGED ({len(rows)}) — LOOK at each asset's frames, then:",
             "  broll_pool.py annotate <broll_dir> <id> "
             "--tags \"tok,tok\" --description \"...\""]
    for r in rows:
        dur = f"{r['duration']:.1f}s" if r.get("duration") else r["kind"]
        lines.append(f"  {r['id']:<38} {r.get('category') or '-':<20} {dur:>8}")
        lines.extend(f"      {broll_dir / f}" for f in r.get("frames") or [])
    return lines


def load_catalog(broll_dir: Path) -> list[dict]:
    """The pool catalog records (mtime stripped), ids included."""
    cache = _load_broll_cache(broll_dir / BROLL_CATALOG_NAME)
    return [{k: v for k, v in r.items() if k != "mtime"} for r in cache.values()]


def annotate(broll_dir: Path, rec_id: str, tags: list[str],
             description: str) -> dict:
    """Write the brain's vision verdict for one asset; sets ``cataloged: true``.

    Tags are lowercased single tokens (the resolver's match currency).
    Both fields are required — an unseen asset stays uncataloged.
    """
    clean = sorted({t.strip().lower() for t in tags if t.strip()})
    if not clean:
        raise ValueError("annotate needs at least one non-empty tag")
    if not description.strip():
        raise ValueError("annotate needs a description — look at the frames first")
    cache_path = broll_dir / BROLL_CATALOG_NAME
    cache = _load_broll_cache(cache_path)
    rec = next((r for r in cache.values() if r.get("id") == rec_id), None)
    if rec is None:
        raise ValueError(f"unknown asset id {rec_id!r} — run scan first")
    rec.update(tags=clean, description=description.strip(),
               descriptionSource="vision", cataloged=True)
    _write_broll_cache(cache_path, list(cache.values()))
    return {k: v for k, v in rec.items() if k != "mtime"}


def manifest_entries(catalog: list[dict]) -> list[dict]:
    """``manifest["broll"]`` rows for CATALOGED assets only (paths absolute)."""
    return [{k: r.get(k) for k in MANIFEST_FIELDS}
            for r in catalog if r.get("cataloged")]


def _entity_tokens(note: str) -> frozenset:
    """'receipt: YouTube comedy channel' -> {youtube, comedy, channel}."""
    if not note.startswith(RECEIPT_PREFIX):
        return frozenset()
    raw = re.split(r"[^a-z0-9]+", note[len(RECEIPT_PREFIX):].lower())
    return frozenset(t for t in raw if t)


def _resolve_row(row: dict, tagged: list[tuple]) -> dict:
    """One receipt row -> resolved copy, or the row untouched.

    Tags only, ALL entity tokens required, exactly ONE hit fills assetId.
    Zero or multiple hits stay needsOperator (no fuzzy fallback, no ranking).
    """
    if row.get("assetId") is not None:
        return row
    tokens = _entity_tokens(row.get("note") or "")
    if not tokens:
        return row
    hits = [rid for rid, tags in tagged if tokens <= tags]
    if len(hits) != 1:
        return row
    return {**row, "assetId": hits[0], "needsOperator": False,
            "note": f"{row['note']}{RESOLVED_SUFFIX}"}


def resolve_receipts(proposals: dict, catalog: list[dict]) -> dict:
    """Fill brollReceipts assetIds from the pool (CATALOGED tags only).

    Returns a new proposals dict; the input and its rows are never mutated.
    ``brollConcept`` (R24 concept stock) passes through untouched — always
    operator-choice.
    """
    tagged = [(r["id"], frozenset(t.lower() for t in r.get("tags") or []))
              for r in catalog if r.get("cataloged")]
    out = dict(proposals)
    out["brollReceipts"] = [_resolve_row(row, tagged)
                            for row in proposals.get("brollReceipts") or []]
    return out


def _cmd_resolve(broll_dir: Path, args: argparse.Namespace) -> int:
    """Resolve a proposal file in place (or to --out), NDJSON per outcome."""
    with open(args.proposal) as f:
        proposals = json.load(f)
    resolved = resolve_receipts(proposals, load_catalog(broll_dir))
    before = proposals.get("brollReceipts") or []
    after = resolved.get("brollReceipts") or []
    for old, new in zip(before, after):
        if old.get("assetId") is None and new.get("assetId") is not None:
            status(status="receipt_resolved", assetId=new["assetId"],
                   note=old.get("note"))
        elif new.get("assetId") is None:
            status(status="receipt_unresolved", note=new.get("note"),
                   needsOperator=True)
    out_path = args.out or args.proposal
    with open(out_path, "w") as f:
        json.dump(resolved, f, indent=2)
    status(status="pool_resolve_done", out=out_path,
           resolved=sum(1 for o, n in zip(before, after)
                        if o.get("assetId") is None and n.get("assetId")),
           unresolved=sum(1 for n in after if n.get("assetId") is None))
    return 0


def _dispatch(args: argparse.Namespace) -> int:
    broll_dir = Path(args.broll_dir).resolve()
    if not broll_dir.is_dir():
        raise ValueError(f"not a directory: {broll_dir}")
    if args.cmd == "scan":
        records = scan_pool(broll_dir)
        print("\n".join(uncataloged_table(records, broll_dir)))
        return 0
    if args.cmd == "annotate":
        rec = annotate(broll_dir, args.id, args.tags.split(","), args.description)
        status(status="pool_annotated", id=rec["id"], tags=rec["tags"])
        return 0
    if args.cmd == "manifest":
        print(json.dumps(manifest_entries(load_catalog(broll_dir)), indent=2))
        return 0
    return _cmd_resolve(broll_dir, args)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="PRODUCER b-roll pool: vision cataloging + R17 receipt "
                    "resolution (tags only, no fuzzy fallbacks)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    scan = sub.add_parser("scan", help="catalog the pool + extract frames")
    scan.add_argument("broll_dir")
    ann = sub.add_parser("annotate", help="write the brain's tags/description")
    ann.add_argument("broll_dir")
    ann.add_argument("id")
    ann.add_argument("--tags", required=True, help="comma-separated tokens")
    ann.add_argument("--description", required=True)
    man = sub.add_parser("manifest", help="emit manifest['broll'] (cataloged only)")
    man.add_argument("broll_dir")
    res = sub.add_parser("resolve", help="fill receipt assetIds from the pool")
    res.add_argument("broll_dir")
    res.add_argument("proposal", help="graphics_planner proposal.json")
    res.add_argument("--out", default=None,
                     help="write here instead of updating the proposal in place")
    args = ap.parse_args()
    try:
        return _dispatch(args)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        status(error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
