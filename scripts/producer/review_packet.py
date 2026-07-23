#!/usr/bin/env python3
"""review_packet — hash-bound critic evidence packet for the skill review wall.

The GUI controller's plan-review packet (``src/app/api/producer/auto-edit/
plan-review-packet.ts``) proved the pattern: every review round, critics READ
one bound evidence packet instead of re-deriving transcript understanding from
raw files. This is the skill-lane equivalent (SKILL.md step 4): ONE
deterministic JSON binding

* the plan + manifest content with their exact byte hashes (sha256),
* the compiled cut-segment table (source↔output geometry + the brain's own
  ``rationale`` per kept range),
* every KEPT word remapped to output time through ``compile_timeline`` (the
  correctness keystone — never hand-derived offsets),
* the word on each side of every cut boundary (edge/dangling-word evidence),
* the deterministic gate verdicts (plan_lint / hook_contract /
  claims_contract) plus their ``gateDigest``,
* the pacing report — the exact JSON ``planner/pacing.py <plan>`` prints.

``contentDigest`` is a canonical-JSON sha256 of everything above, so the same
inputs always produce the same digest: two concurrent round-1 critics handed
packets with equal digests are provably reviewing the same authority.

CLI: review_packet.py <plan> <transcripts_dir> <manifest> --out packet.json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import plan_lint  # noqa: E402
from claims_contract import check_claims_contract  # noqa: E402
from compile_timeline import Segment, TimelineMap, compile_plan  # noqa: E402
from edit_scope import resolve_scope  # noqa: E402
from fingerprints import json_canon  # noqa: E402
from hook_contract import check_hook_contract  # noqa: E402
from planner import pacing  # noqa: E402
from planner.motion_triggers import flatten_words  # noqa: E402

SCHEMA_VERSION = 1
PACKET_KIND = "producer-skill-review-packet"

# Mirrors compile_timeline.remap_words: a word whose kept span is this short
# is inaudible and dropped (it "starts" exactly on a seam).
_EPS = 1e-6


def _digest(obj: object) -> str:
    """Full sha256 hex of the canonical JSON serialization of ``obj``.

    Canonicalization rides ``fingerprints.json_canon`` (integral floats →
    ints) + sorted keys, so semantically identical structures hash equal
    regardless of construction order or ``30.0``-vs-``30`` float spelling.
    """
    blob = json.dumps(json_canon(obj), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def packet_content_digest(packet: dict) -> str:
    """Recompute a packet's digest from everything except the binding itself.

    Equal to ``packet["contentDigest"]`` iff the packet is untampered — the
    verification a critic (or the doctrine's staleness check) runs.
    """
    return _digest({k: v for k, v in packet.items() if k != "contentDigest"})


def _bound_json(path: str, label: str) -> dict:
    """Read ``path`` once → ``{byteHash, content}`` (exact-bytes bind)."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise ValueError(f"{label} unreadable: {exc}") from exc
    try:
        content = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    return {"byteHash": hashlib.sha256(raw).hexdigest(), "content": content}


def _segment_rows(plan: dict, tmap: TimelineMap) -> list[dict]:
    """The cut-segment table: compiled geometry + the brain's rationale."""
    track = plan.get("cutTrack") or []
    return [{
        "index": seg.index,
        "sourceId": seg.source_id,
        "sourceStart": seg.src_start,
        "sourceEnd": seg.src_end,
        "speed": seg.speed,
        "outputStart": seg.out_start,
        "outputEnd": seg.out_end,
        "rationale": track[seg.index].get("rationale"),
        "protectedPauses": track[seg.index].get("protectedPauses") or [],
    } for seg in tmap.segments]


def _utterance_rows(parsed: object) -> list[dict]:
    """Compact ``{start, end, text}`` rows (empty for flat word-list files)."""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("transcript"), list):
        return []
    return [{k: u.get(k) for k in ("start", "end", "text")}
            for u in parsed["transcript"] if isinstance(u, dict)]


