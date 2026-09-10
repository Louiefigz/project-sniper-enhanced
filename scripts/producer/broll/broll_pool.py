#!/usr/bin/env python3
"""broll_pool — the operator's b-roll ASSET POOL: vision cataloging + receipt resolution.

R17 receipts need ground truth: graphics_planner_receipts proposes
``{assetId: null, needsOperator: true, note: "receipt: <entity>"}`` rows and
nothing resolves them until the pool is cataloged (assess-pool-FIRST doctrine,
SKILL.md). This module owns that lane, on top of ingest_scan's probe + cache
machinery (same ``broll_catalog.json``, path+mtime keyed):

* ``scan <broll_dir> --manifest <asset_manifest.json>`` — reverify the
  source-set authority, reject files added after ingest, and inspect only the
  admitted snapshots. Every NEW/CHANGED admitted video gets a stable id +
  vision fields and 3 representative frames (15%/50%/85% of duration — off
  the fade-prone edges) in ``<broll_dir>/.frames/``; images are their own frame.
  Idempotent: unchanged records keep their vision fields; an mtime change
  re-extracts frames and resets ``cataloged`` to false (stale tags never feed
  renders). Prints NDJSON + a human UNCATALOGED table — the list a Claude
  vision pass (the BRAIN, not a paid API) reviews to fill tags/description.
* ``annotate <broll_dir> <id> --manifest <asset_manifest.json> ...`` — the
  brain writes what it SAW; sets ``cataloged: true``. The tool invents no tags.
* ``manifest <broll_dir> --manifest <asset_manifest.json>`` — emit the
  ``manifest["broll"]`` array (cataloged assets only) in the exact executable
  projection downstream authority consumes.
* ``resolve <broll_dir> <proposal.json> --manifest <asset_manifest.json>`` —
  fill brollReceipts assetIds by case-insensitive EXACT token match against
  catalog TAGS ONLY. A multi-token entity needs ALL tokens. Exactly one hit
  resolves; zero or MANY stays ``needsOperator`` untouched (no fuzzy fallback).

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

from broll.pool_admission import (PoolAsset, PoolAuthority, open_pool,  # noqa: E402
                                  proof_fields)
from broll.pool_frames import (extract_frames, frames_current,  # noqa: E402
                               validate_asset_id)
from broll.pool_receipts import resolve_file, resolve_receipts  # noqa: E402
from broll.pool_views import manifest_entries, uncataloged_table  # noqa: E402
from ingest_probe import probe_media, run_command, status, warn  # noqa: E402
from ingest_scan import (BROLL_CATALOG_NAME, _category_tag,  # noqa: E402
                         _load_broll_cache, _write_broll_cache, broll_fields)


def vision_defaults() -> dict:
    """The vision-catalog fields a fresh (un-reviewed) pool record carries."""
    return {"frames": [], "tags": [], "description": "", "cataloged": False}


def _asset_id(rel: str) -> str:
    """Stable pool id from the broll-relative path (an opaque HANDLE — never
    matched against; resolution is tags-only)."""
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", rel)
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    if not slug:
        return hashlib.sha1(rel.encode()).hexdigest()[:10]
    if len(slug) <= 96:
        return slug
    return f"{slug[:87].rstrip('-')}-{hashlib.sha1(rel.encode()).hexdigest()[:8]}"


def _claim_id(existing: Optional[str], rel: str, used: dict) -> str:
    """Keep a record's existing id; slug new ones; de-collide deterministically."""
    cand = validate_asset_id(existing) if existing is not None else _asset_id(rel)
    owner = used.get(cand)
    if owner is not None and owner != rel:
        if existing is not None:
            raise RuntimeError("b-roll pool catalog repeats an asset id")
        suffix = hashlib.sha1(rel.encode()).hexdigest()[:6]
        cand = f"{cand[:89].rstrip('-')}-{suffix}"
    used[cand] = rel
    return cand


