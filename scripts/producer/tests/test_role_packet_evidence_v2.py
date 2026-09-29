"""Shared-evidence schema version 2 (P2-07): certainty and basis rules, caption phrases, and version 1 read-only.

Fixtures are TEST-labelled synthetic productions (_role_packet_evidence_v2_fixture); nothing here is a real
observation, attribution, approval or review.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import contextlib
import io
import json
import sys
import unittest
from collections.abc import Callable
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import context as entry
from role_packet_evidence import seal
from role_packet_evidence_record import content_digest, evidence_check
from role_packet_evidence_schema import EvidenceError
from role_packet_evidence_speakers import BASES, CERTAINTIES, mapped_intervals
from _role_packet_evidence_v2_fixture import BATCH, SpeakerEvidenceFixture, interval
from test_role_packet_evidence import authored

SPEAKERS = ("speakers", "intervals")


def edit(path: tuple[str, ...], index: int, **fields: object) -> Callable[[dict], None]:
    """A draft change that updates one row of a list inside the draft."""
    def change(value: dict) -> None:
        """Apply the TEST edit."""
        rows = value
        for key in path:
            rows = rows[key]
        rows[index].update(fields)
    return change


class VocabularyTests(unittest.TestCase):
    """X53: P2-07's names, verbatim, defined once for P3a to import."""

    def test_vocabulary_is_p2_07_verbatim(self) -> None:
        """CERTAINTIES and BASES are exactly P2-07's enumerations, in its order."""
        self.assertEqual(CERTAINTIES, ("established", "probable", "unresolved"))
        self.assertEqual(BASES, ("listening", "operator-statement", "visual-and-stereo", "transcript-only"))


class SpeakerRuleTests(SpeakerEvidenceFixture):
    """Each refusal names its row; the TEST fixture's own intervals seal."""

    def refused(self, change: Callable[[dict], None], message: str) -> None:
        """Sealing the fixture with ``change`` applied is refused with ``message``."""
        with self.subTest(message), self.assertRaisesRegex(EvidenceError, message):
            self.sealed_v2(change)

    def test_v2_established_requires_listening_or_operator_statement(self) -> None:
        """Listening needs speakers.listening true; an operator statement needs a bound-file citation."""
        listened = edit(SPEAKERS, 0, certainty="established", basis="listening")
        self.refused(listened, r"intervals\[0\]: established needs basis listening with speakers.listening true")
        self.refused(edit(SPEAKERS, 1, evidence=[{"source": "raw-1", "atSeconds": 9}]),
                     r"intervals\[1\]: established needs .*operator-statement citing at least one bound file")
        self.refused(edit(SPEAKERS, 0, certainty="established"), r"intervals\[0\]: established needs")

        def heard(value: dict) -> None:
            """The same interval once the record says the audio was heard."""
            listened(value)
            value["speakers"]["listening"] = True
        record = json.loads(self.sealed_v2(heard).read_text())
        self.assertEqual([row["certainty"] for row in record["speakers"]["intervals"]],
                         ["established", "established", "unresolved"])

    def test_unresolved_requires_null_speaker(self) -> None:
        """Unresolved exactly when the speaker is null, both ways."""
        self.refused(edit(SPEAKERS, 2, speaker="S1"), r"intervals\[2\]: certainty is unresolved exactly when")
        self.refused(edit(SPEAKERS, 0, speaker=None), r"intervals\[0\]: certainty is unresolved exactly when")

    def test_transcript_only_never_established(self) -> None:
        """Even with listening true, a transcript-only basis is never established; probable is allowed."""
        def claimed(value: dict) -> None:
            """A transcript-only interval claimed as established."""
            edit(SPEAKERS, 0, certainty="established", basis="transcript-only")(value)
            value["speakers"]["listening"] = True
        self.refused(claimed, r"intervals\[0\]: a transcript-only basis is never established")
        self.assertTrue(self.sealed_v2(edit(SPEAKERS, 0, basis="transcript-only")).is_file())

    def test_interval_and_person_shapes_are_refused(self) -> None:
        """Unknown vocabulary, a missing key, bad evidence and a bad face region are refused by name."""
        self.refused(edit(SPEAKERS, 0, certainty="likely"), r"intervals\[0\]\.certainty must be one of")
        self.refused(edit(SPEAKERS, 0, basis="stills"), r"intervals\[0\]\.basis must be one of")
        self.refused(edit(SPEAKERS, 0, evidence="TEST"), r"intervals\[0\]\.evidence must list 0-64")
        self.refused(edit(SPEAKERS, 0, evidence=[{"file": "unbound"}]), "bound file keys")
        self.refused(lambda value: value["speakers"]["intervals"][0].pop("basis"), "exactly")
        people = ("speakers", "people")
        self.refused(edit(people, 0, faceRegion={"source": "raw-1", "xRange": [900, 0]}), r"people\[0\]\.faceRegion")
        self.refused(edit(people, 1, faceRegion={"source": "raw-9", "xRange": [0, 9]}), r"people\[1\]\.faceRegion")
        self.refused(edit(people, 0, faceRegion={"source": "raw-1", "xRange": [0, 9], "y": 1}), "exactly")


