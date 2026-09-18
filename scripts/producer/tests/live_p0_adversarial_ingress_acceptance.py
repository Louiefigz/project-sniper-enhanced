#!/usr/bin/env python3
"""Retain hostile-byte proof for the shared external-ingress sandbox (native jail).

Schema v2 (2026-09-18): admission runs in the native macOS jail
(headless/native_media_*), so the artifact binds the jail's runtime identity instead
of an approved container image, and cleanup is proved by the absence of any
process still referring to the case's snapshot store.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import struct
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from headless.external_media_probe import admit_external_media
from headless.native_media_sandbox import verified_runtime
from headless.external_media_probe_policy import MediaProbeLimits
from headless.sealed_archive import verify_archive_file
PRODUCER = Path(__file__).parents[1]
REPO = PRODUCER.parents[1]
CASES = (
    "malformed-codec",
    "huge-dimensions",
    "huge-frame-count",
    "truncated-stream",
    "decoder-timeout",
    "archive-bomb",
)
CLOSURE = (
    "scripts/producer/tests/live_p0_adversarial_ingress_acceptance.py",
    "scripts/producer/headless/external_media_probe.py",
    "scripts/producer/headless/external_media_probe_native.py",
    "scripts/producer/headless/external_media_probe_policy.py",
    "scripts/producer/headless/external_media_snapshot.py",
    "scripts/producer/headless/native_media_jail.py",
    "scripts/producer/headless/native_media_probe.sb",
    "scripts/producer/headless/native_media_runtime.py",
    "scripts/producer/headless/native_media_runtime_approval.json",
    "scripts/producer/headless/native_media_sandbox.py",
    "scripts/producer/headless/native_media_watchdog.py",
    "scripts/producer/headless/native_macho.py",
    "scripts/producer/headless/sealed_archive.py",
)
def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
def _ffmpeg(*args: str, timeout: int = 60) -> None:
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"fixture ffmpeg failed: {result.stderr[-400:]}")
def _tiny_avi(path: Path) -> None:
    _ffmpeg(
        "-f", "lavfi", "-i", "color=size=2x2:rate=1:duration=1",
        "-c:v", "rawvideo", str(path),
    )
def _malformed_codec(root: Path) -> Path:
    source = root / "codec-source.avi"
    target = root / "unknown-codec.avi"
    _tiny_avi(source)
    data = bytearray(source.read_bytes())
    stream, format_chunk = data.find(b"strh"), data.find(b"strf")
    if min(stream, format_chunk) < 0:
        raise RuntimeError("AVI codec fixture has no stream headers")
    data[stream + 12:stream + 16] = b"ZZZZ"
    data[format_chunk + 24:format_chunk + 28] = b"ZZZZ"
    target.write_bytes(data)
    return target
def _huge_dimensions(root: Path) -> Path:
    target = root / "huge-dimensions.nut"
    _ffmpeg(
        "-f", "lavfi", "-i", "color=size=8194x2:rate=1:duration=1",
        "-c:v", "rawvideo", str(target),
    )
    return target


def _huge_frame_count(root: Path) -> Path:
    source = root / "frame-source.avi"
    target = root / "huge-frame-count.avi"
    _tiny_avi(source)
    data = bytearray(source.read_bytes())
    avi, stream = data.find(b"avih"), data.find(b"strh")
    if min(avi, stream) < 0:
        raise RuntimeError("AVI frame fixture has no stream headers")
    struct.pack_into("<I", data, avi + 8, 1000)
    struct.pack_into("<I", data, avi + 24, 2_000_001)
    struct.pack_into("<I", data, stream + 28, 1)
    struct.pack_into("<I", data, stream + 32, 1000)
    struct.pack_into("<I", data, stream + 40, 2_000_001)
    target.write_bytes(data)
    return target


def _truncated_stream(root: Path) -> Path:
    source = root / "complete.mp4"
    target = root / "truncated.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30:duration=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
    )
    payload = source.read_bytes()
    target.write_bytes(payload[:max(1, len(payload) // 3)])
    return target


def _nal_units(data: bytes) -> list[tuple[int, bytes]]:
    starts = []
    for index in range(len(data) - 4):
        if data[index:index + 4] == b"\0\0\0\1":
            starts.append(index)
        elif data[index:index + 3] == b"\0\0\1" \
                and (index == 0 or data[index - 1] != 0):
            starts.append(index)
    result = []
    for number, start in enumerate(starts):
        end = starts[number + 1] if number + 1 < len(starts) else len(data)
        prefix = 4 if data[start:start + 4] == b"\0\0\0\1" else 3
        result.append((data[start + prefix] & 31, data[start:end]))
    return result


def _decoder_timeout(root: Path) -> Path:
    two_frames = root / "two-4k.h264"
    repeated = root / "slow-4k.h264"
    target = root / "decoder-timeout.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i",
        "color=size=4096x4096:rate=1000:duration=0.002",
        "-frames:v", "2", "-c:v", "libx264", "-preset", "ultrafast",
        "-x264-params", "keyint=999:scenecut=0",
        "-f", "h264", str(two_frames),
    )
    units = _nal_units(two_frames.read_bytes())
    if not units or units[-1][0] != 1:
        raise RuntimeError("4K timeout fixture has no repeatable P slice")
    repeated.write_bytes(
        b"".join(value for _kind, value in units[:-1])
        # 600,000 skip-coded 4K frames: ~10x the 90 s ceiling at the fastest decode seen
        # (60,000 finished inside it on an idle Mac); under the 2,000,000-frame ceiling.
        + units[-1][1] * 600_000)
    _ffmpeg("-r", "1000", "-i", str(repeated), "-c", "copy", str(target))
    return target


def _processes(store: Path) -> list[str]:
    """Live processes whose command line still names this case's snapshot store."""
    result = subprocess.run(["/usr/bin/pgrep", "-f", str(store)], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=30, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError("could not enumerate jailed decoder processes")
    return sorted(result.stdout.split())


def _media_case(
    case_id: str,
    source: Path,
    root: Path,
    limits: MediaProbeLimits | None = None,
) -> dict:
    store = root / f"{case_id}-store"
    store.mkdir()
    before = _processes(store)
    try:
        admit_external_media(
            str(source),
            str(store),
            limits or MediaProbeLimits(),
        )
    except RuntimeError as exc:
        error = str(exc)
    else:
        raise RuntimeError(f"{case_id} unexpectedly entered admission")
    after = _processes(store)
    return {
        "caseId": case_id,
        "inputSha256": _sha(source),
        "status": "rejected",
        "error": error,
        "admissionReceiptPublished": bool(list(store.glob("*.json"))),
        "processCleanupProved": before == after == [],
    }


def _archive_case(root: Path) -> dict:
    path = root / "archive-bomb.tar"
    data = b"x"
    with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as archive:
        info = tarfile.TarInfo("motion/compositions/card.html")
        info.size, info.mode, info.mtime = len(data), 0o444, 0
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        archive.addfile(info, io.BytesIO(data))
    path.chmod(0o600)
    digest = hashlib.sha256(data).hexdigest()
    required = (
        "motion/compositions/card.html",
        "motion/hyperframes.json",
        "motion/index.html",
        "motion/package.json",
        "request/asset-bindings.json",
        "request/variables.json",
    )
    manifest = tuple({
        "path": name,
        "sizeBytes": 129 * 1024 * 1024 if name.endswith("card.html") else 1,
        "sha256": digest,
    } for name in required)
    try:
        verify_archive_file(str(path), _sha(path), manifest)
    except RuntimeError as exc:
        error = str(exc)
    else:
        raise RuntimeError("archive bomb unexpectedly passed admission")
    return {
        "caseId": "archive-bomb",
        "inputSha256": _sha(path),
        "status": "rejected",
        "error": error,
        "admissionReceiptPublished": False,
        "processCleanupProved": True,
    }


def run_cohort() -> dict:
    """Execute every retained hostile input through its released boundary."""
    generators = (
        ("malformed-codec", _malformed_codec, None),
        ("huge-dimensions", _huge_dimensions, None),
        ("huge-frame-count", _huge_frame_count, None),
        ("truncated-stream", _truncated_stream, None),
        (
            "decoder-timeout",
            _decoder_timeout,
            MediaProbeLimits(max_decode_seconds=90),
        ),
    )
    with tempfile.TemporaryDirectory(prefix="sniper-p0-adversarial-") as raw:
        root = Path(raw).resolve()
        results = [
            _media_case(case_id, generator(root), root, limits)
            for case_id, generator, limits in generators
        ]
        results.append(_archive_case(root))
    identity = verified_runtime().identity
    return {
        "schemaVersion": 2,
        "kind": "p0-adversarial-ingress-acceptance",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "nativeRuntime": {key: identity[key] for key in (
            "policy", "profileSha256", "launcherSha256", "closureSha256", "platform")}
        | {"ffmpeg": identity["tools"]["ffmpeg"]["version"]},
        "sourceClosure": {
            name: _sha(REPO / name)
            for name in CLOSURE
        },
        "cases": results,
        "passed": all(
            row["status"] == "rejected"
            and row["admissionReceiptPublished"] is False
            and row["processCleanupProved"] is True
            for row in results
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True, type=Path)
    args = parser.parse_args()
    result = run_cohort()
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    args.artifact.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
