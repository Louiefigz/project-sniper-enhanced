"""DRAFT inert geometry tests; TEST observation stubs are NOT renderer evidence."""
from __future__ import annotations

import copy
import unittest

from cut_preview_io import digest
from guided_caption_layout import inspect_layout

H = "a" * 64
REF = {"path": "/TEST-only/template.html", "sha256": H}


def fixture(portrait: bool = False) -> dict:
    """Construct a closed TEST geometry packet, not authentic render authority."""
    width, height = (1080, 1920) if portrait else (1920, 1080)
    clock = {"frameRate": "30000/1001", "totalFrames": 9325, "width": width, "height": height}
    binding = {**clock, "graphicId": "TEST-g", "entryHash": H, "specHash": H,
        "template": REF, "sources": [REF, {"path": "/TEST-only/tokens.css", "sha256": H},
        {"path": "/TEST-only/motion.js", "sha256": H}], "executionInputHash": H,
        "graphicRequestHash": H, "graphicMediaSha256": H}
    graphic = {"graphicId": "TEST-g", "order": 0, "entryHash": H, "startFrame": 682,
               "endFrameExclusive": 793, "binding": binding}
    cue = {"cueId": "TEST-cue", "startFrame": 693, "endFrameExclusive": 809,
           "media": {"path": "/TEST-only/shard.mov", "sha256": H},
           "shapedSafeBounds": {"minX": 300, "maxX": 699, "minY": 648, "maxY": 759, "framesMeasured": 116}}
    declaration = {"schemaVersion": 1, "kind": "native-caption-layout-declaration", "binding": copy.deepcopy(binding),
                   "captionClearRect": [240, 620, width - 240, 790], "gutterPx": 8,
                   "protectedRoles": ["headline", "footline"]}
    return {"schemaVersion": 1, "kind": "held-caption-layout-input", "clock": clock,
            "captionProjectionHash": H, "cues": [cue], "graphics": [graphic], "declarations": [declaration]}


def observation(value: dict, boxes: list[list[int]] | None = None, index: int = 0) -> tuple[dict, dict]:
    """Build explicit TEST owner-reader facts for pure branch tests only."""
    graphic, declaration = value["graphics"][index], value["declarations"][0]
    boxes = boxes or [[100, 100, 900, 300], [100, 820, 900, 860]]
    roles = [{"id": name, "bounds": box, "overflow": False}
             for name, box in zip(declaration["protectedRoles"], boxes, strict=True)]
    return ({"path": "/TEST-only/owned-geometry.json", "sha256": H}, {
        "schemaVersion": 1, "kind": "native-caption-layout-observation", "binding": copy.deepcopy(graphic["binding"]),
        "declarationHash": digest(declaration), "startFrame": graphic["startFrame"],
        "endFrameExclusive": graphic["endFrameExclusive"],
        "framesObserved": graphic["endFrameExclusive"] - graphic["startFrame"], "roles": roles})


def evaluate(value: dict, returned: tuple | None = None) -> dict:
    """Only geometry, no file-reader/renderer/approval side effects."""
    return inspect_layout(value, lambda _binding, _declaration: returned, lambda: None)


def retained_graphics(value: dict, selected: int) -> None:
    """Keep all real occurrence IDs/order/entry hashes; render refs stay TEST-only."""
    rows = [
        ("g-afb7e1d1", 25, 113, "9ea71a9d05ec8e9e8e50f53440a019d14d9e7516f75cc41f9f8a5a35f996d09b"),
        ("g-5a94d147", 406, 561, "05fbb5985611dfb92c9bd49ceaa3f5a68d83e9b4ef76dedbd78d3d429da85e85"),
        ("g-b0451408", 682, 793, "bc868bc8f6f5b468b0df2d751f1fd875e10ec89f4765b60cd6a231238bfd5e3d"),
        ("g-640726c0", 1004, 1209, "e49173efa00fb74eac81fcd1f3bd4646cbdcbe283416f1fa9eddc56d78317f53"),
        ("g-b2456b21", 1377, 1532, "49d490a5dfc9b322a7c9bcfd1e90e0f9352c916d9aa9bd5dd7badb8140ea298c"),
        ("g-3ceb3564", 1642, 1753, "b09758f7bd95a2e836ef5c32fc459a7bf18b8659154e6da98d9b5b2ad74931ce"),
        ("g-51f25587", 1964, 2065, "8667388b36ed451c5a93ca9248a89918a9b9d35e89db7ab9e5707d07eac973a2"),
        ("g-c770873c", 2346, 2398, "8d7d57d461d4059d75030a3edfc2f8893279d0903e602f65a740f3484e845d7d"),
    ]
    binding = value["graphics"][0]["binding"]
    value["graphics"] = [{"graphicId": name, "entryHash": sha, "order": index,
        "startFrame": start, "endFrameExclusive": end,
        "binding": {**copy.deepcopy(binding), "graphicId": name, "entryHash": sha}}
        for index, (name, start, end, sha) in enumerate(rows)]
    value["declarations"][0]["binding"] = copy.deepcopy(value["graphics"][selected]["binding"])