class CaptionPhraseTests(SpeakerEvidenceFixture):
    """Protected phrases: 2-6 transcript words, a decider, bound files, at most 64, never overlapping."""

    def phrases(self, *rows: dict) -> Path:
        """Seal the fixture with exactly these phrases."""
        base = {"source": "raw-1", "display": "TEST phrase", "decidedBy": "operator", "files": ["selections"],
                "note": None}
        return self.sealed_v2(lambda value: value.update(captionPhrases=[{**base, **row} for row in rows]))

    def test_caption_phrase_bounds(self) -> None:
        """Two and six words seal; one, seven or past the transcript's 25 words is refused."""
        self.assertTrue(self.phrases({"sourceWordIndexes": [10, 11]}, {"sourceWordIndexes": [12, 17]}).is_file())
        for indexes in ([10, 10], [10, 16], [23, 25], [-1, 1], [11, 10], [10]):
            with self.subTest(indexes), self.assertRaisesRegex(EvidenceError, r"sourceWordIndexes must be \[first"):
                self.phrases({"sourceWordIndexes": indexes})

    def test_caption_phrase_fields_and_overlap(self) -> None:
        """Files, decider, display, count and overlap are each refused by name."""
        cases = (({"files": []}, "bound file keys"), ({"files": ["unbound"]}, "bound file keys"),
                 ({"decidedBy": "editor"}, "decidedBy must be one of"), ({"display": " "}, "display must be"),
                 ({"source": "raw-9"}, "source must be an admitted source id"))
        for row, message in cases:
            with self.subTest(message), self.assertRaisesRegex(EvidenceError, message):
                self.phrases({"sourceWordIndexes": [10, 11], **row})
        with self.assertRaisesRegex(EvidenceError, r"captionPhrases\[1\] overlaps captionPhrases\[0\]"):
            self.phrases({"sourceWordIndexes": [10, 11]}, {"sourceWordIndexes": [11, 12]})
        with self.assertRaisesRegex(EvidenceError, "at most 64 phrases"):
            self.phrases(*({"sourceWordIndexes": [index % 12 * 2, index % 12 * 2 + 1]} for index in range(65)))
        self.assertTrue(self.phrases({"sourceWordIndexes": [10, 11]}, {"sourceWordIndexes": [12, 13]}).is_file())


