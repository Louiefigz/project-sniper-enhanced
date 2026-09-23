"""Adversarial cross-binding tests for retained graphic render receipts."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import unittest

from _common import pl  # noqa: F401
from _assembly_receipt_fixture import canonical
from _build_receipt_semantics_fixture import build_receipt_fixture
from headless.build_receipt_binding import bind_build_receipt_semantics
from headless.graphic_render_receipt_binding import (
    GRAPHIC_RENDER_RECEIPT_STATUS,
    GraphicRenderReceiptBindingError,
    GraphicRenderReceiptBindingV1,
    bind_graphic_render_receipts,
    require_graphic_render_execution_authorized,
)
from headless.graphic_render_receipt_admission import (
    _bind_render_build,
    _bind_source,
)
from headless.graphic_render_receipt_binding_checks import (
    checked_binding,
    plan_rows,
)


class _AlwaysEqual:
    def __eq__(self, value: object) -> bool:
        return True


def _binding(value) -> GraphicRenderReceiptBindingV1:
    return GraphicRenderReceiptBindingV1(
        value.runtime_binding,
        value.render_receipt,
        value.plan_json,
        value.graphic_receipts,
        value.admission_manifest_json,
        value.admission_request_json,
        value.graphic_source_seal_jsons,
    )


class GraphicRenderReceiptBindingTests(unittest.TestCase):
    def test_all_structural_relationships_bind_without_authority(self) -> None:
        value = build_receipt_fixture()
        report = bind_graphic_render_receipts(_binding(value))
        self.assertEqual(report.status, GRAPHIC_RENDER_RECEIPT_STATUS)
        self.assertTrue(report.plan_intents_bound)
        self.assertTrue(report.media_refs_bound)
        self.assertTrue(report.receipt_artifacts_bound)
        self.assertTrue(report.build_identity_bound)
        self.assertTrue(report.tool_identities_bound)
        self.assertTrue(report.admission_artifact_bound)
        self.assertTrue(report.source_seals_bound)
        self.assertTrue(report.render_key_bound)
        self.assertEqual(len(report.receipts), 1)
        self.assertEqual(report.receipts[0].ordinal, 0)
        self.assertEqual(report.receipts[0].graphic_id, "g-00000001")
        self.assertFalse(report.media_bytes_reobserved)
        self.assertFalse(report.source_snapshot_reobserved)
        self.assertFalse(report.runtime_verified)
        self.assertFalse(report.dynamic_library_closure_verified)
        self.assertFalse(report.execution_attested)
        self.assertFalse(report.execution_authorized)
        self.assertFalse(report.publication_authorized)
        from graphics.template_contract import validate_entry
        source = json.loads(value.graphic_source_seal_jsons[0])
        row = json.loads(value.plan_json)["graphicsTrack"][0]
        with self.assertRaisesRegex(ValueError, "retired"):
            validate_entry(row, source["compositionHtml"])
        with self.assertRaisesRegex(
            GraphicRenderReceiptBindingError, GRAPHIC_RENDER_RECEIPT_STATUS
        ):
            require_graphic_render_execution_authorized(report)

    def test_build_graph_closes_only_graphic_receipt_blocker(self) -> None:
        report = bind_build_receipt_semantics(build_receipt_fixture())
        codes = tuple(row.code for row in report.unresolved_authority)
        self.assertTrue(report.graphic_receipt_semantics_bound)
        self.assertNotIn("GRAPHIC_RENDER_RECEIPT_SEMANTICS_AND_BINDING", codes)
        self.assertEqual(
            codes,
            (
                "BUILD_SOURCE_AND_TOOL_BYTES_NOT_REOBSERVED",
                "BUILD_EXECUTION_ATTESTATION_UNAVAILABLE",
            ),
        )
        self.assertFalse(report.execution_authorized)
        self.assertFalse(report.publication_authorized)

    def test_admission_key_snapshot_and_order_substitutions_reject(
        self,
    ) -> None:
        def admission(value: dict) -> None:
            value["admissionArtifactDigest"] = "9" * 64

        def key(value: dict) -> None:
            value["renderInputKey"] = "8" * 64

        def snapshot(value: dict) -> None:
            value["sourceSnapshotSha256"] = "7" * 64

        def ordinal(value: dict) -> None:
            value["ordinal"] = 1

        def selection(value: dict) -> None:
            value["selectionId"] = "another-selection"

        for mutate in (admission, key, snapshot, ordinal, selection):
            value = build_receipt_fixture(graphic_mutator=mutate)
            with self.subTest(case=mutate.__name__), self.assertRaises(
                GraphicRenderReceiptBindingError
            ):
                bind_graphic_render_receipts(_binding(value))

    def test_intent_media_build_image_and_tool_substitutions_reject(
        self,
    ) -> None:
        def intent(value: dict) -> None:
            value["renderIntentDigest"] = "9" * 64

        def media(value: dict) -> None:
            digest = "8" * 64
            value["media"]["artifact"]["sha256"] = digest
            value["renderArtifactDigest"] = digest

        def build(value: dict) -> None:
            value["renderBuildDigest"] = "7" * 64

        def image(value: dict) -> None:
            value["runtimeImageId"] = "sha256:" + "6" * 64

        def tool(value: dict) -> None:
            value["tools"]["ffmpegSha256"] = "5" * 64

        def request(value: dict) -> None:
            value["requestDigest"] = "4" * 64

        for mutate in (intent, media, build, image, tool, request):
            value = build_receipt_fixture(graphic_mutator=mutate)
            with self.subTest(case=mutate.__name__), self.assertRaises(
                GraphicRenderReceiptBindingError
            ):
                bind_graphic_render_receipts(_binding(value))

    def test_manifest_and_source_records_are_not_loose_caller_claims(
        self,
    ) -> None:
        value = build_receipt_fixture()
        manifest = json.loads(value.admission_manifest_json)
        manifest["requestDocumentDigest"] = "9" * 64
        changed_manifest = canonical(manifest) + b"\n"
        source = json.loads(value.graphic_source_seal_jsons[0])
        source["snapshotSha256"] = "8" * 64
        changed_source = canonical(source) + b"\n"
        request = json.loads(value.admission_request_json)
        request["overlays"][0]["entry"]["spec"]["line1"] = "other"
        changed_request = canonical(request) + b"\n"
        cases = (
            dataclasses.replace(
                _binding(value), admission_manifest_json=changed_manifest
            ),
            dataclasses.replace(_binding(value), source_seal_jsons=(changed_source,)),
            dataclasses.replace(
                _binding(value), admission_request_json=changed_request
            ),
        )
        for forged in cases:
            with self.subTest(forged=forged), self.assertRaises(
                GraphicRenderReceiptBindingError
            ):
                bind_graphic_render_receipts(forged)

    def test_manifest_rows_are_exact_and_fail_with_domain_error(self) -> None:
        value = build_receipt_fixture()
        manifest = json.loads(value.admission_manifest_json)
        manifest["files"][0] = None
        forged = dataclasses.replace(
            _binding(value), admission_manifest_json=canonical(manifest) + b"\n"
        )
        with self.assertRaises(GraphicRenderReceiptBindingError):
            bind_graphic_render_receipts(forged)

    def test_build_and_snapshot_rows_bind_their_retained_identities(self) -> None:
        value = build_receipt_fixture()
        checked = checked_binding(_binding(value))
        _groups, plan = plan_rows(checked)
        manifest = json.loads(value.admission_manifest_json)
        rows = {row["path"]: row for row in manifest["files"]}
        build_rows = copy.deepcopy(rows)
        build_rows["render-build.json"]["sha256"] = "9" * 64
        with self.assertRaises(GraphicRenderReceiptBindingError):
            _bind_render_build(checked, build_rows)
        snapshot_rows = copy.deepcopy(rows)
        tar_path = next(path for path in rows if path.endswith("render-input.tar"))
        snapshot_rows[tar_path]["sha256"] = "8" * 64
        with self.assertRaises(GraphicRenderReceiptBindingError):
            _bind_source(checked, snapshot_rows, plan[0], 0)

    def test_source_seal_semantics_are_not_just_commit_consistent(self) -> None:
        value = build_receipt_fixture()
        checked = checked_binding(_binding(value))
        _groups, plan = plan_rows(checked)
        source = json.loads(value.graphic_source_seal_jsons[0])
        source["compositionHtml"] = "<forged and inconsistent>"
        source["sourceCompositionSha256"] = hashlib.sha256(
            source["compositionHtml"].encode()
        ).hexdigest()
        raw = canonical(source) + b"\n"
        checked = dataclasses.replace(checked, source_seal_jsons=(raw,))
        manifest = json.loads(value.admission_manifest_json)
        rows = {row["path"]: row for row in manifest["files"]}
        path = next(name for name in rows if name.endswith("source-seal.json"))
        rows[path].update(
            {"sha256": hashlib.sha256(raw).hexdigest(), "sizeBytes": len(raw)}
        )
        with self.assertRaises(GraphicRenderReceiptBindingError):
            _bind_source(checked, rows, plan[0], 0)

    def test_source_snapshot_manifest_derived_sizes_are_bound(self) -> None:
        value = build_receipt_fixture()
        checked = checked_binding(_binding(value))
        _groups, plan = plan_rows(checked)
        source = json.loads(value.graphic_source_seal_jsons[0])
        row = next(
            item
            for item in source["snapshotManifest"]
            if item["path"] == "request/render-intent.json"
        )
        row["sizeBytes"] += 1
        raw = canonical(source) + b"\n"
        checked = dataclasses.replace(checked, source_seal_jsons=(raw,))
        manifest = json.loads(value.admission_manifest_json)
        rows = {item["path"]: item for item in manifest["files"]}
        path = next(name for name in rows if name.endswith("source-seal.json"))
        rows[path].update(
            {"sha256": hashlib.sha256(raw).hexdigest(), "sizeBytes": len(raw)}
        )
        with self.assertRaises(GraphicRenderReceiptBindingError):
            _bind_source(checked, rows, plan[0], 0)

    def test_hostile_equality_and_plan_byte_substitution_reject(self) -> None:
        value = build_receipt_fixture()
        forged_receipt = dataclasses.replace(
            value.graphic_receipts[0], render_input_key=_AlwaysEqual()
        )
        plan = json.loads(value.plan_json)
        plan["graphicsTrack"][0]["spec"]["line1"] = "forged"
        cases = (
            dataclasses.replace(_binding(value), receipts=(forged_receipt,)),
            dataclasses.replace(_binding(value), plan_json=canonical(plan)),
        )
        for forged in cases:
            with self.subTest(forged=forged), self.assertRaises(
                GraphicRenderReceiptBindingError
            ):
                bind_graphic_render_receipts(forged)


if __name__ == "__main__":
    unittest.main(verbosity=2)
