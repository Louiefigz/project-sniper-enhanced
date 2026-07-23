"""Draft mode: watermark command construction + the no-approval invariant."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import draft_render as dr

_HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
_FONT = os.path.join(dr.FONTS_DIR, "Inter-Bold.ttf")


class WatermarkCmdTests(unittest.TestCase):
    """build_watermark_cmd is pure — assert the contract, not just strings."""

    def _cmd(self, h: int = 1920, w: int = 1080) -> list:
        return dr.build_watermark_cmd("/in/final.mp4", "/out/draft.mp4",
                                      (w, h), "/fonts/Inter-Bold.ttf")

    def test_output_is_draft_never_final(self) -> None:
        cmd = self._cmd()
        self.assertEqual(os.path.basename(cmd[-1]), "draft.mp4")
        with self.assertRaises(ValueError):
            dr.build_watermark_cmd("/in/final.mp4", "/out/final.mp4",
                                   (1080, 1920), "/fonts/f.ttf")

    def test_fast_pass_audio_copy(self) -> None:
        cmd = self._cmd()
        self.assertIn("veryfast", cmd)          # DRAFT["preset"]
        idx = cmd.index("-c:a")
        self.assertEqual(cmd[idx + 1], "copy")  # never re-encode the master bus
        self.assertEqual(cmd[cmd.index("-i") + 1], "/in/final.mp4")

    def test_two_draft_layers_burned(self) -> None:
        vf = self._cmd()[self._cmd().index("-vf") + 1]
        self.assertEqual(vf.count("drawtext="), 2)   # center mark + corner badge
        self.assertIn("text=DRAFT:", vf)
        self.assertIn("text=DRAFT - NOT FINAL:", vf)
        self.assertIn("box=1", vf)                   # solid badge is unmissable

    def test_geometry_scales_with_height(self) -> None:
        vf_short = self._cmd(h=1920)[self._cmd(h=1920).index("-vf") + 1]
        vf_long = self._cmd(h=1080, w=1920)[self._cmd(h=1080, w=1920).index("-vf") + 1]
        self.assertIn(f"fontsize={int(1920 * 0.16)}", vf_short)
        self.assertIn(f"fontsize={int(1080 * 0.16)}", vf_long)

    def test_fontfile_path_is_filter_escaped(self) -> None:
        cmd = dr.build_watermark_cmd("/in/final.mp4", "/out/draft.mp4",
                                     (1080, 1920), "/f/we:ird's.ttf")
        vf = cmd[cmd.index("-vf") + 1]
        self.assertIn("fontfile=/f/we\\:ird\\'s.ttf", vf)


class NoApprovalSidecarTests(unittest.TestCase):
    """The invariant: the draft dir never contains .sniper-qc-approved.json."""

    def test_clean_or_missing_dir_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dr.assert_no_approval_sidecar(tmp)                       # empty
            dr.assert_no_approval_sidecar(os.path.join(tmp, "no"))   # missing

    def test_present_sidecar_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, dr.APPROVAL_SIDECAR).write_text("{}")
            with self.assertRaises(RuntimeError):
                dr.assert_no_approval_sidecar(tmp)

    def test_draft_flow_writes_no_sidecar(self) -> None:
        """scrub_intermediates leaves ONLY draft artifacts — no approval, no
        unwatermarked master, no provenance a governance path could key on."""
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, dr.DRAFT_NAME).write_bytes(b"wm")
            Path(tmp, dr.INTERMEDIATE_NAME).write_bytes(b"raw")
            Path(tmp, dr.INTERMEDIATE_NAME + ".assembled.json").write_text("{}")
            dr.scrub_intermediates(tmp)
            self.assertEqual(sorted(os.listdir(tmp)), [dr.DRAFT_NAME])
            dr.assert_no_approval_sidecar(tmp)   # end state honors the invariant

    def test_scrub_refuses_without_watermarked_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, dr.INTERMEDIATE_NAME).write_bytes(b"raw")
            with self.assertRaises(RuntimeError):
                dr.scrub_intermediates(tmp)
            # the failed burn's evidence must remain for diagnosis
            self.assertTrue(os.path.exists(os.path.join(tmp, dr.INTERMEDIATE_NAME)))


class FontResolutionTests(unittest.TestCase):
    def test_missing_font_fails_loud(self) -> None:
        with self.assertRaises(RuntimeError):
            dr.resolve_font("/nope/missing-font.ttf")

    @unittest.skipUnless(os.path.isfile(_FONT), "repo font not vendored here")
    def test_default_font_resolves_to_repo_asset(self) -> None:
        self.assertEqual(dr.resolve_font(None), _FONT)


@unittest.skipUnless(_HAVE_FFMPEG and os.path.isfile(_FONT),
                     "ffmpeg + repo font required")
class WatermarkBurnE2ETests(unittest.TestCase):
    """The built command actually parses and burns (font + filter proof)."""

    def test_burn_produces_watchable_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "final.mp4")
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                 "-i", "color=c=gray:s=320x180:d=0.5:r=30",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", src], check=True)
            dst = os.path.join(tmp, "draft.mp4")
            cmd = dr.build_watermark_cmd(src, dst, (320, 180), _FONT)
            proc = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
            self.assertTrue(os.path.getsize(dst) > 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
