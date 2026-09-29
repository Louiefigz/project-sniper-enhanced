"""Shared source evidence: drafted once, sealed, fully re-validated at bind, refused when stale, moved or forged.

Fixtures are TEST-labelled synthetic productions; nothing here is a real observation or review.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import contextlib
import io
import json
import shutil
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import context as entry
from role_packet_evidence import EvidenceDraftRequest, seal, write_draft
from role_packet_evidence_record import content_digest, evidence_check
from role_packet_evidence_schema import EvidenceError
from role_packet_text import render_role_packet
from role_packets import RoleRequest, resolve_role_packet
from _role_packet_fixture import RolePacketFixture, sha

REPO = entry.REPO
TEXTS = {10: "TEST", 11: "given", 13: "words"}


def authored(draft: dict) -> dict:
    """Fill every authored field of a draft with TEST content that cites its provenance."""
    draft.update({
        "author": {"sessionId": "TEST-coordinator", "identity": "TEST coordinator"},
        "sourceScan": {"method": "TEST sampled stills", "coverage": "TEST 0-60 s every 5 s",
                       "facts": [{"statement": "TEST one static two-shot", "evidence": [{"source": "raw-1", "atSeconds": 5}]}],
                       "limits": ["TEST sampling gaps"]},
        "speakers": {"method": "TEST stills plus transcript", "listening": False,
                     "people": [{"id": "S1", "description": "TEST presenter", "visibility": "TEST right, throughout",
                                 "evidence": [{"file": "title-reference"}]}],
                     "intervals": [{"source": "raw-1", "startSeconds": 0, "endSeconds": 10, "speaker": "S1",
                                    "visible": ["S1"], "note": None}],
                     "limits": ["TEST stills do not establish who is speaking"]},
        "reference": {"statement": "TEST title family A01", "files": ["title-reference"], "limits": []},
        "decisions": [{"topic": "TEST selections", "statement": "TEST decided before the clock", "files": ["selections"]}],
        "limits": []})
    return draft


class EvidenceFixture(RolePacketFixture):
    """A TEST production: admitted manifest, word-timed transcript, reference image, decision file and a plan."""

    def setUp(self) -> None:
        """Write the TEST production inputs every case shares."""
        super().setUp()
        self.media = self.write("source/raw.media", "TEST media bytes")
        self.transcript = self.write("source/raw-1.transcript.json", {"status": "done", "transcript": [
            {"start": 0, "end": 25, "text": "TEST", "words": [
                {"word": TEXTS.get(index, f"w{index}"), "start": index, "end": index + 0.5} for index in range(25)]}]})
        self.manifest = self.write("source/asset_manifest.json", {"sources": [{
            "id": "raw-1", "path": str(self.media), "sourceSha256": sha(self.media), "duration": 60.0, "frameRate": "30/1",
            "transcriptPath": "raw-1.transcript.json"}]})
        self.reference = self.write("production/title-reference/A01.jpg", "TEST jpeg bytes")
        self.selections = self.write("production/SELECTIONS.json", {"TEST": "selections"})

    def draft(self) -> Path:
        """A new draft binding the reference image and the decision file."""
        result = write_draft(EvidenceDraftRequest(str(self.root / "production"), str(self.manifest),
                                                  (f"title-reference={self.reference}", f"selections={self.selections}")))
        return Path(result["draft"])

    def sealed(self, change=None) -> Path:
        """An authored, sealed record (optionally changed before sealing)."""
        draft = self.draft()
        value = authored(json.loads(draft.read_text()))
        if change:
            change(value)
        draft.write_text(json.dumps(value))
        return Path(seal(str(draft))["record"])

    def evidence_plan(self, media: Path | None = None, manifest_sha: str | None = None, extra: dict | None = None) -> Path:
        """A TEST plan whose source asset and request manifest match the production unless overridden."""
        request = self.write("requests/evidence/SHORT-REQUEST.json", {"schemaVersion": 1, "scope": "TEST", "manifest": {
            "path": str(self.manifest), "sha256": manifest_sha or sha(self.manifest)}})
        source = media or self.media
        assets = [{"path": str(source), "sha256": sha(source), "file": "assets/raw.mp4", "role": "source"},
                  {"path": str(self.reference), "sha256": sha(self.reference), "file": "references/A01.jpg",
                   "role": "reference"}]
        canvas = {"frameRate": "30/1", "totalFrames": 90, "title": "TEST", "sourceFile": "assets/raw.mp4"}
        return self.plan({"canvas": canvas, "assets": assets, "requestPacket": {"path": str(request), "sha256": sha(request)},
                          **(extra or {})})

    def packet(self, record: Path, plan: Path | None = None, **extra: str) -> dict:
        """Resolve a plan-critic packet binding the record."""
        request = RoleRequest(role="plan-critic", plan=str(plan or self.evidence_plan()), shared_evidence=str(record), **extra)
        return resolve_role_packet(request, REPO)

    def forged(self, record: Path, change) -> None:
        """Hand-edit a sealed record and recompute its content digest, as a forger would."""
        value = json.loads(record.read_text())
        change(value)
        value["contentSha256"] = content_digest(value)
        record.write_text(json.dumps(value, indent=2))


class DraftAndSealTests(EvidenceFixture):
    """The engine observes identities; every other field is authored and shape/provenance-checked."""

    def test_draft_observes_sources_and_bound_files_and_authors_nothing(self) -> None:
        """Source identity and hashes are pre-filled; every authored value starts empty."""
        draft = json.loads(self.draft().read_text())
        self.assertEqual(draft["sources"][0]["sourceSha256"], sha(self.media))
        self.assertEqual({row["key"]: row["sha256"] for row in draft["bound"]},
                         {"title-reference": sha(self.reference), "selections": sha(self.selections)})
        self.assertEqual(draft["transcripts"][0]["key"], "transcript:raw-1")
        self.assertEqual((draft["author"]["sessionId"], draft["speakers"]["listening"], draft["sourceScan"]["facts"]),
                         (None, None, []))

    def test_seal_refuses_unfilled_extra_unprovenanced_or_malformed_fields(self) -> None:
        """Missing authorship, a smuggled verdict, uncited claims and malformed rows are all refused."""
        draft = self.draft()
        original = draft.read_text()
        with self.assertRaisesRegex(EvidenceError, "author"):
            seal(str(draft))
        cases = ((lambda value: value.update(verdict="pass"), "only its template fields"),
                 (lambda value: value["sourceScan"]["facts"][0].update(evidence=[]), "must cite"),
                 (lambda value: value["speakers"]["people"][0].pop("evidence"), "exactly"),
                 (lambda value: value["sourceScan"]["facts"][0].update(evidence=[{"source": "raw-1", "atSeconds": 99}]),
                  "inside an admitted source"),
                 (lambda value: value["speakers"]["intervals"][0].update(speaker="S9"), "people id or null"),
                 (lambda value: value["speakers"].update(limits=[]), "speakers.limits"),
                 (lambda value: value["speakers"].update(listening="yes"), "listening must be true or false"),
                 (lambda value: value["decisions"][0].update(files=[]), "bound file keys"),
                 (lambda value: value["reference"].update(files=[]), "bound file keys"))
        for change, message in cases:
            value = authored(json.loads(original))
            change(value)
            draft.write_text(json.dumps(value))
            with self.subTest(message), self.assertRaisesRegex(EvidenceError, message):
                seal(str(draft))

    def test_a_version_is_sealed_once(self) -> None:
        """Exclusive creation serializes seals: a second seal of the same draft cannot replace the record."""
        draft = self.draft()
        draft.write_text(json.dumps(authored(json.loads(draft.read_text()))))
        seal(str(draft))
        with self.assertRaises(FileExistsError):
            seal(str(draft))

    def test_given_titles_and_scripts_are_not_shared_evidence(self) -> None:
        """An `approved` list or operator-change trail in a draft is refused: the batch authority holds them."""
        draft = self.draft()
        for field in ("approved", "operatorChanges"):
            draft.write_text(json.dumps({**authored(json.loads(draft.read_text())), field: []}))
            with self.subTest(field), self.assertRaisesRegex(EvidenceError, "only its template fields"):
                seal(str(draft))

    def test_seal_refuses_inputs_changed_since_the_draft(self) -> None:
        """A bound file edited between draft and seal requires a new draft."""
        draft = self.draft()
        draft.write_text(json.dumps(authored(json.loads(draft.read_text()))))
        self.selections.write_text('{"TEST": "changed"}')
        with self.assertRaisesRegex(EvidenceError, "stale shared-evidence inputs.*selections"):
            seal(str(draft))

    def test_cli_drafts_rechecks_and_reports_bounded_errors(self) -> None:
        """--evidence-draft prints paths; --evidence-seal of an unfilled draft and --evidence-check of a draft exit 2."""
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(entry.main(["--evidence-draft", str(self.root / "production"), "--manifest",
                                         str(self.manifest), "--bind", f"selections={self.selections}"]), 0)
        draft = json.loads(output.getvalue())["draft"]
        for flag in ("--evidence-seal", "--evidence-check"):
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                self.assertEqual(entry.main([flag, draft]), 2)
            self.assertEqual(json.loads(errors.getvalue())["status"], "shared-evidence-unavailable")


class BindingTests(EvidenceFixture):
    """Packets bind the sealed record by hash and re-validate everything it stores."""

    def test_packet_binds_the_record_and_everything_it_binds(self) -> None:
        """Record inspect-class, its files bound-class, engine facts apart from claims, typed scene basis in the draft."""
        record = self.sealed()
        result = self.packet(record)
        packet = result["packet"]
        rows = {row["key"]: row for row in packet["artifacts"]}
        self.assertEqual((rows["shared-evidence"]["sha256"], rows["shared-evidence"]["read"]), (sha(record), "inspect"))
        self.assertEqual(rows["shared-evidence:selections"]["read"], "bound")
        self.assertEqual(packet["sharedEvidence"]["engineObserved"]["manifest"], sha(self.manifest))
        self.assertEqual(packet["sharedEvidence"]["authoredClaims"]["sourceScanFacts"], 1)
        pc18 = next(row["check"] for row in packet["checks"] if row["id"] == "PC-18")
        self.assertTrue(all(phrase in pc18 for phrase in ("only its engineObserved identities", "never overrides PC-01",
                                                          "raise a wrong", "evidenceBasis", "Only the given title and script")))
        self.assertEqual(packet["given"]["status"], "not-supplied")
        draft = json.loads(Path(result["published"]["observations"]).read_text())
        self.assertEqual({row["evidenceBasis"] for row in draft["scenes"]}, {None})
        self.assertIn("Authored claims (check and dispute)", render_role_packet(packet, result["published"]))

    def test_stale_bound_file_or_transcript_is_refused(self) -> None:
        """A decision file or the admitted transcript replaced after sealing refuses every new packet."""
        record = self.sealed()
        self.selections.write_text('{"TEST": "edited after sealing"}')
        with self.assertRaisesRegex(EvidenceError, "stale shared evidence.*selections"):
            self.packet(record)
        self.selections.write_text('{"TEST": "selections"}')
        self.transcript.write_text(self.transcript.read_text().replace('"w12"', '"REPLACED"'))
        with self.assertRaisesRegex(EvidenceError, "stale shared evidence.*transcript:raw-1"):
            self.packet(record)

    def test_hand_edited_record_with_recomputed_digest_is_refused(self) -> None:
        """Bind re-runs the full validation: unknown keys, invalid claims and oversized text never bind."""
        record = self.sealed()
        original = record.read_text()
        cases = ((lambda value: value.update(verdict="pass"), "not a sealed shared-evidence record"),
                 (lambda value: value["speakers"].update(listening="yes"), "listening must be true or false"),
                 (lambda value: value["speakers"].update(limits=[]), "speakers.limits"),
                 (lambda value: value["sourceScan"]["facts"][0].update(statement="T" * 3000), "at most 2000"),
                 (lambda value: value["sourceScan"]["facts"][0].update(evidence=[]), "must cite"))
        for change, message in cases:
            record.write_text(original)
            self.forged(record, change)
            with self.subTest(message), self.assertRaisesRegex(EvidenceError, message):
                self.packet(record)

    def test_edited_moved_copied_or_superseded_record_is_refused(self) -> None:
        """Content digest, recorded path and later versions are checked at packet time and by evidence_check."""
        record = self.sealed()
        original = record.read_text()
        value = json.loads(original)
        value["sourceScan"]["limits"] = ["TEST edited"]
        record.write_text(json.dumps(value, indent=2))
        with self.assertRaisesRegex(EvidenceError, "edited after sealing"):
            self.packet(record)
        record.write_text(original)
        self.assertEqual(evidence_check(str(record))["version"], 1)
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        shutil.copyfile(record, elsewhere / record.name)
        with self.assertRaisesRegex(EvidenceError, "not at its recorded path"):
            self.packet(elsewhere / record.name)
        self.sealed()
        with self.assertRaisesRegex(EvidenceError, "superseded by \\['SHARED-EVIDENCE-v2.json'\\]"):
            evidence_check(str(record))

    def test_foreign_source_or_manifest_is_refused(self) -> None:
        """Evidence for another recording or another admitted manifest cannot be bound to this plan."""
        record = self.sealed()
        other = self.write("source/other.media", "TEST another recording")
        with self.assertRaisesRegex(EvidenceError, "not this plan's source"):
            self.packet(record, self.evidence_plan(media=other))
        with self.assertRaisesRegex(EvidenceError, "different admitted manifest"):
            self.packet(record, self.evidence_plan(manifest_sha="e" * 64))

    def test_owner_packet_checks_production_even_without_a_plan(self) -> None:
        """An owner with only --project binds evidence only when that folder holds the same admitted manifest."""
        record = self.sealed()
        packet = resolve_role_packet(RoleRequest(role="clip-owner", project=str(self.root),
                                                 shared_evidence=str(record)), REPO)["packet"]
        self.assertIn("OW-18", [row["id"] for row in packet["checks"]])
        self.assertFalse(packet["sharedEvidence"]["checkedAgainstPlan"])
        stranger = self.root / "stranger"
        stranger.mkdir()
        with self.assertRaisesRegex(EvidenceError, "cannot establish that this shared evidence describes the project"):
            resolve_role_packet(RoleRequest(role="clip-owner", project=str(stranger), shared_evidence=str(record)), REPO)
        self.write("stranger/source/asset_manifest.json", {"sources": []})
        with self.assertRaisesRegex(EvidenceError, "is not the admitted manifest"):
            resolve_role_packet(RoleRequest(role="clip-owner", project=str(stranger), shared_evidence=str(record)), REPO)


if __name__ == "__main__":
    unittest.main()
