"""Adversarial original observation projection tests; no fresh pixel/admission claim."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import unittest

from _guided_presenter_read_fixture import PresenterReadFixture
from guided_presenter_read import read_presenter_graphs, verify_opening_presenter_layers
from opening_prefix_contract import canonical_hash


class PresenterReadRecordTests(unittest.TestCase):
    """Malformed summaries cannot acquire source identity or change graph geometry."""

    def setUp(self) -> None:
        """Create controlled original stub observations under actual tiny file identities."""
        self.fixture = PresenterReadFixture()
        self.addCleanup(self.fixture.close)

    def test_missing_extra_duplicate_unknown_policy_and_graph_metadata_refuse(self) -> None:
        """Closed inventories, actual pixel class and per-occurrence coverage remain exact."""
        source = self.fixture.records
        mutations = [("policy", "other"), ("scope", "approved"), ("admissionHash", "f" * 64),
            ("requestedFrameRate", "30/1"), ("graphFrameRate", "30"), ("headerSha256", "bad"),
            ("framesSha256", "F" * 64)]
        variants = [[], [*deepcopy(source), *deepcopy(source)], [{**deepcopy(source[0]), "extra": True}]]
        variants += [[{**deepcopy(source[0]), key: value}] for key, value in mutations]
        asset_changes = {"kind": "still-image", "total_frames": 4, "zero_origin": 1,
            "sample_aspect_ratio": "0:1", "color_policy": "unqualified", "width": 66,
            "pixel_format": "yuv420p10le", "asset_id": "missing", "path": "/TEST/substitution"}
        variants += [[{**deepcopy(source[0]), "graphAsset": {**source[0]["graphAsset"], key: value}}]
                     for key, value in asset_changes.items()]
        for index, rows in enumerate(variants):
            with self.subTest(index=index), self.assertRaises((RuntimeError, ValueError)):
                read_presenter_graphs(rows, self.fixture.context)

    def test_source_tool_sha_size_stat_and_exact_commands_are_independently_bound(self) -> None:
        """A matching self-hash does not permit different current files or argv."""
        variants = []
        for role in ("source", "ffprobe"):
            for key, value in (("path", "/TEST/other"), ("sha256", "e" * 64), ("size_bytes", 1),
                               ("statIdentityEncoding", "numbers"), ("stat_identity", [0] * 9)):
                rows = deepcopy(self.fixture.records)
                rows[0][role][key] = value
                variants.append(rows)
        for key, value in (("commands", []), ("commandSha256", []), ("pngMetadata", {})):
            variants.append([{**deepcopy(self.fixture.records[0]), key: value}])
        for index, rows in enumerate(variants):
            with self.subTest(index=index), self.assertRaises((RuntimeError, ValueError)):
                read_presenter_graphs(rows, self.fixture.context)

    def test_attestation_digests_are_not_mislabeled_as_recomputed_raw_stdout(self) -> None:
        """Only the outer authenticated receipt can certify unseen original stdout hashes."""
        rows = deepcopy(self.fixture.records)
        rows[0]["framesSha256"] = "e" * 64
        result = read_presenter_graphs(rows, self.fixture.context)
        self.assertEqual(result.observations[0]["framesSha256"], "e" * 64)
        self.assertFalse(result.executable)
        self.assertIn("original-worker-attestations", result.scope)

    def test_observation_order_is_not_graph_input_order(self) -> None:
        """Two source records may reorder; graph inputs retain actual selected first-use order."""
        fixture = PresenterReadFixture(two_assets=True)
        self.addCleanup(fixture.close)
        original = read_presenter_graphs(fixture.records, fixture.context)
        records = list(reversed(deepcopy(fixture.records)))
        reordered = read_presenter_graphs(records, fixture.context)
        self.assertEqual(reordered.full, original.full)
        self.assertEqual(reordered.assets, original.assets)
        self.assertNotEqual(reordered.observations, original.observations)
        pictures = deepcopy(fixture.pictures)
        pictures["presenterLayers"]["observations"] = records
        self.assertEqual(verify_opening_presenter_layers(pictures, fixture.context, ((), None)).full, original.full)

    def test_exact_new_profiles_and_original_base_tool_not_receipt_declared_replacements(self) -> None:
        """A legacy token cannot execute new semantics or borrow another probe identity."""
        inputs = self.fixture.inputs
        context = replace(self.fixture.context, inputs=replace(inputs, value={**inputs.value, "profile": "unity-source-float-own-screen-v1"}))
        with self.assertRaisesRegex(RuntimeError, "new profile"):
            read_presenter_graphs(self.fixture.records, context)
        context = replace(self.fixture.context, ffprobe=replace(self.fixture.tool, sha256="b" * 64))
        with self.assertRaisesRegex(RuntimeError, "independently held"):
            read_presenter_graphs(self.fixture.records, context)


class PresenterReadPngTests(unittest.TestCase):
    """Original exact tagged PNG metadata survives canonical JSON without frame reads."""

    def test_actual_chunk_projection_roundtrip_and_malformed_hex_inventory_reject(self) -> None:
        """These are real tiny PNG chunk bytes but stubbed decoder/admission facts."""
        fixture = PresenterReadFixture(image=True)
        self.addCleanup(fixture.close)
        result = verify_opening_presenter_layers(fixture.pictures, fixture.context, ((), None))
        self.assertEqual(result.full["windows"][0]["asset"]["kind"], "still-image")
        self.assertEqual(result.observations[0]["pngMetadata"]["metadataEncoding"], "hex")
        for key, value in (("metadataEncoding", "raw"), ("width", 64.0), ("metadata", [["sRGB", "FF"]]),
                           ("metadata", [["sRGB", " 01"]]), ("chunks", []), ("metadata_bytes_read", 1)):
            rows = deepcopy(fixture.records)
            rows[0]["pngMetadata"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises((RuntimeError, ValueError)):
                read_presenter_graphs(rows, fixture.context)
        self.assertEqual(canonical_hash(result.full), fixture.pictures["presenterLayers"]["fullPresenterGraphHash"])


if __name__ == "__main__":
    unittest.main()
