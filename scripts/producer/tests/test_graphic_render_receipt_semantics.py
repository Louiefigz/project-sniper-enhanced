"""Exact schema and real-writer tests for graphic render receipts."""

from __future__ import annotations

import copy
import dataclasses
import json
import unittest
from pathlib import Path

from _common import pl  # noqa: F401
from _assembly_receipt_fixture import _Builder, canonical
from _graphic_render_receipt_fixture import graphic_writer_inputs
from headless.graphic_render_receipt_semantics import (
    GraphicRenderReceiptSchemaError,
    parse_graphic_render_receipt_v1,
    validate_graphic_render_receipt_v1,
)
from headless.graphic_render_receipt_writer import (
    GraphicRenderReceiptWriterError,
    build_graphic_render_receipt_v1,
)

IMAGE_ID = "sha256:" + "1" * 64


class _AlwaysEqual:
    def __eq__(self, value: object) -> bool:
        return True


def _builder() -> _Builder:
    value = _Builder()
    value.asset = dataclasses.replace(
        value.asset,
        render_artifact_digest=value.asset.media.artifact.sha256,
        render_build_digest="6" * 64,
    )
    return value


def _writer_inputs() -> tuple:
    return graphic_writer_inputs(_builder(), IMAGE_ID)[:3]


def _mutated(raw: bytes, mutate) -> bytes:
    document = json.loads(raw)
    mutate(document)
    return canonical(document)


