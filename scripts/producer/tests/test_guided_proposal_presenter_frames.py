"""Actual V8 schema, source/window and executor-geometry fault tests; no media."""
from __future__ import annotations

from copy import deepcopy
import unittest

from _guided_proposal_presenter_fixture import noop, operation, values
from _guided_proposal_music_fixture import values as music_values
from guided_media_profile import CAPTION_SHORT_PROFILE
from guided_proposal_presenter import guided_presenter_policy, validate_requested_presenter
from guided_proposal_reframe import validate_requested_manual_crop


class PresenterFrameTests(unittest.TestCase):
    """Authoring intent is not proof of source clocks or executable geometry."""

    def test_actual_indices_sort_chronologically_without_changing_packet(self) -> None:
        """Source IDs derive from half-open overlap order, not all manifest sources."""
        late, early = operation(), operation()
        late.update(startAnchor=20, endAnchorExclusive=30)
        late["presenterLayout"]["sourceIds"] = ["raw-2"]
        early.update(startAnchor=0, endAnchorExclusive=10)
        early["presenterLayout"]["sourceIds"] = ["raw-2"]
        rows = values(operations=[late, noop(), early])
        before = deepcopy(rows)
        result = validate_requested_presenter(*rows)
        self.assertEqual([row["operationIndex"] for row in result.windows], [2, 0])
        self.assertEqual(rows, before)
        self.assertEqual(result.prior_packet["proposal"]["clauses"][0]["operationIndices"], [0, 1, 2])
        result.prior_packet["rawRequest"]["rawIntent"] = "changed"
        self.assertEqual(rows, before)

    def test_original_utf16_request_cannot_be_rewritten_or_split(self) -> None:
        """Unicode quotes and actual operation links survive local version validation."""
        changes = [{"quote": "changed"}, {"start": 1}, {"operationIndices": []}, {"operationIndices": [1]},
                   {"operationIndices": [0, 0]}, {"disposition": "blocked"}]
        for change in changes:
            rows = values()
            rows[2]["proposal"]["clauses"][0].update(change)
            with self.subTest(change=change), self.assertRaises((RuntimeError, ValueError)):
                validate_requested_presenter(*rows)
        rows = values()
        rows[2]["rawRequest"]["rawIntent"] += " extra"
        with self.assertRaisesRegex(RuntimeError, "request"):
            validate_requested_presenter(*rows)

    def test_timed_payloads_are_never_laundered_by_validation_view(self) -> None:
        """Every old payload remains null; original timing/beat/reason are checked first."""
        changes = [{"music": {"schemaVersion": 1, "assetId": "bed", "gapDb": 11, "duck": True}},
            {"presenterLayout": None}, {"reason": " "}, {"reason": None}, {"beatIndex": None},
            {"beatIndex": 1}, {"startAnchor": 28}, {"startAnchor": -1}, {"endAnchorExclusive": 31},
            {"extra": True}, {"clauseIndex": 1}, {"reframe": {}}, {"grade": {}}, {"captions": {}}]
        for change in changes:
            rows = values()
            rows[2]["proposal"]["operations"][0].update(change)
            with self.subTest(change=change), self.assertRaises((RuntimeError, ValueError)):
                validate_requested_presenter(*rows)
        rows = values(operations=[noop()])
        rows[2]["proposal"]["operations"][0]["presenterLayout"] = operation()["presenterLayout"]
        with self.assertRaises((RuntimeError, ValueError)):
            validate_requested_presenter(*rows)

    def test_actual_v8_schema_and_closed_typed_geometry_are_mandatory(self) -> None:
        """Const equality, nonfinite numbers and extra fields cannot bypass real types."""
        changes = [{"schemaVersion": True}, {"track": 0}, {"track": True}, {"easing": "linear"},
            {"assetAudio": "mix"}, {"cropSpace": "source"}, {"sourceIds": []}, {"sourceIds": ["raw-2", "raw-2"]},
            {"assetStart": {"numerator": 0, "denominator": 2}}, {"assetStart": {"numerator": True, "denominator": 1}},
            {"enterFrames": 0}, {"exitFrames": False}, {"mask": {"kind": "rect"}}, {"extra": None}]
        changes += [{"presenterCrop": {"x": bad, "y": 0, "width": 1, "height": 1}}
                    for bad in (False, -0.0, float("nan"), float("inf"), 10**400)]
        for change in changes:
            rows = values()
            rows[2]["proposal"]["operations"][0]["presenterLayout"].update(change)
            with self.subTest(change=change), self.assertRaises((RuntimeError, ValueError)):
                validate_requested_presenter(*rows)
        rows = values()
        del rows[2]["proposal"]["operations"][0]["presenterLayout"]
        with self.assertRaises((RuntimeError, ValueError)):
            validate_requested_presenter(*rows)

    def test_clock_partition_and_source_identity_faults_reject(self) -> None:
        """Neither caller-selected source order nor incomplete segments can own a window."""
        changes = [{"frameRate": value} for value in ("30", "030/1", "60/2", "0/1", "30/0", ["30/1"], "9007199254740993/1")]
        changes += [{"totalFrames": value} for value in (0, True, 601, 1_000_000_001)]
        changes += [{"anchors": value} for value in ([0, 600, 600], [1, 600], [0, 400], [0, True, 600])]
        for change in changes:
            rows = values()
            rows[2]["evidence"].update(change)
            with self.subTest(change=change), self.assertRaises((RuntimeError, ValueError)):
                validate_requested_presenter(*rows)
        for change in ({"index": True}, {"startFrame": 1}, {"endFrameExclusive": 199}, {"sourceId": "raw-1"}):
            rows = values()
            rows[2]["evidence"]["segments"][0].update(change)
            with self.assertRaises((RuntimeError, ValueError)):
                validate_requested_presenter(*rows)
        rows = values()
        rows[2]["proposal"]["operations"][0]["presenterLayout"]["sourceIds"].reverse()
        with self.assertRaisesRegex(RuntimeError, "chronological"):
            validate_requested_presenter(*rows)

    def test_maximum_windows_overlap_and_complete_ramp_hold(self) -> None:
        """No ambiguous overlap or missing last-frame return can be excused by hashing."""
        for operations in ([operation(), operation()], [operation()] * 33):
            with self.assertRaisesRegex(RuntimeError, "overlap|32"):
                validate_requested_presenter(*values(operations=operations))
        rows = values()
        for layout in (rows[1]["presenterLayouts"][0]["layout"], rows[2]["proposal"]["operations"][0]["presenterLayout"]):
            layout.update(enterFrames=260, exitFrames=259)
        self.assertEqual(len(validate_requested_presenter(*rows).windows), 1)
        rows[2]["proposal"]["operations"][0]["presenterLayout"]["exitFrames"] = 260
        with self.assertRaisesRegex(ValueError, "ramps"):
            validate_requested_presenter(*rows)

    def test_exact_32_disjoint_windows_keep_every_actual_occurrence(self) -> None:
        """The cap is inclusive; repeated assets retain separate operation/frame records."""
        plan, candidate, packet, manifest = values()
        packet["evidence"]["anchors"] = list(range(0, 601, 5))
        packet["proposal"]["beats"][0]["endAnchorExclusive"] = 120
        packet["proposal"].update(openingEndAnchor=120, continuityEndAnchor=120)
        operations, windows = [], []
        for index in range(32):
            row, start, end = operation(), index * 15, (index + 1) * 15
            row.update(startAnchor=start // 5, endAnchorExclusive=end // 5)
            sources = list(dict.fromkeys(segment["sourceId"] for segment in packet["evidence"]["segments"]
                if segment["startFrame"] < end and segment["endFrameExclusive"] > start))
            row["presenterLayout"].update(sourceIds=sources, enterFrames=1, exitFrames=1)
            operations.append(row)
            windows.append({"operationIndex": index, "startFrame": start, "endFrameExclusive": end, "layout": deepcopy(row["presenterLayout"])})
        packet["proposal"]["operations"] = operations
        packet["proposal"]["clauses"][0]["operationIndices"] = list(range(32))
        candidate["presenterLayouts"] = windows
        self.assertEqual(list(validate_requested_presenter(plan, candidate, packet, manifest).windows), windows)

    def test_executor_geometry_is_explicitly_narrower_than_authoring(self) -> None:
        """No-upscale/even-canvas class is an intake policy, not observed pixel metadata."""
        for size in ((16384, 9216), (1921, 1080)):
            rows = values()
            for target in (rows[0]["target"], rows[1]["target"], rows[2]["evidence"]["target"]):
                target.update(width=size[0], height=size[1])
            with self.assertRaises(ValueError):
                validate_requested_presenter(*rows)
        rows = values()
        crop = {"x": .3, "y": .3, "width": .4, "height": .4}
        rows[2]["proposal"]["operations"][0]["presenterLayout"].update(presenterCrop=crop,
            presenterRect={"x": .2, "y": .2, "width": .5, "height": .5})
        with self.assertRaisesRegex(ValueError, "upscale"):
            validate_requested_presenter(*rows)

    def test_existing_crop_validator_only_receives_local_view(self) -> None:
        """A V8 no-presenter crop/caption/music proposal preserves the old lane parser."""
        plan, candidate, packet, manifest = music_values(crop=True)
        packet["proposal"]["schemaVersion"] = packet["evidence"]["schemaVersion"] = 8
        for operation in packet["proposal"]["operations"]:
            operation["presenterLayout"] = None
        packet["evidence"]["presenterPolicy"] = guided_presenter_policy(plan, manifest)
        before = deepcopy(packet)
        result = validate_requested_presenter(plan, candidate, packet, manifest)
        self.assertEqual(result.windows, ())
        self.assertTrue(validate_requested_manual_crop(plan, candidate, result.prior_packet, CAPTION_SHORT_PROFILE))
        self.assertEqual(packet, before)


if __name__ == "__main__":
    unittest.main()