class LayoutTests(unittest.TestCase):
    """Declared versus measured authority and exact geometry failures."""

    def test_declaration_alone_is_unqualified(self) -> None:
        result = evaluate(fixture())
        self.assertEqual(result["state"], "unqualified")
        self.assertEqual(result["graphics"][0]["intersections"], [
            {"cueId": "TEST-cue", "startFrame": 693, "endFrameExclusive": 793}])
        self.assertFalse(result["qcPassed"])

    def test_no_declaration_is_unqualified_and_never_calls_reader(self) -> None:
        value = fixture()
        value["declarations"] = []
        result = inspect_layout(value, lambda *_: self.fail("must not read"), lambda: None)
        self.assertEqual(result["state"], "unqualified")

    def test_screened_geometry_is_not_quality_or_delivery_approval(self) -> None:
        value = fixture()
        result = evaluate(value, observation(value))
        self.assertEqual(result["state"], "screened-no-overlap")
        self.assertFalse(result["qcPassed"] or result["creativeApproved"] or result["deliveryApproved"])

    def test_caption_free_window_preserves_not_applicable(self) -> None:
        value = fixture()
        value["cues"][0].update(startFrame=793, endFrameExclusive=909)
        value["declarations"] = []
        result = inspect_layout(value, lambda *_: self.fail("must not read"), lambda: None)
        self.assertEqual(result["state"], "not-applicable")

    def test_no_captions_needs_no_geometry_reader(self) -> None:
        value = fixture()
        value["cues"], value["declarations"] = [], []
        value["captionProjectionHash"] = None
        self.assertEqual(evaluate(value)["state"], "not-applicable")

    def test_whole_cue_origin_is_not_restarted_at_opening_trim(self) -> None:
        value = fixture()
        value["cues"][0].update(startFrame=577, endFrameExclusive=693)
        result = evaluate(value, observation(value))
        pair = result["graphics"][0]["intersections"][0]
        self.assertEqual((pair["startFrame"], pair["endFrameExclusive"]), (682, 693))

    def test_inclusive_alpha_maximum_reaches_final_pixel(self) -> None:
        value = fixture()
        value["declarations"][0]["gutterPx"] = 0
        proof = observation(value, [[699, 650, 710, 700], [100, 820, 900, 860]])
        self.assertEqual(evaluate(value, proof)["state"], "envelope-conflict")

    def test_touching_half_open_pixel_edges_do_not_overlap(self) -> None:
        value = fixture()
        value["declarations"][0]["gutterPx"] = 0
        proof = observation(value, [[700, 650, 710, 700], [100, 820, 900, 860]])
        self.assertEqual(evaluate(value, proof)["state"], "screened-no-overlap")

    def test_readability_gutter_is_explicit_not_silently_ignored(self) -> None:
        value = fixture()
        proof = observation(value, [[704, 650, 710, 700], [100, 820, 900, 860]])
        self.assertEqual(evaluate(value, proof)["state"], "envelope-conflict")

    def test_measured_caption_outside_declared_region_conflicts(self) -> None:
        value = fixture()
        value["declarations"][0]["captionClearRect"][3] = 750
        result = evaluate(value, observation(value))
        self.assertIn("caption-outside-declared-clear-region", result["graphics"][0]["intersections"][0]["conflicts"])

    def test_portrait_native_geometry_is_not_landscape_clamped(self) -> None:
        value = fixture(True)
        value["cues"][0]["shapedSafeBounds"].update(minX=300, maxX=700, minY=1200, maxY=1339)
        value["declarations"][0]["captionClearRect"] = [240, 1150, 840, 1400]
        self.assertEqual(evaluate(value, observation(value))["state"], "screened-no-overlap")

    def test_out_of_frame_empty_nonfinite_boolean_and_partial_rects_reject(self) -> None:
        for box in ([0, 0, 1921, 100], [-1, 0, 100, 100], [0, 0, 0, 100],
                    [0, 0, 100, float("nan")], [False, 0, 100, 100], [0, 0, 100]):
            value = fixture()
            value["declarations"][0]["captionClearRect"] = box
            try:
                result = evaluate(value, None)
            except (TypeError, ValueError):
                continue
            self.assertEqual(result["state"], "unqualified", box)

    def test_clock_or_shard_frame_coverage_mismatch_rejects(self) -> None:
        for field, replacement in (("framesMeasured", 115), ("minY", -1), ("maxY", 1080), ("maxX", True)):
            value = fixture()
            value["cues"][0]["shapedSafeBounds"][field] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError):
                evaluate(value)

    def test_noncanonical_rate_and_unsupported_canvas_reject(self) -> None:
        for field, replacement in (("frameRate", "60000/2002"), ("frameRate", "0/1"), ("width", 3840), ("height", True)):
            value = fixture()
            value["clock"][field] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError):
                evaluate(value)

    def test_template_css_js_spec_media_and_execution_changes_are_unqualified(self) -> None:
        for key in ("entryHash", "specHash", "graphicRequestHash", "graphicMediaSha256", "executionInputHash"):
            value = fixture()
            value["declarations"][0]["binding"][key] = "b" * 64
            with self.subTest(key=key):
                self.assertEqual(evaluate(value)["state"], "unqualified")
        for index in range(3):
            value = fixture()
            value["declarations"][0]["binding"]["sources"][index]["sha256"] = "b" * 64
            self.assertEqual(evaluate(value)["state"], "unqualified")

    def test_transplanted_observation_self_assertion_and_missing_roles_do_not_pass(self) -> None:
        value = fixture()
        for mutate in (lambda row: row.update(kind="self-declared-geometry"),
                       lambda row: row.update(declarationHash="b" * 64),
                       lambda row: row.update(framesObserved=1),
                       lambda row: row["binding"].update(totalFrames=9325.0),
                       lambda row: row.update(roles=row["roles"][:1]),
                       lambda row: row["roles"][0].update(overflow=True),
                       lambda row: row["binding"].update(graphicMediaSha256="b" * 64)):
            proof = observation(value)
            mutate(proof[1])
            self.assertEqual(evaluate(value, proof)["state"], "unqualified")

    def test_direct_serialized_observation_cannot_replace_owned_reader_tuple(self) -> None:
        value = fixture()
        self.assertEqual(evaluate(value, observation(value)[1])["state"], "unqualified")

    def test_unknown_input_fields_duplicate_cues_and_reordered_graphics_reject(self) -> None:
        for mutate in (lambda row: row.update(approved=True),
                       lambda row: row["cues"].append(copy.deepcopy(row["cues"][0])),
                       lambda row: row["graphics"][0].update(order=1)):
            value = fixture()
            mutate(value)
            with self.assertRaises(ValueError):
                evaluate(value)

    def test_unexpected_reader_error_and_original_clock_expiry_never_pass(self) -> None:
        value = fixture()
        def fail(*_args: object) -> None:
            raise RuntimeError("TEST original deadline/reader failed")
        with self.assertRaises(RuntimeError):
            inspect_layout(value, fail, lambda: None)
        with self.assertRaises(RuntimeError):
            inspect_layout(value, lambda *_: None, fail)

    def test_mutation_during_last_reader_rejects(self) -> None:
        value = fixture()
        def mutate(_binding: dict, _declaration: dict) -> tuple:
            result = observation(value)
            value["cues"][0]["shapedSafeBounds"]["maxX"] += 1
            return result
        with self.assertRaisesRegex(ValueError, "changed"):
            inspect_layout(value, mutate, lambda: None)

    def test_observation_mutation_at_final_strong_read_is_unqualified(self) -> None:
        value, calls = fixture(), []
        def mutate(_binding: dict, _declaration: dict) -> tuple:
            proof = observation(value)
            if calls:
                proof[1]["roles"][0]["bounds"][0] += 1
            calls.append(True)
            return proof
        result = inspect_layout(value, mutate, lambda: None)
        self.assertEqual(result["state"], "unqualified")
        self.assertEqual(len(calls), 2)


