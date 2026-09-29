"""Shared-evidence version 2 coverage (P2-07, X59, X68): approved scripts, speaker observations and the 90% face stop.

Fixtures are TEST-labelled synthetic productions and synthetic completed inspections
(_role_packet_evidence_v2_fixture); nothing here ran an inspection, opened media, heard or watched anything.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import json
import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from role_packet_evidence import EvidenceDraftRequest, seal, write_draft
from role_packet_evidence_record import content_digest, evidence_check
from role_packet_evidence_schema import EvidenceError
from role_packet_files import ArtifactError
from studio import native_budget_batches
from _role_packet_evidence_v2_fixture import BATCH, SpeakerEvidenceFixture, authored_v2, saved
from test_role_packet_evidence import sha


def bounds(*spans: tuple[float, float]) -> Callable[[dict], None]:
    """A draft change that moves the fixture's first intervals to these spans."""
    def change(value: dict) -> None:
        """Apply the TEST spans."""
        for row, (start, end) in zip(value["speakers"]["intervals"], spans):
            row.update(startSeconds=start, endSeconds=end)
    return change


class CoverageTests(SpeakerEvidenceFixture):
    """Every retained word's midpoint lies in exactly one half-open interval of its source."""

    def test_sealed_v2_record_binds_coverage_and_observations(self) -> None:
        """The engine records the batch, the clips in clipId order and the observations it read; the record binds."""
        record = self.sealed_v2()
        value = json.loads(record.read_text())
        rows = [{"person": person, "found": 10, "frames": 10} for person in ("S1", "S2")]
        self.assertEqual(value["coverage"], {"batch": BATCH, "clips": self.scripts(), "observations": {
            "reference": json.loads(self.observations.read_text()), "faceCoverage": rows}})
        self.assertEqual(evidence_check(str(record))["contentSha256"], value["contentSha256"])
        self.assertEqual(self.packet(record)["packet"]["sharedEvidence"]["contentSha256"], value["contentSha256"])

    def test_coverage_gap_refused(self) -> None:
        """An uncovered run is named by clip, source words and seconds; a midpoint on a shared edge is not a gap."""
        with self.assertRaisesRegex(EvidenceError, r"do not cover clip Q2 source words 10-11 \(10-11.5 s\)"):
            self.sealed_v2(bounds((0, 8), (8, 10)))
        with self.assertRaisesRegex(EvidenceError, r"do not cover clip Q1 source words 5-5 \(5-5.5 s\)"):
            self.sealed_v2(bounds((0, 5.25), (8, 12)))
        self.assertTrue(self.sealed_v2(bounds((0, 5.25), (5.25, 12))).is_file())

    def test_overlapping_intervals_refused(self) -> None:
        """A midpoint inside two intervals is an overlap, named by its time."""
        with self.assertRaisesRegex(EvidenceError, r"speaker intervals overlap at 3.25 s"):
            self.sealed_v2(bounds((0, 8), (3, 12)))

    def test_intervals_need_the_current_batch_and_coverage_is_the_engines(self) -> None:
        """No --batch, an authored coverage, another batch, a missing approval or another transcript is refused."""
        with self.assertRaisesRegex(EvidenceError, "needs --batch B"):
            seal(str(self.draft_v2()))
        with self.assertRaisesRegex(EvidenceError, "coverage is observed by the engine"):
            self.sealed_v2(lambda value: value.update(coverage={"clips": []}))
        with patch.object(native_budget_batches, "current_batches", lambda root: [("batch-other", {"clips": {}})]):
            with self.assertRaisesRegex(EvidenceError, "is not the current active or draining batch"):
                self.sealed_v2()
        self.clips.append("Q3")
        self.approved["Q3"] = {**self.approved["Q1"], "current": None}
        with self.assertRaisesRegex(EvidenceError, "clip Q3 has no approved title/script"):
            self.sealed_v2()
        self.clips.pop()
        self.approved["Q2"]["current"]["transcript"] = "f" * 64
        with self.assertRaisesRegex(ArtifactError, "approval is for transcript ffffffffffff"):
            self.sealed_v2()

    def test_approval_change_makes_record_stale(self) -> None:
        """A changed approval makes the record stale; an unchanged one stays checkable after the batch closes."""
        record = self.sealed_v2()
        self.approved["Q1"] = self.approval([[2, 5]], status="closed")
        self.assertEqual(evidence_check(str(record))["version"], json.loads(record.read_text())["version"])
        with self.assertRaisesRegex(EvidenceError, "coverage is sealed against an active or draining batch"):
            self.sealed_v2()
        self.approved["Q1"] = self.approval([[2, 6]])
        with self.assertRaisesRegex(EvidenceError, r"shared evidence is stale: clip Q1's approved script changed "
                                                   r"since sealing; reseal"):
            evidence_check(str(record))

    def test_forged_coverage_is_refused(self) -> None:
        """Coverage is re-observed at bind: edited numbers, a dropped coverage or a malformed one never bind."""
        record = self.sealed_v2()
        original = record.read_text()
        cases = ((lambda value: value["coverage"]["observations"]["faceCoverage"][0].update(found=9), "coverage differs"),
                 (lambda value: value.update(coverage=None), "needs --batch B"),
                 (lambda value: value["coverage"].pop("batch"), "coverage must be"))
        for change, message in cases:
            value = json.loads(original)
            change(value)
            value["contentSha256"] = content_digest(value)
            record.write_text(json.dumps(value))
            with self.subTest(message), self.assertRaisesRegex(EvidenceError, message):
                evidence_check(str(record))


