"""Role packet exclusions stay pinned, sections other units add stay assigned, and C3 suppression windows reach
every critic subject.

Fixtures are TEST-labelled synthetic plans; no packet here grants or implies any review.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from role_packet_catalog import INSTRUCTIONS
from role_packet_sections import SectionError, instruction_row
from role_packet_text import render_role_packet
from role_packets import RoleRequest, resolve_role_packet
from test_role_packet_scope import ABSENT, PRESENT, REPO, covered
from _role_packet_fixture import RolePacketFixture

NATIVE_DOC = "docs/producer/NATIVE_SHORTS_WORKFLOW.md"
# Unit C3's paragraph (commit b3cd114, NATIVE_SHORTS_WORKFLOW.md), inserted after the source-burned paragraph.
C3_PARAGRAPH = """For frames where native captions must not draw, such as while the opening title
card holds, declare `canvas.captionSuppressions`: an ordered list of
`{startFrame, endFrame, reason}` on the output frame clock, end exclusive. Caption
views and suppressions together partition the Short, so end the preceding view at
`startFrame` and start the next at `endFrame`; a caption-free gap without a
suppression still fails. The reason states the actual editorial basis."""

class PinTests(unittest.TestCase):
    """Exclusions are pinned: text inserted into an excluded range fails closed; text beside one stays assigned."""

    def resolve(self, text: str, features: dict) -> dict:
        """Resolve the plan critic's native-workflow row against a modified copy of the document."""
        spec = next(spec for spec in INSTRUCTIONS["plan-critic"] if spec[0] == NATIVE_DOC)
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / NATIVE_DOC).parent.mkdir(parents=True)
            (Path(temp) / NATIVE_DOC).write_text(text)
            return instruction_row(Path(temp), spec, features)

    def test_c3_suppression_paragraph_is_assigned_whether_or_not_the_plan_uses_it(self) -> None:
        """C3 (b3cd114) inserts its paragraph right after the source-burned paragraph; it never falls in that drop."""
        text = (REPO / NATIVE_DOC).read_text()
        anchor = "For progressive native reveals"
        merged = text.replace(anchor, C3_PARAGRAPH + "\n\n" + anchor, 1)
        for features in (ABSENT, {**ABSENT, "caption-suppressions": True}, PRESENT):
            row = self.resolve(merged, features)
            lines = merged.splitlines()
            number = next(index + 1 for index, line in enumerate(lines) if line.startswith(C3_PARAGRAPH[:40]))
            self.assertIn(number, covered(row["sections"]))

    def test_insertion_into_an_excluded_range_fails_closed(self) -> None:
        """A6/E1-style text added inside the exporter-mechanics exclusion stops resolution until reclassified."""
        text = (REPO / NATIVE_DOC).read_text()
        # P0 adapt (STATUS:22): src keeps the exporter mechanics in the packet, so insert into an exclusion it keeps.
        anchor = "The pacing report explicitly does not measure burned-caption timing."
        self.assertEqual(text.count(anchor), 1)
        merged = text.replace(anchor, "TEST inserted rule. " + anchor, 1)
        with self.assertRaisesRegex(SectionError, "no longer matches its catalog pin"):
            self.resolve(merged, ABSENT)


class SuppressionTests(RolePacketFixture):
    """C3 caption-suppression windows reach every critic subject with their reasons and uncaptioned speech."""

    def suppressed_plan(self, windows: object) -> Path:
        """A TEST plan whose canvas declares caption suppressions over three kept words."""
        canvas = {"frameRate": "30/1", "totalFrames": 90, "title": "TEST", "captionSuppressions": windows,
                  "occurrences": [[0, 0, 10, 0, 30, "TEST", 0], [1, 0, 11, 30, 60, "hidden", 0], [2, 0, 12, 60, 90, "later", 0]]}
        return self.plan({"canvas": canvas})

    def test_windows_list_reason_and_uncaptioned_words_with_their_check(self) -> None:
        """The subject shows each window and the words spoken inside it; PC-20 joins the checks; events mark edges."""
        plan = self.suppressed_plan([{"startFrame": 0, "endFrame": 45, "reason": "TEST title card holds"}])
        result = resolve_role_packet(RoleRequest(role="plan-critic", plan=str(plan)), REPO)
        window = result["packet"]["subject"]["captionSuppressions"][0]
        self.assertEqual((window["spokenOccurrenceIds"], window["spokenText"], window["endSeconds"]),
                         ([0, 1], "TEST hidden", 1.5))
        self.assertIn("PC-20", [row["id"] for row in result["packet"]["checks"]])
        self.assertIn("uncaptioned speech: 'TEST hidden'", render_role_packet(result["packet"], result["published"]))
        from fractions import Fraction
        from role_packet_media import program_events
        self.write("project/index.html", "<html></html>")
        events = program_events(json.loads(plan.read_text()), self.root / "project", Fraction(30), None)["events"]
        self.assertEqual([row["labels"] for row in events if row["frame"] in (0, 45)],
                         [["caption suppression starts"], ["caption suppression ends"]])

    def test_absent_field_adds_nothing_and_a_malformed_one_is_refused(self) -> None:
        """Older plans keep an empty list and no check; a malformed window stops resolution with the reason."""
        packet = resolve_role_packet(RoleRequest(role="plan-critic", plan=str(self.plan())), REPO)["packet"]
        self.assertEqual(packet["subject"]["captionSuppressions"], [])
        self.assertNotIn("PC-20", [row["id"] for row in packet["checks"]])
        plan = self.suppressed_plan([{"startFrame": 50, "endFrame": 40, "reason": "TEST"}])
        from role_packet_files import ArtifactError
        with self.assertRaisesRegex(ArtifactError, "captionSuppressions"):
            resolve_role_packet(RoleRequest(role="plan-critic", plan=str(plan)), REPO)


if __name__ == "__main__":
    unittest.main()
