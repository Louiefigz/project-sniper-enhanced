"""Current build writers and frozen historical cohorts; no production media."""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from _common import pl  # noqa: F401
from _build_manifest_import_closure import dynamic_import_calls, local_import_closure
from _build_receipt_semantics_fixture import compositor_manifest_document, compositor_receipt_bytes
from _current_render_build_fixture import current_receipt as historical_render_v2
from _current_build_release_fixture import current_manifest, current_receipt
from headless import prebound_compositor_build as compositor
from headless import render_build as render
from headless.compositor_build_manifest_v3_semantics import COMPOSITOR_BUILD_V3_IMPLEMENTATION_PATHS
from headless.compositor_build_receipt_semantics import parse_compositor_build_receipt_v1
from headless.compositor_build_receipt_v3_semantics import parse_compositor_build_receipt_v3
from headless.render_build_manifest_v4_semantics import RENDER_BUILD_V4_IMPLEMENTATION_PATHS
from headless.render_build_receipt import encode_render_build_receipt
from headless.render_build_receipt_v2_semantics import parse_render_build_receipt_v2
from headless.render_build_receipt_v4_semantics import parse_render_build_receipt_v4

FROZEN_SOURCES = {
    "headless/compositor_build_manifest_v2_contract.py": "29f24f459685a6457cc84cb2665dfa80a9189956522dacc0c080872b50df0157",
    "headless/compositor_build_manifest_v2_semantics.py": "2dc172d64fd7c105f09b8e95bda057cb961a1b448ef0d4d34cc2cc6dd1ec2ca7",
    "headless/compositor_build_receipt_v2_semantics.py": "5e6edd35c578354bb10f68475fba1f824d45a6ed06e81b63813ab5e0ec6ad81c",
    "headless/render_build_manifest_v3_contract.py": "5b6e2ea67228ceb37695f78897fe68aef2aff001e7db5c657da067c3dbb03910",
    "headless/render_build_manifest_v3_semantics.py": "02d98116ff531f2a5692ae53cebfa16e0d4707b93e8e4d4dc7d0da377d240c3b",
    "headless/render_build_receipt_v3_semantics.py": "8a6ed9eefd8f9c719a80fd079f39ecee41fbff499f41949b507548936e242e99",
    "tests/_pre_catalog_build_fixture.py": "299a400b407afae235c2fe0585c8584e0c52d5ca24d7a179332b8f6cf840be0b",

    "headless/compositor_build_manifest_v1_contract.py": "99409fa994f7da450ba2e61928f44e9c605f7de6d2fabb8bcf7f52c4b8110921",
    "headless/compositor_build_manifest_semantics.py": "592828973aff79515d24f6c48e6a7ecf3968c763fd416f060955d9dfd41c7f07",
    "headless/compositor_build_receipt_semantics.py": "3228def5b2e6a00d7ee59332d464df690487fb7415421ed00ec4ef92c8305d03",
    "headless/render_build_manifest_v2_contract.py": "4420fdd55a836bb2819f2fe79f524533d142a4cf80ea40f4759342c76a5059bc",
    "headless/render_build_manifest_v2_semantics.py": "e568852e1c992598a5b8fb841fc5706867ceb6fc4088275da16742caff262f15",
    "headless/render_build_receipt_v2_semantics.py": "aac67b2d650fdbe497282c007a42962ca5924612d92da9ec290f16828e5f12d5",
    "tests/_current_render_build_fixture.py": "28bca4992e4493bb9e367bebca5b62c3e101aa6b8c489df8f20cb2c2aebea5f9",
    "tests/_build_receipt_semantics_fixture.py": "1081647a3f56b8b5829bdb72a6a41bd45688c26cbc8c8a8ac058b2ac0c3cb634",
}


