"""Decoded-frame acceptance for b-roll gaps, not perceptual face-quality proof.

Actual FFmpeg composition and OpenCV sampling stay live. The face detector is
replaced by a pixel-label oracle: red means an exposed, colliding presenter;
green/blue mean opaque b-roll with no presenter. This isolates timing from face
detector accuracy while requiring the verifier to inspect the correct frames.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import cv2
except ImportError:
    cv2 = None

from broll.broll_insert import BrollInsert, build_filter
from graphics import placement_verify as pv

if cv2 is not None:
    from motion import face_track, visual_state


FPS = 30
FRAME_SIZE = 64


def _color(frame) -> str:
    """Read the source-layer label from an actual decoded BGR frame."""
    pixel = frame[FRAME_SIZE // 2, FRAME_SIZE // 2]
    return ("blue", "green", "red")[max(range(3), key=lambda i: int(pixel[i]))]


def _render(path: Path, restart_time: float) -> None:
    """Render the production b-roll filter with enough tail for inclusive ends."""
    inserts = [BrollInsert("green", 0.0, 1.0),
               BrollInsert("blue", restart_time, 3.0)]
    profile = {"w": FRAME_SIZE, "h": FRAME_SIZE, "fps": FPS}
    graph = build_filter(inserts, profile, [(FRAME_SIZE, FRAME_SIZE)] * 2)
    command = [shutil.which("ffmpeg") or "ffmpeg", "-nostdin", "-v", "error"]
    for color in ("red", "lime", "blue"):
        source = f"color=c={color}:s={FRAME_SIZE}x{FRAME_SIZE}:r={FPS}:d=3.5"
        command.extend(["-f", "lavfi", "-i", source])
    command.extend(["-filter_complex", graph, "-map", "[vout]", "-an",
                    "-frames:v", "90", "-c:v", "libx264", "-preset", "ultrafast",
                    "-qp", "0", "-pix_fmt", "yuv420p", "-video_track_timescale",
                    "15360", str(path)])
    subprocess.run(command, check=True, capture_output=True, timeout=30)


def _decoded_frames(path: Path) -> list[tuple[int, float, str]]:
    """Decode sequentially to establish ground truth independently of seeking."""
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"cannot decode timing fixture {path}")
    rows: list[tuple[int, float, str]] = []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            rows.append((len(rows), capture.get(cv2.CAP_PROP_POS_MSEC) / 1000,
                         _color(frame)))
    finally:
        capture.release()
    return rows


def _pixel_face(frame, _cascade, _config) -> tuple | None:
    """Treat only the red, genuinely exposed source as a colliding presenter."""
    return (20.0, 20.0, 10.0, 10.0) if _color(frame) == "red" else None


def _verify(path: Path, restart_time: float) -> tuple:
    """Run real sampling/geometry, returning gate outcome and decoded receipts."""
    reads: list[dict] = []
    rows: list[dict] = []
    original_read = face_track._read_at

    def read_at(capture, second: float):
        frame = original_read(capture, second)
        if frame is not None:
            reads.append({"requested": second,
                          "frame": round(capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1,
                          "pts": capture.get(cv2.CAP_PROP_POS_MSEC) / 1000,
                          "color": _color(frame)})
        return frame

    occlusions = {"broll": [[0.0, 1.0], [restart_time, 3.0]]}
    context = pv.VerifyContext("FAIL", occlusions,
                               emit=lambda **fields: rows.append(fields))
    clip = {"outStart": 0.0, "outEnd": 3.0, "anchor": "headroom",
            "placedBBox": [10, 10, 40, 40]}
    error = None
    with mock.patch.object(face_track, "_read_at", side_effect=read_at), \
            mock.patch.object(visual_state, "_largest_face", side_effect=_pixel_face):
        try:
            pv.run_verify([clip], str(path), context)
        except RuntimeError as exc:
            error = str(exc)
    return error, rows, reads


@unittest.skipUnless(cv2 is not None and shutil.which("ffmpeg"),
                     "installed OpenCV and FFmpeg required")
class PlacementCoverageMediaTests(unittest.TestCase):
    """A positive wall-clock gap is not necessarily an exposed output frame."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create tiny, disposable production-compositor boundary fixtures."""
        cls.temporary = tempfile.TemporaryDirectory(prefix="placement-pts-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.restarts = {"none": 1.0 + 1 / FPS, "one": 1.05,
                        "rounded": 1.0 + 2 / FPS, "longer": 2.05}
        cls.paths = {name: Path(cls.temporary.name) / f"gap-{name}.mp4"
                     for name in cls.restarts}
        for name, path in cls.paths.items():
            _render(path, cls.restarts[name])

    def test_one_frame_time_gap_has_no_displayed_presenter(self) -> None:
        """Inclusive b-roll covers both PTS bracketing the smaller time gap."""
        frames = _decoded_frames(self.paths["none"])
        self.assertEqual(len(frames), 90)
        self.assertEqual([row[2] for row in frames[29:33]],
                         ["green", "green", "blue", "blue"])
        self.assertEqual([row[0] for row in frames if row[2] == "red"], [])

    def test_wider_time_gap_exposes_exactly_one_presenter_frame(self) -> None:
        """The next wider gap exposes only frame 31 at PTS 31/30."""
        frames = _decoded_frames(self.paths["one"])
        self.assertEqual(len(frames), 90)
        self.assertEqual([row[2] for row in frames[29:34]],
                         ["green", "green", "red", "blue", "blue"])
        self.assertEqual([row[0] for row in frames if row[2] == "red"], [31])
        self.assertAlmostEqual(frames[31][1], 31 / FPS, places=6)

    def test_no_displayed_gap_never_routes_to_geometry_repair(self) -> None:
        """Do not manufacture a no-face collision from covered neighboring PTS."""
        error, rows, reads = _verify(self.paths["none"], self.restarts["none"])
        self.assertIsNone(error, json.dumps({"error": error, "reads": reads}))
        self.assertFalse(any(row["status"] == "placement_verified" for row in rows))
        self.assertTrue(any(row["status"] == "placement_verify_skip" for row in rows))

    def test_genuine_single_frame_collision_is_measured_without_neighbor_frames(self) -> None:
        """A real exposed frame must block and its probe must not inspect b-roll."""
        error, _rows, reads = _verify(self.paths["one"], self.restarts["one"])
        self.assertIsNotNone(error, json.dumps(reads))
        self.assertIn("NoLegalRegion", error)
        self.assertEqual({row["frame"] for row in reads}, {31}, json.dumps(reads))
        self.assertEqual({row["color"] for row in reads}, {"red"}, json.dumps(reads))

    def test_serialized_restart_exposes_two_frames_and_both_are_checked(self) -> None:
        """Six-decimal restart rounding must not hide the last exposed frame."""
        frames = _decoded_frames(self.paths["rounded"])
        self.assertEqual([row[0] for row in frames if row[2] == "red"], [31, 32])
        error, _rows, reads = _verify(self.paths["rounded"], self.restarts["rounded"])
        self.assertIsNotNone(error, json.dumps(reads))
        self.assertIn("NoLegalRegion", error)
        self.assertEqual({row["frame"] for row in reads}, {31, 32}, json.dumps(reads))
        self.assertEqual({row["color"] for row in reads}, {"red"}, json.dumps(reads))

    def test_budgeted_decoded_samples_keep_first_and_last_exposed_frame(self) -> None:
        """Longer gaps remain bounded without discarding their visible edges."""
        frames = _decoded_frames(self.paths["longer"])
        exposed = [row[0] for row in frames if row[2] == "red"]
        self.assertEqual(exposed, list(range(31, 62)))
        error, _rows, reads = _verify(self.paths["longer"], self.restarts["longer"])
        self.assertIsNotNone(error, json.dumps(reads))
        selected = [row["frame"] for row in reads]
        self.assertEqual(len(selected), pv.FREE_SPACE["samples_per_window"])
        self.assertEqual((selected[0], selected[-1]), (31, 61))
        self.assertEqual(sorted(set(selected)), selected)
        self.assertEqual({row["color"] for row in reads}, {"red"}, json.dumps(reads))


if __name__ == "__main__":
    unittest.main(verbosity=2)