def _load_transcript(source: dict, transcripts_dir: str) -> dict:
    """One source's transcript bound by byte hash: utterances + flat words."""
    path = str(source.get("transcriptPath"))
    if not os.path.isabs(path):
        path = os.path.join(transcripts_dir, path)
    bound = _bound_json(path, f"transcript {source.get('id')}")
    return {"byteHash": bound["byteHash"],
            "words": flatten_words(bound["content"]),
            "utterances": _utterance_rows(bound["content"])}


def _kept_word(word: dict, source_id: str, segments: list[Segment]) -> dict | None:
    """``remap_words`` semantics, keeping source identity for the critics."""
    start = float(word["start"])
    seg = next((s for s in segments if s.contains_src(source_id, start)), None)
    if seg is None:
        return None
    end_src = min(float(word["end"]), seg.src_end)
    if end_src <= start + _EPS:
        return None
    return {
        "word": str(word.get("punctuated_word") or word.get("word", "")),
        "sourceId": source_id,
        "segmentIndex": seg.index,
        "sourceStart": start,
        "sourceEnd": end_src,
        "sourceOriginalEnd": float(word["end"]),
        "outputStart": round(seg.src_to_out(start), 4),
        "outputEnd": round(seg.src_to_out(end_src), 4),
    }


def _kept_from(source_id: str, words: list[dict],
               segments: list[Segment]) -> list[dict]:
    """Every kept word of one source (order preserved; cut words dropped)."""
    out: list[dict] = []
    for word in words:
        kept = _kept_word(word, source_id, segments)
        if kept is not None:
            out.append(kept)
    return out


def _boundary_rows(seg: Segment, words: list[dict]) -> list[dict]:
    """The source word on each side of both edges of one segment."""
    rows: list[dict] = []
    for edge in ("in", "out"):
        t = seg.src_start if edge == "in" else seg.src_end
        before = next((w for w in reversed(words) if float(w["start"]) < t), None)
        after = next((w for w in words if float(w["start"]) >= t), None)
        rows.append({"segmentIndex": seg.index, "sourceId": seg.source_id,
                     "edge": edge, "sourceTime": t,
                     "before": before, "after": after})
    return rows


def _used_sources(plan: dict, manifest: dict) -> list[tuple[str, dict]]:
    """Fail-closed source resolution: every cutTrack source needs a transcript."""
    index = {str(s.get("id")): s for s in (manifest.get("sources") or [])}
    used = sorted({str(r.get("sourceId")) for r in plan.get("cutTrack") or []})
    resolved: list[tuple[str, dict]] = []
    for sid in used:
        src = index.get(sid)
        if src is None:
            raise ValueError(f"cutTrack references unknown source {sid}")
        if not isinstance(src.get("transcriptPath"), str) or not src["transcriptPath"]:
            raise ValueError(f"kept source {sid} has no transcript")
        resolved.append((sid, src))
    return resolved


def _transcript_evidence(plan: dict, transcripts_dir: str,
                         manifest: dict, tmap: TimelineMap) -> dict:
    """Kept-word + boundary evidence for every source the cutTrack uses."""
    loaded = {sid: _load_transcript(src, transcripts_dir)
              for sid, src in _used_sources(plan, manifest)}
    kept = [row for sid, data in loaded.items()
            for row in _kept_from(sid, data["words"], tmap.segments)]
    kept.sort(key=lambda w: (w["outputStart"], w["segmentIndex"], w["sourceStart"]))
    neighbors = [row for seg in tmap.segments
                 for row in _boundary_rows(seg, loaded[seg.source_id]["words"])]
    missing = sorted(str(s.get("id")) for s in (manifest.get("sources") or [])
                     if not s.get("transcriptPath"))
    return {
        "transcripts": [{"sourceId": sid,
                         "byteHash": data["byteHash"],
                         "utteranceCount": len(data["utterances"]),
                         "sourceWordCount": len(data["words"]),
                         "utterances": data["utterances"]}
                        for sid, data in loaded.items()],
        "missingTranscriptSourceIds": missing,
        "keptWords": kept,
        "boundaryNeighbors": neighbors,
    }


