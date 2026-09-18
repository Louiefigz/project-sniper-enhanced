"""Adversarial tests for path-free, plan-bound compositor clip inputs."""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import unittest

from _common import pl  # noqa: F401
from headless.prebound_clips import (
    PreboundClipContractError,
    parse_prebound_clips,
    prebound_clip_set_digest,
    validate_prebound_clips,
)
from headless.quality_pass_contract import (
    ArtifactRefV1,
    GraphicAssetRefV1,
    MediaFactsV1,
    MediaRefV1,
    graphic_render_intent_digest,
)


def _plan_row(index: int = 1) -> dict:
    return {
        "id": f"g-{index:08d}",
        "kind": "section-marker",
        "outStart": float(index),
        "outEnd": float(index) + 2.5,
        "anchor": "free-band",
        "placement": {"x": 40 + index, "y": 90 + index},
        "spec": {
            "num": f"Rule {index}",
            "line1": "Exact",
            "line2": "Binding",
            "side": "left",
            "accent": "#054BC9",
        },
    }


def _artifact(path: str, digest: str, size: int) -> ArtifactRefV1:
    return ArtifactRefV1(path, digest, size)


def _asset(row: dict, marker: str = "a") -> GraphicAssetRefV1:
    media_digest = marker * 64
    receipt_digest = chr(ord(marker) + 1) * 64
    media_artifact = _artifact(
        f"graphics/{row['id']}.mov", media_digest, 100)
    media = MediaRefV1(
        media_artifact,
        MediaFactsV1(
            width=1080, height=1920, duration_seconds=2.5,
            fps_numerator=30, fps_denominator=1, frame_count=75,
            size_bytes=100, video_codec="prores", pixel_format="yuva444p10le",
            profile="4444", alpha_mode="straight", audio_codec=None),
    )
    return GraphicAssetRefV1(
        row["id"],
        graphic_render_intent_digest(row),
        media,
        _artifact(f"graphics/{row['id']}.receipt.json", receipt_digest, 10),
        "d" * 64,
        "e" * 64,
    )


def _clip_row(row: dict, asset: GraphicAssetRefV1) -> dict:
    return {
        "graphicId": row["id"],
        "outStart": row["outStart"],
        "outEnd": row["outEnd"],
        "anchor": row["anchor"],
        "x": row["placement"]["x"],
        "y": row["placement"]["y"],
        "mediaSha256": asset.media.artifact.sha256,
        "renderReceiptSha256": asset.receipt.sha256,
    }


def _document(rows: list[dict]) -> bytes:
    return json.dumps(rows, ensure_ascii=True, separators=(",", ":"),
                      sort_keys=True, allow_nan=False).encode("ascii")


def _fixture() -> tuple[dict, tuple[GraphicAssetRefV1, ...], bytes]:
    row = _plan_row()
    asset = _asset(row)
    plan = {"planVersion": 3, "graphicsTrack": [row]}
    return plan, (asset,), _document([_clip_row(row, asset)])


