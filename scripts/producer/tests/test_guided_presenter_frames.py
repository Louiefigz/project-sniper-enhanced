"""Pure actual-V8/V2 metadata; no authenticated project, rendering or approval."""
from __future__ import annotations

from copy import deepcopy
import unittest

from _guided_presenter_capture_fixture import PresenterCaptureFixture, add_capture_graphic, bind_capture_documents
from cut_preview_io import digest
from guided_presenter_frames import presenter_program_frames


def resign_packet(documents: dict) -> None:
    """TEST attacker recomputes transport hashes, never original independently held authority."""
    documents["authority"]["frameBindingsHash"] = digest(documents["frameBindings"])
    documents["readinessPacket"]["executionBindings"] = deepcopy(documents["frameBindings"])


class PresenterFrameBindingTests(unittest.TestCase):
    """Every original full-program operation must retain its exact entry and endpoints."""

    def setUp(self) -> None:
        """Use native destination declarations with tiny explicitly stubbed asset metadata."""
        self.fixture = PresenterCaptureFixture(repeated=True)
        self.addCleanup(self.fixture.close)
        self.inputs = self.fixture.inputs
        add_capture_graphic(self.inputs.documents, (0, 2))
        add_capture_graphic(self.inputs.documents, (42, 48))

    def test_full_original_graphics_include_future_body_without_mutating_v8(self) -> None:
        """The second graphic is after the opening review but keeps its real operation index."""
        before = deepcopy(self.inputs.documents)
        rows = presenter_program_frames(self.inputs)
        self.assertEqual([row["operationIndex"] for row in rows], [2, 3])
        self.assertEqual([row["startFrame"] for row in rows], [0, 42])
        self.assertEqual(self.inputs.documents, before)

    def test_binding_version_window_and_header_cannot_be_resealed_into_compatibility(self) -> None:
        """Actual V8 cannot be downgraded, and a matching hash cannot reauthor its windows."""
        before = deepcopy(self.inputs.documents)
        changes = ({"schemaVersion": value} for value in (1, True, 2.0, "2", None))
        for change in changes:
            self.inputs.documents["frameBindings"].update(change)
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                presenter_program_frames(self.inputs)
        self.inputs.documents.clear()
        self.inputs.documents.update(before)
        self.inputs.documents["frameBindings"]["presenterLayouts"][1]["startFrame"] += 1
        resign_packet(self.inputs.documents)
        with self.assertRaisesRegex(RuntimeError, "V2 frame bindings changed"):
            presenter_program_frames(self.inputs)

    def test_missing_or_extra_closed_fields_and_original_raw_packet_link_fail(self) -> None:
        """Original packet linkage and the exact header are not optional self-hash fields."""
        before = deepcopy(self.inputs.documents)
        for mutation in ("extra", "missing", "packet", "occurrence"):
            docs = self.inputs.documents
            docs.clear()
            docs.update(deepcopy(before))
            if mutation == "extra":
                docs["frameBindings"]["approved"] = True
            if mutation == "missing":
                del docs["frameBindings"]["presenterLayouts"]
            if mutation == "packet":
                docs["readinessPacket"]["executionBindings"]["graphics"] = []
            if mutation == "occurrence":
                docs["occurrences"]["anchors"][1] += 1
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                presenter_program_frames(self.inputs)

    def test_future_graphic_order_hash_endpoints_and_presentation_are_still_checked(self) -> None:
        """No opening-only shortcut admits an unsupported or substituted later graphic."""
        before = deepcopy(self.inputs.documents)
        changes = ({"order": 0}, {"graphicId": "TEST-other"}, {"entryHash": "f" * 64},
                   {"operationIndex": 2}, {"startFrame": 43}, {"endFrameExclusive": 47})
        for change in changes:
            docs = self.inputs.documents
            docs.clear()
            docs.update(deepcopy(before))
            docs["frameBindings"]["graphics"][1].update(change)
            resign_packet(docs)
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                presenter_program_frames(self.inputs)
        docs.clear()
        docs.update(deepcopy(before))
        docs["candidatePlan"]["graphicsTrack"][1]["exitOnCut"] = True
        docs["frameBindings"]["graphics"][1]["entryHash"] = digest(docs["candidatePlan"]["graphicsTrack"][1])
        bind_capture_documents(docs)
        with self.assertRaisesRegex(RuntimeError, "placement/effect intent"):
            presenter_program_frames(self.inputs)

    def test_original_operation_coverage_cannot_drop_or_duplicate_graphics(self) -> None:
        """Every actual catalog operation owns one ordered candidate entry."""
        docs = self.inputs.documents
        docs["candidatePlan"]["graphicsTrack"].pop()
        docs["frameBindings"]["graphics"].pop()
        bind_capture_documents(docs)
        with self.assertRaisesRegex(RuntimeError, "original operation coverage"):
            presenter_program_frames(self.inputs)


if __name__ == "__main__":
    unittest.main()
