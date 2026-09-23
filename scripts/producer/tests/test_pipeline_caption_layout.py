"""Retained pipeline intent grammar and current refusal, never native visual approval."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from graphics.template_visual_contract import visual_entry_errors
from graphics.template_contract import validate_entry
from headless.render_layout_contract import PIPELINE_POLICY, role_inventory, sealed_documents
import test_guided_caption_pipeline_observation as retained



class PipelineCaptionLayoutTest(unittest.TestCase):
    """Preserve retained copy/layout grammar and current-source refusal."""

    def setUp(self) -> None:
        """Use the retained failing card's authored copy without changing it."""
        self.entry = {"kind": "module-pipeline", "anchor": "own-screen", "outStart": 0, "outEnd": 8,
            "spec": {"layout": "caption-safe-upper-v1", "eyebrow": "This stage",
                     "headlineLines": "At this stage your content system|is a folder",
                     "explainer": "Ideas go in and nothing ever comes back", "footChip": "nothing comes back",
                     "nodes": "Ideas~go in|nothing~ever|comes~back", "presenterFrame": False, "exit": "hold"}}

    def test_existing_copy_is_accepted_without_editing_input(self) -> None:
        """Contract acceptance declares only layout intent, never observed safety."""
        before = copy.deepcopy(self.entry)
        self.assertEqual(visual_entry_errors(self.entry), [])
        self.assertEqual(self.entry, before)

    def test_upper_layout_requires_two_through_six_nodes(self) -> None:
        """Over-capacity copy rejects instead of dropping or squeezing nodes."""
        for count in (0, 1, 7, 8):
            with self.subTest(count=count):
                self.entry["spec"]["nodes"] = "|".join(f"{index}~label" for index in range(count))
                self.assertTrue(any("two to six" in item for item in visual_entry_errors(self.entry)))

    def test_upper_layout_rejects_presenter_hole_blur_or_other_anchor(self) -> None:
        """These render classes require separate observed geometry support."""
        for field, value in (("presenterFrame", True), ("presenterFrame", 0), ("exit", "blur-recede")):
            changed = copy.deepcopy(self.entry)
            changed["spec"][field] = value
            with self.subTest(field=field, value=value):
                self.assertTrue(visual_entry_errors(changed))
        self.entry["anchor"] = "bottom-left"
        self.assertTrue(visual_entry_errors(self.entry))

    def test_default_layout_keeps_legacy_eight_node_presenter_class(self) -> None:
        """The opt-in does not shrink the historical template's content class."""
        self.entry["spec"].pop("layout")
        self.entry["spec"].update(nodes="|".join(f"{index}~label" for index in range(8)),
                                  presenterFrame=True, exit="blur-recede")
        self.assertEqual(visual_entry_errors(self.entry), [])

    def test_unknown_layout_is_not_a_permissive_fallback(self) -> None:
        """Only the closed enum selects new placement behavior."""
        self.entry["spec"]["layout"] = "make-it-fit"
        self.assertTrue(any("explicit supported" in row for row in visual_entry_errors(self.entry)))

    def test_teaching_layout_accepts_full_width_copy_and_blur_exit(self) -> None:
        """Use the entire frame without borrowing caption or presenter guarantees."""
        self.entry["spec"].update(layout="teaching-full-width-v1", exit="blur-recede")
        before = copy.deepcopy(self.entry)
        self.assertEqual(visual_entry_errors(self.entry), [])
        self.assertEqual(self.entry, before)
        for field, value in (("presenterFrame", True), ("presenterFrame", 0),
                             ("nodes", "1~Only one"), ("exit", "unknown")):
            changed = copy.deepcopy(self.entry)
            changed["spec"][field] = value
            with self.subTest(field=field, value=value):
                self.assertTrue(visual_entry_errors(changed))
        self.entry["anchor"] = "free-band"
        self.assertTrue(visual_entry_errors(self.entry))

    def test_retained_role_inventory_keeps_every_authored_copy_field(self) -> None:
        """Verify lexical metadata, with no assertion about retired CSS or pixels."""
        with tempfile.TemporaryDirectory(prefix="TEST-pipeline-roles-") as raw:
            held = retained.PipelineObservationTests._seal(
                retained.pipeline_intent(self.entry["spec"]), Path(raw).resolve())
            request = retained.observer.observation_request(retained.intent_record(held))
            documents = sealed_documents(held.snapshot, request)
            actual = {row["id"]: row["text"] for row in role_inventory(documents, PIPELINE_POLICY)}
        self.assertEqual(actual, {"node-1": "Ideasgo in", "node-2": "nothingever", "node-3": "comesback",
            "connector-1": "", "connector-2": "", "eyebrow": "This stage",
            "headline-line-1": "At this stage your content system", "headline-line-2": "is a folder",
            "explainer": "Ideas go in and nothing ever comes back", "footnote": "nothing comes back"})

    def test_current_source_policy_rejects_retained_layout_before_media(self) -> None:
        """Historical grammar acceptance cannot authorize a retired composition."""
        from unittest.mock import patch
        before = copy.deepcopy(self.entry)
        with patch("subprocess.Popen") as process:
            with self.assertRaisesRegex(ValueError, "module-pipeline.*retired"):
                validate_entry(self.entry)
        process.assert_not_called()
        self.assertEqual(self.entry, before)

    def test_retained_archive_tamper_is_rejected_before_role_read(self) -> None:
        """Historical readback still verifies actual sealed bytes and their manifest."""
        with tempfile.TemporaryDirectory(prefix="TEST-pipeline-tamper-") as raw:
            held = retained.PipelineObservationTests._seal(
                retained.pipeline_intent(self.entry["spec"]), Path(raw).resolve())
            request = retained.observer.observation_request(retained.intent_record(held))
            archive = Path(held.snapshot.path)
            archive.chmod(0o600)
            archive.write_bytes(archive.read_bytes() + b"TEST mutation")
            with self.assertRaises((RuntimeError, ValueError)):
                sealed_documents(held.snapshot, request)


if __name__ == "__main__":
    unittest.main()
