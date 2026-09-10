"""Prove exact prefix pixels of the supplied full and opening compositor graphs.

Both graphs execute through the ordinary shared compositor, with only the lossy
encoder/output suffix replaced by rawvideo frame hashes. This is NOT comparison
of encoded delivery files. A caller must bind these actual resolved graphs and
held inputs to its owned execution; this function grants no approval authority.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path

from cut_preview_io import read_bytes
from graphics.composite_core import CompositeOptions, composite
from headless.process_runner import ProcessRequest, run_text
from opening_prefix_contract import (
    CompositorPrefixRequest, GRAPH_WORKLOAD_POLICY, HeldPrefixInput, PrefixDeadline, PrefixOracleError,
    PrefixOracleRuntime, canonical_hash, valid_canvas, validate_request, verify_held_input,
)
from producer_config import CANVAS
from render_effect_discovery import local_python_import_closure
from opening_prefix_graphs import freeze_request, graph_hash, graph_layer_policy, proof_header
from opening_prefix_presenter import (compositor_rate, presenter_for_role, presenter_input_pixels,
                                     validate_presenter_base, assert_presenter_live, presenter_observation_records)

SCOPE = "executed-preencode-graph-prefix-not-encoded-output-or-approval"


def _run(command: list[str], context: tuple[PrefixOracleRuntime, PrefixDeadline], maximum: int) -> str:
    """Use existing ledger/group ownership and cap stdout+stderr before append."""
    runtime, deadline = context
    environment = {"LANG": "C", "LC_ALL": "C", "TZ": "UTC", "AV_LOG_FORCE_NOCOLOR": "1"}
    result = run_text(ProcessRequest(tuple(command), "", runtime.working_directory, environment,
        deadline.remaining(), termination_grace_seconds=1.0, max_output_bytes=maximum))
    deadline.remaining()
    if result.returncode:
        raise PrefixOracleError("prefix oracle command failed: " + result.stderr[-1200:])
    return result.stdout


def _probe(request: CompositorPrefixRequest, context: tuple[PrefixOracleRuntime, PrefixDeadline]) -> dict:
    """Fully count base frames; reject unqualified offset, canvas and declared clock."""
    runtime, _deadline = context
    colors = ",color_space,color_primaries,color_transfer,color_range" if request.presenter is not None else ""
    raw = _run([runtime.ffprobe.path, "-v", "error", "-count_frames", "-show_entries",
        "stream=codec_type,width,height,pix_fmt,r_frame_rate,avg_frame_rate,start_pts,time_base,"
        f"nb_read_frames,sample_aspect_ratio{colors}:stream_tags=rotate:stream_side_data=rotation",
        "-of", "json", request.base.path], context, 65536)
    streams = json.loads(raw).get("streams")
    if type(streams) is not list:
        raise PrefixOracleError("prefix base stream observation is malformed")
    videos = [row for row in streams if row.get("codec_type") == "video"]
    if len(videos) != 1:
        raise PrefixOracleError("prefix base requires exactly one picture stream")
    row, clock = videos[0], request.clock
    expected = (clock.width, clock.height, clock.total_frames, Fraction(clock.frame_rate))
    actual = (row.get("width"), row.get("height"), int(row.get("nb_read_frames", -1)),
              Fraction(row.get("avg_frame_rate", "0")))
    if actual != expected or Fraction(row.get("r_frame_rate", "0")) != expected[-1] \
            or int(row.get("start_pts", -1)) != 0 or row.get("sample_aspect_ratio") != "1:1" \
            or row.get("pix_fmt") != CANVAS["pix_fmt"] or row.get("tags", {}).get("rotate", "0") != "0" \
            or any(item.get("rotation", 0) != 0 for item in row.get("side_data_list", [])):
        raise PrefixOracleError("prefix base frame count, canvas or zero-origin CFR metadata differs")
    base = Fraction(row.get("time_base", "0"))
    if base <= 0 or (1 / expected[-1] / base).denominator != 1:
        raise PrefixOracleError("prefix base timebase cannot exactly express the frame clock")
    if request.presenter is not None:
        validate_presenter_base(row)
    return row


def _raw_command(request: CompositorPrefixRequest, runtime: PrefixOracleRuntime,
                  role: tuple[str, tuple[int, int] | None]) -> tuple[list[str], str]:
    """Capture the real compositor command; preserve inputs, graph and animation origin."""
    name, span = role
    clips = request.full_clips if name == "full" else request.opening_clips
    commands = []
    original_span = span if clips or span is not None else (0, request.clock.total_frames)
    tail = request.caption_tail[0 if name == "full" else 1] if request.caption_tail is not None else None
    composite(request.base.path, list(clips), "unused-oracle-output.mp4", CompositeOptions(
        eof_pass=True, ffmpeg=runtime.ffmpeg.path, ffprobe=runtime.ffprobe.path,
        command_runner=commands.append, frame_rate=compositor_rate(request),
        frame_range=original_span, video_only=True, caption_tail=tail, presenter=presenter_for_role(request, name)))
    if len(commands) != 1:
        raise PrefixOracleError("prefix oracle expected exactly one shared compositor command")
    original = commands[0]
    end = request.ranges.review[1] if span is None else span[1] - span[0]
    command = original[:original.index("-c:v")] + ["-c:v", "rawvideo", "-pix_fmt", CANVAS["pix_fmt"],
        "-an", "-frames:v", str(end), "-fps_mode", "passthrough", "-f", "framehash", "-hash", "sha256", "-"]
    return command, canonical_hash(original)


def _graphic_metadata(path: str, context: tuple[PrefixOracleRuntime, PrefixDeadline], rate: str) -> dict:
    """Observe bounded native surfaces without decoding complete graphic assets."""
    runtime, _deadline = context
    raw = _run([runtime.ffprobe.path, "-v", "error", "-show_entries",
        "stream=codec_type,width,height,r_frame_rate,avg_frame_rate,start_pts,time_base,sample_aspect_ratio:"
        "stream_tags=rotate:stream_side_data=rotation", "-of", "json", path], context, 65536)
    rows = json.loads(raw).get("streams")
    if type(rows) is not list:
        raise PrefixOracleError("prefix graphic metadata is malformed")
    videos = [row for row in rows if row.get("codec_type") == "video"]
    if len(videos) != 1:
        raise PrefixOracleError("prefix graphic requires one native picture stream")
    row, expected = videos[0], Fraction(rate)
    if not valid_canvas(row.get("width"), row.get("height")):
        raise PrefixOracleError("prefix graphic native canvas exceeds verifier workload")
    if Fraction(row.get("r_frame_rate", "0")) != expected \
            or Fraction(row.get("avg_frame_rate", "0")) != expected or int(row.get("start_pts", -1)) != 0 \
            or row.get("sample_aspect_ratio") != "1:1" or row.get("tags", {}).get("rotate", "0") != "0" \
            or any(item.get("rotation", 0) != 0 for item in row.get("side_data_list", [])):
        raise PrefixOracleError("prefix graphic requires unchanged zero-origin rational frame clock/aspect")
    timebase = Fraction(row.get("time_base", "0"))
    if timebase <= 0 or (1 / expected / timebase).denominator != 1:
        raise PrefixOracleError("prefix graphic timebase cannot express its exact frame clock")
    return row


def _graphic_workload(request: CompositorPrefixRequest, rows: dict[str, dict]) -> dict:
    """Count repeated decoder occurrences, not just unique file paths; never drop inputs."""
    base = request.clock.width * request.clock.height
    sizes = {path: row["width"] * row["height"] for path, row in rows.items()}
    full = base + sum(sizes[row["path"]] for row in request.full_clips)
    opening = base + sum(sizes[row["path"]] for row in request.opening_clips)
    presentation = presenter_input_pixels(request)
    full, opening = full + presentation[0], opening + presentation[1]
    if max(full, opening) > GRAPH_WORKLOAD_POLICY["maxGraphInputPixels"]:
        raise PrefixOracleError("prefix aggregate native input pixels exceed conservative verifier workload")
    return {"policy": GRAPH_WORKLOAD_POLICY, "fullGraphInputPixels": full,
            "openingGraphInputPixels": opening, "nativeVideoMetadata": rows,
            "graphicMetadataOnly": True, "fixedProcessRssQualified": False}


def _probe_graphics(request: CompositorPrefixRequest,
                    context: tuple[PrefixOracleRuntime, PrefixDeadline]) -> dict:
    rows = {row.path: _graphic_metadata(row.path, context, request.clock.frame_rate) for row in request.assets}
    return _graphic_workload(request, rows)


def _frame(line: str, index: int, size: int) -> str:
    """Validate exact integer raw-frame timing and planar byte size before digest use."""
    columns = [value.strip() for value in line.split(",")]
    if len(columns) != 6 or columns[:1] != ["0"]:
        raise PrefixOracleError("prefix raw frame record is malformed")
    dts, pts, duration, observed_size = (int(value) for value in columns[1:5])
    if (dts, pts, duration, observed_size) != (index, index, 1, size):
        raise PrefixOracleError("prefix raw frame PTS, duration or byte count differs")
    value = columns[5]
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise PrefixOracleError("prefix raw frame digest is malformed")
    return value


def _frames(raw: str, expected: tuple[int, str, int]) -> tuple[str, ...]:
    """Require every expected frame and its exact time base, including the last frame."""
    count, rate_text, size = expected
    rate, timebases, rows = Fraction(rate_text), [], []
    for line in raw.splitlines():
        if line.startswith("#tb 0:"):
            timebases.append(Fraction(line.split(":", 1)[1].strip()))
        if line and not line.startswith("#"):
            rows.append(_frame(line, len(rows), size))
    if timebases != [1 / rate] or len(rows) != count:
        raise PrefixOracleError("prefix raw frame count or timebase is not exact")
    return tuple(rows)


def _execute(request: CompositorPrefixRequest, context: tuple[PrefixOracleRuntime, PrefixDeadline],
             role: tuple[str, tuple[int, int] | None]) -> tuple[tuple[str, ...], dict]:
    runtime, _deadline = context
    command, graph_hash = _raw_command(request, runtime, role)
    span = role[1]
    count = request.ranges.review[1] if span is None else span[1] - span[0]
    raw = _run(command, context, 65536 + count * 256)
    pixels = request.clock.width * request.clock.height * 3 // 2
    frames = _frames(raw, (count, request.clock.frame_rate, pixels))
    return frames, {"sharedCompositorCommandHash": graph_hash, "observedCommandHash": canonical_hash(command),
        "frameCount": count, "pixelFormat": CANVAS["pix_fmt"], "frameHashesSha256": canonical_hash(list(frames))}


def _compare(request: CompositorPrefixRequest, context: tuple[PrefixOracleRuntime, PrefixDeadline]) -> dict:
    """Compare ranges of the full graph; never restart or shorten graphic assets."""
    full, full_proof = _execute(request, context, ("full", None))
    result, seen = {"fullGraphPrefix": full_proof}, {}
    for role in ("core", "review"):
        span = getattr(request.ranges, role)
        frames, proof = seen.get(span) or _execute(request, context, (role, span))
        seen[span] = (frames, proof)
        _matching_frames(frames, full[span[0]:span[1]], (role, span))
        result[role] = {**proof, "startFrame": span[0], "endFrameExclusive": span[1],
                        "exactPreencodePixels": True}
    return result


def _matching_frames(observed: tuple[str, ...], expected: tuple[str, ...],
                     role: tuple[str, tuple[int, int]]) -> None:
    if observed == expected:
        return
    first = next((index for index, values in enumerate(zip(observed, expected)) if values[0] != values[1]), None)
    absolute = role[1][0] + first if first is not None else None
    raise PrefixOracleError(f"{role[0]} pre-encode graph differs at absolute frame {absolute}")


def _implementation(deadline: PrefixDeadline) -> tuple[HeldPrefixInput, ...]:
    """Record current local oracle/compositor implementation, not a fabricated pinned approval."""
    paths = local_python_import_closure([Path(__file__)])
    if len(paths) > 512:
        raise PrefixOracleError("prefix oracle implementation inventory exceeds its bound")
    result = []
    for path in paths:
        deadline.remaining()
        size = path.stat().st_size
        if not 0 < size <= 1024 * 1024:
            raise PrefixOracleError("prefix oracle implementation file exceeds its bound")
        value = hashlib.sha256(read_bytes(path, 1024 * 1024)).hexdigest()
        result.append(HeldPrefixInput(str(path), value, size))
    return tuple(result)


def _verify_rows(rows: tuple[HeldPrefixInput, ...], deadline: PrefixDeadline) -> tuple:
    return tuple(verify_held_input(row, deadline) for row in rows)


def verify_compositor_prefix(request: CompositorPrefixRequest, runtime: PrefixOracleRuntime) -> dict:
    """Prove supplied graph prefixes only; original source/approval/deadline authority stays with caller."""
    deadline = PrefixDeadline(runtime.timeout_seconds)
    rows = validate_request(request, runtime)
    request = freeze_request(request)
    rows = validate_request(request, runtime)
    start = time.monotonic()
    implementation = _implementation(deadline)
    identities = _verify_rows((*rows, *implementation), deadline)
    by_path = dict(zip((row.path for row in (*rows, *implementation)), identities))
    observations = presenter_observation_records(request, runtime, by_path, deadline)
    hashed = time.monotonic()
    base = _probe(request, (runtime, deadline))
    base_probed = time.monotonic()
    graphics = _probe_graphics(request, (runtime, deadline))
    probed = time.monotonic()
    assert_presenter_live(request, runtime, by_path)
    deadline.remaining()
    comparison = _compare(request, (runtime, deadline))
    compared = time.monotonic()
    if presenter_observation_records(request, runtime, by_path, deadline) != observations:
        raise PrefixOracleError("prefix presenter observations changed during graph execution")
    if _verify_rows((*rows, *implementation), deadline) != identities:
        raise PrefixOracleError("prefix held inventory changed during graph execution")
    deadline.remaining()
    finished = time.monotonic()
    result = {**proof_header(request), "scope": SCOPE, "status": "verified",
        "inputs": [asdict(row) for row in rows], "implementation": [asdict(row) for row in implementation],
        "clock": asdict(request.clock), "baseSelectedVideo": base, "graphicWorkload": graphics, **observations,
        "fullGraphHash": graph_hash(request, "full"),
        "openingGraphHash": graph_hash(request, "opening"), "comparison": comparison, **graph_layer_policy(request),
        "encodedOutputObserved": False, "audioCompared": False, "approvalObserved": False,
        "audioAuthority": "requires-separate-held-full-program-master-excerpt",
        "timingMs": {"inputHash": (hashed - start) * 1000, "baseProbe": (base_probed - hashed) * 1000,
            "graphicMetadataProbe": (probed - base_probed) * 1000,
            "preencodeOracle": (compared - probed) * 1000, "inputRecheck": (finished - compared) * 1000,
            "total": (finished - deadline.started) * 1000},
        "cleanupScope": "observed-owned-local-process-groups; no Docker invoked"}
    result["timingMs"]["total"] = (time.monotonic() - deadline.started) * 1000
    deadline.remaining()
    return result
