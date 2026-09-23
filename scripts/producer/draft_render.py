#!/usr/bin/env python3
"""Render an explicitly admitted, watermarked draft before independent review.

Mint with ``mint-delivery-approval.ts <producer_dir> --draft`` first. The shared
renderer validates separate draft readiness, writes only inside producer/draft,
burns the DRAFT watermark, and removes the unwatermarked final and provenance.
This wrapper consumes only the draft receipt, including on failure. Final
readiness and existing independent review evidence remain separate.

CLI: draft_render.py <edit_plan.json> <asset_manifest.json> <producer_dir>
                     [--audit] [--font FILE]
A draft is not final QC or editorial approval. Long full drafts can be expensive;
prefer small representative/changed-region previews from existing renderers.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional

from ingest_probe import probe_media
from producer_config import DRAFT
from stage_timing_context import timing_environment

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "assets", "fonts"))
APPROVAL_SIDECAR = ".sniper-qc-approved.json"
DELIVERY_RECEIPT = ".sniper-draft-ready.json"
DRAFT_NAME = "draft.mp4"
INTERMEDIATE_NAME = "final.mp4"


def emit(**fields) -> None:
    """Emit one JSON status line on stdout (NDJSON, like the sibling CLIs)."""
    print(json.dumps(fields), flush=True)


@dataclass(frozen=True)
class DraftJob:
    """One draft run (keeps every function ≤4 params)."""

    plan_path: str
    manifest_path: str
    producer_dir: str
    audit: bool = False
    fontfile: Optional[str] = None

    @property
    def draft_dir(self) -> str:
        """The draft output dir — always ``<producer_dir>/draft/``."""
        return os.path.join(self.producer_dir, "draft")


def resolve_font(override: Optional[str]) -> str:
    """Absolute watermark fontfile: explicit ``--font`` wins, else the repo font.

    Args:
        override: Operator-supplied font path, or None for the vendored default.

    Returns:
        Absolute path to an existing font file.

    Raises:
        RuntimeError: If the resolved font file does not exist (fail loud —
            a silent fontconfig fallback could render an empty watermark).
    """
    path = override or os.path.join(FONTS_DIR, DRAFT["fontfile"])
    if not os.path.isfile(path):
        raise RuntimeError(f"watermark font not found: {path} (pass --font)")
    return os.path.abspath(path)


def _escape_filter_value(value: str) -> str:
    """Escape a value for use inside an ffmpeg filter option (path-safe)."""
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def build_watermark_cmd(src: str, dst: str, dims: "tuple[int, int]",
                        fontfile: str) -> "list[str]":
    """The single-pass DRAFT burn command (pure — unit-testable).

    Two drawtext layers on every frame: a large translucent centered "DRAFT"
    and a solid top-right "DRAFT - NOT FINAL" badge. Video re-encodes once at
    ``DRAFT['preset']``/``DRAFT['crf']``; the mastered audio is stream-copied.

    Args:
        src: The unwatermarked rendered intermediate.
        dst: The watermarked output (must be the draft name, never final.mp4).
        dims: (width, height) of the source video in display pixels.
        fontfile: Absolute path to the watermark font.

    Returns:
        The full ffmpeg argv list.

    Raises:
        ValueError: If ``dst`` is not named ``draft.mp4`` — the non-final name
            is a design invariant, not a convention.
    """
    if os.path.basename(dst) != DRAFT_NAME:
        raise ValueError(f"draft output must be named {DRAFT_NAME}, got {dst}")
    _w, h = dims
    center = max(24, int(h * DRAFT["center_frac"]))
    corner = max(12, int(h * DRAFT["corner_frac"]))
    margin = max(8, int(h * DRAFT["corner_margin_frac"]))
    font = _escape_filter_value(fontfile)
    alpha = DRAFT["center_alpha"]
    filters = ",".join([
        f"drawtext=fontfile={font}:text=DRAFT:fontsize={center}"
        f":fontcolor=white@{alpha}:borderw={max(2, center // 24)}"
        f":bordercolor=black@{alpha}:x=(w-text_w)/2:y=(h-text_h)/2",
        f"drawtext=fontfile={font}:text=DRAFT - NOT FINAL:fontsize={corner}"
        f":fontcolor=white:box=1:boxcolor=black@{DRAFT['corner_box_alpha']}"
        f":boxborderw={max(4, margin // 2)}:x=w-text_w-{margin}:y={margin}",
    ])
    return ["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", filters,
            "-c:v", "libx264", "-preset", DRAFT["preset"],
            "-crf", str(DRAFT["crf"]), "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-c:a", "copy", dst]


def assert_no_approval_sidecar(draft_dir: str) -> None:
    """The draft-dir invariant: it must NEVER contain a QC approval sidecar.

    Args:
        draft_dir: The ``<producer_dir>/draft`` directory (may not exist yet).

    Raises:
        RuntimeError: If ``.sniper-qc-approved.json`` is present — a draft must
            never carry (or sit next to) an approval; remove it and re-run.
    """
    path = os.path.join(draft_dir, APPROVAL_SIDECAR)
    if os.path.exists(path):
        raise RuntimeError(
            f"{APPROVAL_SIDECAR} found in draft dir — a draft is never "
            f"approved; remove {path} and re-run")


def scrub_intermediates(draft_dir: str) -> None:
    """Delete the unwatermarked master + its provenance from the draft dir.

    Refuses to delete anything unless the watermarked ``draft.mp4`` exists —
    a failed burn must leave the evidence in place for diagnosis, not silently
    discard the render.

    Args:
        draft_dir: The draft output directory.

    Raises:
        RuntimeError: If ``draft.mp4`` is missing.
    """
    if not os.path.isfile(os.path.join(draft_dir, DRAFT_NAME)):
        raise RuntimeError(
            f"{DRAFT_NAME} missing — refusing to delete the unwatermarked "
            "intermediate (nothing watchable would remain)")
    for name in (INTERMEDIATE_NAME, INTERMEDIATE_NAME + ".assembled.json"):
        path = os.path.join(draft_dir, name)
        if os.path.exists(path):
            os.remove(path)
            emit(status="draft_scrubbed", removed=name)


def run_base_render(job: DraftJob) -> None:
    """Subprocess render.py into the draft dir, streaming its NDJSON through.

    ``--draft-only`` validates separate draft readiness and makes watermarking
    mandatory even for direct renderer calls. Audit B is optional for drafts.

    Args:
        job: The draft run parameters.

    Raises:
        RuntimeError: If render.py exits non-zero.
    """
    cmd = [sys.executable, os.path.join(SCRIPT_DIR, "render.py"),
           job.plan_path, job.manifest_path, job.draft_dir,
           "--approval-dir", job.producer_dir, "--draft-only"]
    if job.fontfile:
        cmd.extend(["--draft-font", job.fontfile])
    if not job.audit:
        cmd.append("--no-audit")
    emit(status="stage_start", stage="draft_base_render", out=job.draft_dir)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True,
                            env=timing_environment())
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
    if proc.wait() != 0:
        raise RuntimeError("draft base render failed (render.py exited "
                           f"{proc.returncode}; see NDJSON above)")


def burn_watermark(job: DraftJob) -> str:
    """Burn the DRAFT watermark into ``draft.mp4`` (single fast ffmpeg pass).

    Args:
        job: The draft run parameters.

    Returns:
        Absolute path to the watermarked ``draft.mp4``.

    Raises:
        RuntimeError: If the intermediate is missing, unprobeable, or the
            ffmpeg pass fails.
    """
    src = os.path.join(job.draft_dir, INTERMEDIATE_NAME)
    if not os.path.isfile(src):
        raise RuntimeError(f"render produced no {INTERMEDIATE_NAME} in "
                           f"{job.draft_dir}")
    probe = probe_media(src)
    if probe.width is None or probe.height is None:
        raise RuntimeError(f"cannot probe draft intermediate dimensions: {src}")
    dst = os.path.join(job.draft_dir, DRAFT_NAME)
    cmd = build_watermark_cmd(src, dst, (probe.width, probe.height),
                              resolve_font(job.fontfile))
    emit(status="stage_start", stage="draft_watermark", out=dst)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.isfile(dst):
        raise RuntimeError("draft watermark pass failed: "
                           + (proc.stderr or "")[-400:])
    return os.path.abspath(dst)


def revoke_delivery_receipt(producer_dir: str) -> None:
    """Consume only draft admission; preserve final readiness and review evidence.

    Args:
        producer_dir: The producer directory owning the draft receipt.
    """
    path = os.path.join(producer_dir, DELIVERY_RECEIPT)
    if os.path.exists(path):
        os.remove(path)
        emit(status="draft_receipt_revoked", path=path,
             note="draft admission consumed; final rendering requires current independent review")


def run_draft(job: DraftJob) -> str:
    """The full draft flow: render → burn → scrub → invariant check.

    Args:
        job: The draft run parameters.

    Returns:
        Absolute path to the finished ``draft.mp4``.
    """
    assert_no_approval_sidecar(job.draft_dir)
    run_base_render(job)
    dst = os.path.join(job.draft_dir, DRAFT_NAME)
    if not os.path.isfile(dst):
        raise RuntimeError("Draft-only renderer did not publish its watermarked output")
    assert_no_approval_sidecar(job.draft_dir)
    return dst


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Pre-review-wall watchable DRAFT (watermarked, unshippable)")
    ap.add_argument("plan_path")
    ap.add_argument("manifest_path")
    ap.add_argument("producer_dir",
                    help="producer dir owning the delivery approval; the draft "
                         "lands in <producer_dir>/draft/draft.mp4")
    ap.add_argument("--audit", action="store_true",
                    help="also run Audit B on the draft base (default: skipped "
                         "— the draft is pre-wall and never ships)")
    ap.add_argument("--font", default=None,
                    help="watermark fontfile override (default: repo "
                         "assets/fonts/" + DRAFT["fontfile"] + ")")
    args = ap.parse_args()
    job = DraftJob(plan_path=args.plan_path, manifest_path=args.manifest_path,
                   producer_dir=os.path.abspath(args.producer_dir),
                   audit=args.audit, fontfile=args.font)
    started = time.monotonic()
    try:
        dst = run_draft(job)
        emit(status="draft_ready", path=dst, shippable=False,
             watermark="burned", ms=int((time.monotonic() - started) * 1000))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        emit(error=str(exc))
        sys.exit(1)
    finally:
        # Success or failure consumes only the separate draft admission.
        revoke_delivery_receipt(job.producer_dir)


if __name__ == "__main__":
    main()
