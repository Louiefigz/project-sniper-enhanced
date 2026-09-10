"""Real-media proof that graphics stay above b-roll and below captions."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from broll.broll_insert import BrollInsert, apply_broll_inserts
from captions.caption_authority import burn_caption_artifact
from graphics.composite_core import composite


def _run(command: list[str], binary: bool = False) -> bytes | str:
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace")[-1000:])
    return result.stdout if binary else result.stdout.decode("utf-8")


def _make_base(path: Path) -> None:
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=30:d=3",
        "-f", "lavfi", "-i",
        "sine=frequency=440:sample_rate=48000:duration=3",
        "-frames:v", "90", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2",
        "-shortest", str(path),
    ])


def _make_broll(path: Path) -> None:
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=30:d=2.25",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", str(path),
    ])


def _make_graphic(path: Path, color: str) -> None:
    _run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i",
        f"color=c={color}:s=320x180:r=30:d=1",
        "-f", "lavfi", "-i",
        "color=c=black:s=320x180:r=30:d=1,format=gray,"
        "drawbox=x=40:y=105:w=240:h=60:color=#808080:t=fill",
        "-filter_complex", "[0:v][1:v]alphamerge",
        "-c:v", "prores_ks", "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le", str(path),
    ])


def _write_ass(path: Path) -> None:
    path.write_text(
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 320\nPlayResY: 180\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
        "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
        "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding\n"
        "Style: Default,Arial,24,&H00FFFFFF,&H00FFFFFF,&H00000000,"
        "&H00000000,-1,0,0,0,100,100,0,0,1,2,0,2,10,10,14,1\n"
        "[Events]\n"
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,"
        "Effect,Text\n"
        "Dialogue: 0,0:00:00.80,0:00:02.20,Default,,0,0,0,,CAPTION\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _audio_md5(path: Path) -> str:
    return str(_run([
        "ffmpeg", "-v", "error", "-i", str(path),
        "-map", "0:a:0", "-c", "copy", "-f", "md5", "-",
    ])).strip()


def _frame(path: Path, second: float) -> bytes:
    value = _run([
        "ffmpeg", "-v", "error", "-ss", str(second), "-i", str(path),
        "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
    ], binary=True)
    assert isinstance(value, bytes)
    if len(value) != 320 * 180 * 3:
        raise RuntimeError("layering fixture did not decode one full RGB frame")
    return value


def _pixel(frame: bytes, x: int, y: int) -> tuple[int, int, int]:
    offset = (y * 320 + x) * 3
    return tuple(frame[offset:offset + 3])  # type: ignore[return-value]


def _green_graphic_over_blue(candidate: bytes, broll: bytes) -> bool:
    blue = _pixel(broll, 160, 130)
    mixed = _pixel(candidate, 160, 130)
    corner_delta = sum(abs(left - right) for left, right in zip(
        _pixel(broll, 20, 20), _pixel(candidate, 20, 20)))
    return mixed[1] > blue[1] + 30 and mixed[2] > 30 and corner_delta < 24


class GraphicsOverBrollLayeringTests(unittest.TestCase):
    def test_render_routes_broll_before_graphics(self) -> None:
        render_path = Path(__file__).parents[1] / "render.py"
        source = render_path.read_text(encoding="utf-8")
        body = source.split("\ndef render(", 1)[1].split("\ndef ", 1)[0]
        self.assertLess(
            body.index("broll_stage("), body.index("graphics_track_stage("))

    def test_real_layering_caption_audio_and_dirty_invalidation(self) -> None:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg and ffprobe are required")
        with tempfile.TemporaryDirectory(prefix="layering-proof-") as raw:
            root = Path(raw)
            base, broll = root / "base.mp4", root / "broll.mp4"
            _make_base(base)
            _make_broll(broll)
            brolled = root / "brolled.mp4"
            insert = BrollInsert("receipt", 0.5, 2.5, path=str(broll))
            result = apply_broll_inserts(str(base), [insert], str(brolled))
            self.assertEqual(result["inFrames"], result["outFrames"])
            broll_identity = (_sha(brolled), brolled.stat().st_mtime_ns)
            caption = root / "caption.ass"
            _write_ass(caption)
            caption_hash = _sha(caption)
            outputs: list[tuple[Path, Path]] = []
            for name, color in (("green", "lime"), ("red", "red")):
                graphic = root / f"{name}.mov"
                _make_graphic(graphic, color)
                plain = root / f"{name}-plain.mp4"
                composite(str(brolled), [{
                    "path": str(graphic), "outStart": 1.0, "outEnd": 2.0,
                }], str(plain))
                captioned = root / f"{name}-captioned.mp4"
                shutil.copyfile(plain, captioned)
                burn_caption_artifact(str(captioned), str(caption))
                outputs.append((plain, captioned))
            self.assertEqual(
                broll_identity, (_sha(brolled), brolled.stat().st_mtime_ns))
            self.assertEqual(caption_hash, _sha(caption))
            audio = [_audio_md5(path) for path in (
                base, brolled, outputs[0][0], outputs[0][1],
                outputs[1][0], outputs[1][1])]
            self.assertEqual(len(set(audio)), 1)
            broll_frame = _frame(brolled, 1.5)
            green_frame = _frame(outputs[0][0], 1.5)
            self.assertTrue(
                _green_graphic_over_blue(green_frame, broll_frame))
            self.assertFalse(
                _green_graphic_over_blue(broll_frame, broll_frame))
            before_broll = root / "green-before-broll.mp4"
            composite(str(base), [{
                "path": str(root / "green.mov"),
                "outStart": 1.0, "outEnd": 2.0,
            }], str(before_broll))
            reversed_order = root / "broll-after-graphic.mp4"
            apply_broll_inserts(
                str(before_broll), [insert], str(reversed_order))
            self.assertFalse(_green_graphic_over_blue(
                _frame(reversed_order, 1.5), broll_frame))
            self.assertNotEqual(
                _frame(outputs[0][0], 1.5), _frame(outputs[0][1], 1.5))
            self.assertNotEqual(
                _frame(outputs[0][0], 1.5), _frame(outputs[1][0], 1.5))
            self.assertEqual(
                _frame(outputs[0][0], 0.75), _frame(outputs[1][0], 0.75))


if __name__ == "__main__":
    unittest.main(verbosity=2)
