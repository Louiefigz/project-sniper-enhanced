"""Real HTTP fixtures and cold authority assertions; no mock admission or provider use."""
from __future__ import annotations

import json
import os
import select
import subprocess
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from fingerprints import file_sha256
from ingest_execution_authority import verify_execution_media_authority
from ingest_scan import atomic_write_json
from test_supporting_rescan_media import _png, _recording
from transcript_source_authority import bind_result, observe_source, verify_result

INTENT = {"mode": "short", "scope": "produced", "lanes": {}, "music": False,
          "shortDirection": {"selection": "auto", "supportingVideo": "source-first",
                             "mediaPolicy": {"placement": "auto", "sources": "provided-only"}}}


class HttpFixture(unittest.TestCase):
    """Use one real isolated Next server; each test owns separate retained fixture files."""

    def setUp(self) -> None:
        self.runtime = json.loads(Path(os.environ["SNIPER_HTTP_ACCEPTANCE_RUNTIME"]).read_text())
        self.output = Path(self.runtime["output"])
        self.fixture = self.output / "fixtures" / self._testMethodName
        self.fixture.mkdir(parents=True)
        self.workspace = Path(self.runtime["workspace"])
        self.base = self.runtime["baseUrl"]
        self.node = self.runtime["node"]
        self.request_sequence = 0

    def post(self, route: str, body: dict) -> tuple[int, list[dict] | dict]:
        """Consume the actual HTTP response, including every complete SSE data frame."""
        from http_server import verified_connection
        started = time.monotonic()
        remaining = self.runtime["deadlineMonotonic"] - started
        self.assertGreater(remaining, 0, "Original HTTP suite deadline expired")
        connection = verified_connection(self.runtime, self.runtime["serverGroupPid"], min(180, remaining))
        try:
            connection.request("POST", route, body=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "Origin": self.base, "Sec-Fetch-Site": "same-origin"})
            response = connection.getresponse()
            content = response.read(16 * 1024 * 1024 + 1)
            self.assertLessEqual(len(content), 16 * 1024 * 1024)
        finally:
            connection.close()
        if "text/event-stream" not in response.headers.get("Content-Type", ""):
            result = json.loads(content)
            self.record_response({"route": route, "body": body, "status": response.status, "response": result}, started)
            return response.status, result
        frames = content.decode().split("\n\n")
        self.assertFalse(frames[-1].strip(), "SSE stream ended with an incomplete frame")
        data = [frame.removeprefix("data: ").strip() for frame in frames if frame.startswith("data: ")]
        result = [json.loads(value) for value in data if not value.startswith(":")]
        self.record_response({"route": route, "body": body, "status": response.status, "response": result}, started)
        return response.status, result

    def record_response(self, record: dict, started: float) -> None:
        """Retain exact synthetic HTTP evidence, including all failed responses."""
        self.request_sequence += 1
        record["elapsedSeconds"] = time.monotonic() - started
        atomic_write_json(self.fixture / f"http-{self.request_sequence:02d}.json", record)

    def manifest_event(self, events: list[dict]) -> dict:
        self.assertFalse([row for row in events if row.get("event") == "error" or "error" in row], events)
        manifests = [row for row in events if row.get("event") == "manifest"]
        self.assertEqual(len(manifests), 1, events)
        self.assertEqual(len([row for row in events if row.get("status") == "done"]), 1)
        providers = [row for row in events if row.get("status") == "transcription_provider"]
        self.assertEqual(len(providers), 1)
        self.assertIs(providers[0]["enabled"], False)
        return manifests[0]

    def initial_project(self, referenced: bool = False) -> None:
        """Admit both placements through the actual initial ingest HTTP/CLI path."""
        incoming = self.fixture / "take.mp4"
        _recording(incoming)
        body = {"inputPath": str(incoming), "noTranscribe": True, "intent": INTENT}
        if referenced:
            root = self.workspace / self._testMethodName
            (root / "source").mkdir(parents=True)
            (root / "producer").mkdir()
            atomic_write_json(root / "project.json", {"origin": "raw", "history": [],
                                                       "sourceMode": "referenced", "intent": INTENT})
            body["projectRoot"] = str(root)
        status, events = self.post("/api/producer/ingest", body)
        self.assertEqual(status, 200, events)
        event = self.manifest_event(events)
        self.project = Path(event["projectRoot"])
        self.directory = Path(event["outDir"])
        self.manifest_path = Path(event["manifestPath"])
        self.source = self.manifest_path.parent
        manifest = json.loads(self.manifest_path.read_text())
        self.assertTrue(verify_execution_media_authority({}, manifest, str(self.manifest_path)))
        row = manifest["sources"][0]
        self.assertEqual(Path(row["originalPath"]), incoming if referenced else self.source / "take.mp4")
        self.assertEqual(file_sha256(row["originalPath"]), file_sha256(str(incoming)))
        self.assertEqual((self.source / "take.mp4").exists(), not referenced)
        self._bind_synthetic_transcript(manifest)

    def _bind_synthetic_transcript(self, manifest: dict) -> None:
        """Attach explicitly synthetic timing to admitted tone media, never ASR speech evidence."""
        row = manifest["sources"][0]
        result = bind_result({"status": "done", "fixturePurpose": "TEST-ONLY synthetic transcript over tone",
            "speechAccuracyVerified": False, "editorialApproved": False,
            "transcript": [{"start": .1, "end": .8, "text": "Test fixture", "words": [
                {"word": "Test", "start": .1, "end": .4}, {"word": "fixture", "start": .5, "end": .8}]}]},
            observe_source(Path(row["path"]), (row["sourceSha256"], row["sourceSizeBytes"])))
        row["transcriptPath"] = "raw-1.transcript.json"
        self.transcript_path = self.source / row["transcriptPath"]
        atomic_write_json(self.transcript_path, result)
        atomic_write_json(self.manifest_path, manifest)
        self.previous = manifest
        self.manifest_before = self.manifest_path.read_bytes()
        self.transcript_before = self.transcript_path.read_bytes()

    def stage(self, invalid: bool = False) -> dict:
        """Call the real supporting-media POST and independently rehash its staged copy."""
        selected = self.fixture / "provided.png"
        if invalid:
            selected.write_bytes(b"TEST invalid PNG for actual decode rejection")
        else:
            _png(selected, "red")
        status, result = self.post("/api/producer/supporting-media", {"dir": str(self.directory), "inputPath": str(selected)})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["status"], "staged-awaiting-sandbox-admission")
        self.assertEqual(result["sha256"], file_sha256(str(selected)))
        self.assertEqual(result["sha256"], file_sha256(result["path"]))
        self.assertEqual(self.manifest_path.read_bytes(), self.manifest_before)
        return result

    def rescan(self) -> tuple[int, list[dict] | dict]:
        return self.post("/api/producer/ingest", {"inputPath": str(self.source),
                         "projectRoot": str(self.project), "reuseTranscripts": True})

    def assert_published(self, events: list[dict], staged: dict) -> None:
        event = self.manifest_event(events)
        manifest = json.loads(self.manifest_path.read_text())
        self.assertEqual(event["manifest"], manifest)
        self.assertNotEqual(self.manifest_path.read_bytes(), self.manifest_before)
        self.assertEqual(self.transcript_path.read_bytes(), self.transcript_before)
        self.assertTrue(verify_execution_media_authority({}, manifest, str(self.manifest_path)))
        self.assertNotEqual(manifest["sourceSetAdmission"]["sourceSetDigest"], self.previous["sourceSetAdmission"]["sourceSetDigest"])
        refreshed = {"admissionReceiptPath", "admissionReceiptSha256"}
        self.assertEqual({k: v for k, v in manifest["sources"][0].items() if k not in refreshed},
                         {k: v for k, v in self.previous["sources"][0].items() if k not in refreshed})
        self.assertIsNone(verify_result(json.loads(self.transcript_before), manifest["sources"][0], str(self.transcript_path)))
        matches = [row for row in manifest["broll"] if row["originalPath"] == staged["path"]]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["sourceSha256"], staged["sha256"])
        self.assertEqual(file_sha256(matches[0]["path"]), staged["sha256"])
        project = json.loads((self.project / "project.json").read_text())
        for key in ("intent", "requestedIntent", "resolvedIntent"):
            self.assertEqual(project[key]["shortDirection"]["mediaPolicy"], INTENT["shortDirection"]["mediaPolicy"])

    def unchanged(self) -> None:
        self.assertEqual(self.manifest_path.read_bytes(), self.manifest_before)
        self.assertEqual(self.transcript_path.read_bytes(), self.transcript_before)
        self.assertTrue(verify_execution_media_authority({}, self.previous, str(self.manifest_path)))

    def fixture_command(self, action: str) -> list[str]:
        return [self.node, "--import", "tsx", str(self.output / "fixture-authority.ts"), action, str(self.project)]

    def checkpoint(self) -> None:
        result = subprocess.run(self.fixture_command("checkpoint"), cwd=self.runtime["repo"],
                                capture_output=True, text=True, timeout=30, check=True)
        self.assertIn("synthetic-negative-checkpoint-only", result.stdout)

    def child_ledgers(self) -> dict[str, bytes]:
        """An HTTP rejection must neither start Python nor request a decoder container."""
        return {name: (self.output / name).read_bytes()
                for name in ("requested-containers.jsonl", "python-observer.jsonl")}

    @contextmanager
    def held_project(self) -> Iterator[None]:
        """Bound real lease readiness and reap this exact helper on every failure."""
        proc = subprocess.Popen(self.fixture_command("hold-lease"), cwd=self.runtime["repo"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertTrue(select.select([proc.stdout], [], [], 15)[0], "Lease helper readiness timed out")
            self.assertEqual(os.read(proc.stdout.fileno(), 4096), b"lease-held\n")
            yield
        finally:
            try:
                proc.communicate(b"release\n", timeout=15)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate(timeout=2)
        self.assertEqual(proc.returncode, 0)
