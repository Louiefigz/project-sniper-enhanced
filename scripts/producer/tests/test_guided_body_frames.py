"""Pure synthetic full-program profile checks; no media/approval is fabricated."""
from __future__ import annotations

import copy
import unittest
from fractions import Fraction
from pathlib import Path

from cut_preview_io import digest
from guided_opening_frames import executable_frames, full_program_frames
from guided_opening_inputs import OpeningInputs


def fixture(count: int = 12, rate: str = "30000/1001") -> OpeningInputs:
    """Small TEST-only frame packet, not an authenticated OpeningInputs invocation."""
    presentation = {"schemaVersion": 1, "anchor": "own-screen", "placement": "full-canvas",
        "compositeMode": "normal", "baseTreatment": "preserve", "rationale": "TEST whole-card layout"}
    track, rows, operations, anchors = [], [], [], {}
    for index in range(count):
        start, end = 1 + index * 100, 61 + index * 100
        entry = {"id": f"test-{index}", "kind": "statement-card", "anchor": "own-screen",
            "outStart": float(Fraction(start, 1) / Fraction(rate)),
            "outEnd": float(Fraction(end, 1) / Fraction(rate)), "spec": {"text": "TEST synthetic"}}
        operation = {"type": "catalog-graphic", "startAnchor": f"s-{index}",
            "endAnchorExclusive": f"e-{index}", "presentation": copy.deepcopy(presentation)}
        anchors.update({operation["startAnchor"]: start, operation["endAnchorExclusive"]: end})
        rows.append({"graphicId": entry["id"], "operationIndex": index, "order": index,
            "startFrame": start, "endFrameExclusive": end,
            "presentation": copy.deepcopy(presentation), "entryHash": digest(entry)})
        track.append(entry)
        operations.append(operation)
    plan = {"target": {"mode": "longform", "width": 1920, "height": 1080, "fps": 30},
        "cutTrack": [{"sourceId": "TEST", "in": 0, "out": 100}], "graphicsTrack": track}
    occurrence = {"anchors": anchors, "occurrences": [], "segments": []}
    authority = {"frameRate": rate, "totalFrames": max(200, count * 100), "target": plan["target"],
        "candidatePlanHash": digest(plan), "occurrenceEvidenceHash": digest(occurrence),
        "core": {"startFrame": 0, "endFrameExclusive": 80}, "review": {"startFrame": 0, "endFrameExclusive": 100}}
    bindings = {"schemaVersion": 1, "kind": "guided-frame-presentation-bindings",
        "scope": "controller-frames-and-declared-presentation-not-rendered-proof", "frameRate": rate,
        "totalFrames": authority["totalFrames"], "targetHash": digest(plan["target"]),
        "candidatePlanHash": digest(plan), "occurrenceEvidenceHash": digest(occurrence),
        "graphics": rows, "unboundInheritedGraphicIds": []}
    return OpeningInputs(Path("/TEST/not-an-invocation"), "0" * 64, {}, {"authority": authority,
        "candidatePlan": plan, "frameBindings": bindings, "occurrences": occurrence,
        "readinessPacket": {"proposal": {"operations": operations}}})


def rebind(inputs: OpeningInputs) -> None:
    """Keep local TEST hashes self-consistent; this never creates actual authority."""
    docs = inputs.documents
    for row, entry in zip(docs["frameBindings"]["graphics"], docs["candidatePlan"]["graphicsTrack"]):
        row["entryHash"] = digest(entry)
    for key, value in (("candidatePlanHash", docs["candidatePlan"]), ("occurrenceEvidenceHash", docs["occurrences"])):
        docs["authority"][key] = docs["frameBindings"][key] = digest(value)


