"""Offline contracts for the P5 connected Palmier acceptance harness."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from ingest_probe import MediaProbe
from palmier.live_acceptance_proofs import (
    ManualProofInput, RepairProofInput, SENTINEL_OPACITY,
    prove_manual_preservation, repair_delta, repair_scope)
from palmier.live_acceptance_media import revalidate_bootstrap
from palmier.live_acceptance_session import (
    LiveAcceptanceConfig, created_project, trash_disposable, validate_config)
from palmier.live_acceptance_runtime import AppliedResponseLost
from palmier.live_acceptance_worklist import GovernedWorklist
from palmier.master import MasterFacts
from palmier.mcp_client import PalmierError
import live_p5_connected_palmier_acceptance as live_harness


def _bind_test_assets(steps: list[dict], root: str) -> list[dict]:
    value = json.loads(json.dumps(steps))
    paths: dict[str, tuple[str, str]] = {}

    def bind(row: dict, path_key: str, hash_key: str) -> None:
        original = row.get(path_key)
        if not isinstance(original, str):
            return
        if original not in paths:
            path = Path(root, f"asset-{len(paths)}{Path(original).suffix}")
            path.write_bytes(original.encode("utf-8"))
            paths[original] = (str(path), file_sha256(str(path)))
        row[path_key], row[hash_key] = paths[original]

    for row in value:
        bind(row, "path", "fileHash")
        bind(row, "assetPath", "assetHash")
        for entry in row.get("entries") or []:
            if isinstance(entry, dict):
                bind(entry, "assetPath", "assetHash")
    imports = {row.get("key"): row for row in value
               if row.get("op") == "import"}
    for row in value:
        targets = row.get("entries") or [row]
        for target in targets:
            source = imports.get(target.get("mediaKey")) \
                if isinstance(target, dict) else None
            if isinstance(source, dict) and "assetPath" not in target:
                target["assetPath"] = source["path"]
                target["assetHash"] = source["fileHash"]
    return value


def _plan(path: Path, end: float = 2.0, repair: bool = False) -> None:
    path.write_text(json.dumps({
        "cutTrack": [{
            "sourceId": "raw-1", "start": 0.0, "end": end,
        }],
        "graphicsTrack": [{
            "id": "graphic-1", "kind": "lower-third",
            "anchor": "bottom-left", "informationForm": "label",
            "chassis": "card", "outStart": 0.2, "outEnd": 1.0,
            "spec": {"text": "changed" if repair else "original"},
        }],
    }))


def _timeline(opacity: float | None = None) -> dict:
    clip = {"id": "graphic-clip", "mediaRef": "graphic-media",
            "mediaType": "video", "frames": [3, 9]}
    if opacity is not None:
        clip["opacity"] = opacity
    return {"id": "candidate", "fps": 30, "width": 1080, "height": 1920,
            "totalFrames": 60, "tracks": [{
                "id": "track", "type": "video", "clips": [clip]}]}


class FakeClient:
    def __init__(self) -> None:
        self.calls = []
        self.waits = []

    def call(self, tool, args):
        self.calls.append((tool, args))
        if tool == "import_media":
            return json.dumps({"mediaRef": f"media-{len(self.calls)}"})
        return json.dumps({"ok": True})

    def wait_media(self, media_ref):
        self.waits.append(media_ref)

    def call_json(self, tool, args):
        self.calls.append((tool, args))
        return _timeline()


class ResponseLossClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.armed = False

    def arm_response_loss(self):
        self.armed = True

    def call(self, tool, args):
        self.calls.append((tool, args))
        result = json.dumps({
            "mediaRef": "media-1"} if tool == "import_media"
            else {"ok": True})
        if self.armed:
            self.armed = False
            raise AppliedResponseLost(f"{tool}: applied, response lost")
        return result


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.execution_authority_patcher = patch(
            "palmier.live_acceptance_media.verify_execution_media_authority",
            return_value=True)
        self.execution_authority = self.execution_authority_patcher.start()
        self.addCleanup(self.execution_authority_patcher.stop)

    def _fixture(self, root: str) -> LiveAcceptanceConfig:
        base = Path(root)
        out, transcripts = base / "out", base / "transcripts"
        out.mkdir(); transcripts.mkdir()
        (out / "final.mp4").write_bytes(b"final")
        (out / "cut_delivery.v1.json").write_text("{}")
        (out / "audit_report.json").write_text(json.dumps({
            "overall": "pass", "exitCode": 0,
            "checks": [{"name": "fixture", "status": "pass"}],
        }))
        (out / ".sniper-quality-policy.json").write_text(json.dumps({
            "schemaVersion": 1, "mode": "managed",
        }))
        (out / ".sniper-qc-approved.json").write_text("{}")
        (out / ".sniper-auto-edit-job.json").write_text("{}")
        _plan(base / "plan.json")
        _plan(base / "repair.json", repair=True)
        (base / "manifest.json").write_text("{}")
        (base / "bootstrap.mp4").write_bytes(b"media")
        return LiveAcceptanceConfig(
            root, str(out), str(base / "plan.json"),
            str(base / "repair.json"), str(base / "manifest.json"),
            str(base / "bootstrap.mp4"), str(transcripts),
            str(base / "evidence.json"), "short", 30, "9:16", "1080p",
            "Sniper P5 Test")

    @staticmethod
    def _master(config: LiveAcceptanceConfig, frames: int) -> MasterFacts:
        final = str(Path(config.out_dir, "final.mp4"))
        return MasterFacts(
            final, file_sha256(final), frames / 30, 30.0,
            1080, 1920, frames, "30/1")

    @staticmethod
    def _bootstrap(config: LiveAcceptanceConfig, frames: int) -> dict:
        return {
            "receiptHash": "a" * 64,
            "bootstrapArtifact": {
                "path": config.bootstrap_path, "sha256": "b" * 64,
                "videoFrames": frames, "statSignature": {}},
            "negativeDeclaration": {
                "stageBoundary": (
                    "after-reframe-before-recompose-punch-broll-title-"
                    "graphics-captions"),
                "containsTitleCards": False, "containsGraphics": False,
                "containsCaptions": False, "containsBroll": False},
        }

    @patch("palmier.live_acceptance_media.verify_palmier_visual_bootstrap")
    @patch("palmier.live_acceptance_media.approved_master")
    @patch("palmier.live_acceptance_media.probe_media")
    @patch("palmier.live_acceptance_media.probe_video_frames")
    def test_explicit_short_contract_and_bootstrap_are_bound(
            self, exact_frames, probe, approved, bootstrap):
        probe.return_value = MediaProbe(
            2.0, 30.0, False, 1080, 1920, 0, True, 2, 48000, "30/1")
        exact_frames.return_value = 60
        with tempfile.TemporaryDirectory() as tmp:
            config = self._fixture(tmp)
            approved.return_value = self._master(config, 60)
            bootstrap.return_value = self._bootstrap(config, 60)
            result = validate_config(config)
            self.assertEqual(result["targetFrames"], 60)
            self.assertEqual(result["projectRate"], "30/1")
            self.assertEqual(result["roundingDeltaFrames"], 0)
            Path(
                config.out_dir, ".sniper-quality-policy.json"
            ).write_text(json.dumps({
                "schemaVersion": 1, "mode": "managed", "drift": True,
            }))
            with self.assertRaisesRegex(PalmierError, "authority changed"):
                revalidate_bootstrap(config, result)

    @patch("palmier.live_acceptance_media.verify_palmier_visual_bootstrap")
    @patch("palmier.live_acceptance_media.approved_master")
    @patch("palmier.live_acceptance_media.probe_media")
    @patch("palmier.live_acceptance_media.probe_video_frames")
    def test_format_frames_and_repair_cut_changes_fail_closed(
            self, exact_frames, probe, approved, bootstrap):
        probe.return_value = MediaProbe(
            2.0, 30.0, False, 1080, 1920, 0, True, 2, 48000, "30/1")
        exact_frames.return_value = 59
        with tempfile.TemporaryDirectory() as tmp:
            config = self._fixture(tmp)
            approved.return_value = self._master(config, 60)
            bootstrap.return_value = self._bootstrap(config, 60)
            with self.assertRaisesRegex(PalmierError, "frames"):
                validate_config(config)
            wrong = replace(config, aspect="16:9")
            with self.assertRaisesRegex(PalmierError, "requires aspect"):
                validate_config(wrong)
            _plan(Path(config.repair_plan_path), 1.9, True)
            with self.assertRaisesRegex(PalmierError, "exact cutTrack"):
                validate_config(config)

    @patch("palmier.live_acceptance_media.verify_palmier_visual_bootstrap")
    @patch("palmier.live_acceptance_media.approved_master")
    @patch("palmier.live_acceptance_media.probe_media")
    @patch("palmier.live_acceptance_media.probe_video_frames")
    def test_exact_1553_authority_wins_over_1554_plan_rounding(
            self, exact_frames, probe, approved, bootstrap):
        probe.return_value = MediaProbe(
            51.807, 30.0, False, 1080, 1920, 0, True, 2, 48000, "30/1")
        exact_frames.return_value = 1553
        with tempfile.TemporaryDirectory() as tmp:
            config = self._fixture(tmp)
            _plan(Path(config.plan_path), 51.79)
            _plan(Path(config.repair_plan_path), 51.79, True)
            approved.return_value = self._master(config, 1553)
            bootstrap.return_value = self._bootstrap(config, 1553)
            result = validate_config(config)
        self.assertEqual(result["targetFrames"], 1553)
        self.assertEqual(result["planRoundedFrames"], 1554)
        self.assertEqual(result["roundingDeltaFrames"], 1)

    @patch("palmier.live_acceptance_media.approved_master")
    def test_missing_or_stale_managed_qc_never_reaches_bootstrap(
            self, approved):
        failures = (
            "quality-policy marker is missing",
            "managed QC approval authority is stale",
        )
        for message in failures:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                config = self._fixture(tmp)
                approved.side_effect = PalmierError(message)
                with self.assertRaisesRegex(PalmierError, message):
                    validate_config(config)

    @patch("palmier.live_acceptance_media.approved_master")
    def test_failed_renderer_audit_blocks_even_when_final_and_delivery_exist(
            self, approved):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._fixture(tmp)
            audit = Path(config.out_dir, "audit_report.json")
            audit.write_text(json.dumps({
                "overall": "fail", "exitCode": 1,
                "checks": [{
                    "name": "graphic_composite_reference",
                    "status": "fail",
                    "detail": "base_final.mp4 missing",
                }],
            }))
            with self.assertRaisesRegex(PalmierError, "renderer audit"):
                validate_config(config)
        approved.assert_not_called()

    def test_short_requires_true_execution_media_authority(self):
        self.execution_authority.return_value = False
        with tempfile.TemporaryDirectory() as tmp:
            config = self._fixture(tmp)
            with self.assertRaisesRegex(PalmierError, "admitted source-set"):
                validate_config(config)

    @patch("palmier.live_acceptance_media.approved_master")
    def test_legacy_quality_policy_cannot_enter_connected_release_cohort(
            self, approved):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._fixture(tmp)
            Path(
                config.out_dir, ".sniper-quality-policy.json"
            ).write_text(json.dumps({
                "schemaVersion": 1, "mode": "legacy",
                "migratedAt": "2026-07-31T00:00:00Z",
                "reason": "fixture",
            }))
            with self.assertRaisesRegex(PalmierError, "requires managed"):
                validate_config(config)
        approved.assert_not_called()

    @patch("palmier.live_acceptance_media.approved_master")
    def test_repair_must_change_exactly_one_graphic_before_mcp(
            self, approved):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._fixture(tmp)
            _plan(Path(config.repair_plan_path))
            with self.assertRaisesRegex(PalmierError, "exactly one graphic"):
                validate_config(config)
        approved.assert_not_called()


class WorklistTests(unittest.TestCase):
    def _run(self, steps, disconnect=True):
        with tempfile.TemporaryDirectory() as tmp:
            steps = _bind_test_assets(steps, tmp)
            path = Path(tmp, "operations.json")
            path.write_text(json.dumps({"steps": steps}))
            client = FakeClient()
            driver = GovernedWorklist(
                client, tmp, _timeline(), disconnect_first_import=disconnect)
            patches = (
                patch("palmier.live_acceptance_worklist.authorize_pre"),
                patch("palmier.live_acceptance_worklist.observe_post"),
                patch("palmier.live_acceptance_worklist.reconcile",
                      return_value={"operationCount": 1,
                                    "pendingOperation": None}),
            )
            with patches[0] as pre, patches[1] as post, patches[2] as recovery:
                result = driver.execute(str(path))
            return client, driver, result, pre, post, recovery

    def test_first_import_loses_post_receipt_then_reconciles(self):
        steps = [
            {"op": "import", "key": "gfx:0", "elementId": "g-1",
             "path": "/bound/card.mov"},
            {"op": "overlays", "entries": [{
                "mediaKey": "gfx:0", "elementId": "g-1",
                "startFrame": 3, "endFrame": 9}]},
        ]
        client, driver, result, pre, post, recovery = self._run(steps)
        self.assertEqual([row[0] for row in client.calls],
                         ["import_media", "add_clips"])
        self.assertEqual(recovery.call_count, 1)
        self.assertEqual(post.call_count, 1)
        self.assertTrue(result["disconnect"]["pendingCleared"])
        self.assertEqual(len(driver.calls), 2)
        self.assertEqual(pre.call_count, 2)

    def test_exact_master_and_mastered_stereo_calls_are_dynamic(self):
        steps = [
            {"op": "import", "key": "exact-master-reference",
             "path": "/bound/final.mp4", "importName": "exact"},
            {"op": "exact-master-reference-add",
             "mediaKey": "exact-master-reference", "startFrame": 0,
             "endFrame": 60},
            {"op": "exact-master-reference-disable"},
            {"op": "native-audio-master", "key": "mastered-stereo-authority",
             "elementId": "mastered-stereo-authority",
             "path": "/bound/master.wav", "importName": "audio",
             "startFrame": 0, "endFrame": 60},
            {"op": "mastered-stereo-route"},
        ]
        with patch("palmier.live_acceptance_worklist.load_state"), \
                patch("palmier.live_acceptance_worklist.load_state_dir",
                      return_value="/state"), \
                patch("palmier.live_acceptance_worklist.expected_disable_args",
                      return_value={"set": [{"index": 2, "hidden": True}]}), \
                patch("palmier.live_acceptance_worklist.expected_route_args",
                      return_value={"set": [{"index": 4, "muted": False}]}):
            client, _driver, _result, *_ = self._run(steps, False)
        self.assertEqual([row[0] for row in client.calls], [
            "import_media", "add_clips", "manage_tracks", "import_media",
            "add_clips", "get_timeline", "manage_tracks"])

    def test_unknown_worklist_op_never_mutates(self):
        with self.assertRaisesRegex(PalmierError, "cannot execute"):
            self._run([{"op": "future-destructive-op"}], False)

    def test_malformed_later_step_blocks_before_first_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            steps = _bind_test_assets([
                {"op": "import", "key": "gfx", "path": "/bound/card.mov"},
                {"op": "text", "content": "late malformed row"},
            ], tmp)
            path = Path(tmp, "operations.json")
            path.write_text(json.dumps({"steps": steps}))
            client = FakeClient()
            driver = GovernedWorklist(client, tmp, _timeline())
            with self.assertRaisesRegex(PalmierError, "frame window"):
                driver.execute(str(path))
            self.assertEqual(client.calls, [])

    def test_every_worklist_mutation_loses_response_then_reconciles_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            steps = _bind_test_assets([
                {"op": "import", "key": "gfx:0", "elementId": "g-1",
                 "path": "/bound/card.mov"},
                {"op": "overlays", "entries": [{
                    "mediaKey": "gfx:0", "elementId": "g-1",
                    "startFrame": 3, "endFrame": 9}]},
            ], tmp)
            path = Path(tmp, "operations.json")
            path.write_text(json.dumps({"steps": steps}))
            state = {
                "operationCount": 2, "pendingOperation": None,
                "mediaLedger": {"gfx:0": {
                    "path": steps[0]["path"], "mediaRef": "media-1",
                }},
            }
            client = ResponseLossClient()
            driver = GovernedWorklist(
                client, tmp, _timeline(), fault_every_mutation=True)
            with patch(
                    "palmier.live_acceptance_worklist.authorize_pre") as pre, \
                    patch(
                        "palmier.live_acceptance_worklist.observe_post") as post, \
                    patch(
                        "palmier.live_acceptance_worklist.reconcile",
                        return_value=state) as recovery:
                result = driver.execute(str(path))
        self.assertEqual(
            [row[0] for row in client.calls],
            ["import_media", "add_clips"])
        self.assertEqual(recovery.call_count, 2)
        self.assertEqual(pre.call_count, 2)
        self.assertEqual(post.call_count, 0)
        self.assertTrue(result["everyMutationReconciled"])
        self.assertTrue(all(row["responseLost"] for row in result["calls"]))


class ProofTests(unittest.TestCase):
    def test_repair_scope_and_delta_are_one_clip_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset = Path(tmp, "card.mov"); asset.write_bytes(b"card")
            operations = Path(tmp, "ops.json")
            operations.write_text(json.dumps({"steps": [
                {"op": "import", "path": str(asset)},
                {"op": "replace-overlay", "elementId": "g-1"}]}))
            _value, ident = repair_scope(str(operations))
            before, after = _timeline(), _timeline()
            after["tracks"][0]["clips"][0]["id"] = "new-clip"
            state = {"outDir": tmp, "elementLedger": {"elements": {
                ident: {"status": "current", "clipId": "new-clip",
                        "assetHash": "new", "startFrame": 3, "endFrame": 9,
                        "trackIndex": 0}}}}
            prior = {"clipId": "graphic-clip", "assetHash": "old",
                     "startFrame": 3, "endFrame": 9, "trackIndex": 0}
            result = repair_delta(RepairProofInput(
                before, after, state, ident, {}, prior))
            self.assertTrue(all(result["checks"].values()))
            self.assertFalse(
                result["postRepairFullMasterParity"]["claimed"])

    def test_repair_scope_must_match_preflight_graphic(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset = Path(tmp, "card.mov"); asset.write_bytes(b"card")
            operations = Path(tmp, "ops.json")
            operations.write_text(json.dumps({"steps": [
                {"op": "import", "path": str(asset)},
                {"op": "replace-overlay", "elementId": "wrong-graphic"}]}))
            with self.assertRaisesRegex(PalmierError, "different graphic"):
                repair_scope(str(operations), "expected-graphic")

    @patch("palmier.live_acceptance_proofs._write_sidecar")
    @patch("palmier.live_acceptance_proofs.fork_candidate")
    @patch("palmier.live_acceptance_proofs.reconcile_working_authority")
    @patch("palmier.live_acceptance_proofs.load_candidate")
    @patch("palmier.live_acceptance_proofs.load_state")
    @patch("palmier.live_acceptance_proofs.read_active")
    @patch("palmier.live_acceptance_proofs.authorize_pre")
    def test_manual_sentinel_is_blocked_adopted_and_forked(self, *mocks):
        authorize, read, state, candidate, reconcile, fork, _sidecar = mocks
        authorize.side_effect = PalmierError(
            "Palmier candidate changed outside verified Desktop ancestry")
        before = SimpleNamespace(
            fingerprint="before", semantic_fingerprint="sem-before",
            timeline=_timeline())
        manual = SimpleNamespace(
            fingerprint="manual", semantic_fingerprint="sem-manual",
            timeline=_timeline(SENTINEL_OPACITY))
        copied = SimpleNamespace(
            fingerprint="copy", semantic_fingerprint="sem-manual",
            timeline=_timeline(SENTINEL_OPACITY))
        read.side_effect = [before, manual, manual, copied]
        state.return_value = {"projectId": "project", "elementLedger": {
            "elements": {"g-1": {"clipId": "graphic-clip"}}}}
        candidate.side_effect = [
            {"status": "edited"}, {"status": "superseded-manual"}]
        reconcile.return_value = (
            {"origin": "palmier-manual"}, "candidate-manual")
        fork.return_value = {"timelineId": "copy", "fingerprint": "copy",
                             "semanticFingerprint": "sem-manual"}
        client = FakeClient()
        result = prove_manual_preservation(ManualProofInput(
            client, "/repo", "/out", {"id": "project"}, "g-1"))
        self.assertTrue(result["governedBlock"]["blocked"])
        self.assertEqual(result["sentinelOpacity"], SENTINEL_OPACITY)
        self.assertEqual(client.calls[0][0], "set_clip_properties")

    @patch("palmier.live_acceptance_proofs.authorize_pre")
    def test_manual_drift_requires_exact_ancestry_rejection(self, authorize):
        authorize.side_effect = PalmierError("some other hook failure")
        proof = __import__(
            "palmier.live_acceptance_proofs",
            fromlist=["_prove_governed_block"])
        request = proof.GovernedBlockInput(
            FakeClient(), "/repo", "/out", "clip", "fingerprint")
        with self.assertRaisesRegex(PalmierError, "exact ancestry"):
            proof._prove_governed_block(request)

    def test_cleanup_target_must_match_own_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "User Project.palmier"); path.mkdir()
            with self.assertRaisesRegex(PalmierError, "refusing to trash"):
                trash_disposable(
                    {"path": str(path)}, "Sniper P5 Connected")
            self.assertTrue(path.exists())

    def test_created_project_rejects_a_prior_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "Test.palmier")
            path.mkdir()
            client = Mock()
            client.call_json.return_value = {"openCount": 1, "projects": [{
                "id": "project", "name": "Test", "path": str(path),
                "isAccessible": True, "isOpen": True, "isActive": True}]}
            with self.assertRaisesRegex(PalmierError, "safely disposable"):
                created_project(client, "Test", {str(path)})

    def test_created_project_rejects_symlink_alias_to_existing_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp, "User Project.palmier")
            existing.mkdir()
            alias = Path(tmp, "Sniper Test.palmier")
            alias.symlink_to(existing, target_is_directory=True)
            client = Mock()
            client.call_json.return_value = {"openCount": 1, "projects": [{
                "id": "project", "name": "Sniper Test", "path": str(alias),
                "isAccessible": True, "isOpen": True, "isActive": True}]}
            with self.assertRaisesRegex(PalmierError, "safely disposable"):
                created_project(client, "Sniper Test", {str(existing)})

    def test_unproved_main_client_close_forces_disposable_retention(self):
        evidence = SimpleNamespace(
            value={
                "cleanupPolicy": {"trashDisposable": True},
                "cleanup": {},
            },
            save=Mock(),
        )
        main = Mock()
        main.close.side_effect = PalmierError("close unproved")
        cleanup_client = Mock()
        cleanup_client.phase.return_value = nullcontext()
        cleanup_client.connections = []
        cleanup_client.response_loss_receipts = []
        context = SimpleNamespace(
            config=SimpleNamespace(cleanup_timeout_s=30),
            inventory=Mock(), client=main, evidence=evidence,
            cleanup_connections=[], cleanup_fault_receipts=[],
        )
        with patch.object(
                live_harness, "fault_client",
                return_value=cleanup_client), patch.object(
                    live_harness, "cleanup_cohort",
                    return_value=[]) as cleanup:
            errors = live_harness._cleanup(
                context, {"surface": {
                    "openCount": 0, "openProjects": []}},
                {"path": "/tmp/Sniper.palmier"})
        self.assertTrue(any("close unproved" in row for row in errors))
        self.assertFalse(
            evidence.value["cleanupPolicy"]["trashDisposable"])
        self.assertEqual(
            evidence.value["cleanup"]["retainedReason"],
            "main MCP client close was not proved")
        self.assertFalse(
            cleanup.call_args.args[1].value[
                "cleanupPolicy"]["trashDisposable"])


if __name__ == "__main__":
    unittest.main()
