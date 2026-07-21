"""Closed request and approved-parent regressions for headless quality pass."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import unittest

from _common import pl  # noqa: F401
from fingerprints import base_plan_digest, plan_content_hash
from headless.quality_pass_contract import (
    ApprovedParentV1,
    ArtifactRefV1,
    GraphicAssetRefV1,
    MediaFactsV1,
    MediaRefV1,
    QualityPassContractError,
    QualityPassInputV1,
    graphic_render_intent_digest,
    parse_quality_pass_input,
    validate_approved_parent,
    validate_quality_pass_input,
)
from headless.repair_intent import approved_plan_digest
from headless.repair_intent import current_accent_policy
from headless.quality_policy import current_deterministic_quality_policy

GENERATION = "11111111-1111-4111-8111-111111111111"
REQUEST = "22222222-2222-4222-8222-222222222222"
DIGEST = "a" * 64


def _plan() -> dict:
    return {
        "planVersion": 3,
        "target": {"mode": "short"},
        "graphicsTrack": [
            {
                "id": "g-00000001",
                "kind": "section-marker",
                "outStart": 1.0,
                "outEnd": 3.5,
                "anchor": "free-band",
                "placement": {"x": 50, "y": 100},
                "spec": {
                    "num": "One",
                    "line1": "Old",
                    "line2": "Rule",
                    "side": "left",
                    "accent": "#054BC9",
                },
            }
        ],
        "captions": {"enabled": True},
    }


def _parent_ref(plan: dict) -> dict:
    return {
        "authorityId": "authority-mp4-v1",
        "publicationSeq": 7,
        "generationId": GENERATION,
        "commitDigest": "b" * 64,
        "planDigest": approved_plan_digest(plan),
    }


def _repair(plan: dict) -> dict:
    return {
        "schemaVersion": 1,
        "effectClass": "SECTION_MARKER_ACCENT_V1",
        "realizationKind": "deterministic-mp4",
        "expectedParent": _parent_ref(plan),
        "requestId": REQUEST,
        "target": {"lane": "graphicsTrack", "id": "g-00000001"},
        "op": "replace",
        "relativePointer": "/spec/accent",
        "expectedOld": "#054BC9",
        "value": "#FFD400",
    }


def _document(plan: dict) -> dict:
    return {
        "schemaVersion": 1,
        "operation": "quality-pass",
        "realizationKind": "deterministic-mp4",
        "fallbackPolicy": "none",
        "repairPolicyId": current_accent_policy().policy_id,
        "qualityPolicyId": current_deterministic_quality_policy().policy_id,
        "repairIntent": _repair(plan),
    }


def _artifact(path: str, digest: str = DIGEST, size: int = 10) -> ArtifactRefV1:
    return ArtifactRefV1(path, digest, size)


def _media(path: str, digest: str) -> MediaRefV1:
    artifact = _artifact(path, digest, 100)
    facts = MediaFactsV1(
        width=1080,
        height=1920,
        duration_seconds=4.0,
        fps_numerator=30,
        fps_denominator=1,
        frame_count=120,
        size_bytes=100,
        video_codec="h264",
        pixel_format="yuv420p",
        profile="High",
        alpha_mode="none",
        audio_codec="aac",
    )
    return MediaRefV1(artifact, facts)


def _approved(plan: dict | None = None) -> ApprovedParentV1:
    plan = plan or _plan()
    raw = json.dumps(
        plan, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")
    parsed = parse_quality_pass_input(_document(plan))
    ref = parsed.repair.expected_parent
    asset = GraphicAssetRefV1(
        "g-00000001",
        graphic_render_intent_digest(plan["graphicsTrack"][0]),
        _media("graphics/g-00000001.mov", "e" * 64),
        _artifact("graphics/g-00000001.receipt.json", "f" * 64),
        "1" * 64,
        "2" * 64,
    )
    return ApprovedParentV1(
        ref,
        _artifact("generation-verification.json", "3" * 64),
        parsed.repair_policy_id,
        parsed.quality_policy_id,
        raw,
        _artifact("edit_plan.json", hashlib.sha256(raw).hexdigest(), len(raw)),
        plan_content_hash(plan),
        _media("base_final.mp4", "4" * 64),
        _artifact("base_plan.json", "5" * 64),
        _artifact("base-receipt.json", "6" * 64),
        base_plan_digest(plan),
        _artifact("timeline_map.json", "7" * 64),
        _artifact("prebound-clips.json", "d" * 64),
        (asset,),
        _media("final.mp4", "8" * 64),
        _artifact("assembly-receipt.json", "9" * 64),
        _artifact("cover.png", "a" * 64),
        _artifact("cover-proof.json", "0" * 64),
        _artifact("qc-receipt.json", "b" * 64),
        _artifact("final-approval.json", "c" * 64),
    )


class QualityPassContractTests(unittest.TestCase):
    def test_request_is_closed_canonical_and_domain_separated(self) -> None:
        document = _document(_plan())
        parsed = parse_quality_pass_input(document)
        validate_quality_pass_input(parsed)
        self.assertEqual(parsed.repair.graphic_id, "g-00000001")
        self.assertEqual(len(parsed.request_digest), 64)
        changed = copy.deepcopy(document)
        changed["qualityPolicyId"] = "d" * 64
        self.assertNotEqual(
            parsed.request_digest, parse_quality_pass_input(changed).request_digest
        )

    def test_unknown_fields_boolean_schema_and_fallback_reject(self) -> None:
        cases = []
        extra = _document(_plan())
        extra["unknown"] = True
        cases.append(extra)
        boolean = _document(_plan())
        boolean["schemaVersion"] = True
        cases.append(boolean)
        fallback = _document(_plan())
        fallback["fallbackPolicy"] = "semantic"
        cases.append(fallback)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(QualityPassContractError):
                parse_quality_pass_input(value)

    def test_direct_input_construction_cannot_bypass_parser(self) -> None:
        parsed = parse_quality_pass_input(_document(_plan()))
        forged = QualityPassInputV1(
            parsed.repair,
            parsed.repair_policy_id,
            parsed.quality_policy_id,
            parsed.document_json,
            "0" * 64,
        )
        with self.assertRaisesRegex(QualityPassContractError, "identity"):
            validate_quality_pass_input(forged)

    def test_complete_approved_parent_validates_and_plan_copy_is_disposable(
        self,
    ) -> None:
        parent = _approved()
        validate_approved_parent(parent)
        plan = parent.decoded_plan()
        plan["captions"]["enabled"] = False
        self.assertTrue(parent.decoded_plan()["captions"]["enabled"])

    def test_plan_identities_are_independent_and_all_required(self) -> None:
        parent = _approved()
        cases = (
            dataclasses.replace(
                parent,
                plan_artifact=dataclasses.replace(
                    parent.plan_artifact, sha256="0" * 64
                ),
            ),
            dataclasses.replace(parent, plan_content_hash="0" * 64),
            dataclasses.replace(parent, base_projection_digest="0" * 64),
            dataclasses.replace(
                parent, ref=dataclasses.replace(parent.ref, plan_digest="0" * 64)
            ),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(QualityPassContractError):
                validate_approved_parent(value)

    def test_graphic_asset_set_is_exact_ordered_and_canonical(self) -> None:
        parent = _approved()
        bad_asset = dataclasses.replace(
            parent.graphics_assets[0], graphic_id="legacy-id"
        )
        cases = (
            dataclasses.replace(parent, graphics_assets=()),
            dataclasses.replace(parent, graphics_assets=(bad_asset,)),
            dataclasses.replace(parent, graphics_assets=parent.graphics_assets * 2),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(QualityPassContractError):
                validate_approved_parent(value)

    def test_graphics_only_change_preserves_full_base_projection_digest(self) -> None:
        before = _plan()
        after = copy.deepcopy(before)
        after["graphicsTrack"][0]["spec"]["accent"] = "#FFD400"
        self.assertEqual(base_plan_digest(before), base_plan_digest(after))
        after["captions"]["enabled"] = False
        self.assertNotEqual(base_plan_digest(before), base_plan_digest(after))

    def test_relative_paths_media_lengths_and_digest_shapes_fail_closed(self) -> None:
        parent = _approved()
        escaped = dataclasses.replace(
            parent.timeline_map, relative_path="../timeline_map.json"
        )
        nul = dataclasses.replace(
            parent.timeline_map, relative_path="timeline\x00map.json"
        )
        bad_media = dataclasses.replace(
            parent.base, facts=dataclasses.replace(parent.base.facts, size_bytes=99)
        )
        cases = (
            dataclasses.replace(parent, timeline_map=escaped),
            dataclasses.replace(parent, timeline_map=nul),
            dataclasses.replace(parent, base=bad_media),
            dataclasses.replace(parent, quality_policy_id="short"),
            dataclasses.replace(
                parent,
                cover=dataclasses.replace(
                    parent.cover, relative_path=parent.final.artifact.relative_path
                ),
            ),
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(QualityPassContractError):
                validate_approved_parent(value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
