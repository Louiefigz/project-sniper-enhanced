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


class SnipersOwnToolsRun(unittest.TestCase):
    """deps_check_tools: every one of Sniper's own tools runs, with the features Sniper uses."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-tools-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.pkg = fx.make_package(self.base)
        self.bin = fx.runtime_prefix(self.base / "home") / "bin"

    def _check(self) -> str:
        done = fx.bash(self.pkg, 'deps_paths; deps_check_tools && echo ok || echo "problem: $DEPS_TOOL_PROBLEM"')
        return done.stdout.strip()

    def _replace(self, tool: str, body: str) -> None:
        (self.bin / tool).write_text(f"#!/bin/bash\n{body}\n")   # a stand-in file, never a real tool

    def test_all_present_passes(self) -> None:
        self.assertEqual(self._check(), "ok")

    def test_tesseract_without_english_data_is_named(self) -> None:
        self._replace("tesseract", 'case "$1" in --list-langs) printf "List:\\nosd\\n" ;; *) echo 5.5.3 ;; esac')
        self.assertEqual(self._check(), "problem: tesseract has no English data")

    def test_a_tool_that_does_not_start_is_named(self) -> None:
        self._replace("yt-dlp", "exit 1")
        self.assertEqual(self._check(), "problem: yt-dlp does not start")

    def test_an_ffmpeg_without_a_renderer_filter_is_refused(self) -> None:
        self._replace("ffmpeg", 'case "$*" in *-encoders*) printf "E:\\n V libx264 x\\n A aac x\\n" ;; '
                                '*-filters*) printf "F:\\n ... crop A->A x\\n" ;; *) echo ffmpeg version 8 ;; esac')
        self.assertIn("problem: ffmpeg lacks rubberband zscale", self._check())


if __name__ == "__main__":
    unittest.main()
