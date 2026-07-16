"""Offline contracts for Claude Code Desktop → Palmier authority hooks."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from palmier.candidate_receipt import load_candidate, save_candidate
from palmier.desktop_authority import (JOURNAL_NAME, REVIEW_CHECKS, advance,
                                       approve, load_state, now, reconcile,
                                       run_qc, save_state, state_path)
from palmier.desktop_lease import renew
from palmier.desktop_hook import authorize_pre, observe_post
from palmier.desktop_manifest import _visual_steps, prepare_desktop_manifest
from palmier.desktop_state import DesktopStageInput
from palmier.mcp_client import PalmierError
from palmier.timeline_authority import snapshot


class DesktopClient:
    def __init__(self):
        self.active = "candidate"
        self.timeline = {
            "id": "candidate", "name": "Desktop candidate", "fps": 24,
            "width": 1920, "height": 1080, "totalFrames": 120,
            "tracks": [{"id": "video", "clips": [{
                "id": "clip-1", "frames": [0, 120], "mediaRef": "source",
                "opacity": 1.0}]}],
        }

    def call_json(self, tool, _args=None):
        if tool == "get_projects":
            return {"projects": [{"id": "project", "isActive": True}]}
        if tool == "get_timeline":
            return json.loads(json.dumps(self.timeline))
        raise AssertionError(tool)


class DesktopAuthorityHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        self.out = os.path.join(self.tmp.name, "producer")
        os.makedirs(self.repo); os.makedirs(self.out)
        self.client = DesktopClient()
        found = snapshot("project", self.client.timeline)
        self._write("plan.json", {"planVersion": 1})
        self._write("manifest.json", {"sources": []})
        self._write("gates.json", {
            "ok": True, "stage": "visual",
            "planHash": file_sha256(os.path.join(self.out, "plan.json")),
            "manifestHash": file_sha256(os.path.join(self.out, "manifest.json"))})
        self._write("operations.json", {
            "stage": "visual",
            "planHash": file_sha256(os.path.join(self.out, "plan.json")),
            "manifestHash": file_sha256(os.path.join(self.out, "manifest.json")),
            "steps": []})
        journal = os.path.join(self.out, JOURNAL_NAME)
        open(journal, "w", encoding="utf-8").close()
        save_candidate(self.out, {
            "schemaVersion": 1, "status": "staged", "projectId": "project",
            "timelineId": "candidate", "fingerprint": found.fingerprint,
            "semanticFingerprint": found.semantic_fingerprint,
            "timeline": found.timeline, "readbackCoverage": found.coverage,
            "base": {"projectId": "project", "timelineId": "parent",
                     "fingerprint": "p" * 64}})
        state = {
            "schemaVersion": 1, "kind": "palmier-desktop-authority",
            "status": "active", "stage": "visual", "outDir": self.out,
            "updatedAt": now(), "expiresAt": "2099-01-01T00:00:00+00:00",
            "projectId": "project", "candidate": {
                "projectId": "project", "timelineId": "candidate",
                "fingerprint": found.fingerprint},
            "expectedFingerprint": found.fingerprint,
            "plan": self._ref("plan.json"), "manifest": self._ref("manifest.json"),
            "gates": self._ref("gates.json"),
            "operations": self._ref("operations.json"),
            "journalPath": journal, "operationCount": 0,
            "verifiedOperationKeys": [], "pendingOperation": None,
        }
        save_state(self.repo, state)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, value):
        with open(os.path.join(self.out, name), "w", encoding="utf-8") as handle:
            json.dump(value, handle)

    def _ref(self, name):
        path = os.path.join(self.out, name)
        return {"path": path, "hash": file_sha256(path)}

    def _factory(self):
        return self.client

    def _event(self):
        return {"tool_name": "mcp__palmier-pro__set_keyframes",
                "tool_input": {"clipId": "clip-1", "property": "scale",
                               "keyframes": [[0, 1.0], [12, 1.08]]}}

    def test_each_mutation_advances_only_after_fresh_readback(self):
        event = self._event()
        authorize_pre(event, self.repo, self._factory)
        self.assertIsNotNone(load_state(self.out)["pendingOperation"])
        self.client.timeline["tracks"][0]["clips"][0]["scale"] = 1.08
        observe_post(event, self.repo, self._factory)
        state = load_state(self.out)
        self.assertEqual(state["operationCount"], 1)
        self.assertIsNone(state["pendingOperation"])
        self.assertEqual(state["expectedFingerprint"],
                         state["candidate"]["fingerprint"])
        with self.assertRaisesRegex(PalmierError, "replay"):
            authorize_pre(event, self.repo, self._factory)

    def test_cut_stage_cannot_author_graphics(self):
        state = load_state(self.out); state["stage"] = "cut"
        with open(state["gates"]["path"], encoding="utf-8") as handle:
            gates = json.load(handle)
        with open(state["operations"]["path"], encoding="utf-8") as handle:
            operations = json.load(handle)
        self._write("gates.json", {**gates, "stage": "cut"})
        self._write("operations.json", {**operations, "stage": "cut"})
        state["gates"] = self._ref("gates.json")
        state["operations"] = self._ref("operations.json")
        save_state(self.repo, state)
        with self.assertRaisesRegex(PalmierError, "not allowed"):
            authorize_pre(self._event(), self.repo, self._factory)

    def test_no_observable_change_pauses_authority(self):
        event = self._event()
        authorize_pre(event, self.repo, self._factory)
        with self.assertRaisesRegex(PalmierError, "no observable"):
            observe_post(event, self.repo, self._factory)
        self.assertEqual(load_state(self.out)["status"], "paused")

    def test_reconcile_adopts_only_the_reserved_landed_operation(self):
        event = self._event()
        authorize_pre(event, self.repo, self._factory)
        self.client.timeline["tracks"][0]["clips"][0]["scale"] = 1.08
        state = reconcile(self.client, self.repo)
        self.assertEqual(state["operationCount"], 1)
        self.assertIsNone(state["pendingOperation"])
        self.assertEqual(load_candidate(self.out)["timeline"]
                         ["tracks"][0]["clips"][0]["scale"], 1.08)

    def test_import_must_use_a_path_from_the_bound_worklist(self):
        asset = os.path.join(self.out, "graphic.mov")
        open(asset, "w", encoding="utf-8").close()
        with open(os.path.join(self.out, "operations.json"),
                  encoding="utf-8") as handle:
            operations = json.load(handle)
        operations["steps"] = [{"op": "native-broll", "path": asset,
                                "fileHash": file_sha256(asset)}]
        self._write("operations.json", operations)
        state = load_state(self.out)
        state["operations"] = self._ref("operations.json")
        save_state(self.repo, state)
        event = {"tool_name": "mcp__palmier-pro__import_media",
                 "tool_input": {"source": {"path": asset}}}
        authorize_pre(event, self.repo, self._factory)
        state = load_state(self.out); state["pendingOperation"] = None
        save_state(self.repo, state)
        event["tool_input"]["source"]["path"] = "/tmp/not-authorized.mov"
        with self.assertRaisesRegex(PalmierError, "bound worklist"):
            authorize_pre(event, self.repo, self._factory)

    def test_caption_detail_rows_are_valid_update_text_targets(self):
        self.client.timeline["tracks"].append({
            "type": "video", "captionGroups": [{"clips": [
                ["caption-1", 0, 12, "wrong words"]]}]})
        found = snapshot("project", self.client.timeline)
        state = load_state(self.out)
        state["expectedFingerprint"] = found.fingerprint
        state["candidate"]["fingerprint"] = found.fingerprint
        save_state(self.repo, state)
        event = {"tool_name": "mcp__palmier-pro__update_text",
                 "tool_input": {"clipIds": ["caption-1"],
                                "content": "right words"}}
        authorize_pre(event, self.repo, self._factory)
        self.assertEqual(load_state(self.out)["pendingOperation"]["tool"],
                         "update_text")

    def test_completion_requires_every_bound_composition_and_editorial_check(self):
        state = load_state(self.out)
        state.update({"status": "review-required", "qc": {
            "export": {"hash": "e" * 64}, "audit": {"digest": "a" * 64}}})
        save_state(self.repo, state)
        base = {"verdict": "pass", "materialIssues": [],
                "candidateFingerprint": state["expectedFingerprint"],
                "exportHash": "e" * 64, "auditDigest": "a" * 64}
        rows = [{**base, "lens": lens,
                 "checks": {key: "pass" for key in keys}}
                for lens, keys in REVIEW_CHECKS.items()]
        reviews = os.path.join(self.out, "reviews.json")
        with open(reviews, "w", encoding="utf-8") as handle:
            json.dump({"schemaVersion": 1, "reviews": rows}, handle)
        rows[0]["checks"].pop("contrast")
        with open(reviews, "w", encoding="utf-8") as handle:
            json.dump({"schemaVersion": 1, "reviews": rows}, handle)
        with self.assertRaisesRegex(PalmierError, "stale or did not pass"):
            approve(self.client, self.repo, reviews)
        rows[0]["checks"]["contrast"] = "pass"
        with open(reviews, "w", encoding="utf-8") as handle:
            json.dump({"schemaVersion": 1, "reviews": rows}, handle)
        self.assertEqual(approve(self.client, self.repo, reviews)["status"],
                         "complete")

    def test_advance_invalidates_stale_qc_and_reviews(self):
        state = load_state(self.out)
        state.update({"status": "review-required", "qc": {"old": True},
                      "reviews": {"path": "old"}})
        save_state(self.repo, state)
        gates = {"path": os.path.join(self.out, "next-gates.json")}
        operations = {"path": os.path.join(self.out, "next-operations.json")}
        self._write("next-gates.json", {"ok": True})
        self._write("next-operations.json", {"steps": []})
        gates["hash"] = file_sha256(gates["path"])
        operations["hash"] = file_sha256(operations["path"])
        prepared = {**operations, "content": {"steps": []}}
        inputs = DesktopStageInput(
            self.repo, "", os.path.join(self.out, "plan.json"),
            os.path.join(self.out, "manifest.json"), "visual")
        with patch("palmier.desktop_gates.run_desktop_gates",
                   return_value=gates), patch(
                       "palmier.desktop_manifest.prepare_desktop_manifest",
                       return_value=prepared):
            result = advance(self.client, inputs)
        self.assertNotIn("qc", result)
        self.assertNotIn("reviews", result)
        self.assertEqual(result["status"], "active")

    def test_qc_waits_for_every_revision_page(self):
        state = load_state(self.out)
        operations = {"stage": "revision", "revision": {
            "revisionSetId": "rev-1234567890abcdef",
            "pages": [{"index": 0, "mutationIds": ["pending"]}]}}
        self._write("operations.json", operations)
        state.update({"stage": "revision",
                      "operations": self._ref("operations.json"),
                      "revisionProgress": {
                          "revisionSetId": "rev-1234567890abcdef",
                          "verifiedMutationIds": [], "currentPage": 0,
                          "pageCount": 1}})
        save_state(self.repo, state)
        with self.assertRaisesRegex(PalmierError, "unverified mutations"):
            run_qc(self.client, self.repo)

    def test_lease_renewal_preserves_stage_and_candidate(self):
        before = load_state(self.out)
        result = renew(self.client, self.repo, 6)
        self.assertEqual(result["stage"], before["stage"])
        self.assertEqual(result["expectedFingerprint"],
                         before["expectedFingerprint"])
        self.assertNotEqual(result["expiresAt"], before["expiresAt"])


class DesktopManifestTests(unittest.TestCase):
    def test_visual_worklist_layers_overlapping_overlays(self):
        steps = _visual_steps([{"op": "overlays", "entries": [
            {"mediaKey": "card-a", "startFrame": 0, "endFrame": 40},
            {"mediaKey": "card-b", "startFrame": 40, "endFrame": 80},
            {"mediaKey": "transition", "startFrame": 30, "endFrame": 35},
        ]}])
        self.assertEqual(len(steps), 2)
        self.assertEqual([row["layer"] for row in steps], [0, 1])
        self.assertEqual([row["mediaKey"] for row in steps[0]["entries"]],
                         ["card-a", "card-b"])
        self.assertEqual(steps[1]["entries"][0]["mediaKey"], "transition")

    def test_cut_worklist_edits_existing_source_without_duplicate_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.mp4")
            open(source, "w", encoding="utf-8").close()
            plan_path = os.path.join(tmp, "edit_plan.json")
            manifest_path = os.path.join(tmp, "asset_manifest.json")
            with open(plan_path, "w", encoding="utf-8") as handle:
                json.dump({"target": {"mode": "longform"},
                           "cutTrack": [{"sourceId": "src", "start": 1,
                                         "end": 4}]}, handle)
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump({"sources": [{"id": "src", "role": "primary",
                                        "path": source, "fps": 24,
                                        "resolution": [1920, 1080]}]}, handle)
            inputs = DesktopStageInput(
                tmp, tmp, plan_path, manifest_path, "cut")
            result = prepare_desktop_manifest(inputs, {
                    "projectName": "demo", "projectSettings": {
                        "fps": 24, "width": 1920, "height": 1080}})
            (step,) = result["content"]["steps"]
            self.assertEqual(step["op"], "native-cut-spine")
            self.assertEqual(step["strategy"], "edit-existing-source")
            self.assertEqual(step["targetTotalFrames"], 72)

    def test_visual_worklist_restores_native_lanes_stripped_by_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.mp4")
            broll = os.path.join(tmp, "broll.mp4")
            music = os.path.join(tmp, "music.wav")
            master = os.path.join(tmp, "master.wav")
            for path in (source, broll, music, master):
                open(path, "w", encoding="utf-8").close()
            plan_path = os.path.join(tmp, "edit_plan.json")
            manifest_path = os.path.join(tmp, "asset_manifest.json")
            with open(plan_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "target": {"mode": "longform"},
                    "cutTrack": [{"sourceId": "src", "start": 0, "end": 5}],
                    "brollTrack": [{"assetId": "b1", "outStart": 1,
                                    "outEnd": 2}],
                    "music": {"enabled": True, "assetId": "m1"},
                    "captions": {"burn": False, "style": "line"},
                    "audioEnhance": {"preset": "voice",
                                     "palmierDenoise": {"enabled": True,
                                                        "strength": 0.45},
                                     "palmierAudioMaster": {"path": master,
                                         "targetLUFS": -14,
                                         "targetTruePeak": -1.5}},
                    "baselineLook": {"palmierColor": {"contrast": 0.1}},
                }, handle)
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump({
                    "sources": [{"id": "src", "role": "primary",
                                 "path": source, "fps": 24,
                                 "resolution": [1920, 1080]}],
                    "broll": [{"id": "b1", "path": broll}],
                    "music": [{"id": "m1", "path": music}],
                }, handle)
            inputs = DesktopStageInput(
                tmp, tmp, plan_path, manifest_path, "visual")
            result = prepare_desktop_manifest(inputs, {
                    "projectName": "demo", "projectSettings": {
                        "fps": 24, "width": 1920, "height": 1080}})
            content = result["content"]
            ops = {row["op"] for row in content["steps"]}
            self.assertTrue({"native-broll", "native-music", "native-captions",
                             "native-denoise", "native-color",
                             "native-audio-master"} <= ops)
            path_steps = [row for row in content["steps"] if row.get("path")]
            self.assertTrue(path_steps)
            self.assertTrue(all(row.get("fileHash") for row in path_steps))
            omitted = {row["lane"] for row in
                       content["capability"]["omissions"]}
            self.assertFalse({"broll", "music", "captions", "audio", "color"}
                             & omitted)
            self.assertEqual(content["qualityContract"]["contrast"]
                             ["normalTextMin"], 4.5)


if __name__ == "__main__":
    unittest.main()
