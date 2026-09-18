"""Offline reservation/readback proof for one scene clip replacement."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from palmier.candidate_receipt import save_candidate
from palmier.desktop_authority import JOURNAL_NAME
from palmier.desktop_hook import authorize_pre, observe_post
from palmier.desktop_revision import DesktopRevisionContext, prepare_revision
from palmier.desktop_revision_progress import (
    initialize_revision_progress,
    revision_complete,
)
from palmier.desktop_state import load_state, now, save_state
from palmier.mcp_client import PalmierError
from palmier.revision_schema import write_revision
from palmier.scene_binding_revision import build_scene_binding_revision
from palmier.timeline_authority import snapshot
from tests.scene_binding_revision_fixture import make_scene_revision_fixture


class _DesktopClient:
    def __init__(self, timeline: dict) -> None:
        self.timeline = timeline

    def call_json(self, tool: str, _args: dict | None = None) -> dict:
        if tool == "get_projects":
            return {"projects": [{"id": "project", "isActive": True}]}
        if tool == "get_timeline":
            return copy.deepcopy(self.timeline)
        raise AssertionError(tool)


def _clip(ident: str, media: str, start: int, end: int) -> dict:
    return {"id": ident, "mediaRef": media, "frames": [start, end],
            "opacity": 1.0}


def _timeline() -> dict:
    return {
        "id": "candidate", "name": "Scene repair", "fps": 30,
        "width": 1920, "height": 1080, "totalFrames": 1800,
        "tracks": [
            {"id": "base", "clips": [_clip(
                "source", "source-media", 0, 1800)]},
            {"id": "music", "clips": [_clip(
                "music", "music-media", 0, 1800)]},
            {"id": "left", "clips": [_clip(
                "clip-left", "media-left", 1350, 1530)]},
            {"id": "right", "clips": [_clip(
                "clip-right-old", "media-right-old", 1350, 1530)]},
        ],
    }


class SceneBindingDesktopExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.repo = root / "repo"
        self.out = root / "producer"
        self.repo.mkdir()
        self.out.mkdir()
        self.fixture = make_scene_revision_fixture(root)
        self.revision = build_scene_binding_revision(self.fixture.request())
        context = DesktopRevisionContext(
            {}, 30.0, 1800, str(root), {"id": "source"},
            self.fixture.ledger)
        self.prepared = prepare_revision(self.revision, context)
        self.client = _DesktopClient(_timeline())
        self._write_authority()

    def _json(self, name: str, value: dict) -> str:
        path = self.out / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return str(path)

    @staticmethod
    def _ref(path: str) -> dict:
        return {"path": path, "hash": file_sha256(path)}

    def _write_authority(self) -> None:
        plan = self._json("plan.json", {})
        manifest = self._json("manifest.json", {"sources": []})
        plan_hash, manifest_hash = file_sha256(plan), file_sha256(manifest)
        gates = self._json("gates.json", {
            "ok": True, "stage": "revision",
            "planHash": plan_hash, "manifestHash": manifest_hash})
        saved = write_revision(str(self.out), self.revision)
        revision_ref = {
            "revisionSetId": self.revision["revisionSetId"],
            "path": saved["path"], "hash": file_sha256(saved["path"]),
            "pages": self.prepared["pages"],
        }
        operations = self._json("operations.json", {
            "stage": "revision", "planHash": plan_hash,
            "manifestHash": manifest_hash, "steps": self.prepared["steps"],
            "revision": revision_ref})
        journal = self.out / JOURNAL_NAME
        journal.touch()
        found = snapshot("project", self.client.timeline)
        save_candidate(str(self.out), {
            "schemaVersion": 1, "status": "staged",
            "projectId": "project", "timelineId": "candidate",
            "fingerprint": found.fingerprint,
            "semanticFingerprint": found.semantic_fingerprint,
            "timeline": found.timeline, "readbackCoverage": found.coverage,
            "base": {"projectId": "project", "timelineId": "parent",
                     "fingerprint": "a" * 64},
        })
        state = {
            "schemaVersion": 1, "kind": "palmier-desktop-authority",
            "status": "active", "stage": "revision",
            "outDir": str(self.out), "updatedAt": now(),
            "expiresAt": "2099-01-01T00:00:00+00:00",
            "projectId": "project",
            "candidate": {"projectId": "project", "timelineId": "candidate",
                          "fingerprint": found.fingerprint},
            "expectedFingerprint": found.fingerprint,
            "plan": self._ref(plan), "manifest": self._ref(manifest),
            "gates": self._ref(gates), "operations": self._ref(operations),
            "revision": {key: revision_ref[key] for key in
                         ("revisionSetId", "path", "hash")},
            "journalPath": str(journal), "operationCount": 0,
            "verifiedOperationKeys": [], "pendingOperation": None,
            "elementLedger": copy.deepcopy(self.fixture.ledger),
        }
        initialize_revision_progress(state, revision_ref)
        save_state(str(self.repo), state)

    def _factory(self) -> _DesktopClient:
        return self.client

    def _import(self) -> None:
        step = self.prepared["steps"][0]
        event = {
            "tool_name": "mcp__palmier-pro__import_media",
            "tool_input": {"source": {"path": step["path"]},
                           "name": step["importName"]},
            "tool_response": {"mediaRef": "media-right-new"},
        }
        authorize_pre(event, str(self.repo), self._factory)
        self.assertEqual(
            load_state(str(self.out))["pendingOperation"]["binding"]["kind"],
            "resource")
        observe_post(event, str(self.repo), self._factory)

    def _reserve_replace(self) -> dict:
        step = self.prepared["steps"][1]
        event = {
            "tool_name": "mcp__palmier-pro__add_clips",
            "tool_input": {"entries": [{
                "mediaRef": "media-right-new",
                "startFrame": step["startFrame"],
                "endFrame": step["endFrame"],
                "trackIndex": step["trackIndex"],
            }]},
        }
        authorize_pre(event, str(self.repo), self._factory)
        return event

    def _land_replace(self) -> None:
        self.client.timeline["tracks"][3]["clips"] = [_clip(
            "clip-right-new", "media-right-new", 1350, 1530)]

    def test_reserved_import_and_replace_advance_only_after_exact_readback(self) -> None:
        before = copy.deepcopy(self.client.timeline)
        self._import()
        event = self._reserve_replace()
        self._land_replace()
        observe_post(event, str(self.repo), self._factory)
        state = load_state(str(self.out))
        right = state["elementLedger"]["elements"]["scene-045-unit-right"]
        self.assertEqual(
            (right["clipId"], right["mediaRef"], right["version"]),
            ("clip-right-new", "media-right-new", 2))
        self.assertEqual(
            state["elementLedger"]["elements"]["scene-045-unit-left"],
            self.fixture.ledger["elements"]["scene-045-unit-left"])
        self.assertEqual(
            self.client.timeline["tracks"][1], before["tracks"][1])
        self.assertTrue(revision_complete(state))
        self.assertEqual(state["operationCount"], 2)

    def test_unrelated_in_place_change_pauses_without_advancing_ledger(self) -> None:
        self._import()
        event = self._reserve_replace()
        self._land_replace()
        self.client.timeline["tracks"][2]["clips"][0]["opacity"] = 0.25
        with self.assertRaisesRegex(PalmierError, "unrelated clip in place"):
            observe_post(event, str(self.repo), self._factory)
        state = load_state(str(self.out))
        self.assertEqual(state["status"], "paused")
        right = state["elementLedger"]["elements"]["scene-045-unit-right"]
        self.assertEqual(right["clipId"], "clip-right-old")

    def test_non_atomic_add_cannot_complete_a_scene_replacement(self) -> None:
        self._import()
        event = self._reserve_replace()
        self.client.timeline["tracks"][3]["clips"].append(_clip(
            "clip-right-new", "media-right-new", 1350, 1530))
        with self.assertRaisesRegex(PalmierError, "superseded Palmier clip"):
            observe_post(event, str(self.repo), self._factory)
        state = load_state(str(self.out))
        self.assertEqual(state["status"], "paused")
        self.assertFalse(revision_complete(state))

    def test_wrong_window_or_unbound_removal_is_rejected_before_mutation(self) -> None:
        self._import()
        event = self._reserve_replace()
        state = load_state(str(self.out))
        state["pendingOperation"] = None
        save_state(str(self.repo), state)
        event["tool_input"]["entries"][0]["endFrame"] = 1529
        with self.assertRaisesRegex(PalmierError, "uniquely bound"):
            authorize_pre(event, str(self.repo), self._factory)
        remove = {"tool_name": "mcp__palmier-pro__remove_clips",
                  "tool_input": {"clipIds": ["music"]}}
        with self.assertRaisesRegex(PalmierError, "revision-bound"):
            authorize_pre(remove, str(self.repo), self._factory)


if __name__ == "__main__":
    unittest.main(verbosity=2)
