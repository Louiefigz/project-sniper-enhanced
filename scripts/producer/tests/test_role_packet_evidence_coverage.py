"""Shared-evidence version 2 coverage (P2-07, X59, X68, X127): listed clips, speaker observations, face measurement.

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
from role_packet_evidence_coverage import face_owner
from role_packet_evidence_record import content_digest, evidence_check
from role_packet_evidence_schema import EvidenceError
from role_packet_files import ArtifactError
from studio import native_budget_batches
from _role_packet_evidence_v2_fixture import FACES, BATCH, SpeakerEvidenceFixture, authored_v2, saved
from test_role_packet_evidence import sha


def bounds(*spans: tuple[float, float]) -> Callable[[dict], None]:
    """A draft change that moves the fixture's first intervals to these spans."""
    def change(value: dict) -> None:
        """Apply the TEST spans."""
        for row, (start, end) in zip(value["speakers"]["intervals"], spans):
            row.update(startSeconds=start, endSeconds=end)
    return change


def measured(record: Path) -> list[tuple]:
    """(person, framesWithFace, framesSampled, ratio) rows a sealed record keeps."""
    rows = json.loads(record.read_text())["coverage"]["observations"]["faceCoverage"]
    return [(row["person"], row["framesWithFace"], row["framesSampled"], row["ratio"]) for row in rows]


class CoverageTests(SpeakerEvidenceFixture):
    """Every listed clip's retained word midpoints lie in exactly one half-open interval of its source."""

    def test_sealed_v2_record_binds_coverage_and_observations(self) -> None:
        """The engine records the batch, the clips in clipId order and the observations it read; the record binds."""
        record = self.sealed_v2()
        value = json.loads(record.read_text())
        rows = [{"person": person, "framesWithFace": 10, "framesSampled": 10, "ratio": 1.0} for person in ("S1", "S2")]
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
        """No --batch, authored coverage, another or a second current batch, no approval, another form or transcript."""
        with self.assertRaisesRegex(EvidenceError, "needs --batch B"):
            seal(str(self.draft_v2()))
        with self.assertRaisesRegex(EvidenceError, "coverage is observed by the engine"):
            self.sealed_v2(lambda value: value.update(coverage={"clips": []}))
        for batches in ([("batch-other", {"clips": {}})], [(BATCH, {"clips": {"Q1": {}}}), ("batch-other", {})]):
            with patch.object(native_budget_batches, "current_batches", lambda root: batches), \
                    self.subTest(batches), self.assertRaisesRegex(EvidenceError, "is not the current active or draining"):
                self.sealed_v2()
        self.clips.append("Q3")
        self.approved["Q3"] = {**self.approved["Q1"], "current": None}
        with self.assertRaisesRegex(EvidenceError, "clip Q3 has no approved title/script"):
            self.sealed_v2()
        self.approved["Q3"] = {**self.approved["Q1"], "canonicalForm": "approval-v1: TEST older form"}
        with self.assertRaisesRegex(EvidenceError, "clip Q3's approval is not in approval-v2 form"):
            self.sealed_v2()
        self.clips.pop()
        self.approved["Q2"]["current"]["transcript"] = "f" * 64
        with self.assertRaisesRegex(ArtifactError, "approval is for transcript ffffffffffff"):
            self.sealed_v2()

    def test_approval_change_makes_record_stale(self) -> None:
        """A changed approval of any clip is stale; an unchanged one stays checkable after the batch closes."""
        record = self.sealed_v2()
        kept = self.approved["Q2"]
        self.approved["Q2"] = self.approval([[10, 12]])
        with self.assertRaisesRegex(EvidenceError, r"shared evidence is stale: clip Q2's approved script changed"):
            evidence_check(str(record))
        self.approved["Q2"] = kept
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
        cases = ((lambda value: value["coverage"]["observations"]["faceCoverage"][0].update(framesWithFace=9),
                  "coverage differs"),
                 (lambda value: value.update(coverage=None), "needs --batch B"),
                 (lambda value: value["coverage"].pop("batch"), "coverage must be"))
        for change, message in cases:
            value = json.loads(original)
            change(value)
            value["contentSha256"] = content_digest(value)
            record.write_text(json.dumps(value))
            with self.subTest(message), self.assertRaisesRegex(EvidenceError, message):
                evidence_check(str(record))

    def test_a_batch_drawn_from_two_sources_is_never_refused(self) -> None:
        """X127: a clip on another source is outside this record, whether or not the manifest admits that source."""
        for admitted in (False, True):
            other = self.second_source(admitted)
            self.clips = ["Q1", "Q2", "Q3"]
            self.approved["Q3"] = self.approval([[20, 22]], media=other)
            record = self.sealed_v2(observations=self.observe(f"two-sources-{admitted}"))
            value = json.loads(record.read_text())
            self.assertEqual([row["clipId"] for row in value["coverage"]["clips"]], ["Q1", "Q2"])
            self.assertEqual(evidence_check(str(record))["version"], value["version"])

    def test_intervals_on_another_source_never_cover_a_clip(self) -> None:
        """Intervals on raw-2 do not hold raw-1's retained midpoints."""
        self.second_source()

        def elsewhere(value: dict) -> None:
            """Move the interval holding Q1's words to raw-2."""
            value["speakers"]["intervals"][0].update(source="raw-2", evidence=[])
        with self.assertRaisesRegex(EvidenceError, "do not cover clip Q1"):
            self.sealed_v2(elsewhere)


