"""Real FFmpeg proof for the private prebound R0 compositor."""

from __future__ import annotations

import ast
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from _common import pl  # noqa: F401
from _prebound_compositor_fixture import (
    Fixture,
    sample_rgb,
    transparent_overlay,
)
from headless.prebound_compositor import compose_prebound_candidate
from headless.prebound_compositor_media import alpha_mode
from headless.quality_pass_types import CompositeRequestV1


def _import_closure(producer: Path, starts: tuple[str, ...]) -> set[str]:
    pending, seen = list(starts), set()
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        path = producer.joinpath(*module.split(".")).with_suffix(".py")
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        parent = module.split(".")[:-1]
        discovered = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                discovered.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                prefix = parent[: len(parent) - node.level + 1]
                parts = (
                    (*prefix, node.module or "") if node.level else (node.module or "",)
                )
                name = ".".join(parts)
                discovered.append(name.strip("."))
        pending.extend(name for name in discovered if name and name not in seen)
    return seen


class PreboundCompositorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise unittest.SkipTest("ffmpeg/ffprobe unavailable")
        cls.ffmpeg, cls.ffprobe = os.path.realpath(ffmpeg), os.path.realpath(ffprobe)

    def _assert_transparent_rejected(self, fixture: Fixture, root: Path) -> None:
        transparent = fixture.sources / "transparent.mov"
        transparent_overlay(self.ffmpeg, transparent)
        receipt, _receipt_path = fixture.json_ref(
            "transparent-receipt.json", {"render": "transparent"}
        )
        application = fixture.composite_request().candidate.application
        asset, mapping = fixture.graphic(
            transparent, receipt, application.decoded_plan()
        )
        fixture.mapping.update(mapping)
        bad = CompositeRequestV1(
            fixture.request.request_digest,
            fixture.composite_request().candidate,
            (asset,),
        )
        candidate = root / "candidate-transparent"
        candidate.mkdir(mode=0o700)
        with self.assertRaisesRegex(RuntimeError, "alpha occupancy"):
            compose_prebound_candidate(bad, fixture.context(candidate))
        self.assertFalse((candidate / "assembly-receipt.json").exists())

    def test_real_private_candidate_is_deterministic_and_fully_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(os.path.realpath(tmp))
            fixture = Fixture(root, self.ffmpeg, self.ffprobe)
            results = []
            for index in range(2):
                candidate = root / f"candidate-{index}"
                candidate.mkdir(mode=0o700)
                results.append(
                    compose_prebound_candidate(
                        fixture.composite_request(), fixture.context(candidate)
                    )
                )
                receipt = json.loads((candidate / "assembly-receipt.json").read_bytes())
                self.assertEqual(receipt["status"], "complete-private-counterfactual")
                self.assertTrue(receipt["compositor"]["fullDecode"]["passed"])
                self.assertEqual(
                    receipt["compositor"]["audio"]["baseSha256"],
                    receipt["compositor"]["audio"]["finalSha256"],
                )
                self.assertFalse((candidate / "final.proxy.mp4").exists())
                red, green, blue = sample_rgb(self.ffmpeg, candidate / "final.mp4", 1.0)
                self.assertGreater(red, 180)
                self.assertGreater(green, 180)
                self.assertLess(blue, 100)
            self.assertEqual(
                results[0].final.artifact.sha256, results[1].final.artifact.sha256
            )
            self.assertEqual(
                results[0].assembly_receipt.sha256, results[1].assembly_receipt.sha256
            )
            self._assert_transparent_rejected(fixture, root)

    def test_alpha_pixel_format_classification_is_exact(self) -> None:
        self.assertEqual(alpha_mode("yuva444p12le"), "straight")
        for value in ("gray", "pal8", "rgba", "yuva444p10le"):
            with self.subTest(value=value):
                self.assertEqual(alpha_mode(value), "none")

    def test_transitive_entry_modules_exclude_legacy_and_gui_paths(self) -> None:
        producer = Path(__file__).resolve().parents[1]
        starts = ("headless.prebound_compositor", "graphics.composite_core")
        forbidden = (
            "graphics.graphics_render",
            "assemble",
            "palmier",
            "src.app",
            "gui",
        )
        names = _import_closure(producer, starts)
        self.assertFalse([name for name in names if name.startswith(forbidden)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
