"""Retired R0 compositor refusal and inert clip-binding unit tests."""

from __future__ import annotations

import ast
import json
import dataclasses
from unittest.mock import patch
import tempfile
import unittest
from pathlib import Path

from _common import pl  # noqa: F401
from _quality_pass_fixture import _Harness
from test_quality_pass import _historical_candidate
from test_prebound_clips import _clip_row, _document
from headless.prebound_clips import parse_prebound_clips
from headless.prebound_compositor import compose_prebound_candidate, _candidate_clip_bytes
from headless.prebound_compositor_build import PreboundCompositorContextV1, compositor_build_digest
from headless.repair_intent import approved_plan_digest
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
    def test_retired_parent_or_candidate_refuses_before_import_write_or_media(self) -> None:
        """Public compositor rejects either retired plan before opening its store."""
        harness = _Harness()
        candidate = _historical_candidate(harness)
        plan = candidate.application.decoded_plan()
        plan['graphicsTrack'][0].update(kind='marker-highlight',
            spec={'text': 'TEST current source', 'emphasisWord': 'current'})
        current_application = dataclasses.replace(candidate.application,
            plan_json=json.dumps(plan, separators=(',', ':'), sort_keys=True).encode(),
            after_digest=approved_plan_digest(plan))
        cases = (candidate, dataclasses.replace(candidate, application=current_application))
        with tempfile.TemporaryDirectory(prefix='TEST-compositor-refusal-') as root:
            target = Path(root).resolve() / 'candidate-never-created'
            resolver = unittest.mock.Mock(side_effect=AssertionError('artifact resolution'))
            context = PreboundCompositorContextV1(str(target), resolver,
                '/TEST-not-invoked/ffmpeg', '/TEST-not-invoked/ffprobe', compositor_build_digest())
            for value in cases:
                request = CompositeRequestV1(harness.request.request_digest,
                                             value, harness.parent.graphics_assets)
                with self.subTest(candidate=value.application.after_digest), patch(
                        'headless.prebound_compositor._import_inputs') as imports, patch(
                            'subprocess.Popen') as process, self.assertRaisesRegex(
                                ValueError, 'section-marker.*retired'):
                    compose_prebound_candidate(request, context)
                imports.assert_not_called()
                process.assert_not_called()
                resolver.assert_not_called()
                self.assertFalse(target.exists())
                self.assertEqual(tuple(Path(root).iterdir()), ())

    def test_inert_clip_rebinding_changes_only_asset_hashes(self) -> None:
        import dataclasses
        harness = _Harness()
        asset = harness.parent.graphics_assets[0]
        row = harness.parent.decoded_plan()['graphicsTrack'][0]
        clips = parse_prebound_clips(_document([_clip_row(row, asset)]))
        changed = dataclasses.replace(asset, receipt=dataclasses.replace(asset.receipt, sha256='e' * 64),
            media=dataclasses.replace(asset.media, artifact=dataclasses.replace(asset.media.artifact, sha256='f' * 64)))
        raw = _candidate_clip_bytes(clips, (changed,))
        expected = _clip_row(row, changed)
        self.assertEqual(json.loads(raw), [expected])
        self.assertEqual(raw, _candidate_clip_bytes(clips, (changed,)))
        self.assertNotEqual(raw, _candidate_clip_bytes(clips, (asset,)))
        self.assertEqual(json.loads(clips[0].row_json), _clip_row(row, asset))

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
        self.assertFalse([name for name in names if any(
            name == prefix or name.startswith(prefix + ".") for prefix in forbidden)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