class PreboundClipContractTests(unittest.TestCase):
    def test_canonical_manifest_binds_and_has_domain_digest(self) -> None:
        plan, assets, document = _fixture()
        clips = parse_prebound_clips(document)
        validate_prebound_clips(clips, plan, assets)
        expected = hashlib.sha256(
            b"sniper-prebound-clip-set-v1\0" + document).hexdigest()
        self.assertEqual(prebound_clip_set_digest(clips), expected)
        self.assertNotEqual(expected, hashlib.sha256(document).hexdigest())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            clips[0].x = 999  # type: ignore[misc]

    def test_only_exact_canonical_immutable_bytes_are_accepted(self) -> None:
        _, _, document = _fixture()
        values = (b" " + document, document + b"\n",
                  document.decode("ascii"), bytearray(document))
        for value in values:
            with self.subTest(value=type(value)), self.assertRaises(
                    PreboundClipContractError):
                parse_prebound_clips(value)  # type: ignore[arg-type]

    def test_unknown_and_graph_effect_clip_fields_are_rejected(self) -> None:
        plan, assets, _ = _fixture()
        base = _clip_row(plan["graphicsTrack"][0], assets[0])
        cases = []
        for key, value in (
                ("unknown", True), ("scaleDims", [1080, 1920]),
                ("takeoverBase", "blur-desat"),
                ("pipHole", {"crop": [1, 2, 3, 4]}),
                ("placedBBox", [0, 0, 100, 100])):
            row = dict(base)
            row[key] = value
            cases.append(row)
        for row in cases:
            with self.subTest(keys=set(row)), self.assertRaisesRegex(
                    PreboundClipContractError, "keys"):
                parse_prebound_clips(_document([row]))

    def test_nonfinite_booleans_bad_windows_and_bad_identifiers_reject(self) -> None:
        plan, assets, _ = _fixture()
        base = _clip_row(plan["graphicsTrack"][0], assets[0])
        cases = []
        for key, value in (
                ("outStart", True), ("x", False), ("outStart", -1),
                ("outEnd", base["outStart"]), ("x", 10 ** 1000),
                ("graphicId", "../g-00000001"),
                ("graphicId", "g-0000\x0001"),
                ("anchor", "focus-shift"),
                ("mediaSha256", "A" * 64)):
            row = dict(base)
            row[key] = value
            cases.append(row)
        for row in cases:
            with self.subTest(row=row), self.assertRaises(
                    PreboundClipContractError):
                parse_prebound_clips(_document([row]))
        nonfinite = dict(base, x=float("nan"))
        raw = json.dumps([nonfinite], ensure_ascii=True, separators=(",", ":"),
                         sort_keys=True, allow_nan=True).encode("ascii")
        with self.assertRaises(PreboundClipContractError):
            parse_prebound_clips(raw)

    def test_direct_dataclass_change_cannot_bypass_row_identity(self) -> None:
        plan, assets, document = _fixture()
        clip = parse_prebound_clips(document)[0]
        for forged in (dataclasses.replace(clip, x=clip.x + 1),
                       dataclasses.replace(clip, x=True)):
            with self.subTest(forged=forged), self.assertRaisesRegex(
                    PreboundClipContractError, "identity"):
                validate_prebound_clips((forged,), plan, assets)

    def test_timing_anchor_and_placement_must_equal_plan(self) -> None:
        plan, assets, document = _fixture()
        clips = parse_prebound_clips(document)
        mutations = []
        for path, value in (("outStart", 1.25), ("outEnd", 4.0),
                            ("anchor", "focus-shift")):
            changed = copy.deepcopy(plan)
            changed["graphicsTrack"][0][path] = value
            mutations.append(changed)
        for axis in ("x", "y"):
            changed = copy.deepcopy(plan)
            changed["graphicsTrack"][0]["placement"][axis] += 1
            mutations.append(changed)
        for changed in mutations:
            with self.subTest(changed=changed), self.assertRaises(
                    PreboundClipContractError):
                validate_prebound_clips(clips, changed, assets)

    def test_asset_media_receipt_and_render_intent_are_all_bound(self) -> None:
        plan, assets, document = _fixture()
        clips = parse_prebound_clips(document)
        asset = assets[0]
        wrong_media = dataclasses.replace(
            asset,
            media=dataclasses.replace(
                asset.media,
                artifact=dataclasses.replace(
                    asset.media.artifact, sha256="c" * 64)),
        )
        wrong_receipt = dataclasses.replace(
            asset,
            receipt=dataclasses.replace(asset.receipt, sha256="c" * 64),
        )
        wrong_intent = dataclasses.replace(asset, render_intent_digest="c" * 64)
        for changed in (wrong_media, wrong_receipt, wrong_intent):
            with self.subTest(asset=changed), self.assertRaisesRegex(
                    PreboundClipContractError, "match"):
                validate_prebound_clips(clips, plan, (changed,))

    def test_counts_duplicates_and_order_fail_closed_before_r0(self) -> None:
        first, second = _plan_row(1), _plan_row(2)
        assets = (_asset(first, "a"), _asset(second, "b"))
        plan = {"graphicsTrack": [first, second]}
        rows = [_clip_row(first, assets[0]), _clip_row(second, assets[1])]
        clips = parse_prebound_clips(_document(rows))
        with self.assertRaisesRegex(PreboundClipContractError, "exactly one"):
            validate_prebound_clips(clips, plan, assets)
        with self.assertRaisesRegex(PreboundClipContractError, "order"):
            validate_prebound_clips(tuple(reversed(clips)), plan, assets)
        with self.assertRaisesRegex(PreboundClipContractError, "order"):
            validate_prebound_clips(clips, plan, tuple(reversed(assets)))
        with self.assertRaisesRegex(PreboundClipContractError, "duplicated"):
            parse_prebound_clips(_document([rows[0], rows[0]]))

    def test_r0_plan_rejects_optional_effects_and_implicit_placement(self) -> None:
        plan, assets, document = _fixture()
        clips = parse_prebound_clips(document)
        cases = []
        for key, value in (("takeoverBase", "blur-desat"),
                           ("pipHole", {}), ("exitOnCut", False)):
            changed = copy.deepcopy(plan)
            changed["graphicsTrack"][0][key] = value
            cases.append(changed)
        scaled = copy.deepcopy(plan)
        scaled["graphicsTrack"][0]["placement"]["scale"] = 1.0
        cases.append(scaled)
        implicit = copy.deepcopy(plan)
        implicit["graphicsTrack"][0].pop("placement")
        cases.append(implicit)
        for changed in cases:
            with self.subTest(changed=changed), self.assertRaises(
                    PreboundClipContractError):
                validate_prebound_clips(clips, changed, assets)


if __name__ == "__main__":
    unittest.main(verbosity=2)
