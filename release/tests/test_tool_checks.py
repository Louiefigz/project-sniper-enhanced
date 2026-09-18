"""Prerequisite checks must not report a present feature as missing.

rc3's ffmpeg check piped the whole filter list into `grep -q` under `set -o
pipefail`. When the list is larger than a pipe buffer, grep exits at the first
match, the writer gets SIGPIPE, and the pipeline "fails" - a present filter is
reported missing. It surfaced under load during the rc4 repair runs; a long
filter list makes it deterministic here.

Run: .venv/bin/python -m unittest release.tests.test_tool_checks
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from release.tests import _fixture as fx

WANTED = ("rubberband zscale subtitles ass drawtext arnndn loudnorm ebur128 afftdn acompressor alimiter "
          "sidechaincompress aresample amix overlay crop").split()


def _fake_ffmpeg(folder: Path, filters: list[str]) -> Path:
    """An ffmpeg whose -filters lists the given names first, then 200,000 filler filters."""
    listing = folder / "filters.txt"
    rows = [f" ... {name:<20} A->A  test" for name in filters]
    rows += [f" ... filler{i:<14} A->A  padding" for i in range(200_000)]
    listing.write_text("Filters:\n" + "\n".join(rows) + "\n")
    encoders = folder / "encoders.txt"
    encoders.write_text("Encoders:\n V....D libx264  H.264\n A....D aac  AAC\n")
    fake = folder / "ffmpeg"
    fake.write_text(f'#!/bin/bash\ncase "$*" in *-filters*) cat "{listing}" ;; *-encoders*) cat "{encoders}" ;; esac\n')
    fake.chmod(0o755)
    return fake


class FfmpegFeatureCheck(unittest.TestCase):
    """ffmpeg_missing_features against a fake ffmpeg with a very long filter list."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-tools-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.pkg = fx.make_package(self.base)

    def _missing(self, filters: list[str]) -> str:
        fake = _fake_ffmpeg(self.base, filters)
        done = fx.bash(self.pkg, f'printf "[%s]" "$(ffmpeg_missing_features "{fake}")"')
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_every_present_filter_is_found_even_in_a_long_list(self) -> None:
        for _ in range(3):
            self.assertEqual(self._missing(WANTED), "[]")

    def test_a_genuinely_missing_filter_is_named(self) -> None:
        self.assertEqual(self._missing([f for f in WANTED if f != "rubberband"]), "[rubberband ]")

    def test_first_line_needs_no_pipe(self) -> None:
        done = fx.bash(self.pkg, 'first_line "$(printf "codex-cli 0.144.1\\nextra\\n")"')
        self.assertEqual(done.stdout, "codex-cli 0.144.1")


class ExternalToolsAtInstall(unittest.TestCase):
    """check_external_tools (installer step 1) on a Mac without the reference tools."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-tools-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.pkg = fx.make_package(self.base)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        for tool in ("ffmpeg", "ffprobe", "whisper-cli"):
            real = shutil.which(tool, path="/opt/homebrew/bin:/usr/local/bin")
            if real:
                (self.bin / tool).symlink_to(real)

    @unittest.skipUnless(shutil.which("ffmpeg", path="/opt/homebrew/bin:/usr/local/bin"), "no ffmpeg on this Mac")
    def test_missing_tesseract_and_ytdlp_are_listed_together_with_brew_commands(self) -> None:
        # common.sh appends Homebrew's folders to PATH, so the test narrows PATH after sourcing it.
        done = fx.bash(self.pkg, f'. "$FIXTURE_PKG/install/lib/steps.sh"; PATH="{self.bin}"; check_external_tools')
        self.assertEqual(done.returncode, 1)
        out = done.stdout + done.stderr
        self.assertIn("tesseract is required for reference study", out)
        self.assertIn("brew install tesseract", out)
        self.assertIn("yt-dlp is required for adding a reference from a URL", out)
        self.assertIn("brew install yt-dlp", out)
        self.assertIn("Missing: tesseract yt-dlp.", out)


if __name__ == "__main__":
    unittest.main()
