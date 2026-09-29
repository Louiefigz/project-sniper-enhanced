"""TEST-only version 2 shared-evidence productions: two approved clips, speaker intervals and speaker observations.

The batch authority is a TEST reader patched over ``studio.production.api.read_approval`` and
``studio.native_budget_batches.current_batches``. The speaker observations are an explicitly synthetic completed
inspection (request, owner record and owner-captured result) that the real ``read_inspection`` reads. Nothing
here ran an inspection, opened media, heard or watched anything, and no row is a real observation or approval.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import role_packet_approvals as approvals
from role_packet_evidence import EvidenceDraftRequest, seal, write_draft
from role_packet_transcript import observe_transcript
from studio import native_budget_batches
from studio.native_stage_evidence import STABLE_FIELDS
from studio.owned_inspection import STATUS
from studio.production import api as authority
from test_role_packet_evidence import EvidenceFixture, authored, sha

BATCH = "batch-test"
RANGES = {"Q1": [[2, 5]], "Q2": [[10, 13]]}
REGIONS = {"S1": [0, 900], "S2": [960, 1920]}
FACES = {"S1": {"x": 300, "y": 200, "w": 200, "h": 240, "score": 0.9},
         "S2": {"x": 1300, "y": 220, "w": 200, "h": 240, "score": 0.9}}
FRAMES = 10


def interval(span: tuple[float, float], speaker: str | None, certainty: str, **extra: object) -> dict:
    """One TEST version 2 interval on raw-1 with both people visible."""
    return {"source": "raw-1", "startSeconds": span[0], "endSeconds": span[1], "speaker": speaker,
            "visible": ["S1", "S2"], "note": None, "certainty": certainty, "basis": "visual-and-stereo", "evidence": [],
            **extra}


def intervals() -> list[dict]:
    """TEST intervals holding every retained midpoint: word i spans [i, i + 0.5] s in the shared TEST transcript."""
    return [interval((0, 8), "S1", "probable", evidence=[{"source": "raw-1", "atSeconds": 3}]),
            interval((8, 12), "S2", "established", basis="operator-statement", evidence=[{"file": "selections"}]),
            interval((12, 20), None, "unresolved", basis="transcript-only")]


def authored_v2(draft: dict) -> dict:
    """A version 2 draft: the shared TEST fields, v2 speakers with face regions, one protected phrase, null coverage."""
    value = authored(draft)
    people = [{"id": person, "description": f"TEST person {person}", "visibility": "TEST throughout",
               "evidence": [{"file": "title-reference"}], "faceRegion": {"source": "raw-1", "xRange": span}}
              for person, span in REGIONS.items()]
    value.update(schemaVersion=2, coverage=None, captionPhrases=[
        {"source": "raw-1", "sourceWordIndexes": [10, 11], "display": "TEST given", "decidedBy": "operator",
         "files": ["selections"], "note": None}],
        speakers={"method": "TEST observations plus transcript", "listening": False, "people": people,
                  "intervals": intervals(), "limits": ["TEST stills do not establish who is speaking"]})
    return value


def saved(file: Path, value: dict) -> dict:
    """Write exact TEST JSON bytes and return their pin."""
    file.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, sort_keys=True).encode()
    file.write_bytes(data)
    return {"path": str(file), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def owned(directory: Path, record: dict, captured: bool = True) -> dict:
    """An explicitly synthetic completed inspection whose owner captured ``record`` as its result."""
    request = saved(directory / "request.json", {"kind": "TEST-ONLY speaker observation request"})
    output = saved(directory / "result.json", record)
    pins = {request["path"]: request["sha256"]}
    owner = {"args": ["TEST-python", "-B", "TEST-worker"], "status": STATUS, "exitCode": 0, "pid": 100,
             "ownerIdentities": [{"pid": 100, "pgid": 100, "parent_pid": 99, "started": "TEST-only"}],
             "cleanup": {"verified": True, "survivors": []}, "output": output["path"],
             "additionalFilePinsBefore": pins, "additionalFilePinsAfter": pins, **{key: True for key in STABLE_FIELDS}}
    if captured:
        owner["completedOutput"] = output
    proof = saved(directory / "inspection.render.json", owner)
    return {"path": output["path"], "sha256": output["sha256"], "owner": proof["path"], "ownerSha256": proof["sha256"]}


class SpeakerEvidenceFixture(EvidenceFixture):
    """The shared TEST production plus batch-test's approvals of Q1 and Q2 and their speaker observations."""

    def setUp(self) -> None:
        """Approve Q1 and Q2, patch the TEST authority reader and publish matching observations."""
        super().setUp()
        self.approved: dict[str, dict] = {clip: self.approval(ranges) for clip, ranges in RANGES.items()}
        self.clips = list(RANGES)
        self.enterContext(patch.object(authority, "read_approval", lambda root, batch, clip: self.approved[clip]))
        self.enterContext(patch.object(native_budget_batches, "current_batches", lambda root: [
            (BATCH, {"clips": {clip: {} for clip in self.clips}})]))
        self.observations = self.observe()

    def approval(self, word_ranges: list, status: str = "active", media: Path | None = None) -> dict:
        """A clip's TEST approval-v2 row as the authority's reader returns it (on raw-1 unless ``media`` is given)."""
        transcript = observe_transcript(str(self.transcript), 60.0)
        script = approvals.derive_script(sha(media or self.media), transcript, word_ranges)
        row = approvals.approval_row("TEST title", script)
        return {"batchId": BATCH, "status": status, "current": {**row, "recordedBy": "TEST"}, "history": [row],
                "canonicalForm": approvals.CANONICAL_FORM}

    def scripts(self) -> list[dict]:
        """The observation rows the current approvals on raw-1 give, in clipId order."""
        return [{"clipId": clip, "scriptIdentity": self.approved[clip]["current"]["script"],
                 "wordRanges": self.approved[clip]["current"]["wordRanges"]} for clip in sorted(self.approved)
                if self.approved[clip]["current"]["source"] == sha(self.media)]

    def second_source(self, admitted: bool = True) -> Path:
        """A TEST second recording raw-2 with the same transcript bytes; ``admitted`` adds it to the manifest."""
        other = self.write("source/raw-2.media", "TEST second recording")
        self.write("source/raw-2.transcript.json", self.transcript.read_text())
        if admitted:
            manifest = json.loads(self.manifest.read_text())
            manifest["sources"].append({**manifest["sources"][0], "id": "raw-2", "path": str(other),
                                        "sourceSha256": sha(other), "transcriptPath": "raw-2.transcript.json"})
            self.manifest.write_text(json.dumps(manifest))
        return other

    def observe(self, name: str = "observe", missing: dict | None = None, captured: bool = True,
                **change: object) -> Path:
        """Publish TEST observations: ``missing`` maps a person to how many leading frames lack their face;
        ``captured`` False omits the owner-captured result digest; ``change`` replaces record fields."""
        faces = [{"frame": index * 6, "t": index * 0.2,
                  "faces": [FACES[person] for person in FACES if index >= (missing or {}).get(person, 0)]}
                 for index in range(FRAMES)]
        record = {"schemaVersion": 1, "kind": "sniper-speaker-observations",
                  "source": {"id": "raw-1", "sourceSha256": sha(self.media), "transcriptSha256": sha(self.transcript)},
                  "scripts": self.scripts(), "rate": "30/1", "words": [], "faces": faces, "sampling": {}, "sheets": [],
                  "tools": {}, "limits": ["TEST synthetic observations; nothing was measured"]}
        record.update(change)
        reference = owned(self.root / name / "inspection", record, captured)
        return Path(saved(self.root / name / "SPEAKER-OBSERVATIONS.json", reference)["path"])

    def draft_v2(self, change: Callable[[dict], None] | None = None, observations: Path | None = None) -> Path:
        """An authored version 2 draft binding the reference, the decisions and the speaker observations."""
        result = write_draft(EvidenceDraftRequest(str(self.root / "production"), str(self.manifest), (
            f"title-reference={self.reference}", f"selections={self.selections}",
            f"speaker-observations={observations or self.observations}")))
        draft = Path(result["draft"])
        value = authored_v2(json.loads(draft.read_text()))
        if change:
            change(value)
        draft.write_text(json.dumps(value))
        return draft

    def sealed_v2(self, change: Callable[[dict], None] | None = None, observations: Path | None = None) -> Path:
        """A sealed version 2 record covering batch-test's approvals."""
        return Path(seal(str(self.draft_v2(change, observations)), BATCH)["record"])