class ObservationBindingTests(SpeakerEvidenceFixture):
    """X59/X68: the bound observations are a completed inspection of exactly these scripts, source and transcript."""

    def refused(self, message: str, **change: object) -> None:
        """Observations published with ``change`` refuse the seal with ``message``."""
        name = f"observe-variant-{len(list(self.root.glob('observe-variant-*')))}"
        with self.subTest(message), self.assertRaisesRegex(EvidenceError, message):
            self.sealed_v2(observations=self.observe(name, **change))

    def test_observations_must_match_source_and_scripts(self) -> None:
        """Another source or transcript, other scripts or another order, or another kind is refused by name."""
        source = {"id": "raw-1", "sourceSha256": self.approved["Q1"]["current"]["source"],
                  "transcriptSha256": self.approved["Q1"]["current"]["transcript"]}
        self.refused("describe source eeeeeeeeeeee, which this evidence does not admit",
                     source={**source, "sourceSha256": "e" * 64})
        self.refused("measured on transcript dddddddddddd, not clip Q1's approved transcript",
                     source={**source, "transcriptSha256": "d" * 64})
        scripts = self.scripts()
        self.refused("measured other scripts than the covered clips, compared in clipId order: \\['Q2', 'Q1'\\]",
                     scripts=scripts[::-1])
        self.refused("measured other scripts", scripts=scripts[:1])
        self.refused("measured other scripts", scripts=[scripts[0], {**scripts[1], "scriptIdentity": "0" * 64}])
        self.refused("holds no sniper-speaker-observations record", kind="TEST-other")

    def test_observations_are_a_completed_owned_inspection(self) -> None:
        """Unbound, a malformed reference, or no owner-captured result digest is refused."""
        self.refused("lacks owner-captured result digest", captured=False)
        reference = json.loads(self.observations.read_text())
        extra = Path(saved(self.root / "extra" / "SPEAKER-OBSERVATIONS.json", {**reference, "note": "TEST"})["path"])
        with self.assertRaisesRegex(EvidenceError, "must hold exactly"):
            self.sealed_v2(observations=extra)
        draft = Path(write_draft(EvidenceDraftRequest(str(self.root / "production"), str(self.manifest), (
            f"title-reference={self.reference}", f"selections={self.selections}")))["draft"])
        draft.write_text(json.dumps(authored_v2(json.loads(draft.read_text()))))
        with self.assertRaisesRegex(EvidenceError, "need the speaker observations bound: --bind speaker-observations="):
            seal(str(draft), BATCH)

    def test_face_detection_below_90_percent_stops_the_seal(self) -> None:
        """P2-06's stop: 9 of 10 frames passes, 8 of 10 refuses with every person's numbers."""
        passed = self.sealed_v2(observations=self.observe("nine", missing={"S2": 1}))
        faces = json.loads(passed.read_text())["coverage"]["observations"]["faceCoverage"]
        self.assertEqual([row["found"] for row in faces], [10, 9])
        self.refused(r"P2-06 stop: face detection finds S1 in 10 of 10, S2 in 8 of 10 measured frames, below 90% "
                     r"for \['S2'\]", missing={"S2": 2})
        self.refused(r"S1 in 0 of 0, S2 in 0 of 0 measured frames", faces=[])

    def test_a_face_in_two_regions_belongs_to_nobody(self) -> None:
        """Regions map faces to people only when exactly one region holds the face's centre x."""
        def widened(value: dict) -> None:
            """S2's region also holds S1's face centre (400 px)."""
            value["speakers"]["people"][1]["faceRegion"]["xRange"] = [0, 1920]
        with self.assertRaisesRegex(EvidenceError, r"S1 in 0 of 10, S2 in 10 of 10"):
            self.sealed_v2(widened)

    def test_observations_of_another_admitted_source_are_refused(self) -> None:
        """With two admitted sources, observations of the one no approval is on are refused (X59)."""
        other = self.write("source/raw-2.media", "TEST second recording")
        self.write("source/raw-2.transcript.json", self.transcript.read_text())
        manifest = json.loads(self.manifest.read_text())
        manifest["sources"].append({**manifest["sources"][0], "id": "raw-2", "path": str(other),
                                    "sourceSha256": sha(other), "transcriptPath": "raw-2.transcript.json"})
        self.manifest.write_text(json.dumps(manifest))
        source = {"id": "raw-2", "sourceSha256": sha(other), "transcriptSha256": sha(self.transcript)}
        with self.assertRaisesRegex(EvidenceError, "describe source .{12}, not clip Q1's approved source"):
            self.sealed_v2(observations=self.observe("other-source", source=source))

if __name__ == "__main__":
    unittest.main()
