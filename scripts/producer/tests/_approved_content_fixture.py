"""Approved-content chain TEST fixture: one production through A12's real batch authority, B1's role packets,
B2's typed submission CLI and B3's hand-off (requirement revision approved-content-production-2026-09-27).

The batch is authorized with A12's own ``authorize``/``complete_setup`` in HandoffFixture's private
authority root (``TEST_READER = False``: A12's real ``studio.production.api`` answers), with the clip's
title and script bound over a real TEST transcript file. Packets are resolved in-process through
``context.main`` so the private root applies; submissions run the real ``native-review.ts`` CLI in a
child process. Media are placeholder bytes: nothing is rendered, played, heard or judged, and nothing
reads the user's authority or work-lease state.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

import context as entry
import native_work_lease
from _handoff_fixture import HandoffFixture
from cross_runtime_canonical_json import canonical_compact_json
from studio import native_budget_store
from studio.native_budget_binding import bind_project
from studio.native_budget_policy import Approval, BatchSpec
from studio.native_preview_history import STATUS as PREVIEW_STATUS
from studio.native_runtime import digest
from studio.production import api as authority
from studio.production.approvals import ApprovalChange
from studio.production.authorization import Setup, authorize, complete_setup
from test_review_player import make_attempt

REPO = entry.REPO
TSX = REPO / "node_modules" / ".bin" / "tsx"
HARNESS = Path(__file__).resolve().parent / "_isolated_review.ts"
BATCH, CLIP, TITLE = "batch-test", "Q1", "TEST press play and post"
DEPARTED = "TEST press play and share"
TEXTS = {10: "TEST", 11: "given", 13: "words"}
OCCURRENCES = [[0, 0, 10, 0, 15, "TEST", 0], [1, 0, 11, 30, 45, "given", 0], [2, 1, 13, 45, 60, "words", 0]]
CUTS = [{"start": 10.0, "end": 11.5, "speed": 1}, {"start": 13.0, "end": 13.5, "speed": 1}]
SEGMENTS = [{"startFrame": 0, "endFrameExclusive": 45}, {"startFrame": 45, "endFrameExclusive": 60}]
CHECKED = "native-short-checked-for-review"
ENGINE = {"root": "/TEST-engine", "identity": "e" * 64, "files": 1}
COVERAGE = ("briefAndRetainedMessage", "assetsAndSourceEvidence", "cuesAndSceneCoverage", "layoutCropAndText",
            "motionAndTransitions", "pacingAndAudio", "feasibility", "visualSourceSelection")
CONTRADICTION = {"code": "TEST_GIVEN_DEPARTS", "severity": "major", "lane": "copy", "evidence": ["TEST packet given block"],
                 "message": "TEST the subject departs from the operator's given title/script",
                 "requiredAction": "TEST render the given words exactly", "scope": "approved-content-contradiction"}
# A rendered-media issue is located at frames someone looked at (the TEST stills sample frame 0).
RENDERED_CONTRADICTION = {**CONTRADICTION, "frames": [0, 1]}


class ApprovedChainFixture(HandoffFixture):
    """A TEST production whose one clip's title and script the real batch authority holds."""

    TEST_READER = False

    def setUp(self) -> None:
        """Production inputs, then authorization with the approval, then setup (clock anchored first)."""
        super().setUp()
        self.media = self.put("source/raw.media", "TEST media bytes")
        words = [{"word": TEXTS.get(index, f"w{index}"), "start": float(index), "end": index + 0.5} for index in range(25)]
        self.transcript = self.put("source/raw-1.transcript.json", {"status": "done", "transcript": [
            {"start": 0, "end": 25, "text": "TEST", "words": words}]})
        self.manifest = self.put("source/asset_manifest.json", {"sources": [{
            "id": "raw-1", "path": str(self.media), "sourceSha256": digest(self.media), "duration": 60.0,
            "frameRate": "30/1", "transcriptPath": "raw-1.transcript.json"}]})
        self.request_packet = self.put("requests/q1/SHORT-REQUEST.json", {"schemaVersion": 1, "scope": "TEST", "manifest": {
            "path": str(self.manifest), "sha256": digest(self.manifest)}})
        self.put("requests/q1/AGENT-BRIEF.md", "TEST brief")
        self.catalog = self.put("catalog/title.html", "<div>TEST</div>")
        self.font = self.put("assets/font.ttf", "TEST font bytes")
        self.authorized = self.authorize_batch()

    def put(self, name: str, content: str | dict) -> Path:
        """Write one production file (JSON for dictionaries)."""
        path = self.root / "production" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content, indent=2) if isinstance(content, dict) else content)
        return path

    def authorize_batch(self) -> dict:
        """A12's authorization: the clock and the approved title/script are durable before setup runs."""
        approval = Approval(title=TITLE, source_sha256=digest(self.media), transcript_sha256=digest(self.transcript),
                            transcript_words=25, transcript_path=str(self.transcript), source_seconds=60.0,
                            word_ranges=((10, 11), (13, 13)), word_texts=("TEST", "given", "words"),
                            ranges=((10.0, 11.5), (13.0, 13.5)), recorded_by="TEST coordinator")
        root = native_budget_store.default_root()
        started = authorize(root, BatchSpec(BATCH, (CLIP,), (), 1, approvals={CLIP: approval}))
        complete_setup(root, BATCH, Setup((digest(self.media),), 1, dict(ENGINE)))
        return started

    def approval(self) -> dict:
        """The authority's current approval row for the clip (the single source)."""
        return authority.read_approval(native_budget_store.default_root(), BATCH, CLIP)["current"]

    def plan_value(self, title: str = TITLE, occurrences: list | None = None, corrections: list | None = None) -> dict:
        """A native plan over the approved words (optionally departing, or with caption display corrections)."""
        canvas = {"frameRate": "30/1", "totalFrames": 60, "title": "TEST", "sourceFile": "assets/raw.mp4",
                  "occurrences": occurrences or OCCURRENCES, "cuts": CUTS, "segments": SEGMENTS,
                  **({"captionCorrections": corrections} if corrections else {})}
        return {"schemaVersion": 1, "canvas": canvas,
                "strategy": {"scenes": [{"startFrame": 0, "endFrame": 30, "format": "presenter"},
                                        {"startFrame": 30, "endFrame": 60, "format": "diagram"}]},
                "assets": [{"path": str(self.media), "sha256": digest(self.media), "file": "assets/raw.mp4", "role": "source"},
                           {"path": str(self.font), "sha256": digest(self.font), "file": "assets/font.ttf", "role": "runtime"}],
                "catalogFiles": [{"path": str(self.catalog), "sha256": digest(self.catalog),
                                  "file": "compositions/title.html", "catalogId": "TEST-title"}],
                "catalogTitle": {"file": "compositions/title.html", "copy": {"text": title}},
                "requestPacket": {"path": str(self.request_packet), "sha256": digest(self.request_packet)}}

    def plan_file(self, name: str, **change: object) -> Path:
        """A plan file in its own clip folder (packets are written beside it)."""
        return self.put(f"{name}/native-plan-v1.json", self.plan_value(**change))

    def staged_project(self, name: str, **change: object) -> Path:
        """A staged native project folder holding the plan."""
        project = self.root / "production" / name
        project.mkdir(parents=True)
        (project / "SHORT-PROJECT.json").write_text(json.dumps(self.plan_value(**change)))
        (project / "index.html").write_text('<html><body><p data-hf-id="hf-p">TEST</p></body></html>')
        return project

    def checked_export(self, name: str, bind: bool = True, **change: object) -> tuple[Path, Path]:
        """A TEST checked export (placeholder MP4 bytes) of a project the batch binds to the clip (unless bind=False)."""
        attempt = make_attempt(self.root / "production", name, CHECKED, audioReviewRequired=True)
        project = self.root / "production" / f"{name}-project"
        plan = project / "SHORT-PROJECT.json"
        plan.write_text(json.dumps(self.plan_value(**change)))
        (project / "index.html").write_text('<html><body><p data-hf-id="hf-p">TEST</p></body></html>')
        request = json.loads((attempt / "export-request.json").read_text())
        request.update(pins={str(plan): digest(plan)}, productionBudget={"batchId": BATCH, "clipId": CLIP,
                                                                         "attemptId": "b" * 32, "route": "final"})
        (attempt / "export-request.json").write_text(json.dumps(request))
        if bind:
            bind_project(native_budget_store.default_root(), BATCH, CLIP, project)
        return attempt, project

    def preview(self, project: Path) -> Path:
        """A completed TEST moving-preview record (one whole-program window, placeholder clip bytes)."""
        attempt = project.parent / f"{project.name}-preview-v1"
        clip = attempt / "window-0" / "core.mp4"
        clip.parent.mkdir(parents=True)
        clip.write_bytes(b"TEST placeholder preview clip; not playable media")
        request_file, file = attempt / "export-request.json", attempt / "motion-previews.json"
        request_file.write_text(json.dumps({"project": str(project), "output": str(attempt), "pins": {}}))
        (attempt / "preview.render.json").write_text(json.dumps({
            "status": PREVIEW_STATUS, "output": str(file), "exitCode": 0, "completedAt": "TEST complete",
            "cleanup": {"verified": True, "survivors": []}, "additionalFilePinsBefore": {str(request_file): digest(request_file)}}))
        packet = {"schemaVersion": 1, "scope": "native-preview-dependencies-not-editorial-approval", "project": str(project),
                  "canvas": {"frameRate": "30/1", "totalFrames": 60}, "sharedHash": "a" * 64,
                  "units": [{"id": "project", "startFrame": 0, "endFrame": 60, "hash": "a" * 64}]}
        clips = [{"path": str(clip), "sha256": digest(clip), "absoluteFrameRange": [0, 60], "startFrame": 0,
                  "endFrameExclusive": 60}]
        file.write_text(json.dumps({"schemaVersion": 1, "status": PREVIEW_STATUS, "packet": packet, "clips": clips,
                                    "changedUnits": ["project"], "reusedUnits": [], "priorPreview": None}))
        return file

    def resolve(self, role: str, subject: tuple[str, Path], *extra: str) -> tuple[int, dict]:
        """``context.py --role`` in-process (the private authority root applies): exit code and JSON output."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = entry.main(["--role", role, subject[0], str(subject[1]), "--format", "json", *extra])
        return code, json.loads(out.getvalue() if code == 0 else err.getvalue())

    def packet(self, role: str, subject: tuple[str, Path], *extra: str) -> dict:
        """A resolved packet naming the batch clip; a refusal fails the test with its reason."""
        code, result = self.resolve(role, subject, "--batch", BATCH, "--clip", CLIP, *extra)
        self.assertEqual(code, 0, result)
        return result

    def observe(self, result: dict, verdict: str = "pass", **fields: object) -> None:
        """Fill the observation draft with TEST judgments: sampled stills of every target, no playback or listening."""
        path = Path(result["published"]["observations"])
        draft, packet = json.loads(path.read_text()), result["packet"]
        targets = packet["submission"]["inspection"]["targets"]
        frames = sorted({0, *(row["frame"] for row in packet["subject"].get("events", []))})
        draft.update(reviewer={"identity": "TEST critic", "sessionId": "TEST-critic", "plannerSessionId": "TEST-author",
                               "independent": True},
                     coverage={key: f"TEST {key}: synthetic fixture, nothing inspected" for key in COVERAGE},
                     verdict=verdict, summary="TEST structural submission; nothing was judged, watched or heard.",
                     limitations=["TEST: stills only; no playback or listening occurred."],
                     inspection=[{"kind": "still-frames", "artifact": {"path": row["path"], "sha256": row["sha256"]},
                                  "span": "whole", "method": "TEST fixture: nothing was inspected",
                                  "samples": [frame for frame in frames if row["frames"][0] <= frame < row["frames"][1]]}
                                 for row in targets],
                     approves=["picture"] if verdict == "pass" and targets else [])
        self.observe_subject(draft, packet, frames)
        draft.update(fields)
        path.write_text(json.dumps(draft))

    def observe_subject(self, draft: dict, packet: dict, frames: list[int]) -> None:
        """Role-specific notes, each at a frame the TEST stills sampled."""
        if "scenes" in draft:
            basis = {"evidenceBasis": "inspected"} if packet["sharedEvidence"] else {}
            draft["scenes"] = [{**row, "note": f"TEST scene {row['index']}", **basis} for row in draft["scenes"]]
            return
        draft["assessment"] = "TEST validator fixture only."
        if "windows" in draft:
            draft["windows"] = [{**row, "observations": [{"frame": row["startFrame"], "note": "TEST"}]} for row in draft["windows"]]
            return
        draft["frameNotes"] = [{"frame": 0, "note": "TEST"}]
        draft["events"] = [{"frame": row["frame"], "note": "TEST"} for row in draft["events"]]

    def gate(self, family: str, *arguments: str) -> subprocess.CompletedProcess:
        """A real native-review.ts ('review') or native-short.ts ('short') command whose engine given check runs in
        this test's private authority root (TEST harness _isolated_review.ts; the gates themselves are unchanged)."""
        roots = (str(native_budget_store.default_root()), str(native_work_lease.state_root()))
        return subprocess.run(["node", "--import", "tsx", str(HARNESS), sys.executable, *roots, family, *arguments],
                              cwd=REPO, capture_output=True, text=True, timeout=180, check=False)

    def submit(self, operation: str, result: dict) -> subprocess.CompletedProcess:
        """The packet's own typed submission command (real native-review.ts)."""
        published = result["published"]
        return self.gate("review", operation, published["packet"], published["observations"], published["record"])

    def submitted(self, operation: str, result: dict) -> dict:
        """A submission that must succeed; returns its JSON report."""
        run = self.submit(operation, result)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)