class GuidedBodyFrameTests(unittest.TestCase):
    """Later intent must be checked explicitly, never silently filtered away."""

    def test_all_rows_keep_original_order_endpoints_and_documents(self) -> None:
        for rate in ("24", "30000/1001", "24000/1001"):
            inputs = fixture(rate=rate)
            before = copy.deepcopy(inputs.documents)
            with self.subTest(rate=rate):
                self.assertEqual(len(executable_frames(inputs)), 1)
                rows = full_program_frames(inputs)
                self.assertEqual([row["order"] for row in rows], list(range(12)))
                self.assertEqual([row["endFrameExclusive"] for row in rows], list(range(61, 1200, 100)))
                self.assertEqual(inputs.documents, before)

    def test_later_hole_and_placement_intent_blocks_only_full_program(self) -> None:
        for extra in ({"kind": "module-takeover"}, {"kind": "module-scoreboard", "spec": {"presenterFrame": True}},
                      {"takeoverBase": "shrink"}, {"exitOnCut": True}, {"placement": {"x": 0}}):
            inputs = fixture()
            inputs.documents["candidatePlan"]["graphicsTrack"][-1].update(extra)
            rebind(inputs)
            with self.subTest(extra=extra):
                self.assertEqual(len(executable_frames(inputs)), 1)
                with self.assertRaisesRegex(RuntimeError, "placement/effect intent"):
                    full_program_frames(inputs)

    def test_later_declared_free_band_or_blend_cannot_inherit_opening_qualification(self) -> None:
        for field, value in (("anchor", "free-band"), ("compositeMode", "screen"),
                             ("baseTreatment", "dim"), ("rationale", " ")):
            inputs = fixture()
            docs = inputs.documents
            docs["frameBindings"]["graphics"][-1]["presentation"][field] = value
            docs["readinessPacket"]["proposal"]["operations"][-1]["presentation"][field] = value
            with self.subTest(field=field):
                self.assertEqual(len(executable_frames(inputs)), 1)
                with self.assertRaisesRegex(RuntimeError, "graphic presentation"):
                    full_program_frames(inputs)

    def test_eight_graphic_opening_limit_is_not_eight_for_whole_body(self) -> None:
        inputs = fixture(9)
        self.assertEqual(len(full_program_frames(inputs)), 9)
        inputs.documents["authority"]["review"]["endFrameExclusive"] = 900
        with self.assertRaisesRegex(RuntimeError, "eight-graphic"):
            executable_frames(inputs)
        self.assertEqual(len(full_program_frames(inputs)), 9)

    def test_zero_graphics_and_full_128_bound_without_inventing_coverage(self) -> None:
        self.assertEqual(full_program_frames(fixture(0)), [])
        self.assertEqual(len(full_program_frames(fixture(128))), 128)
        with self.assertRaisesRegex(RuntimeError, "whole-candidate coverage"):
            full_program_frames(fixture(129))

    def test_lanes_are_never_removed_to_fit_body_profile(self) -> None:
        for key, value in (("captionsTrack", [{"text": "TEST"}]), ("baselineLook", {"exposure": 1}),
                           ("reframe", {"strategy": "face"}), ("audioGain", [{"gainDb": 2}])):
            inputs = fixture()
            inputs.documents["candidatePlan"][key] = value
            rebind(inputs)
            before = copy.deepcopy(inputs.documents)
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                full_program_frames(inputs)
            self.assertEqual(inputs.documents, before)

    def test_later_entry_endpoints_must_match_occurrences_and_seconds(self) -> None:
        for field, value in (("startFrame", True), ("endFrameExclusive", 1199), ("operationIndex", 0), ("order", 0)):
            inputs = fixture()
            inputs.documents["frameBindings"]["graphics"][-1][field] = value
            with self.subTest(field=field), self.assertRaises((RuntimeError, ValueError)):
                full_program_frames(inputs)

    def test_self_consistent_endpoint_drift_still_fails_plan_seconds(self) -> None:
        inputs = fixture()
        docs = inputs.documents
        docs["frameBindings"]["graphics"][-1]["endFrameExclusive"] += 1
        docs["occurrences"]["anchors"]["e-11"] += 1
        rebind(inputs)
        with self.assertRaisesRegex(RuntimeError, "seconds"):
            full_program_frames(inputs)

    def test_duplicate_or_omitted_operations_reject_even_identical_windows(self) -> None:
        inputs = fixture(2)
        docs = inputs.documents
        docs["readinessPacket"]["proposal"]["operations"].append(copy.deepcopy(
            docs["readinessPacket"]["proposal"]["operations"][1]))
        with self.assertRaisesRegex(RuntimeError, "operation coverage"):
            full_program_frames(inputs)

    def test_duplicate_graphic_ids_and_unknown_binding_fields_reject(self) -> None:
        inputs = fixture(2)
        inputs.documents["candidatePlan"]["graphicsTrack"][1]["id"] = "test-0"
        inputs.documents["frameBindings"]["graphics"][1]["graphicId"] = "test-0"
        rebind(inputs)
        with self.assertRaisesRegex(RuntimeError, "operation coverage"):
            full_program_frames(inputs)
        inputs = fixture()
        inputs.documents["frameBindings"]["graphics"][-1]["bodyApproved"] = True
        with self.assertRaisesRegex(RuntimeError, "closed contract"):
            full_program_frames(inputs)

    def test_invalid_clock_and_stale_candidate_hash_reject(self) -> None:
        for token in ("0", "-24", "1/0", "garbage", True):
            inputs = fixture()
            inputs.documents["authority"]["frameRate"] = inputs.documents["frameBindings"]["frameRate"] = token
            with self.subTest(rate=token), self.assertRaises((RuntimeError, ValueError)):
                full_program_frames(inputs)
        inputs = fixture()
        inputs.documents["candidatePlan"]["graphicsTrack"][-1]["spec"]["text"] = "TEST changed"
        with self.assertRaisesRegex(RuntimeError, "candidate/occurrence bytes"):
            full_program_frames(inputs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