class GraphicRenderReceiptSemanticsTests(unittest.TestCase):
    def test_real_normalizer_emits_exact_non_authorizing_receipt(self) -> None:
        authority, row, lane = _writer_inputs()
        receipt = build_graphic_render_receipt_v1(authority, row, lane)
        validate_graphic_render_receipt_v1(receipt)
        self.assertEqual(
            parse_graphic_render_receipt_v1(receipt.document_json), receipt
        )
        self.assertEqual(receipt.graphic_id, "g-00000001")
        self.assertEqual(receipt.selection_id, "g-00000001")
        self.assertEqual(len(receipt.render_input_key), 64)
        self.assertFalse(receipt.claims.execution_attested)
        self.assertFalse(receipt.claims.runtime_verified)
        self.assertFalse(receipt.claims.publication_authorized)

    def test_exact_schema_rejects_overclaim_alias_and_stale_media(
        self,
    ) -> None:
        authority, row, lane = _writer_inputs()
        raw = build_graphic_render_receipt_v1(authority, row, lane).document_json

        def unknown(value: dict) -> None:
            value["unexpected"] = True

        def overclaim(value: dict) -> None:
            value["claims"]["executionAttested"] = True

        def tool_alias(value: dict) -> None:
            value["tools"]["ffprobeSha256"] = value["tools"]["ffmpegSha256"]

        def stale_media(value: dict) -> None:
            value["renderArtifactDigest"] = "0" * 64

        def noncanonical_fps(value: dict) -> None:
            value["media"]["facts"]["fpsNumerator"] = 60
            value["media"]["facts"]["fpsDenominator"] = 2

        def legacy_key(value: dict) -> None:
            value["renderInputKey"] = "a" * 40

        def unsafe_selection(value: dict) -> None:
            value["selectionId"] = "../selection"

        for mutate in (
            unknown,
            overclaim,
            tool_alias,
            stale_media,
            noncanonical_fps,
            legacy_key,
            unsafe_selection,
        ):
            with self.subTest(case=mutate.__name__), self.assertRaises(
                GraphicRenderReceiptSchemaError
            ):
                parse_graphic_render_receipt_v1(_mutated(raw, mutate))

    def test_noncanonical_duplicate_and_direct_construction_reject(
        self,
    ) -> None:
        authority, row, lane = _writer_inputs()
        receipt = build_graphic_render_receipt_v1(authority, row, lane)
        with self.assertRaises(GraphicRenderReceiptSchemaError):
            parse_graphic_render_receipt_v1(b" " + receipt.document_json)
        duplicate = receipt.document_json.replace(
            b'{"admissionArtifactDigest":',
            b'{"admissionArtifactDigest":"'
            + b"0" * 64
            + b'","admissionArtifactDigest":',
            1,
        )
        with self.assertRaises(GraphicRenderReceiptSchemaError):
            parse_graphic_render_receipt_v1(duplicate)
        forged = dataclasses.replace(receipt, render_input_key=_AlwaysEqual())
        with self.assertRaises(GraphicRenderReceiptSchemaError):
            validate_graphic_render_receipt_v1(forged)

    def test_writer_rejects_independent_admission_key_and_snapshot(
        self,
    ) -> None:
        authority, row, original = _writer_inputs()
        cases = []
        admission = copy.deepcopy(original)
        admission["artifactDigest"] = "9" * 64
        cases.append(admission)
        key = copy.deepcopy(original)
        key["result"]["key"] = "8" * 64
        key["result"]["proof"]["copy"]["renderInputKey"] = "8" * 64
        cases.append(key)
        snapshot = copy.deepcopy(original)
        snapshot["result"]["proof"]["runtimeAttestation"]["snapshotSha256"] = "7" * 64
        cases.append(snapshot)
        for lane in cases:
            with self.subTest(lane=lane), self.assertRaises(
                GraphicRenderReceiptWriterError
            ):
                build_graphic_render_receipt_v1(authority, row, lane)

    def test_writer_rejects_malformed_proof_method_objects(self) -> None:
        authority, row, original = _writer_inputs()
        for key, malformed in (
            ("decode", None),
            ("occupancy", []),
            ("terminalFrame", "claimed"),
        ):
            lane = copy.deepcopy(original)
            lane["result"]["proof"][key] = malformed
            with self.subTest(key=key), self.assertRaises(
                GraphicRenderReceiptWriterError
            ):
                build_graphic_render_receipt_v1(authority, row, lane)

    def test_writer_normalizes_malformed_asset_and_authority_values(
        self,
    ) -> None:
        authority, row, original = _writer_inputs()
        lane = copy.deepcopy(original)
        lane["result"]["proof"]["asset"] = ["not", "an", "object"]
        forged = dataclasses.replace(authority, request_digest=_AlwaysEqual())
        for candidate, result in ((authority, lane), (forged, original)):
            with self.subTest(candidate=candidate), self.assertRaises(
                GraphicRenderReceiptWriterError
            ):
                build_graphic_render_receipt_v1(candidate, row, result)

    def test_writer_rejects_hostile_lane_leaf_equality(self) -> None:
        authority, row, original = _writer_inputs()
        cases = []
        selection = copy.deepcopy(original)
        selection["selectionId"] = _AlwaysEqual()
        cases.append(selection)
        output_size = copy.deepcopy(original)
        output_size["outputBinding"]["sizeBytes"] = _AlwaysEqual()
        cases.append(output_size)
        asset_duration = copy.deepcopy(original)
        asset_duration["result"]["proof"]["asset"]["durationS"] = _AlwaysEqual()
        cases.append(asset_duration)
        runtime = copy.deepcopy(original)
        runtime["result"]["proof"]["runtimeAttestation"] = []
        cases.append(runtime)
        for lane in cases:
            with self.subTest(lane=lane), self.assertRaises(
                GraphicRenderReceiptWriterError
            ):
                build_graphic_render_receipt_v1(authority, row, lane)

    def test_writer_closes_all_failures_under_its_error_contract(self) -> None:
        authority, row, original = _writer_inputs()
        aliased = dataclasses.replace(
            authority, proof_ffprobe_sha256=authority.proof_ffmpeg_sha256
        )
        facts = dataclasses.replace(
            authority.media.facts, fps_numerator=60, fps_denominator=2
        )
        non_r0 = dataclasses.replace(
            authority, media=dataclasses.replace(authority.media, facts=facts)
        )
        hostile_proof = copy.deepcopy(original)
        hostile_proof["result"]["proof"]["decode"]["method"] = _AlwaysEqual()
        non_json_row = copy.deepcopy(row)
        non_json_row["spec"]["hostile"] = object()
        cases = (
            (aliased, row, original),
            (non_r0, row, original),
            (authority, row, hostile_proof),
            (authority, non_json_row, original),
        )
        for candidate, plan_row, lane in cases:
            with self.subTest(candidate=candidate), self.assertRaises(
                GraphicRenderReceiptWriterError
            ):
                build_graphic_render_receipt_v1(candidate, plan_row, lane)

    def test_writer_requires_selection_id_to_equal_plan_graphic_id(
        self,
    ) -> None:
        authority, row, lane = _writer_inputs()
        authority = dataclasses.replace(
            authority, selection_id="consistently-rewritten-selection"
        )
        lane["selectionId"] = authority.selection_id
        with self.assertRaises(GraphicRenderReceiptWriterError):
            build_graphic_render_receipt_v1(authority, row, lane)

    def test_writer_rejects_legacy_sha1_even_when_both_sides_agree(
        self,
    ) -> None:
        authority, row, lane = _writer_inputs()
        legacy = "a" * 40
        authority = dataclasses.replace(authority, render_input_key=legacy)
        lane["result"]["key"] = legacy
        lane["result"]["proof"]["copy"]["renderInputKey"] = legacy
        with self.assertRaises(GraphicRenderReceiptWriterError):
            build_graphic_render_receipt_v1(authority, row, lane)

    def test_new_logic_files_obey_repository_line_limit(self) -> None:
        root = Path(__file__).resolve().parents[1] / "headless"
        paths = tuple(root.glob("graphic_render_receipt_*.py"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path.name):
                self.assertLessEqual(len(path.read_text().splitlines()), 300)


if __name__ == "__main__":
    unittest.main(verbosity=2)
