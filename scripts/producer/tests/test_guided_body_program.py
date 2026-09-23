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
from _guided_longform_treatment_check import build_edit_plan
from compile_timeline import compile_plan
from cut_preview_io import digest
from graphics.frame_quantization import rounded_frame_index
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


def catalog_metadata_plan() -> dict:
    """Eight TEST chart instances exercise workload only, not editorial selection."""
    from _guided_longform_program import program_plan
    plan = program_plan(build_program(312, BODY_PROGRAM))
    plan['graphicsTrack'] = [
        {'id': f'test-{index}', 'kind': 'chart-story', 'anchor': 'own-screen',
         'outStart': start, 'outEnd': start + 3,
         'spec': {'type': 'bars', 'data': '10,20', 'labels': 'system,', 'emphasize': 0, 'unit': 'minutes'}}
        for index, start in enumerate((1, 9, 17, 25, 33, 41, 49, 90))]
    return plan


class GuidedBodyProgramTests(unittest.TestCase):
    """Retained script metadata and real current template checks stay distinct."""

    def test_historical_program_values_are_unchanged(self) -> None:
        expected = {96: '9fec159458be8e4612106114e5dfb7dc2ce9e4bd62e6cea2b60403bf680425f7',
                    312: 'c244942738f8ca67bbd0605ede5b3cca403e3cfbf0cb1fd80b0e36cfb394f097'}
        for duration, hashed in expected.items():
            self.assertEqual(digest(build_program(duration)), hashed)

    def test_retired_treatment_is_refused_without_rewriting_script(self) -> None:
        """The old eight-form recipe cannot select retired forms under current policy."""
        from unittest.mock import patch
        for variant, error, reason in ((None, KeyError, 'no allocated kind'),
                                       (BODY_PROGRAM, ValueError, 'statement-card.*outside')):
            program = build_program(312, variant)
            before = copy.deepcopy(program)
            beats, allocation = program_beats(program)
            with self.subTest(variant=variant), patch('subprocess.Popen') as spawn:
                with self.assertRaisesRegex(error, reason):
                    build_treatment(program, beats, allocation)
                spawn.assert_not_called()
            self.assertEqual(program, before)

    def test_script_retains_eight_beats_and_source_grounded_numeric_contrast(self) -> None:
        program = build_program(312, BODY_PROGRAM)
        beats, _ = program_beats(program)
        self.assertGreaterEqual(program['meta']['outputDurationS'], 300)
        self.assertFalse(program['meta']['excerpt'])
        self.assertIn(CONTRAST_SENTENCE, [row['text'] for row in program['transcript']['transcript']])
        self.assertEqual(len(beats), 8)
        self.assertGreater(beats[-1]['outStart'], 67)

    def test_actual_all_row_frame_template_and_workload_checks(self) -> None:
        plan = catalog_metadata_plan()
        for rate in ('30', '30000/1001'):
            inputs = metadata_packet(plan, rate)
            before = copy.deepcopy(inputs.documents)
            result = inspect_full_program_graphics(inputs, lambda: None)
            self.assertEqual(len(result['graphics']), 8)
            self.assertEqual(len(executable_frames(inputs)), 7)
            workload = admit_body_workload(inputs, {'fullProgram': {'base': {'sizeBytes': 1}}})
            self.assertEqual(workload['fullGraphics'], 8)
            self.assertFalse(result['bodyRendered'])
            self.assertFalse(result['deliveryApproved'])
            self.assertEqual(inputs.documents, before)

    def test_historical_later_hole_is_rejected_without_silent_substitution(self) -> None:
        plan = catalog_metadata_plan()
        plan['graphicsTrack'][-1]['kind'] = 'module-takeover'
        inputs = metadata_packet(plan, '30000/1001')
        before = copy.deepcopy(inputs.documents)
        self.assertEqual(len(executable_frames(inputs)), 7)
        with self.assertRaisesRegex(RuntimeError, 'placement/effect intent'):
            full_program_frames(inputs)
        self.assertEqual(inputs.documents, before)

    def test_real_cut_preserves_full_duration_without_visual_recipe(self) -> None:
        from _guided_longform_program import program_plan
        program = build_program(312, BODY_PROGRAM)
        plan = program_plan(program)
        self.assertAlmostEqual(compile_plan(plan).output_duration, program['meta']['outputDurationS'])
        self.assertGreaterEqual(compile_plan(plan).output_duration, 300)
        self.assertFalse(plan.get('graphicsTrack'))
        with tempfile.TemporaryDirectory(prefix='TEST-body-cut-gate-') as root:
            paths = write_inputs(program, root)
            with contextlib.redirect_stdout(io.StringIO()) as log:
                problems = previsual_problems(paths)
            self.assertEqual(problems, [], log.getvalue())

    def test_unspoken_numeric_copy_and_unknown_or_short_variants_fail(self) -> None:
        from claims_contract import check_claims_contract
        from plan_lint import Report
        program = build_program(312, BODY_PROGRAM)
        plan = catalog_metadata_plan()
        plan['graphicsTrack'] = [plan['graphicsTrack'][-1]]
        graphic = plan['graphicsTrack'][0]
        graphic.update(outStart=76.704, outEnd=79.872)
        graphic['spec']['data'] = '10, 20'
        baseline = Report()
        check_claims_contract(plan, kept_words(program), baseline)
        self.assertEqual(baseline.errors, [])
        graphic['spec']['data'] = '10, 99'
        report = Report()
        check_claims_contract(plan, kept_words(program), report)
        self.assertTrue(any('99' in error for error in report.errors), report.errors)
        for duration, variant in ((96, BODY_PROGRAM), (312, 'unregistered')):
            with self.assertRaises(ValueError):
                build_program(duration, variant)


if __name__ == '__main__':
    unittest.main(verbosity=2)