class CurrentBuildReleaseTests(unittest.TestCase):
    """Current source coverage never mutates the meaning of historical receipts."""

    def test_both_current_catalogs_cover_complete_static_import_closures(self) -> None:
        """Include the version validators themselves as well as renderer sources."""
        for paths in (COMPOSITOR_BUILD_V3_IMPLEMENTATION_PATHS, RENDER_BUILD_V4_IMPLEMENTATION_PATHS):
            with self.subTest(first=paths[0], count=len(paths)):
                self.assertEqual(len(paths), len(set(paths)))
                closure = local_import_closure(paths)
                self.assertFalse(closure - set(paths), sorted(closure - set(paths)))
                self.assertFalse(dynamic_import_calls(closure))
        self.assertIn("templates/motion/tokens.css", COMPOSITOR_BUILD_V3_IMPLEMENTATION_PATHS)
        for paths in (COMPOSITOR_BUILD_V3_IMPLEMENTATION_PATHS, RENDER_BUILD_V4_IMPLEMENTATION_PATHS):
            self.assertIn("schemas/producer/visual-source-policy-v1.json", paths)
            self.assertIn("scripts/producer/graphics/visual_source_policy.py", paths)

    def test_current_compositor_writer_emits_exact_v3_and_rejects_old_context(self) -> None:
        """Current static receipt agrees with current digest, without media proof."""
        raw = compositor.compositor_build_receipt_bytes()
        parsed = parse_compositor_build_receipt_v3(raw)
        self.assertEqual(parsed.build_digest, compositor.compositor_build_digest())
        self.assertEqual(compositor.BUILD_SCHEMA_VERSION, 3)
        self.assertEqual(tuple(row.path for row in parsed.manifest.implementation), compositor._IMPLEMENTATION_FILES)
        with self.assertRaises(RuntimeError):
            parse_compositor_build_receipt_v1(raw)
        historical = parse_compositor_build_receipt_v1(compositor_receipt_bytes(compositor_manifest_document()))
        root, tool = str(Path.cwd().resolve()), str(Path(sys.executable).resolve())
        context = compositor.PreboundCompositorContextV1(root, lambda _ref: root, tool, tool, historical.build_digest)
        with self.assertRaises(RuntimeError):
            compositor.validate_compositor_context(context)

    def test_current_render_receipt_matches_independent_v4_encoding(self) -> None:
        """The current writer, pure parser and source catalog must agree."""
        manifest = current_manifest()
        raw = encode_render_build_receipt(manifest)
        self.assertEqual(raw, current_receipt(manifest))
        parsed = parse_render_build_receipt_v4(raw)
        self.assertEqual(parsed.build_digest, render.render_build_manifest_digest(manifest))
        self.assertEqual(render.BUILD_SCHEMA_VERSION, 4)
        self.assertEqual(render._IMPLEMENTATION_FILES, RENDER_BUILD_V4_IMPLEMENTATION_PATHS)

    def test_loaded_compositor_source_drift_is_not_adopted(self) -> None:
        """A fresh hash result cannot replace the original loaded release identity."""
        with patch.object(compositor, "_implementation_rows", return_value=[]), self.assertRaisesRegex(
                RuntimeError, "closure changed"):
            compositor.compositor_build_manifest()

    def test_historical_wire_bytes_and_digests_stay_reproducible(self) -> None:
        """Both prior formats remain usable only through their historical parsers."""
        raw = compositor_receipt_bytes(compositor_manifest_document())
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "e449db9a82252c6db8d17839ffd12f59aaaffd45d9fa4cf1b87ed3be1b76659f")
        parsed = parse_compositor_build_receipt_v1(raw)
        self.assertEqual(parsed.build_digest, compositor.compositor_build_manifest_digest(json.loads(raw)["manifest"]))
        with self.assertRaises(RuntimeError):
            parse_compositor_build_receipt_v3(raw)
        raw = historical_render_v2()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "5280a351f393361a8d94c7d72d9d1e20b6bf36738b1dddf5b010a19ba2b21d90")
        parsed = parse_render_build_receipt_v2(raw)
        self.assertEqual(parsed.build_digest, render.render_build_manifest_digest(json.loads(raw)["manifest"]))
        with self.assertRaises(RuntimeError):
            parse_render_build_receipt_v4(raw)

    def test_pre_catalog_receipts_remain_readable_but_not_current(self) -> None:
        """Preserve V2/V3 history without allowing its policy to authorize new work."""
        from _pre_catalog_build_fixture import current_compositor_receipt as old_compositor
        from _pre_catalog_build_fixture import current_receipt as old_render
        from headless.compositor_build_receipt_v2_semantics import parse_compositor_build_receipt_v2
        from headless.render_build_receipt_v3_semantics import parse_render_build_receipt_v3
        for raw, historical, current, compute in (
            (old_compositor(), parse_compositor_build_receipt_v2,
             parse_compositor_build_receipt_v3, compositor.compositor_build_manifest_digest),
            (old_render(), parse_render_build_receipt_v3,
             parse_render_build_receipt_v4, render.render_build_manifest_digest),
        ):
            parsed = historical(raw)
            self.assertEqual(parsed.document_json, raw)
            self.assertEqual(parsed.build_digest, compute(json.loads(parsed.manifest.document_json)))
            with self.assertRaises(RuntimeError):
                current(raw)

    def test_frozen_sources_and_fixtures_remain_exact_bytes(self) -> None:
        """Prevent compatibility tests from following a silently rewritten baseline."""
        root = Path(__file__).resolve().parents[1]
        for name, expected in FROZEN_SOURCES.items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