class RetainedCollisionTests(unittest.TestCase):
    """Real held cue/frame geometry; manual TEST label boxes, never DOM evidence.

    Original NTSC shard/cue facts and source hashes are recorded in REVIEW_NOTES.
    Label boxes below are conservative manual traces from retained native JPGs.
    The TEST observation reader must NOT be substituted for a sealed renderer.
    """

    def test_pipeline_footline_and_node_collision_geometry(self) -> None:
        value = fixture()
        retained_graphics(value, 2)
        cue = value["cues"][0]
        cue.update(cueId="cue-01d4d448cc1e3c6e", startFrame=693, endFrameExclusive=809)
        cue["shapedSafeBounds"].update(minX=682, maxX=1237, minY=648, maxY=759, framesMeasured=116)
        value["declarations"][0]["protectedRoles"] = ["pipeline-footline", "pipeline-third-node-label"]
        proof = observation(value, [[96, 640, 780, 679], [876, 742, 952, 763]], 2)
        result = evaluate(value, proof)
        self.assertEqual(result["state"], "envelope-conflict")
        self.assertEqual(result["graphics"][2]["intersections"][0]["conflicts"], value["declarations"][0]["protectedRoles"])
        self.assertEqual(evaluate(value)["state"], "unqualified")

    def test_agenda_second_and_third_row_collision_geometry(self) -> None:
        value = fixture()
        retained_graphics(value, 6)
        cue = value["cues"][0]
        cue.update(cueId="cue-d352ac0452fcdae0", startFrame=1978, endFrameExclusive=2093)
        cue["shapedSafeBounds"].update(minX=667, maxX=1251, minY=648, maxY=759, framesMeasured=115)
        value["declarations"][0]["protectedRoles"] = ["agenda-second-row", "agenda-third-row"]
        proof = observation(value, [[690, 632, 1320, 713], [690, 746, 1260, 785]], 6)
        result = evaluate(value, proof)
        self.assertEqual(result["state"], "envelope-conflict")
        self.assertEqual(len(result["graphics"][6]["intersections"][0]["conflicts"]), 2)
        self.assertEqual(evaluate(value)["state"], "unqualified")


if __name__ == "__main__":
    unittest.main()
