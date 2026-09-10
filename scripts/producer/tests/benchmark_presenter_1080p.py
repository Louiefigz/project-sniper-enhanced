"""Opt-in TEST1080p performance sample, never a production grade or deadline claim.

Run explicitly with --run. Fixed30frames at30000/1001, original300s cohort and
60s per child. There is no retry, lower-resolution/preset fallback or Docker.
"""
from __future__ import annotations

import json
import os
import sys
import time
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import guided_presenter_execution
import opening_prefix_oracle
from _presenter_benchmark_fixture import BenchmarkFixture, FRAMES, RATE, SIZE
from _presenter_benchmark_io import BenchmarkClock, BenchmarkIO, observed_group_absence
from graphics.composite_core import CompositeOptions, composite
from headless.process_runner import LEDGER_ENV
from opening_prefix_contract import CompositorPrefixRequest, PrefixClock, PrefixOracleRuntime, PrefixRanges
from opening_prefix_oracle import _frames, verify_compositor_prefix
from producer_config import ENCODE
from test_opening_prefix_contract import held


def compositor_command(fixture: BenchmarkFixture, label: str, output: Path) -> list[str]:
    """Baseline and presenter cases use exactly the same ordinary encoder settings."""
    io, commands = fixture.io, []
    graph = None if label == "baseline" else fixture.owners[label].full_graph()
    composite(str(fixture.base), [], str(output), CompositeOptions(eof_pass=True,
        ffmpeg=io.ffmpeg.path, ffprobe=io.ffprobe.path, command_runner=commands.append,
        frame_rate=RATE, frame_range=(0, FRAMES), video_only=True, presenter=graph))
    if len(commands) != 1:
        raise AssertionError("TEST benchmark requires one shared encoder call")
    return commands[0]


def validate_output_streams(value: dict) -> dict:
    """Require the full native clock and no copied base or asset audio."""
    streams = value.get("streams")
    if type(streams) is not list or len(streams) != 1 or streams[0].get("codec_type") != "video":
        raise AssertionError("TEST benchmark output must contain exactly one video and no audio")
    row = streams[0]
    if (row.get("width"), row.get("height"), row.get("pix_fmt"), row.get("sample_aspect_ratio")) != (*SIZE, "yuv420p", "1:1"):
        raise AssertionError("TEST benchmark output canvas/format/aspect differs")
    if row.get("nb_read_frames") != str(FRAMES) or row.get("start_pts") != 0 \
            or Fraction(row.get("r_frame_rate", "0")) != Fraction(RATE) \
            or Fraction(row.get("avg_frame_rate", "0")) != Fraction(RATE):
        raise AssertionError("TEST benchmark output frame count/clock differs")
    return row