class ObservationBindingTests(SpeakerEvidenceFixture):
    """X59/X68: the bound observations are a completed inspection of exactly the listed scripts and transcripts."""

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

    def test_observations_of_a_source_no_clip_is_on_cover_nothing(self) -> None:
        """Observations of an admitted source that no clip of the batch is approved on leave nothing to cover."""
        other = self.second_source()
        source = {"id": "raw-2", "sourceSha256": sha(other), "transcriptSha256": sha(self.transcript)}
        with self.assertRaisesRegex(EvidenceError, "no clip of the batch is approved on source .{12}, which the speaker"):
            self.sealed_v2(observations=self.observe("other-source", source=source))


class FaceMeasurementTests(SpeakerEvidenceFixture):
    """X127, X59(7): P2-06's per-person measurement is recorded and never refuses a seal."""

    def test_face_coverage_is_recorded_never_refused(self) -> None:
        """Absent faces are numbers, not refusals; every sampled frame is the denominator, even with no face at all."""
        self.assertEqual(measured(self.sealed_v2(observations=self.observe("s2-8", missing={"S2": 2}))),
                         [("S1", 10, 10, 1.0), ("S2", 8, 10, 0.8)])
        both = self.observe("both-8", missing={"S1": 2, "S2": 2})
        self.assertEqual(measured(self.sealed_v2(observations=both)), [("S1", 8, 10, 0.8), ("S2", 8, 10, 0.8)])
        self.assertEqual(measured(self.sealed_v2(observations=self.observe("none", faces=[]))),
                         [("S1", 0, 0, None), ("S2", 0, 0, None)])

    def test_walk_in_person_seals_with_the_numbers_recorded(self) -> None:
        """E-S2: a newcomer with its own region, visible in 3 of 10 frames, seals and is measured 3 of 10."""
        newcomer = {"x": 905, "y": 200, "w": 50, "h": 60, "score": 0.9}
        faces = [{"frame": index * 6, "t": index * 0.2,
                  "faces": [FACES["S1"], FACES["S2"], *([newcomer] if index >= 7 else [])]} for index in range(10)]

        def add(value: dict) -> None:
            """Add S3 with a region between S1's and S2's."""
            value["speakers"]["people"].append({"id": "S3", "description": "TEST newcomer", "visibility": "TEST late",
                                                "evidence": [{"file": "title-reference"}],
                                                "faceRegion": {"source": "raw-1", "xRange": [901, 959]}})
        record = self.sealed_v2(add, observations=self.observe("newcomer", faces=faces))
        self.assertEqual(measured(record)[2], ("S3", 3, 10, 0.3))

    def test_off_camera_interval_is_not_a_refusal(self) -> None:
        """E-S3: S2 speaks the second interval while off camera for half the frames; a picture matter, not a seal."""
        record = self.sealed_v2(observations=self.observe("s2-away", missing={"S2": 5}))
        self.assertEqual(measured(record), [("S1", 10, 10, 1.0), ("S2", 5, 10, 0.5)])
        self.assertEqual(json.loads(record.read_text())["speakers"]["intervals"][1]["speaker"], "S2")

    def test_a_face_in_two_regions_belongs_to_nobody(self) -> None:
        """Regions map faces to people only when exactly one region holds the face's centre x."""
        def widened(value: dict) -> None:
            """S2's region also holds S1's face centre (400 px)."""
            value["speakers"]["people"][1]["faceRegion"]["xRange"] = [0, 1920]
        self.assertEqual(measured(self.sealed_v2(widened)), [("S1", 0, 10, 0.0), ("S2", 10, 10, 1.0)])

    def test_region_edges_are_inclusive_and_a_shared_edge_is_nobodys(self) -> None:
        """A centre on x1 belongs to that region; a centre on an edge two regions share belongs to nobody."""
        face = {"x": 800, "y": 0, "w": 200, "h": 10, "score": 0.9}
        self.assertEqual(face_owner(face, {"S1": (0, 900)}), "S1")
        self.assertIsNone(face_owner(face, {"S1": (0, 899)}))
        self.assertIsNone(face_owner(face, {"S1": (0, 900), "S2": (900, 1920)}))

    def test_face_region_on_another_source_is_not_counted(self) -> None:
        """A person whose region names another admitted source is not measured on this one."""
        self.second_source()

        def moved(value: dict) -> None:
            """S2's region is on raw-2."""
            value["speakers"]["people"][1]["faceRegion"]["source"] = "raw-2"
        self.assertEqual([row[0] for row in measured(self.sealed_v2(moved))], ["S1"])


if __name__ == "__main__":
    unittest.main()
