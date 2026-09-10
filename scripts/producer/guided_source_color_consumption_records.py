"""Pure bounded picture-command metadata, not source or renderer authority.

The recorder joins existing cut manifestation/packet proofs; this module never
hashes media, decodes a frame, changes an encoder argument, or approves color.
"""
from __future__ import annotations

from dataclasses import asdict, fields
from fractions import Fraction
import json
from pathlib import Path

from compile_timeline import Segment, compile_plan
from cut_manifestation_authority import _MANIFEST_KEYS, _receipt_hash, _verify_manifest_parts, _object_hash
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata


def bounded_timeline(plan: dict, authority: dict) -> dict:
    """Refuse unsupported initial workload before retaining/compiling unbounded cuts."""
    rows, count = plan.get("cutTrack"), authority.get("totalFrames")
    if type(rows) is not list or not 1 <= len(rows) <= 10000 \
            or type(count) is not int or not 1 <= count <= 72000:
        raise RuntimeError("source-color picture initial cut/frame workload exceeds its bound")
    result = compile_plan(plan).to_dict()
    if not 1 <= len(result["segments"]) <= 10000:
        raise RuntimeError("source-color picture compiled occurrence workload exceeds its bound")
    return result


def metadata_size(value: object, remaining: int) -> int:
    """Bound UTF-8 JSON-domain retained metadata before growth, not Python heap bytes."""
    size = len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))
    if size > remaining:
        raise RuntimeError("source-color retained picture metadata exceeds its 8MiB aggregate bound")
    return size


def same(value: object, expected: object) -> bool:
    """Compare strict scalar/container types, never bool/numeric coercions."""
    return same_read_metadata(value, hold_read_metadata(expected))


def path(value: object) -> str:
    """Require an absolute spelling without any filesystem observation."""
    if type(value) is not str or not value or len(value) > 4096 or "\x00" in value \
            or not Path(value).is_absolute() or str(Path(value)) != value or ".." in Path(value).parts:
        raise RuntimeError("source-color picture path is not exact absolute metadata")
    return value


def command(value: object) -> tuple[str, ...]:
    """Detach bounded actual argv; executable spelling alone is not tool admission."""
    if type(value) is not list or not 1 <= len(value) <= 512 \
            or any(type(row) is not str or "\x00" in row for row in value) \
            or sum(len(row.encode("utf-8")) for row in value) > 128 * 1024:
        raise RuntimeError("source-color picture argv is malformed or oversized")
    return tuple(value)


def segment(value: Segment) -> dict:
    """Preserve actual compiler source/output timing, including repeated occurrences."""
    if type(value) is not Segment or set(vars(value)) != {row.name for row in fields(value)}:
        raise RuntimeError("source-color picture requires an actual unchanged compiler segment")
    return asdict(value)


def cut_request(values: tuple) -> dict:
    """Project the actual segment/job/output/cumulative-frame command inputs."""
    row, job, output, before = values
    profile = job.profile
    if type(before) is not int or before < 0 or type(profile.fps) is not Fraction:
        raise RuntimeError("source-color cut clock metadata is malformed")
    return {"segment": segment(row), "sourcePath": path(job.src_path), "outputPath": path(output),
            "framesBefore": before, "profile": {"width": profile.width, "height": profile.height,
                "frameRate": f"{profile.fps.numerator}/{profile.fps.denominator}", "pixelFormat": profile.pix_fmt}}


def master_request(spec: object) -> dict:
    """Capture the actual picture-only spec before its mutable fields reach callbacks."""
    return {"inputPath": path(spec.src), "outputPath": path(spec.out), "ass": spec.ass,
            "fps": spec.fps, "fpsExact": spec.fps_exact, "duration": spec.duration,
            "frameCount": spec.frame_count, "cover": spec.cover}


def cut_arguments(values: tuple) -> tuple:
    """Retain complete original job fields and callback identities, not only displayed rows."""
    row, job, output, before = values
    if set(vars(job)) != {item.name for item in fields(job)} or set(vars(job.profile)) != {item.name for item in fields(job.profile)}:
        raise RuntimeError("source-color picture job/profile fields changed")
    return (id(row), segment(row), id(job), tuple(vars(job)), id(job.profile),
            cut_request(values), job.tail, job.source_channels, job.tail_channels,
            id(job.before_encode), id(job.picture_consumption), output, before)


def master_arguments(spec: object) -> tuple:
    """Retain every existing spec field and its separately owned recorder identity."""
    if set(vars(spec)) != {item.name for item in fields(spec)}:
        raise RuntimeError("source-color picture master spec fields changed")
    return (id(spec), tuple(vars(spec)), master_request(spec), id(spec.picture_consumption))


def join_manifestation(value: dict, context: tuple) -> dict:
    """Reuse the existing closed elementary/frame proof without another media read."""
    plan, timeline, requests, paths = context
    if type(value) is not dict or set(value) != _MANIFEST_KEYS \
            or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 \
            or value["kind"] != "cut-manifestation-v1" or value["receiptHash"] != _receipt_hash(value) \
            or value["planCutTrackHash"] != _object_hash(plan["cutTrack"]):
        raise RuntimeError("source-color cut manifestation is not the exact closed receipt")
    _verify_manifest_parts(value, timeline)
    if type(paths) is not tuple or len(paths) != len(requests) or len(requests) != len(value["parts"]):
        raise RuntimeError("source-color cut manifestation omitted an actual encoded part")
    for request, actual_path, observed in zip(requests, paths, value["parts"]):
        if actual_path != request["outputPath"] or not same(observed["partFrames"], request["frames"]):
            raise RuntimeError("source-color cut manifestation changed actual part path/frame coverage")
    return {"receiptHash": value["receiptHash"], "timelineMapSha256": value["timelineMapSha256"],
            "frameRate": value["frameRate"], "parts": value["parts"], "concat": value["concat"]}


def picture_fields(picture: object) -> tuple:
    """Hold actual original packet evidence without new packet/hash observations."""
    return (id(picture), picture.path, picture.sha256,
            picture.time_base.numerator, picture.time_base.denominator,
            tuple((row[0].numerator, row[0].denominator, row[1], row[2], row[3]) for row in picture.packets))


def copy_proof(picture: object) -> dict:
    """Expected exact existing audio-only picture-copy proof, not a new color claim."""
    return {"picturePacketsIdentical": True, "picturePackets": len(picture.packets),
            "pictureTimeBase": str(picture.time_base), "pictureSourceSha256": picture.sha256}