def _gate_verdicts(plan: dict, manifest: dict, words: list[dict]) -> dict:
    """The three deterministic skill-lane gate verdicts, verbatim shapes.

    Calls the same entry points the standalone gate CLIs call, so the
    packet's verdicts cannot drift from what ``plan_lint.py`` /
    ``hook_contract.py`` / ``claims_contract.py`` print for the same inputs.
    """
    lint_rep = plan_lint.lint(plan, manifest, words)
    target = plan.get("target") or {}
    hook_rep = plan_lint.Report()
    check_hook_contract(plan, words, target, hook_rep)
    claims_rep = plan_lint.Report()
    check_claims_contract(plan, words, claims_rep)
    return {
        "planLint": {"ok": not lint_rep.errors, "errors": lint_rep.errors,
                     "warnings": lint_rep.warnings},
        "hookContract": {"scope": resolve_scope(target),
                         "ok": not hook_rep.errors, "errors": hook_rep.errors,
                         "warnings": hook_rep.warnings},
        "claimsContract": {"ok": not claims_rep.errors,
                           "errors": claims_rep.errors,
                           "warnings": claims_rep.warnings},
    }


def build_packet(plan_path: str, transcripts_dir: str, manifest_path: str) -> dict:
    """Build the full packet dict for one review round (pure of the out path)."""
    plan_bound = _bound_json(plan_path, "edit plan")
    manifest_bound = _bound_json(manifest_path, "asset manifest")
    plan = plan_bound["content"]
    if not isinstance(plan, dict) or not isinstance(manifest_bound["content"], dict):
        raise ValueError("plan and manifest must be JSON objects")
    tmap = compile_plan(plan)
    evidence = _transcript_evidence(plan, transcripts_dir,
                                    manifest_bound["content"], tmap)
    # The lint copy carries the render.py `_path` convention (plan_lint_broll
    # resolves relative asset paths against it); the PACKET binds exact file
    # bytes only, so the absolute path never enters the hashed content.
    manifest_lint = copy.deepcopy(manifest_bound["content"])
    manifest_lint.setdefault("_path", os.path.abspath(manifest_path))
    from graphics_planner import output_words  # local: heavy import (gate-CLI convention)
    words = output_words(plan, transcripts_dir, manifest_lint)
    gates = _gate_verdicts(plan, manifest_lint, words)
    core = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": PACKET_KIND,
        "stage": "plan",
        "plan": plan_bound,
        "manifest": manifest_bound,
        "gates": gates,
        "gateDigest": _digest(gates),
        "timeline": {"outputDuration": round(tmap.output_duration, 4),
                     "segments": _segment_rows(plan, tmap)},
        # pacing._cli_report IS what `planner/pacing.py <plan>` prints —
        # reused verbatim so the packet's pacing block can never drift.
        "pacing": pacing._cli_report(plan),
        "transcriptEvidence": evidence,
    }
    return {**core, "contentDigest": _digest(core)}


def main() -> int:
    """CLI: build the packet, write it, print the status/digest line."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plan")
    ap.add_argument("transcripts_dir")
    ap.add_argument("manifest")
    ap.add_argument("--out", required=True, help="packet JSON destination")
    args = ap.parse_args()
    try:
        packet = build_packet(args.plan, args.transcripts_dir, args.manifest)
        with open(args.out, "w") as fh:
            json.dump(packet, fh, indent=2)
            fh.write("\n")
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps({
        "status": "done",
        "path": os.path.abspath(args.out),
        "contentDigest": packet["contentDigest"],
        "planHash": packet["plan"]["byteHash"],
        "manifestHash": packet["manifest"]["byteHash"],
        "gatesOk": all(v.get("ok") for v in packet["gates"].values()),
        "segments": len(packet["timeline"]["segments"]),
        "keptWords": len(packet["transcriptEvidence"]["keptWords"]),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
