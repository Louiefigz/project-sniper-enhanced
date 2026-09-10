"""Inert dictionaries only: no files, source admission, resources or live owners."""
from __future__ import annotations

from copy import deepcopy
from pathlib import PurePosixPath

from color.grade_observation_profile import V2_PROFILE
from cut_preview_io import digest


def reference(path: str) -> dict:
    """Syntactically valid TEST raw reference, deliberately not authenticated bytes."""
    return {"path": path, "sha256": "a" * 64, "sizeBytes": 200}


def planned_job(producer: str, source_id: str, job_id: str) -> dict:
    """Derive prospective names and files without creating their directories."""
    directory = PurePosixPath(producer) / ".sniper-grade-observations" / job_id
    return {"sourceId": source_id, "jobId": job_id, "directory": str(directory),
            "inputPath": str(directory / "input.json"), "implementationPath": str(directory / "implementation.json"),
            "launchClaimPath": str(directory / "launch-claim.json"), "executionDir": str(directory / "execution"),
            "containerName": f"sniper-grade-observation-{job_id.replace('-', '')}"}


def selection(source_id: str, v2: bool) -> dict:
    """Operator-declared context only; group end48 is not an actual source count."""
    return {"profile": V2_PROFILE if v2 else None, "declaration": {
        "schemaVersion": 2 if v2 else 1, "sourceId": source_id, "sourceProfile": "unknown" if v2 else "bt709-sdr",
        "cameraProfile": None, "historyState": "unknown" if v2 else "known", "transformHistory": ["TEST 撮影 😀"],
        "lightingGroups": [{"id": "whole", "startFrame": 0, "endFrame": 48, "intent": "unknown", "description": "TEST declaration"}]}}


def staging_fixture() -> tuple[dict, dict]:
    """Match the literal current TS stager schemas while making no raw-hash claims."""
    producer = "/TEST/source-color-project/producer"
    execution_id = "f612f0c0-bd72-4adf-96b9-50fbb55ef777"
    root = f"{producer}/guided-v2-operations/a8b9ce05-29ec-4bba-93cf-982d811ed137/executions/{execution_id}"
    opening = {"claimPath": f"{root}/execution-claim.json", "claimSha256": "b" * 64,
               "inputPath": f"{root}/media-input/input.json", "inputSha256": "c" * 64,
               "executionId": execution_id, "executionInputHash": "d" * 64, "clockHash": "e" * 64,
               "generationStartedAt": "2026-09-08T00:00:00.000Z", "budgetAdmissionHash": "f" * 64, "beforeJournalHash": "1" * 64}
    runtime = {"dockerPath": "/TEST/tools/docker", "dockerSha256": "2" * 64, "dockerSocketPath": "/TEST/docker.sock",
               "dockerSocketDevice": "1", "dockerSocketInode": "2", "imageId": f"sha256:{'3' * 64}", "userId": "501:20",
               "imageApprovalPath": "/TEST/snapshot/scripts/producer/headless/render_image_approval.json",
               "imageApprovalSha256": "4" * 64, "runtimeRepoRoot": "/TEST/snapshot"}
    source_color = {"schemaVersion": 1, "declarations": {"raw-a": selection("raw-a", False), "raw-b": selection("raw-b", True)}}
    plans = [planned_job(producer, "raw-b", "79c7d2a8-f1ae-4c74-8bfc-6b959b888211"),
             planned_job(producer, "raw-a", "f9167c04-6047-4e0d-8979-ae08455e66bc")]
    jobs = [{**row, **{key: reference(row[field]) for key, field in
                      (("input", "inputPath"), ("implementation", "implementationPath"), ("launchClaim", "launchClaimPath"))}}
            for row in plans]
    reservation = {"schemaVersion": 2, "kind": "guided-source-color-reservation",
                   "scope": "reserved-grade-container-names-not-process-settlement-or-cleanup", "producerDir": producer,
                   "opening": deepcopy(opening), "sourceColorHash": digest(source_color), "sidecarPath": f"{root}/source-color/input.json",
                   "ownerPid": 1234, "runtime": runtime, "jobs": plans}
    sidecar = {"schemaVersion": 1, "kind": "guided-source-color-input", "scope": "private-source-observation-not-transform-or-approval",
               "opening": opening, "producerDir": producer, "sourceColor": source_color,
               "expected": {key: "5" * 64 for key in ("planSha256", "manifestSha256", "projectSha256")},
               "reservation": reference("/TEST/workspace/.sniper-color-resource/active.json"), "jobs": jobs,
               "executable": False, "gradeApplicable": False, "deliveryApproved": False}
    return sidecar, reservation
