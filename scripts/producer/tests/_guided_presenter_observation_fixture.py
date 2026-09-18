"""Invented probe JSON and small owned files for metadata faults, not admission."""
from __future__ import annotations

import copy
import hashlib
import json
import struct
import tempfile
import zlib
from pathlib import Path

from graphics.presenter_layout_contract import PresenterCanvas
from guided_presenter_assets import SelectedPresenterAsset, select_presenter_assets
from guided_presenter_probe_identity import HeldPresenterProbeFile, PresenterObservationRuntime, presenter_stat_identity
from test_presenter_layout_graph import declaration


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    """Build a real chunk CRC for TEST metadata faults, without an image library."""
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def png_bytes(extra: bytes = b"") -> bytes:
    """Encode a tiny TEST-only opaque PNG with explicit sRGB/SAR chunk evidence."""
    data = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 36, 8, 2, 0, 0, 0))
    data += png_chunk(b"pHYs", struct.pack(">IIB", 1, 1, 0)) + png_chunk(b"sRGB", b"\x01") + extra
    return data + png_chunk(b"IDAT", zlib.compress((b"\x00" + b"\x80" * 64 * 3) * 36)) + png_chunk(b"IEND", b"")


def held(path: Path) -> HeldPresenterProbeFile:
    """TEST caller links these tiny bytes to stat identity before invoking the owner."""
    before = path.stat()
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if presenter_stat_identity(before) != presenter_stat_identity(path.stat()):
        raise AssertionError("TEST setup file drifted during its original hash")
    return HeldPresenterProbeFile(str(path), sha, before.st_size, presenter_stat_identity(before))


def selected_fixture(source: HeldPresenterProbeFile, image: bool,
                     asset_id: str = "TEST-presentation") -> SelectedPresenterAsset:
    """Join explicit TEST admission metadata; this is not an isolated admission receipt."""
    row = {"id": asset_id, "kind": "image" if image else "video",
        "originalPath": "/TEST/original.png" if image else "/TEST/original.mp4", "path": source.path,
        "sourceSha256": source.sha256, "sourceSizeBytes": source.size_bytes,
        "admissionReceiptPath": f".sniper-external-media/receipts/{'a' * 64}.json", "admissionReceiptSha256": "a" * 64}
    entry = {"lane": "broll", "mediaKind": "still-image" if image else "timed-media",
        "originalPath": row["originalPath"], "snapshotPath": row["path"], "sha256": row["sourceSha256"],
        "sizeBytes": row["sourceSizeBytes"], "admissionReceiptPath": row["admissionReceiptPath"],
        "admissionReceiptSha256": row["admissionReceiptSha256"]}
    payload = declaration()
    payload["assetId"] = asset_id
    plan = {"presenterLayouts": [{"operationIndex": 7, "startFrame": 2, "endFrameExclusive": 18,
                                  "layout": payload}]}
    return select_presenter_assets(plan, {"broll": [row]}, [entry], PresenterCanvas(64, 36, 24, "yuv420p"))[0]


class OriginalDeadline:
    """Predictably decreasing TEST deadline, not a production runtime timer."""

    def __init__(self) -> None:
        """Start once; calls expose remaining original allowance for assertions."""
        self.calls = 0
        self.expired = False

    def remaining(self) -> float:
        """Record every boundary and fail on a test-controlled original expiry."""
        self.calls += 1
        if self.expired:
            raise RuntimeError("TEST original deadline expired")
        return 30 - self.calls * .001


class ObservationFixture:
    """Fake stream facts over actual small files; no real decoder is invoked here."""

    def __init__(self, image: bool = False, payload: bytes | None = None) -> None:
        """Initialize closed source/entry metadata and fake tool under one TEST root."""
        self.directory = tempfile.TemporaryDirectory(prefix="sniper-presenter-probe-unit-", dir="/private/tmp")
        self.root = Path(self.directory.name)
        data = payload if payload is not None else png_bytes() if image else b"TEST only, not media"
        store = self.root / ".sniper-external-media"
        store.mkdir()
        self.path = store / f"{hashlib.sha256(data).hexdigest()}.media"
        self.path.write_bytes(data)
        self.source = held(self.path)
        tool = self.root / "TEST-ffprobe"
        tool.write_bytes(b"TEST not an executable media probe")
        tool.chmod(0o755)
        self.deadline = OriginalDeadline()
        self.runtime = PresenterObservationRuntime(held(tool), str(self.root), self.deadline, lambda: None)
        self.selected = selected_fixture(self.source, image)
        self.header, self.frames = self._documents(image)

    def _documents(self, image: bool) -> tuple[dict, dict]:
        """Explicit current-shaped mocked observations, never actual decoder output."""
        colors = {"color_range": "pc" if image else "tv", "color_space": "gbr" if image else "bt709",
            "color_primaries": "bt709", "color_transfer": "iec61966-2-1" if image else "bt709"}
        common = {"width": 64, "height": 36, "pix_fmt": "rgb24" if image else "yuv420p",
                  "sample_aspect_ratio": "1:1", **colors}
        count = 1 if image else 24
        stream = {"codec_type": "video", "codec_name": "png" if image else "h264", "index": 0,
            "r_frame_rate": "30000/1001", "avg_frame_rate": "30000/1001", "start_pts": 0,
            "time_base": "1/30000", "nb_frames": str(count), "field_order": "progressive", **common}
        header = {"streams": [stream], "format": {"format_name": "png_pipe" if image else "mov,mp4"}}
        full = copy.deepcopy(header)
        full["streams"][0]["nb_read_frames"] = str(count)
        full["frames"] = [{"media_type": "video", "stream_index": 0, "pts": index * 1001,
            "best_effort_timestamp": index * 1001, "duration": 1001, "interlaced_frame": 0,
            "repeat_pict": 0, **common} for index in range(count)]
        return header, full

    def raw(self) -> tuple[str, str]:
        """Serialize the two explicit stub documents without claiming owned execution."""
        return json.dumps(self.header), json.dumps(self.frames)

    def close(self) -> None:
        """Remove only this small disposable unit-test fixture directory."""
        self.directory.cleanup()
