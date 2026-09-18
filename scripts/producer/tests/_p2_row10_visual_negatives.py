#!/usr/bin/env python3
"""Alter the selected real candidate and run the production visual observer."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import replace

from edit.cut_repair_candidate_qc_contract import load_candidate_authority
from edit.cut_repair_candidate_qc_tools import load_qc_tools
from edit.cut_repair_candidate_qc_types import QcRun
from edit.cut_repair_candidate_qc_visual import visual_observation
from edit.cut_repair_context_sources import stable_file_digest


def _run(command: list[str]) -> None:
    result = subprocess.run(
        command, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[-1000:])


def _variant(run: QcRun, root: str, mode: str) -> str:
    output = os.path.join(root, f"{mode}-candidate.mov")
    ffmpeg = run.tools.ffmpeg.path
    base = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", run.authority.candidate_path,
    ]
    if mode == "delayed":
        samples = run.authority.total_frames * 1600
        command = [
            *base, "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
            "-af", f"adelay=100:all=1,apad,atrim=end_sample={samples}",
            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
            "-frames:v", str(run.authority.total_frames), "-y", output,
        ]
    else:
        selected = run.authority.alternate_take_selection or {}
        frames = selected.get("outputFrameRange", {})
        start = frames.get("firstFrame")
        end = frames.get("endFrameExclusive")
        video = (
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:"
            f"enable='between(n\\,{start}\\,{end - 1})'")
        command = [
            *base, "-map", "0:v:0", "-map", "0:a:0", "-vf", video,
            "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p",
            "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
            "-frames:v", str(run.authority.total_frames), "-y", output,
        ]
    _run(command)
    return output


def _blocked(run: QcRun, root: str, mode: str) -> dict:
    path = _variant(run, root, mode)
    value_hash = stable_file_digest(path, f"{mode} candidate")
    authority = replace(
        run.authority, candidate_path=path, candidate_sha256=value_hash)
    observed = visual_observation(replace(run, authority=authority))
    blocker = observed.get("blocker")
    if observed.get("status") != "blocked" or not isinstance(blocker, dict):
        raise AssertionError(f"{mode} candidate unexpectedly passed")
    return {"candidateSha256": value_hash, "code": blocker.get("code")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("producer_dir")
    parser.add_argument("preparation_hash")
    parser.add_argument("tool_manifest_path")
    args = parser.parse_args()
    authority = load_candidate_authority(
        os.path.abspath(args.producer_dir), args.preparation_hash)
    tools = load_qc_tools(
        authority.producer, os.path.abspath(args.tool_manifest_path))
    root = os.path.join(
        os.path.dirname(authority.package["reviewCandidateDescriptorPath"]),
        "row10-negative-controls")
    os.makedirs(root)
    run = QcRun(authority, tools, "0" * 64, root)
    print(json.dumps({
        "positiveCandidateSha256": authority.candidate_sha256,
        "selectionReceiptHash": authority.alternate_take_selection_hash,
        "delayed": _blocked(run, root, "delayed"),
        "occluded": _blocked(run, root, "occluded"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