def output_qc(io: BenchmarkIO, label: str, path: Path) -> dict:
    """Count and decode every output to strict EOF; this is not visual quality approval."""
    started = time.monotonic()
    io.stage = label + "-output-qc"
    probe = io.execute(io.request([io.ffprobe.path, "-v", "error", "-count_frames", "-show_streams",
                                  "-of", "json=compact=1", str(path)]))
    row = validate_output_streams(json.loads(probe.stdout))
    decoded = io.execute(io.request([io.ffmpeg.path, "-v", "error", "-nostdin", "-xerror", "-err_detect", "explode",
        "-i", str(path), "-map", "0:v:0", "-an", "-c:v", "rawvideo", "-pix_fmt", "yuv420p",
        "-fps_mode", "passthrough", "-f", "framehash", "-hash", "sha256", "-"]))
    frames = _frames(decoded.stdout, (FRAMES, RATE, SIZE[0] * SIZE[1] * 3 // 2))
    return {"elapsedSeconds": time.monotonic() - started, "stream": row, "fullEofFrameCount": len(frames),
            "noAudioStream": True, "visualQualityApproved": False}


def encode_case(fixture: BenchmarkFixture, label: str) -> dict:
    """Separate ordinary single-picture-encode cost from all output QC cost."""
    io = fixture.io
    output = io.root / f"{label}-output.mp4"
    command = compositor_command(fixture, label, output)
    io.stage = label + "-encode"
    started = time.monotonic()
    io.execute(io.request(command))
    elapsed = time.monotonic() - started
    result = {"label": label, "encodeSeconds": elapsed, "encodeFramesPerSecond": FRAMES / elapsed,
        "encodeWallPerMediaSecond": elapsed / float(Fraction(FRAMES, 1) / Fraction(RATE)),
        "output": {"path": str(output), "sha256": held(output).sha256, "sizeBytes": output.stat().st_size}}
    result["qc"] = output_qc(io, label, output)
    print(f"{label}: encode={elapsed:.3f}s QC={result['qc']['elapsedSeconds']:.3f}s", flush=True)
    return result


def prefix_case(fixture: BenchmarkFixture, label: str) -> dict:
    """Measure three actual pre-encode graph traversals separately from the single encode."""
    io = fixture.io
    pair = None if label == "baseline" else fixture.owners[label].prefix_graphs(FRAMES)
    request = CompositorPrefixRequest(held(fixture.base), (), (), (), PrefixClock(RATE, FRAMES, *SIZE),
                                     PrefixRanges((6, 24), (0, FRAMES)), presenter=pair)
    runtime = PrefixOracleRuntime(held(Path(io.ffmpeg.path)), held(Path(io.ffprobe.path)),
                                 str(io.root), io.clock.remaining())
    io.stage = label + "-prefix"
    started = time.monotonic()
    with patch("opening_prefix_oracle.run_text", io.execute), \
            patch("guided_presenter_observation.run_text", side_effect=AssertionError("duplicate selected decode")):
        proof = verify_compositor_prefix(request, runtime)
    elapsed = time.monotonic() - started
    path = io.root / f"{label}-prefix-proof.json"
    path.write_text(json.dumps(proof, indent=2) + "\n")
    print(f"{label}: separate actual prefix={elapsed:.3f}s", flush=True)
    return {"label": label, "elapsedSeconds": elapsed, "oracleTimingMs": proof["timingMs"],
            "proofPath": str(path), "actualGraphFrameTraversals": 78,
            "noDuplicateSelectedObservation": True, "encodedOutputApproved": False}


def benchmark(io: BenchmarkIO, result: dict) -> None:
    """Complete all fixed cases serially; stop on the first failure without a new clock."""
    io.hold_code([Path(__file__), Path(guided_presenter_execution.__file__), Path(opening_prefix_oracle.__file__)])
    io.stage = "installed-versions"
    for tool in (io.ffmpeg, io.ffprobe):
        io.execute(io.request([tool.path, "-version"]))
    started = time.monotonic()
    fixture = BenchmarkFixture(io)
    result["setupAndObservationSeconds"] = time.monotonic() - started
    result["encodes"] = []
    result["prefixes"] = []
    for label in ("baseline", "still", "video"):
        result["encodes"].append(encode_case(fixture, label))
        io.report(result)
    for label in ("baseline", "still", "video"):
        result["prefixes"].append(prefix_case(fixture, label))
        io.report(result)
    io.final_hashes()
    io.clock.remaining()


def run_benchmark(clock: BenchmarkClock) -> tuple[int, Path]:
    """Use only the normal local owned runner and a fresh exact ledger in this process."""
    if os.environ.get(LEDGER_ENV):
        raise RuntimeError("TEST benchmark refuses to replace an ambient owned process ledger")
    io = BenchmarkIO(clock)
    result = {"status": "running", "scope": "TEST-lowlevel-shared-encoder-plus-separate-live-owner-prefix",
        "size": list(SIZE), "frames": FRAMES, "frameRate": RATE, "mediaSeconds": float(Fraction(FRAMES, 1) / Fraction(RATE)),
        "encoder": {key: ENCODE[key] for key in ("vcodec", "mezzanine_crf", "composite_preset")},
        "sourceAdmission": "explicit-TEST-only-metadata-not-isolated-admission", "deliveryApproved": False,
        "audioMasterCompared": False, "tenMinuteOrTwoHourGuarantee": False}
    ledger = io.root / "owned-processes.jsonl"
    try:
        with patch.dict(os.environ, {LEDGER_ENV: str(ledger)}):
            benchmark(io, result)
        result["status"] = "passed"
    except BaseException as error:
        result.update(status="failed", error=f"{type(error).__name__}: {error}")
    result["cleanup"] = observed_group_absence(ledger) if ledger.exists() else {"exactGroupsAbsent": False}
    if not result["cleanup"]["exactGroupsAbsent"]:
        result["status"] = "failed"
    io.report(result)
    return (0 if result["status"] == "passed" else 1), io.root


def main() -> int:
    """Require exact opt-in before any source/media work; no user-settable workload knobs."""
    clock = BenchmarkClock()
    if sys.argv[1:] != ["--run"]:
        print("TEST-only fixed1080p benchmark: pass --run; no media has been launched", file=sys.stderr)
        return 2
    code, root = run_benchmark(clock)
    print(f"TEST1080p terminal={code} evidence={root / 'TEST-benchmark-evidence.json'}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
