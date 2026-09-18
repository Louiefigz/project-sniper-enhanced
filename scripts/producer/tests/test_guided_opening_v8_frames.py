"""Actual V8 no-layout frame compatibility; pure TEST documents, not admission."""
from __future__ import annotations

from copy import deepcopy
import unittest

from _guided_proposal_presenter_fixture import noop, values
from cut_preview_io import digest
from guided_opening_frames import executable_frames, full_program_frames
from guided_opening_inputs import OpeningInputs
from test_guided_body_frames import fixture


def v8_inputs() -> OpeningInputs:
    """Bind genuine closed V8 request metadata to a synthetic empty-graphics clock."""
    inputs = fixture(0, "30/1")
    accepted, candidate, packet, manifest = values(operations=[noop()])
    del accepted["unrelated"], candidate["unrelated"]  # TEST helper's non-render sentinel.
    docs = inputs.documents
    docs.update(acceptedPlan=accepted, candidatePlan=candidate, manifest=manifest, readinessPacket=packet)
    docs["occurrences"] = {key: packet["evidence"].get(key, []) for key in ("anchors", "occurrences", "segments")}
    docs["authority"].update(target=accepted["target"], totalFrames=600, candidatePlanHash=digest(candidate),
                             occurrenceEvidenceHash=digest(docs["occurrences"]))
    bindings = docs["frameBindings"]
    bindings.update(schemaVersion=2, presenterLayouts=[], totalFrames=600, targetHash=digest(accepted["target"]))
    for key in ("candidatePlanHash", "occurrenceEvidenceHash"):
        bindings[key] = docs["authority"][key]
    return inputs


class OpeningV8FrameTests(unittest.TestCase):
    """No legacy profile may hide a layout by changing a schema or dropping a property."""

    def test_actual_noop_preserves_all_v8_documents_and_v2_bindings(self) -> None:
        """Both existing range readers use actual documents without emitting a V1 copy."""
        inputs = v8_inputs()
        before = deepcopy(inputs.documents)
        self.assertEqual(executable_frames(inputs), [])
        self.assertEqual(full_program_frames(inputs), [])
        self.assertEqual(inputs.documents, before)

    def test_v8_cannot_borrow_legacy_v1_or_an_unidentified_binding_version(self) -> None:
        """Strict numbers reject booleans, strings and float relabeling as well."""
        for version in (1, True, 2.0, "2", 3, None):
            inputs = v8_inputs()
            bindings = inputs.documents["frameBindings"]
            bindings["schemaVersion"] = version
            if version == 1:
                del bindings["presenterLayouts"]
            with self.assertRaises(RuntimeError):
                full_program_frames(inputs)

    def test_v2_requires_actual8_policy_and_evidence_not_a_rehashed_label(self) -> None:
        """The new header cannot extend an old proposal's execution authority."""
        for part in ("proposal", "evidence"):
            for version in (7, True, "8", 8.0, None):
                inputs = v8_inputs()
                inputs.documents["readinessPacket"][part]["schemaVersion"] = version
                self.assert_refused(inputs)
        inputs = v8_inputs()
        inputs.documents["readinessPacket"]["evidence"]["presenterPolicy"]["assets"] = []
        self.assert_refused(inputs)

    def assert_refused(self, inputs: OpeningInputs) -> None:
        """Retain all attempted input mutations; no production coercion is accepted."""
        before = deepcopy(inputs.documents)
        with self.assertRaises((RuntimeError, ValueError)):
            full_program_frames(inputs)
        self.assertEqual(inputs.documents, before)

    def test_empty_or_nonempty_candidate_declarations_still_reject_legacy_profiles(self) -> None:
        """A present property is intent, even if a truthiness check would ignore it."""
        for value in (None, [], {}, False, [{"assetId": "TEST"}]):
            inputs = v8_inputs()
            inputs.documents["candidatePlan"]["presenterLayouts"] = value
            self.assert_refused(inputs)
        for value in (None, {}, False, [{"operationIndex": 0}]):
            inputs = v8_inputs()
            inputs.documents["frameBindings"]["presenterLayouts"] = value
            self.assert_refused(inputs)

    def test_missing_unknown_fields_and_timed_presenter_operation_reject(self) -> None:
        """No omitted binding or operation can be silently turned into preserve-cut."""
        inputs = v8_inputs()
        del inputs.documents["frameBindings"]["presenterLayouts"]
        self.assert_refused(inputs)
        inputs = v8_inputs()
        inputs.documents["frameBindings"]["approved"] = True
        self.assert_refused(inputs)
        inputs = v8_inputs()
        inputs.documents["readinessPacket"]["proposal"]["operations"][0]["type"] = "presenter-layout-window"
        self.assert_refused(inputs)


if __name__ == "__main__":
    unittest.main()
