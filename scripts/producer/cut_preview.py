#!/usr/bin/env python3
"""New-only private cut preview; never a plan, template, graph or QC approval."""
from __future__ import annotations

import argparse
import json
import os
import signal
from pathlib import Path

from compile_timeline import compile_plan
from cut_manifestation_authority import ManifestationInputs, write_manifestation, verify_manifestation
from cut_preview_authority import observe_inputs, toolchain, validate_input
from cut_preview_io import bound_json, digest, file_hash, write_new
from cut_preview_audio import AudioContext, render_source_audio
from cut_preview_media import observe_media, reject_hdr, render_profile
from cut_speed import CutSpeedOptions, render_cut_speed_opts
from stage_timing import stage_span


def _bounds(plan: dict, profile: dict) -> None:
    """Limit work admission independently of a child deadline."""
    timeline = compile_plan(plan)
    if len(timeline.segments) > 500 or not 0 < timeline.output_duration <= 20 * 60:
        raise RuntimeError("cut preview exceeds its 500-cut/20-minute admission limit")
    if profile["width"] * profile["height"] * timeline.output_duration > 1_500_000_000:
        raise RuntimeError("cut preview exceeds its pixel-second admission limit")


def assert_supported_cut(plan: dict) -> None:
    """Reject unqualified source retiming before media hashing or rendering."""
    if any(row.get("speed", 1) != 1 for row in plan.get("cutTrack", [])):
        raise RuntimeError("private cut preview currently supports source speed 1 only; "
                           "nonunity retiming is not qualified (do not silently change the approved cut)")


def render_preview(value: dict, output: Path) -> dict:
    """Render and seal only an exact private cut; caller holds the writer lease."""
    assert_supported_cut(bound_json(Path(value["planPath"]), value["request"]["planHash"]))
    plan, manifest, sources = observe_inputs(value)
    runtime = toolchain(value)
    reject_hdr(manifest, runtime["binaries"]["ffprobe"])
    profile = render_profile(plan, manifest, value["proxyScale"])
    _bounds(plan, profile)
    write_new(output / "toolchain.json", runtime)
    timeline = compile_plan(plan)
    timeline_path = output / "timeline_map.json"
    write_new(timeline_path, timeline.to_dict())
    parts_dir = output / "parts"
    parts_dir.mkdir(mode=0o700)
    media_path = output / "cut-preview.mp4"
    raw_concat = output / "cut-concat.mp4"
    proof = render_cut_speed_opts(plan, manifest, str(raw_concat),
                                  CutSpeedOptions(str(parts_dir), profile["proxyScale"]))
    audio_clock_hash = render_source_audio(AudioContext(plan, manifest, output, profile, runtime["binaries"], proof))
    parts = [str(parts_dir / f"part_{row.index:04d}.mp4") for row in timeline.segments]
    manifestation = write_manifestation(ManifestationInputs(
        plan, str(timeline_path), parts, str(media_path), profile["fps"], proof))
    verify_manifestation(str(output), plan)
    media = observe_media(media_path, profile, runtime["binaries"])
    if media["videoFrames"] != manifestation["concat"]["videoFrames"]:
        raise RuntimeError("cut preview decoded frames disagree with exact cut manifestation")
    if observe_inputs(value) != (plan, manifest, sources) or toolchain(value) != runtime:
        raise RuntimeError("cut preview source or executable authority drifted during render")
    request = value["request"]
    core = {"schemaVersion": 1, "kind": "guided-cut-preview",
            **{key: request[key] for key in ("requestHash", "planHash", "authorityDigest",
                "pictureLockHash", "projectionReceiptHash", "timelineMapHash")},
            **sources, "runId": value["runId"], "attempt": value["attempt"],
            "executionKey": value["executionKey"], "createdAt": value["createdAt"],
            "toolchainHash": runtime["toolchainHash"], "profile": profile, "media": media,
            "manifestationHash": manifestation["receiptHash"],
            "manifestationFileHash": file_hash(output / "cut_manifestation.v1.json"),
            "timelineFileHash": file_hash(timeline_path),
            "audioClockHash": audio_clock_hash,
            "scope": "cut-only-source-aspect-ungraded-unmixed-not-delivery"}
    receipt = {**core, "receiptHash": digest(core)}
    write_new(output / "receipt.json", receipt)
    return receipt


def _failure(output: Path, error: str) -> None:
    """Retain bounded failed-attempt evidence without replacing prior artifacts."""
    try:
        write_new(output / "failure.json", {"schemaVersion": 1,
                  "kind": "cut-preview-failure", "error": error[-1000:]})
    except (OSError, RuntimeError):
        pass


def main() -> int:
    """Execute only as the leader of the controller's owned process group."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("--verify-sources", action="store_true")
    args = parser.parse_args()
    input_path = Path(args.input)
    value = bound_json(input_path)
    output = validate_input(value, input_path, new_only=not args.verify_sources)
    if os.getpid() != os.getpgrp():
        raise RuntimeError("cut preview requires a dedicated controller-owned process group")
    def expired(_signum: int, _frame: object) -> None:
        if not args.verify_sources:
            _failure(output, "cut preview process-group deadline exceeded")
        os.killpg(os.getpgrp(), signal.SIGKILL)
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(value["timeoutSeconds"])
    try:
        if args.verify_sources:
            _, _, sources = observe_inputs(value)
            print(json.dumps({"status": "cut_preview_sources_current",
                              "requestHash": value["request"]["requestHash"],
                              "executionKey": value["executionKey"], **sources}), flush=True)
            return 0
        with stage_span(str(output), "cut_preview"):
            result = render_preview(value, output)
        print('{"status":"cut_preview_ready","receiptHash":"'
              + result["receiptHash"] + '"}', flush=True)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        if not args.verify_sources:
            _failure(output, str(error))
        print(json.dumps({"error": str(error)[-1000:]}), flush=True)
        return 1
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
