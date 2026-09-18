"""No-media TEST variant qualification; no source execution or approval claim."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from _guided_body_program import BODY_PROGRAM, CONTRAST_SENTENCE
from _guided_longform_check import previsual_problems, write_inputs
from _guided_longform_program import build_program
from _guided_longform_treatment import build_treatment, kept_words, program_beats
from _guided_longform_treatment_check import (build_edit_plan, run_gates,
                                             treatment_problems)
from compile_timeline import compile_plan
from cut_preview_io import digest
from graphics.frame_quantization import rounded_frame_index
from graphics.template_visual_contract import visible_timing
from guided_body_admission import admit_body_workload
from guided_graphic_template import inspect_full_program_graphics
from guided_opening_frames import executable_frames, full_program_frames
from guided_opening_inputs import OpeningInputs
from test_guided_body_frames import fixture, rebind


def authored(variant: str | None = BODY_PROGRAM) -> tuple:
    """Run the actual script, beat detector and authored treatment compiler."""
    program = build_program(312, variant)
    beats, allocation = program_beats(program)
    treatment = build_treatment(program, beats, allocation)
    return program, beats, treatment, build_edit_plan(program, treatment, beats)


def metadata_packet(plan: dict, rate: str) -> OpeningInputs:
    """TEST ONLY frame records; the real TS compiler/authority remain separate."""
    inputs = fixture(len(plan["graphicsTrack"]), rate)
    docs = inputs.documents
    docs["candidatePlan"] = copy.deepcopy(plan)
    docs["authority"]["target"] = copy.deepcopy(plan["target"])
    total = rounded_frame_index(compile_plan(plan).output_duration, float(Fraction(rate)))
    docs["authority"]["totalFrames"] = docs["frameBindings"]["totalFrames"] = total
    docs["frameBindings"]["targetHash"] = digest(plan["target"])
    docs["authority"]["core"]["endFrameExclusive"] = rounded_frame_index(62, float(Fraction(rate)))
    docs["authority"]["review"]["endFrameExclusive"] = rounded_frame_index(67, float(Fraction(rate)))
    for index, entry in enumerate(plan["graphicsTrack"]):
        row = docs["frameBindings"]["graphics"][index]
        row["graphicId"] = entry["id"]
        for field, edge, anchor in (("outStart", "startFrame", "s"), ("outEnd", "endFrameExclusive", "e")):
            value = rounded_frame_index(entry[field], float(Fraction(rate)))
            row[edge] = docs["occurrences"]["anchors"][f"{anchor}-{index}"] = value
    rebind(inputs)
    return inputs


class GuidedBodyProgramTests(unittest.TestCase):
    """Old hole examples remain; only explicit new source authoring enables chart."""

    def historical_treatment_view(self, treatment: dict) -> dict:
        """Check today's executable fields before comparing historical authored data.

        The retained 312-second treatment has the original expected digest.
        Its only current differences are two new layout defaults and the
        pipeline's necessary 3.45s completion floor, not measurement noise.
        This detached old view is never used for planning or current gates.
        """
        kinds = ("module-pipeline", "agenda-slide")
        rows = [row for row in treatment["beats"] if row["kind"] in kinds]
        self.assertEqual([row["kind"] for row in rows], list(kinds))
        for row in rows:
            layouts = [value for value in row["variables"] if value["name"] == "layout"]
            self.assertEqual(layouts, [{"name": "layout", "value": "full-canvas"}])
        self.assertEqual(rows[0]["minimumHoldS"], 3.45)
        spec = {value["name"]: value["value"] for value in rows[0]["variables"]}
        self.assertEqual(visible_timing(kinds[0], spec), (3.45, 2.0, 0.2, 1.25, 0.0))
        historical = copy.deepcopy(treatment)
        old_rows = [row for row in historical["beats"] if row["kind"] in kinds]
        for row in old_rows:
            row["variables"] = [value for value in row["variables"] if value["name"] != "layout"]
        old_rows[0]["minimumHoldS"] = 1.5
        return historical

    def test_historical_program_and_treatment_values_are_unchanged(self) -> None:
        # Treatment digests after the neutral rename of the module-* graphic kinds. The
        # historical view is byte-identical to the pre-rename one apart from those kind
        # names (pre-rename values: fd4f2c21…, 8d8b0234…); program digests are unchanged.
        expected = {
            96: ("9fec159458be8e4612106114e5dfb7dc2ce9e4bd62e6cea2b60403bf680425f7",
                 "43367928337b17ef7a96ce059f67d62cc3aa87f9bf15e24186e205a7bc30a5ad"),
            312: ("c244942738f8ca67bbd0605ede5b3cca403e3cfbf0cb1fd80b0e36cfb394f097",
                  "06ede061d2366ded6e4f43a649b4a42ea34c91d040af72712d5cdb6e47de3991"),
        }
        for duration, hashes in expected.items():
            program = build_program(duration)
            beats, allocation = program_beats(program)
            treatment = build_treatment(program, beats, allocation)
            historical = self.historical_treatment_view(treatment)
            self.assertEqual((digest(program), digest(historical)), hashes)

    def test_new_script_has_eight_distinct_forms_and_source_grounded_later_chart(self) -> None:
        program, beats, treatment, plan = authored()
        self.assertGreaterEqual(program["meta"]["outputDurationS"], 300)
        self.assertFalse(program["meta"]["excerpt"])
        self.assertIn(CONTRAST_SENTENCE, [row["text"] for row in program["transcript"]["transcript"]])
        self.assertEqual(len(beats), 8)
        self.assertEqual(len({row["kind"] for row in plan["graphicsTrack"]}), 8)
        self.assertEqual(treatment_problems(treatment, beats), [])
        self.assertEqual(plan["graphicsTrack"][-1]["kind"], "chart-story")
        self.assertGreater(plan["graphicsTrack"][-1]["outStart"], 67)
        self.assertTrue(all(row["anchor"] == "own-screen" for row in plan["graphicsTrack"]))

    def test_actual_all_row_frame_template_and_workload_checks(self) -> None:
        plan = authored()[-1]
        for rate in ("30", "30000/1001"):
            inputs = metadata_packet(plan, rate)
            before = copy.deepcopy(inputs.documents)
            result = inspect_full_program_graphics(inputs, lambda: None)
            self.assertEqual(len(result["graphics"]), 8)
            self.assertEqual(len(executable_frames(inputs)), 7)
            workload = admit_body_workload(inputs, {"fullProgram": {"base": {"sizeBytes": 1}}})
            self.assertEqual(workload["fullGraphics"], 8)
            self.assertFalse(result["bodyRendered"])
            self.assertEqual(inputs.documents, before)

    def test_historical_later_hole_is_still_rejected_not_silently_changed(self) -> None:
        inputs = metadata_packet(authored(None)[-1], "30000/1001")
        self.assertEqual(len(executable_frames(inputs)), 7)
        with self.assertRaisesRegex(RuntimeError, "placement/effect intent"):
            full_program_frames(inputs)

    def test_real_cut_and_four_quality_clis_pass_without_media_or_gate_stubs(self) -> None:
        program, _, _, plan = authored()
        with tempfile.TemporaryDirectory(prefix="sniper-body-program-gates-") as root:
            paths = write_inputs(program, root)
            with contextlib.redirect_stdout(io.StringIO()) as log:
                cut_problems = previsual_problems(paths)
                Path(paths["plan"]).write_text(json.dumps(plan))
                problems = run_gates(paths)
            self.assertEqual(cut_problems + problems, [], log.getvalue())

    def test_unspoken_numeric_copy_and_unknown_or_short_variants_fail(self) -> None:
        from claims_contract import check_claims_contract
        from plan_lint import Report
        program, _, _, plan = authored()
        plan["graphicsTrack"][-1]["spec"]["data"] = "10, 99"
        report = Report()
        check_claims_contract(plan, kept_words(program), report)
        self.assertTrue(any("99" in error for error in report.errors), report.errors)
        for duration, variant in ((96, BODY_PROGRAM), (312, "unregistered")):
            with self.assertRaises(ValueError):
                build_program(duration, variant)


if __name__ == "__main__":
    unittest.main(verbosity=2)