class LegacyVersionOneTests(SpeakerEvidenceFixture):
    """ST-2: version 1 records still seal, verify and bind; they read with a mapped certainty."""

    def test_v1_record_reads_with_mapped_certainty(self) -> None:
        """Null speaker: unresolved. Otherwise established if it listened, else probable (basis null)."""
        rows = [{**{key: row[key] for key in ("source", "startSeconds", "endSeconds", "speaker", "note")}, "visible": ["S1"]}
                for row in (interval((0, 5), "S1", "probable"), interval((5, 9), None, "unresolved"))]
        for listening, certainty, basis in ((False, "probable", None), (True, "established", "listening")):
            record = self.sealed(lambda value: value["speakers"].update(listening=listening, intervals=rows))
            value = json.loads(record.read_text())
            self.assertEqual((value["schemaVersion"], "coverage" in value, "captionPhrases" in value), (1, False, False))
            self.assertEqual(evidence_check(str(record))["version"], value["version"])
            self.assertEqual(self.packet(record)["packet"]["sharedEvidence"]["version"], value["version"])
            mapped = mapped_intervals(value["schemaVersion"], value["speakers"])
            self.assertEqual([(row["certainty"], row["basis"]) for row in mapped],
                             [(certainty, basis), ("unresolved", basis)])

    def test_v1_drafts_keep_version_1_rules(self) -> None:
        """A v1 draft carries no v2 fields and takes no --batch; a v1 record relabelled v2 is refused."""
        draft = self.draft()
        original = draft.read_text()
        cases = ((lambda value: value.update(captionPhrases=[]), None, "only its template fields"),
                 (None, BATCH, "--batch applies to version 2 drafts"))
        for change, batch, message in cases:
            value = authored(json.loads(original))
            if change:
                change(value)
            draft.write_text(json.dumps(value))
            with self.subTest(message), self.assertRaisesRegex(EvidenceError, message):
                seal(str(draft), batch)
        record = self.sealed()
        value = json.loads(record.read_text())
        value.update(schemaVersion=2)
        value["contentSha256"] = content_digest(value)
        record.write_text(json.dumps(value))
        with self.assertRaisesRegex(EvidenceError, "is not a sealed shared-evidence record"):
            evidence_check(str(record))


class DraftAndCliTests(SpeakerEvidenceFixture):
    """New drafts are v2; the CLI lists unresolved intervals and seals with --batch."""

    def run_cli(self, *argv: str) -> tuple[int, dict]:
        """Exit status and the JSON the evidence CLI printed (stdout, else stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = entry.main(list(argv))
        return status, json.loads(out.getvalue() or err.getvalue())

    def test_new_drafts_are_version_2_with_engine_coverage(self) -> None:
        """The template holds empty phrases and a null coverage, and the guide explains both."""
        draft = json.loads(self.draft().read_text())
        self.assertEqual((draft["schemaVersion"], draft["captionPhrases"], draft["coverage"]), (2, [], None))
        self.assertIn("--batch B", draft["guide"]["coverage"])
        self.assertIn("transcript-only is never established", draft["guide"]["speakers"])

    def test_cli_lists_unresolved_intervals_and_seals_with_batch(self) -> None:
        """--evidence-unresolved lists probable and unresolved rows; --evidence-seal needs --batch for intervals."""
        draft = self.draft_v2()
        status, listed = self.run_cli("--evidence-unresolved", str(draft))
        self.assertEqual((status, listed["status"]), (0, "shared-evidence-unresolved"))
        self.assertEqual([(row["interval"], row["certainty"]) for row in listed["intervals"]],
                         [(0, "probable"), (2, "unresolved")])
        status, refused = self.run_cli("--evidence-seal", str(draft))
        self.assertEqual(status, 2)
        self.assertIn("needs --batch B", refused["error"])
        status, sealed = self.run_cli("--evidence-seal", str(draft), "--batch", BATCH)
        self.assertEqual(status, 0)
        self.assertEqual(evidence_check(sealed["record"])["contentSha256"], sealed["contentSha256"])
        legacy = self.draft()
        legacy.write_text(json.dumps({**json.loads(legacy.read_text()), "schemaVersion": 1}))
        self.assertEqual(self.run_cli("--evidence-unresolved", str(legacy))[0], 2)

    def test_concurrent_seal_same_version_second_fails(self) -> None:
        """Exclusive creation still serializes v2 seals: the second seal of one draft cannot replace the record."""
        draft = self.draft_v2()
        seal(str(draft), BATCH)
        with self.assertRaises(FileExistsError):
            seal(str(draft), BATCH)


if __name__ == "__main__":
    unittest.main()