class GateFixture(ApprovedChainFixture):
    """Helpers: a passing plan review, the bind gate, an operator title change and a TEST-closed batch."""

    def passed(self, name: str, **change: object) -> tuple[Path, dict]:
        """A plan whose plan-critic pass is recorded (stills-only TEST observations)."""
        plan = self.plan_file(name, **change)
        result = self.packet("plan-critic", ("--plan", plan))
        self.observe(result)
        self.submitted("submit-prebuild", result)
        return plan, result

    def bind(self, plan: Path, record: str, name: str):
        """The build-admission gate: `native-review.ts bind-prebuild` over the recorded review."""
        return self.gate("review", "bind-prebuild", str(plan), record, str(plan.with_name(name)))

    def change_title(self, title: str) -> dict:
        """The operator's typed title change, recorded by the authority (the clock is unchanged)."""
        row = self.approval()
        approval = Approval(title=title, source_sha256=row["source"], transcript_sha256=row["transcript"],
                            transcript_words=row["transcriptWords"], transcript_path=str(self.transcript),
                            source_seconds=60.0, word_ranges=tuple(tuple(item) for item in row["wordRanges"]),
                            word_texts=tuple(row["wordTexts"]), ranges=tuple(tuple(item) for item in row["ranges"]),
                            recorded_by="TEST operator change")
        change = ApprovalChange(approval, "TEST operator retitled")  # P0 adapt: src takes one typed change
        return authority.record_script_change(native_budget_store.default_root(), BATCH, CLIP, change)

    def forged_packet(self, result: dict, change, tag: str) -> dict:
        """A copy of the published packet with its given block changed, and an observations draft answering the copy."""
        published = result["published"]
        packet = json.loads(Path(published["packet"]).read_text())
        change(packet["given"])
        copy = Path(published["packet"]).with_name(f"{tag}-{Path(published['packet']).name}")
        copy.write_text(json.dumps(packet, indent=2))
        draft = json.loads(Path(published["observations"]).read_text())
        draft["rolePacketSha256"] = digest(copy)
        observations = Path(published["observations"]).with_name(f"{tag}-{Path(published['observations']).name}")
        observations.write_text(json.dumps(draft))
        record = Path(published["record"])
        return {"packet": packet, "published": {"packet": str(copy), "observations": str(observations),
                                                "record": str(record.with_name(f"{tag}-{record.name}"))}}

    def record_submitted(self, packet: str, record: dict) -> int:
        """Append a review-submitted event for a hand-built record, as anyone able to run the engine could."""
        sha = hashlib.sha256(canonical_compact_json(record).encode()).hexdigest()
        elapsed = str(record["submission"]["timing"]["submittedElapsed"])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return entry.main(["--review-submitted", packet, "--record-sha256", sha, "--submitted-elapsed", elapsed])

    def close_batch(self, batch: str = BATCH) -> None:
        """TEST stand-in for a batch the operator closed (the lifecycle's own close needs every clip handed off)."""
        path = native_budget_store.default_root() / "batches" / batch / "authority.json"
        record = json.loads(path.read_text())
        record.update(status="closed", closedAtElapsed=5.0)
        path.write_text(json.dumps(record))
