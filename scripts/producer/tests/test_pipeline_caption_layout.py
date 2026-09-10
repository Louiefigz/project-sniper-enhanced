"""Explicit native pipeline layout intent, not observed overlap or legibility."""
from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from graphics.template_visual_contract import visual_entry_errors
from headless.container_io import CompositionInput, create_snapshot, verify_snapshot_archive

MOTION = Path(__file__).resolve().parents[3] / "templates/motion"


class PipelineCaptionLayoutTest(unittest.TestCase):
    """Preserve copy, default rendering and native-size constraints."""

    def setUp(self) -> None:
        """Use the retained failing card's authored copy without changing it."""
        self.entry = {"kind": "nateherk-pipeline", "anchor": "own-screen", "outStart": 0, "outEnd": 8,
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

    def test_native_layout_does_not_change_type_size_or_hide_copy(self) -> None:
        """Static source checks supplement, never replace, real rendered review."""
        html = (MOTION / "compositions/nateherk-pipeline.html").read_text()
        native = html[html.index("/* Explicit native intent only;"):html.index("</style>")]
        for forbidden in ("font-size", "scale(", "text-overflow", "line-clamp", "overflow: hidden", "display: none"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, native)
        self.assertIn("width: 1728px; height: 528px", native)
        self.assertIn('src="/nateherk-pipeline.js"', html)
        self.assertIn('"default":"full-canvas"', html)

    def test_native_line_boxes_reflow_metadata_without_changing_default_type(self) -> None:
        """Real native overflow drove opt-in spacing, not smaller type or a waiver."""
        html = (MOTION / "compositions/nateherk-pipeline.html").read_text()
        original, native = html.split("/* Explicit native intent only;", 1)
        self.assertIn("font-size: 110px;\n        line-height: 1.05", original)
        self.assertIn("font-size: 34px; line-height: 1;", original)
        self.assertIn("#npl-headline { order: 2; line-height: 1.25; }", native)
        self.assertIn("#npl-eyebrow { order: 1; line-height: 1.25; }", native)
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto", native)
        self.assertIn("#npl-stage:has(#npl-foot) #npl-explainer { grid-column: 1; }", native)
        self.assertIn("#npl-stage:has(#npl-explainer) #npl-foot { grid-column: 2; }", native)
        self.assertIn("#npl-chain { order: 5; }", native)

    def test_actual_sealed_input_includes_the_new_local_script_bytes(self) -> None:
        """Exercise ordinary local closure capture, not an invented render archive."""
        relative = "compositions/nateherk-pipeline.html"
        html = (MOTION / relative).read_text()
        with tempfile.TemporaryDirectory(prefix="sniper-native-pipeline-seal-") as raw:
            directory = str(Path(raw).resolve())
            sealed = create_snapshot(str(MOTION.parent.parent), CompositionInput(relative, html, duration=8),
                                     self.entry["spec"], directory)
            verify_snapshot_archive(sealed.path, sealed.sha256, sealed.manifest)
            files = {row["path"]: row for row in sealed.manifest}
            self.assertIn("motion/" + relative, files)
            self.assertEqual(files["motion/nateherk-pipeline.js"]["sha256"],
                             hashlib.sha256((MOTION / "nateherk-pipeline.js").read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
