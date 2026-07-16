"""Rendered-composite contrast and transition QC regressions."""

import os
import tempfile
import unittest

from PIL import Image, ImageDraw

from _common import *  # noqa: F401,F403

from audit import audit_composite_visual as acv
from audit.audit_frames import FrameRef


def _write(path: str, background: tuple[int, int, int],
           foreground: tuple[int, int, int] | None = None) -> None:
    image = Image.new("RGB", (480, 270), background)
    if foreground:
        draw = ImageDraw.Draw(image)
        for y in (30, 42, 54):
            draw.line((30, y, 180, y), fill=foreground, width=1)
    image.save(path)


def _graphic_check(base_color: tuple[int, int, int],
                   text_color: tuple[int, int, int]) -> list:
    directory = tempfile.TemporaryDirectory()
    base = os.path.join(directory.name, "base.png")
    final = os.path.join(directory.name, "final.png")
    _write(base, base_color)
    _write(final, base_color, text_color)
    frames = {"graphic0_mid": FrameRef(
        "graphic0_mid", "graphic", 1.0, final)}
    bases = {"graphic0_mid": FrameRef(
        "graphic0_mid", "graphic", 1.0, base)}
    plan = {"graphicsTrack": [{
        "kind": "glass-rail", "anchor": "free-band",
        "spec": {"accent": "#%02X%02X%02X" % text_color},
    }]}
    checks = acv._graphic_results(plan, frames, bases)
    directory.cleanup()
    return checks


class CompositeContrastTests(unittest.TestCase):
    def test_blue_on_blue_fails_rendered_contrast(self) -> None:
        checks = _graphic_check((5, 65, 165), (5, 75, 201))
        contrast = next(check for check in checks if check.name.endswith("contrast"))

        self.assertEqual(contrast.status, acv.FAIL)
        self.assertIn("actual footage", contrast.detail)

    def test_white_on_blue_passes_rendered_contrast(self) -> None:
        checks = _graphic_check((5, 65, 165), (255, 255, 255))
        contrast = next(check for check in checks if check.name.endswith("contrast"))

        self.assertEqual(contrast.status, acv.PASS)


class TransitionPixelTests(unittest.TestCase):
    def _frames(self, directory: str, colors: list[tuple[int, int, int]]) -> dict:
        frames = {}
        for phase, color in zip(("before", "seam", "after"), colors):
            path = os.path.join(directory, f"{phase}.png")
            _write(path, color)
            frames[f"transition0_{phase}"] = FrameRef(
                f"transition0_{phase}", "transition", 1.0, path)
        return frames

    def test_non_flash_uniform_seam_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frames = self._frames(directory, [
                (10, 20, 40), (220, 220, 220), (80, 50, 30),
            ])
            result = acv._transition_result(0, {"kind": "zoom-pull"}, frames)

        self.assertEqual(result.status, acv.FAIL)
        self.assertIn("stddev", result.measured)

    def test_absent_transition_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            frames = self._frames(directory, [(10, 20, 40)] * 3)
            result = acv._transition_result(0, {"kind": "light-leak"}, frames)

        self.assertEqual(result.status, acv.FAIL)
        self.assertIn("change 0.00", result.measured)


if __name__ == "__main__":
    unittest.main(verbosity=2)