def _pool_record(asset: PoolAsset, authority: PoolAuthority,
                 fresh: Optional[dict],
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
    original = Path(asset.original_path)
    snapshot = Path(asset.snapshot_path)
    try:
        probe = probe_media(str(snapshot))
    except (RuntimeError, ValueError) as exc:
        warn(f"pool probe failed, skipping {original}: {exc}")
        status(status="pool_probe_failed", path=str(original))
        return None, "failed"
    rec = {
        **broll_fields(
            original, probe, _category_tag(original, authority.root)),
        **proof_fields(asset),
        "path": asset.snapshot_path,
        **vision_defaults(),
    }
    if stale is not None:
        rec.update(id=stale.get("id"), tags=stale.get("tags", []),
                   description=stale.get("description", ""))
    return rec, ("updated" if stale is not None else "new")


def _cached_by_original(cache_path: Path) -> dict[str, dict]:
    cache = _load_broll_cache(cache_path)
    return {
        row.get("originalPath", row["path"]): row
        for row in cache.values()
    }


def scan_pool(authority: PoolAuthority) -> list[dict]:
    """Catalog admitted snapshots; reject pool files absent from the source set."""
    broll_dir = authority.root
    cache_path = broll_dir / BROLL_CATALOG_NAME
    cache = _cached_by_original(cache_path)
    used: dict = {}
    records, cache_rows = [], []
    for original_path, asset in sorted(authority.assets.items()):
        original = Path(original_path)
        stale = cache.get(original_path)
        expected = {"path": asset.snapshot_path, **proof_fields(asset)}
        fresh = stale if (
            stale and all(stale.get(key) == value
                          for key, value in expected.items())) else None
        rec, how = _pool_record(asset, authority, fresh, stale)
        if rec is None:
            continue
        rel = str(original.relative_to(broll_dir))
        rec["id"] = _claim_id(rec.get("id"), rel, used)
        if how != "cached" or not frames_current(rec, broll_dir):
            try:
                rec["frames"] = extract_frames(
                    Path(asset.snapshot_path), rec, broll_dir)
            except RuntimeError as exc:
                warn(f"frame extraction failed for {original}: {exc}")
                rec["frames"] = []
        status(status=f"pool_{how}", id=rec["id"], path=rel,
               cataloged=rec["cataloged"], frames=len(rec["frames"]))
        records.append(rec)
        cache_rows.append(rec)
    _write_broll_cache(cache_path, cache_rows)
    status(status="pool_scan_done", assets=len(records),
           cataloged=sum(1 for r in records if r["cataloged"]),
           uncataloged=sum(1 for r in records if not r["cataloged"]))
    return records


def load_catalog(authority: PoolAuthority) -> list[dict]:
    """Load rows only when every row still matches current admission authority."""
    cache = _cached_by_original(authority.root / BROLL_CATALOG_NAME)
    if set(cache) != set(authority.assets):
        raise RuntimeError("b-roll pool catalog is stale; run admitted scan")
    rows = []
    for original, asset in authority.assets.items():
        row = cache[original]
        expected = {"path": asset.snapshot_path, **proof_fields(asset)}
        if any(row.get(key) != value for key, value in expected.items()):
            raise RuntimeError("b-roll pool catalog disagrees with admission")
        rows.append({k: v for k, v in row.items() if k != "mtime"})
    return rows


def annotate(authority: PoolAuthority, rec_id: str, tags: list[str],
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
    load_catalog(authority)
    cache_path = authority.root / BROLL_CATALOG_NAME
    cache = _load_broll_cache(cache_path)
    rec = next((r for r in cache.values() if r.get("id") == rec_id), None)
    if rec is None:
        raise ValueError(f"unknown asset id {rec_id!r} — run scan first")
    rec.update(tags=clean, description=description.strip(),
               descriptionSource="vision", cataloged=True)
    _write_broll_cache(cache_path, list(cache.values()))
    return {k: v for k, v in rec.items() if k != "mtime"}


def _cmd_resolve(authority: PoolAuthority, args: argparse.Namespace) -> int:
    """Resolve a proposal file in place (or to --out), NDJSON per outcome."""
    output = Path(args.out) if args.out else None
    resolve_file(
        authority, Path(args.proposal), output, load_catalog(authority))
    return 0


def _dispatch(args: argparse.Namespace) -> int:
    # Preserve the final path component exactly enough for open_pool's lstat
    # check to see a symlink. Path.resolve() would turn a symlinked operator
    # root into its target before the authority boundary could reject it.
    broll_dir = Path(os.path.abspath(args.broll_dir))
    if not broll_dir.is_dir():
        raise ValueError(f"not a directory: {broll_dir}")
    authority = open_pool(broll_dir, Path(args.manifest))
    if args.cmd == "scan":
        records = scan_pool(authority)
        print("\n".join(uncataloged_table(records, broll_dir)))
        return 0
    if args.cmd == "annotate":
        rec = annotate(
            authority, args.id, args.tags.split(","), args.description)
        status(status="pool_annotated", id=rec["id"], tags=rec["tags"])
        return 0
    if args.cmd == "manifest":
        print(json.dumps(manifest_entries(load_catalog(authority)), indent=2))
        return 0
    return _cmd_resolve(authority, args)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="PRODUCER b-roll pool: vision cataloging + R17 receipt "
                    "resolution (tags only, no fuzzy fallbacks)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    scan = sub.add_parser("scan", help="catalog the pool + extract frames")
    scan.add_argument("broll_dir")
    scan.add_argument("--manifest", required=True)
    ann = sub.add_parser("annotate", help="write the brain's tags/description")
    ann.add_argument("broll_dir")
    ann.add_argument("id")
    ann.add_argument("--manifest", required=True)
    ann.add_argument("--tags", required=True, help="comma-separated tokens")
    ann.add_argument("--description", required=True)
    man = sub.add_parser("manifest", help="emit manifest['broll'] (cataloged only)")
    man.add_argument("broll_dir")
    man.add_argument("--manifest", required=True)
    res = sub.add_parser("resolve", help="fill receipt assetIds from the pool")
    res.add_argument("broll_dir")
    res.add_argument("proposal", help="graphics_planner proposal.json")
    res.add_argument("--manifest", required=True)
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
