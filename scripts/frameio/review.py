"""FRAME.IO REVIEW orchestrator.

Two entry modes, one pipeline:
  • CLI       human progress, writes results.json + report.html, asks before a
              big run.  python -m scripts.frameio.review --input clip.mp4
  • --server  emits one JSON event per line to stdout for the Next.js tab to
              stream (the FRAME.IO REVIEW SSE route forwards these as-is).

Pipeline: extract (ffmpeg) → dedup (pHash) → estimate/confirm → analyze
(Claude vision, concurrent) → aggregate → write results.json + report.html.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from rapidfuzz import fuzz as rf_fuzz

# Allow both `python -m scripts.frameio.review` and `python scripts/frameio/review.py`.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from frameio.extract import extract_frames                 # type: ignore
    from frameio.dedup import dedup_frames, KeptFrame          # type: ignore
    from frameio import ocr_dedup                              # type: ignore
    from frameio import claude_client                          # type: ignore
    from frameio.util import log                               # type: ignore
else:
    from .extract import extract_frames
    from .dedup import dedup_frames, KeptFrame
    from . import ocr_dedup
    from . import claude_client
    from .util import log

TMP_ROOT = tempfile.gettempdir()
CACHE_TTL_SECONDS = 60 * 60  # frameio frame dirs older than 1h are swept at start
CONFIRM_THRESHOLD_DEFAULT = 200
VERDICT_FUZZ = 90  # token_set_ratio to collapse consecutive same-text verdicts

# Approximate list prices ($ per 1M tokens) for the rough pre-send estimate only —
# NOT billing. (input, output). Unknown models fall back to the Sonnet rate.
_PRICE_PER_MTOK = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
# Rough per-frame token cost: one ~1080p JPEG (~1.6k) + prompt/tool (~0.3k) in, short tool call out.
_EST_INPUT_TOKENS = 1900
_EST_OUTPUT_TOKENS = 150


def _estimate_cost(n: int, model: str) -> float:
    """Rough USD estimate for ``n`` single-frame vision calls. Approximate."""
    p_in, p_out = _PRICE_PER_MTOK.get(model, _PRICE_PER_MTOK["claude-sonnet-4-6"])
    per_call = (_EST_INPUT_TOKENS / 1e6) * p_in + (_EST_OUTPUT_TOKENS / 1e6) * p_out
    return n * per_call


# Phrases the model uses in `note` when it's describing text it itself judged to be
# cut off / still animating — a "missing" letter there is cropping, not a real typo.
_TRUNCATION_HINTS = (
    "cut off", "cut-off", "cutoff", "incomplete", "truncat", "mid-animation",
    "mid animation", "partially", "not visible", "off-screen", "off screen",
    "edge of the frame", "right edge", "left edge",
)


def _clean_errors(errors: list[dict]) -> list[dict]:
    """Deterministic per-frame cleanup before flags are emitted/aggregated.

    - Drop no-op flags where the "fix" is identical to the text seen (model
      reported an error it didn't actually change). Exact compare after strip —
      NOT normalized — so real spacing/punctuation fixes (©2025→© 2025) survive.
    - Downgrade to low confidence any flag whose own note says the text is cut
      off / incomplete / mid-animation (cropped renders aren't typos); low-conf
      hits are hidden by the default Hide-low filter.
    """
    out: list[dict] = []
    for e in errors:
        seen = (e.get("exact_text_seen") or "").strip()
        fix = (e.get("suggested_fix") or "").strip()
        if seen == fix:
            continue
        note = (e.get("note") or "").lower()
        if e.get("confidence") != "low" and any(h in note for h in _TRUNCATION_HINTS):
            e = {**e, "confidence": "low"}
        out.append(e)
    return out


_CONF_RANK = {"high": 0, "medium": 1, "low": 2}


def _verdict_dedup(flags: list[dict], fuzz: int = VERDICT_FUZZ) -> list[dict]:
    """Collapse consecutive flags whose ``exact_text_seen`` is fuzzy-equal.

    Uses the judge's own transcription (reliable, unlike tesseract) to fold
    fade-variants and repeated slides into one finding. The kept verdict widens
    its visible span to cover the group and keeps the highest-confidence wording.
    """
    out: list[dict] = []
    for f in sorted(flags, key=lambda x: x["timestamp"]):
        if out:
            prev = out[-1]
            if rf_fuzz.token_set_ratio(f["exact_text_seen"], prev["exact_text_seen"]) >= fuzz:
                prev["t_end"] = max(prev["t_end"], f["t_end"])
                prev["merged_count"] = prev.get("merged_count", 1) + 1
                if _CONF_RANK.get(f["confidence"], 2) < _CONF_RANK.get(prev["confidence"], 2):
                    # Adopt the higher-confidence variant wholesale so the kept
                    # finding stays internally consistent (text, fix, type, note).
                    prev["confidence"] = f["confidence"]
                    prev["exact_text_seen"] = f["exact_text_seen"]
                    prev["suggested_fix"] = f["suggested_fix"]
                    prev["error_type"] = f["error_type"]
                    prev["note"] = f["note"]
                continue
        nf = dict(f)
        nf.setdefault("merged_count", 1)
        out.append(nf)
    return out


class Emitter:
    """Routes progress to NDJSON (server) or human text (CLI)."""

    def __init__(self, server: bool):
        self.server = server

    def event(self, type_: str, **data) -> None:
        if self.server:
            print(json.dumps({"event": type_, **data}), flush=True)
        else:
            self._human(type_, data)

    def _human(self, type_: str, data: dict) -> None:
        if type_ == "extract_progress":
            print(f"\r  extracting frames… {data['done']}/{data['total']}", end="", flush=True)
        elif type_ == "extracted":
            print(f"\r  extracted {data['frames']} frame(s)            ")
        elif type_ == "dedup":
            crit = (f"fuzz ≥ {data['fuzz']}" if data.get("mode") == "ocr"
                    else f"hamming ≤ {data['threshold']}")
            print(f"  select [{data.get('mode', 'visual')}]: {data['extracted']} → "
                  f"{data['kept']} representative(s) ({crit})")
        elif type_ == "estimate":
            print(f"  estimated API calls after dedup: {data['api_calls']}")
        elif type_ == "analyze_progress":
            print(f"\r  analyzing… {data['done']}/{data['total']} "
                  f"({data['flags']} flag(s) so far)", end="", flush=True)
        elif type_ == "done":
            print(f"\r  analyzed {data['frames_analyzed']} frame(s); "
                  f"{data['flag_count']} flag(s)                 ")


def _cache_dir(input_path: str, fps: float) -> str:
    """Deterministic frames dir keyed by input identity + fps, so a re-run
    (e.g. 'proceed anyway' after the >threshold prompt) reuses extracted frames."""
    try:
        mtime = os.path.getmtime(input_path)
        size = os.path.getsize(input_path)
    except OSError:
        mtime = size = 0
    key = f"{os.path.abspath(input_path)}|{size}|{mtime}|{fps}"
    token = hashlib.sha1(key.encode()).hexdigest()[:16]
    return os.path.join(TMP_ROOT, f"frameio-{token}")


def _sweep_stale() -> None:
    """Remove frameio frame dirs older than the TTL (producer owns its temps)."""
    now = time.time()
    try:
        for name in os.listdir(TMP_ROOT):
            if not name.startswith("frameio-"):
                continue
            p = os.path.join(TMP_ROOT, name)
            try:
                if os.path.isdir(p) and (now - os.path.getmtime(p)) > CACHE_TTL_SECONDS:
                    shutil.rmtree(p, ignore_errors=True)
                    log("sweep", f"removed stale {name}")
            except OSError:
                pass
    except OSError:
        pass


def _flags_from(kept: list[KeptFrame], per_frame: dict[int, "claude_client.FrameErrors"]) -> list[dict]:
    """Flatten per-frame error lists into one sortable flag row per error."""
    flags: list[dict] = []
    for k in kept:
        res = per_frame.get(k.index)
        if not res:
            continue
        for err in res.errors:
            flags.append({
                "timestamp": k.t_start,
                "t_start": k.t_start,
                "t_end": k.t_end,
                "thumb": k.path,
                "exact_text_seen": err.get("exact_text_seen", ""),
                "error_type": err.get("error_type", ""),
                "suggested_fix": err.get("suggested_fix", ""),
                "confidence": err.get("confidence", "low"),
                "note": err.get("note", ""),
            })
    flags.sort(key=lambda f: f["timestamp"])
    return flags


def _rep_tag(k: "KeptFrame") -> str:
    if k.is_blank:
        return "[blank]"
    if k.empty_kept:
        return "[empty-kept]"
    return ""


def emit_select_report(em: "Emitter", args: argparse.Namespace,
                       frames: list, kept: list["KeptFrame"]) -> None:
    """Phase-1 report: total_frames → runs → representatives, one row per run.

    CLI prints a table; --server emits a single ``select_report`` event with the
    same per-run rows so the tab can render it. No Claude call happens after this.
    """
    if em.server:
        em.event("select_report", mode=args.mode, fuzz=args.fuzz,
                 total_frames=len(frames), runs=len(kept),
                 items=[{
                     "index": k.index, "t_start": k.t_start, "t_end": k.t_end,
                     "frame_count": k.duplicates + 1, "raw_text": k.raw_text,
                     "is_blank": k.is_blank, "empty_kept": k.empty_kept,
                 } for k in kept])
        return

    blanks = sum(1 for k in kept if k.is_blank)
    empty_kept = sum(1 for k in kept if k.empty_kept)
    print(f"\nmode={args.mode}  fuzz={args.fuzz}  "
          f"total_frames={len(frames)} → runs={len(kept)} → representatives={len(kept)}"
          f"  ({blanks} blank, {empty_kept} empty-kept)\n")
    print(f"{'RUN':>4}  {'T_START':>8}  {'T_END':>8}  {'FRAMES':>6}  REP TEXT")
    for i, k in enumerate(kept, 1):
        text = " ".join(k.raw_text.split())
        tag = _rep_tag(k)
        if tag:
            text = f"{tag} {text}".strip()
        if len(text) > 88:
            text = text[:87] + "…"
        print(f"{i:>4}  {k.t_start:>8.1f}  {k.t_end:>8.1f}  {k.duplicates + 1:>6}  {text}")
    print()


def run(args: argparse.Namespace) -> int:
    em = Emitter(args.server)
    input_path = os.path.abspath(args.input)
    if not os.path.isfile(input_path):
        em.event("error", message=f"Input not found: {input_path}")
        return 2

    log("run",
        f"input={input_path} fps={args.fps} hamming={args.hamming} "
        f"model={args.model} workers={args.workers} server={args.server} yes={args.yes}")
    t0 = time.time()

    _sweep_stale()
    frames_dir = _cache_dir(input_path, args.fps)
    log("run", f"frames dir = {frames_dir}")

    # 1) Extract --------------------------------------------------------------
    em.event("extract_start", input=input_path, fps=args.fps, max_frames=args.max_frames)
    frames = extract_frames(
        input_path, frames_dir, fps=args.fps, max_frames=args.max_frames,
        on_progress=lambda d, t: em.event("extract_progress", done=d, total=t),
    )
    em.event("extracted", frames=len(frames))
    if not frames:
        em.event("error", message="No frames were extracted (bad input or fps?).")
        return 2

    # 2) Select representatives (OCR-text runs, or legacy visual/pHash) --------
    if args.mode == "ocr":
        kept = ocr_dedup.select_representatives(frames, fuzz=args.fuzz, workers=args.workers)
    else:
        kept = dedup_frames(frames, threshold=args.hamming)
    em.event("dedup", mode=args.mode, extracted=len(frames), kept=len(kept),
             threshold=args.hamming, fuzz=args.fuzz)
    em.event("frames", items=[
        {"index": k.index, "t_start": k.t_start, "t_end": k.t_end,
         "thumb": k.path, "duplicates": k.duplicates}
        for k in kept
    ])

    # 2b) Phase-1 hard stop: report the run table, never touch Claude ---------
    if args.select_only:
        emit_select_report(em, args, frames, kept)
        return 0

    # 3) Cap + estimate + confirm ---------------------------------------------
    # Skip true-blank reps (ocr mode only); take the first --max-reps by time.
    eligible = [k for k in kept if not k.is_blank]
    blanks_skipped = len(kept) - len(eligible)
    to_send = eligible[: args.max_reps] if args.max_reps is not None else eligible
    n = len(to_send)
    est_cost = _estimate_cost(n, args.model)
    em.event("estimate", api_calls=n, representatives=len(kept),
             eligible=len(eligible), blanks_skipped=blanks_skipped,
             capped=n, est_cost_usd=round(est_cost, 4))
    if not args.server:
        cap_note = f" (capped from {len(eligible)} by --max-reps {args.max_reps})" \
            if args.max_reps and len(eligible) > args.max_reps else ""
        print(f"\n  representatives: {len(kept)}"
              + (f", {blanks_skipped} blank skipped" if blanks_skipped else ""))
        print(f"  sending {n} frame(s) to {args.model}{cap_note}")
        print(f"  rough cost estimate: ≈ ${est_cost:.3f}  (approx; ~{_EST_INPUT_TOKENS}"
              f" in + {_EST_OUTPUT_TOKENS} out tokens/frame)\n")
    if n > args.confirm_threshold and not args.yes:
        if args.server:
            # UI shows the estimate + thumbnails, then re-invokes with --yes
            # (extraction reuses the cached frames dir, so no rework).
            em.event("needs_confirm", api_calls=n, threshold=args.confirm_threshold)
            return 0
        print(f"  ⚠ This will make {n} API calls (> {args.confirm_threshold}).")
        if input("  Proceed? [y/N] ").strip().lower() not in ("y", "yes"):
            print("  Aborted.")
            return 0

    # 4) Analyze (concurrent) -------------------------------------------------
    try:
        client = claude_client.make_client()
    except RuntimeError as e:
        em.event("error", message=str(e))
        return 2

    log("analyze", f"sending {n} frame(s) to {args.model} ({args.workers} concurrent)")
    t_analyze = time.time()
    per_frame: dict[int, claude_client.FrameErrors] = {}
    done = 0
    flag_count = 0
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(claude_client.analyze_frame, client, k.path, args.model): k
            for k in to_send
        }
        for fut in as_completed(futures):
            k = futures[fut]
            res = fut.result()
            if res.ok:
                res.errors = _clean_errors(res.errors)  # drop no-ops, bury cut-off → low
            per_frame[k.index] = res
            done += 1
            if not res.ok:
                failures += 1
                log("analyze", f"[{done}/{n}] frame@{k.t_start}s FAILED: {res.error_message}")
            elif res.errors:
                flag_count += len(res.errors)
                log("analyze", f"[{done}/{n}] frame@{k.t_start}s → {len(res.errors)} error(s)")
                em.event(
                    "flag", timestamp=k.t_start, t_start=k.t_start, t_end=k.t_end,
                    thumb=k.path, errors=res.errors,
                )
            else:
                log("analyze", f"[{done}/{n}] frame@{k.t_start}s → clean")
            em.event("analyze_progress", done=done, total=n, flags=flag_count)
    log("analyze", f"done in {time.time() - t_analyze:.1f}s — "
        f"{flag_count} flag(s), {failures} failure(s)")

    # 5) Verdict-dedup + aggregate + write ------------------------------------
    raw_flags = _flags_from(to_send, per_frame)
    flags = _verdict_dedup(raw_flags)
    if not args.server:
        print(f"\n  verdict-dedup: {len(raw_flags)} → {len(flags)} finding(s) "
              f"(token_set_ratio ≥ {VERDICT_FUZZ})")
        for fl in flags:
            span = f"{fl['t_start']:.0f}–{fl['t_end']:.0f}s" if fl["t_end"] > fl["t_start"] \
                else f"{fl['timestamp']:.0f}s"
            mult = f" ×{fl['merged_count']}" if fl.get("merged_count", 1) > 1 else ""
            print(f"   @{span} [{fl['confidence']}] {fl['error_type']}{mult}: "
                  f"\"{fl['exact_text_seen']}\" → \"{fl['suggested_fix']}\"")
        flagged_reps = sum(1 for k in to_send
                           if per_frame.get(k.index) and per_frame[k.index].errors)
        print(f"\n  reps sent: {n}  ·  flagged: {flagged_reps}  ·  clean: {n - flagged_reps - failures}"
              f"  ·  raw flags: {len(raw_flags)} → {len(flags)} after dedup"
              f"  ·  est spend ≈ ${est_cost:.3f}\n")
    report = {
        "input": input_path,
        "model": args.model,
        "mode": args.mode,
        "fps": args.fps,
        "hamming": args.hamming,
        "fuzz": args.fuzz,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "frames_extracted": len(frames),
        "representatives": len(kept),
        "blanks_skipped": blanks_skipped,
        "frames_analyzed": n,
        "frame_failures": failures,
        "flag_count_raw": len(raw_flags),
        "flag_count": len(flags),
        "est_cost_usd": round(est_cost, 4),
        "flags": flags,
    }

    out_dir = os.path.abspath(args.out_dir) if args.out_dir else os.path.dirname(input_path)
    os.makedirs(out_dir, exist_ok=True)
    results_path = os.path.join(out_dir, "results.json")
    report_path = os.path.join(out_dir, "report.html")
    with open(results_path, "w") as f:
        json.dump(report, f, indent=2)
    with open(report_path, "w") as f:
        f.write(build_report_html(report))

    log("run", f"complete in {time.time() - t0:.1f}s — wrote {results_path} + {report_path}")
    em.event(
        "done",
        frames_analyzed=n, flag_count=len(flags), frame_failures=failures,
        results_path=results_path, report_path=report_path, flags=flags,
        frames_dir=frames_dir,
    )
    return 0


def build_report_html(report: dict) -> str:
    """Standalone HTML report — thumbnails inlined as base64 so it opens with no server."""
    rows = []
    for i, fl in enumerate(report["flags"]):
        thumb_b64 = ""
        try:
            with open(fl["thumb"], "rb") as f:
                thumb_b64 = base64.standard_b64encode(f.read()).decode("ascii")
        except OSError:
            pass
        rows.append({
            "i": i,
            "timestamp": fl["timestamp"],
            "t_start": fl["t_start"],
            "t_end": fl["t_end"],
            "thumb": f"data:image/jpeg;base64,{thumb_b64}" if thumb_b64 else "",
            "exact_text_seen": fl["exact_text_seen"],
            "error_type": fl["error_type"],
            "suggested_fix": fl["suggested_fix"],
            "confidence": fl["confidence"],
            "note": fl["note"],
        })
    data_json = json.dumps(rows)
    meta = html.escape(
        f'{os.path.basename(report["input"])} · {report["frames_analyzed"]} frames analyzed · '
        f'{report["flag_count"]} flag(s) · model {report["model"]}'
    )
    return _REPORT_TEMPLATE.replace("__META__", meta).replace("__DATA__", data_json)


_REPORT_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FRAME.IO REVIEW — report</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto;
         background:#0c0e14; color:#e6e8ee; padding:32px; }
  h1 { font-size:18px; letter-spacing:.04em; margin:0 0 4px; }
  .meta { color:#8b90a0; margin-bottom:20px; }
  .controls { margin-bottom:16px; display:flex; gap:16px; align-items:center; flex-wrap:wrap; }
  label { color:#b8bdcc; font-size:13px; }
  table { border-collapse:collapse; width:100%; }
  th,td { text-align:left; padding:10px 12px; border-bottom:1px solid #1d212c; vertical-align:top; }
  th { color:#8b90a0; font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.05em; }
  img { width:160px; border-radius:6px; border:1px solid #1d212c; display:block; }
  code { background:#161a24; padding:2px 6px; border-radius:4px; }
  .ts { font-variant-numeric:tabular-nums; color:#7fd1ff; white-space:nowrap; }
  .badge { font-size:11px; padding:2px 8px; border-radius:999px; text-transform:uppercase; letter-spacing:.04em; }
  .high { background:#3a1620; color:#ff8da3; } .medium { background:#3a2e16; color:#ffd27f; }
  .low { background:#1d2330; color:#9aa3b8; }
  .fix { color:#7fe0a8; }
  .empty { color:#8b90a0; padding:40px 0; }
</style></head><body>
<h1>FRAME.IO REVIEW</h1>
<div class="meta">__META__</div>
<div class="controls">
  <label><input type="checkbox" id="hideLow" checked> Hide low confidence</label>
  <label>Sort:
    <select id="sort">
      <option value="timestamp">Timestamp</option>
      <option value="confidence">Confidence</option>
      <option value="error_type">Error type</option>
    </select>
  </label>
  <span id="count" class="meta"></span>
</div>
<table><thead><tr>
  <th>Time</th><th>Frame</th><th>Text seen</th><th>Type</th><th>Suggested fix</th><th>Conf.</th><th>Note</th>
</tr></thead><tbody id="rows"></tbody></table>
<div id="empty" class="empty" style="display:none">No flags match the current filter.</div>
<script>
const DATA = __DATA__;
const RANK = { high:0, medium:1, low:2 };
const tbody = document.getElementById('rows');
const esc = s => (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const fmt = s => { s=Math.floor(s); return Math.floor(s/60)+':'+String(s%60).padStart(2,'0'); };
function render() {
  const hideLow = document.getElementById('hideLow').checked;
  const sort = document.getElementById('sort').value;
  let rows = DATA.filter(d => !(hideLow && d.confidence === 'low'));
  rows.sort((a,b) => sort==='confidence' ? RANK[a.confidence]-RANK[b.confidence]
    : sort==='error_type' ? (a.error_type||'').localeCompare(b.error_type||'')
    : a.timestamp-b.timestamp);
  tbody.innerHTML = rows.map(d => `<tr>
    <td class="ts">${fmt(d.timestamp)}${d.t_end>d.t_start?'–'+fmt(d.t_end):''}<br><span class="meta">${d.timestamp.toFixed(1)}s</span></td>
    <td>${d.thumb?`<img src="${d.thumb}">`:''}</td>
    <td><code>${esc(d.exact_text_seen)}</code></td>
    <td>${esc(d.error_type)}</td>
    <td class="fix">${esc(d.suggested_fix)}</td>
    <td><span class="badge ${d.confidence}">${esc(d.confidence)}</span></td>
    <td class="meta">${esc(d.note)}</td></tr>`).join('');
  document.getElementById('empty').style.display = rows.length ? 'none' : 'block';
  document.getElementById('count').textContent = rows.length + ' of ' + DATA.length + ' flag(s)';
}
document.getElementById('hideLow').onchange = render;
document.getElementById('sort').onchange = render;
render();
</script></body></html>"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scan an MP4 for on-screen text errors.")
    p.add_argument("--input", required=True, help="Path to a local .mp4")
    p.add_argument("--fps", type=float, default=1.0, help="Frames per second to extract (default 1)")
    p.add_argument("--max-frames", type=int, default=None, help="Cap extracted frames (cheap test runs)")
    p.add_argument("--mode", choices=("ocr", "visual"), default="visual",
                   help="Representative selection: visual (pHash settled-frame, default) "
                        "or ocr (tesseract text — for clean slideware)")
    p.add_argument("--fuzz", type=int, default=90,
                   help="OCR-mode token_set_ratio threshold to group frames (default 90)")
    p.add_argument("--hamming", type=int, default=5, help="visual-mode pHash Hamming dedup threshold (default 5)")
    p.add_argument("--select-only", action="store_true",
                   help="Phase-1 hard stop: print the run table and exit before any Claude call")
    p.add_argument("--max-reps", type=int, default=None,
                   help="Cap representatives sent to Claude (e.g. 15 for a cheap test run; default none)")
    p.add_argument("--model", default=claude_client.MODEL,
                   help=f"Anthropic model (default {claude_client.MODEL}; e.g. claude-haiku-4-5)")
    p.add_argument("--workers", type=int, default=5, help="Concurrent API calls (default 5)")
    p.add_argument("--confirm-threshold", type=int, default=CONFIRM_THRESHOLD_DEFAULT,
                   help="Prompt/abort if API calls exceed this (default 200)")
    p.add_argument("--out-dir", default=None, help="Where to write results.json + report.html")
    p.add_argument("--yes", action="store_true", help="Skip the >threshold confirmation")
    p.add_argument("--server", action="store_true", help="Emit NDJSON events for the Next.js tab")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
