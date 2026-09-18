"""Immutable Palmier Auto Edit checkpoint transaction tests (no live MCP)."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from motion import recompose as rc
from palmier.checkpoint import (CheckpointInput, _authority,
                                publish_checkpoint)
from palmier import checkpoint_cli
from palmier.checkpoint_inputs import checkpoint_inputs, checkpoint_label
from palmier.checkpoint_plan import prepare_checkpoint_plan
from palmier.mcp_client import PalmierError
from palmier.executor import Executor
from palmier.sync import parse_steps
from palmier.timeline_authority import (load_authority, record_authority,
                                        snapshot)
from palmier.translate import TranslateRequest, translate


class CheckpointCliFailureTests(unittest.TestCase):
    """Required checkpoint failures must propagate to the GUI process."""

    def _main(self, error: Exception) -> tuple[int, dict]:
        output = io.StringIO()
        with patch.object(checkpoint_cli, "run", side_effect=error), \
                contextlib.redirect_stdout(output):
            code = checkpoint_cli.main()
        return code, json.loads(output.getvalue().strip().splitlines()[-1])

    def test_plan_or_render_failure_returns_nonzero(self):
        code, event = self._main(PalmierError(
            "required graphicsTrack[0] could not be rendered and proved"))
        self.assertEqual(code, 1)
        self.assertEqual(event["status"], "checkpoint_error")
        self.assertTrue(event["required"])

    def test_transport_waiting_is_not_reported_as_success(self):
        from palmier.mcp_client import PalmierWaiting
        code, event = self._main(PalmierWaiting("Palmier MCP unavailable"))
        self.assertEqual(code, 75)
        self.assertEqual(event["status"], "checkpoint_waiting")
        self.assertTrue(event["required"])


class CutStageCheckpointTests(unittest.TestCase):
    """Stage 'cut' lands the approved cut spine only, via the plan path."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.plan_path = os.path.join(self.dir, "edit_plan.json")
        self.manifest_path = os.path.join(self.dir, "asset-manifest.json")
        plan = {"target": {"mode": "longform"},
                "cutTrack": [{"sourceId": "src", "start": 0, "end": 1}],
                "punchIns": [{"outStart": 0, "outEnd": 1, "zoom": 1.1}],
                "graphicsTrack": [{"kind": "statement-card", "outStart": 0,
                                   "outEnd": 1,
                                   "spec": {"variant": "classic",
                                            "text": "Required copy"}}]}
        manifest = {"sources": [{"id": "src", "role": "primary",
                                 "path": "/source.mp4", "fps": 24,
                                 "resolution": [1920, 1080]}]}
        with open(self.plan_path, "w") as handle:
            json.dump(plan, handle)
        with open(self.manifest_path, "w") as handle:
            json.dump(manifest, handle)
        self.state = {"projectName": "demo"}

    def tearDown(self):
        self.tmp.cleanup()

    def _spec(self, stage):
        return CheckpointInput(self.dir, self.plan_path, self.manifest_path,
                               stage, 0)

    def test_cli_accepts_the_cut_stage(self):
        spec = checkpoint_cli._parse([self.plan_path, self.manifest_path,
                                      self.dir, "--stage", "cut"])
        self.assertEqual(spec.stage, "cut")

    def test_cut_stage_builds_cut_spine_steps_only(self):
        authority, steps, capability = checkpoint_inputs(
            self._spec("cut"), self.state)
        ops = {row["op"] for row in steps}
        self.assertIn("cuts", ops)
        self.assertFalse({"overlays", "keyframes", "text"} & ops)
        (row,) = [row for row in capability["omissions"]
                  if row["lane"] == "cut-stage"]
        self.assertIn("graphicsTrack", row["reason"])
        self.assertIn("punchIns", row["reason"])
        self.assertIn("Cut approved",
                      checkpoint_label(self._spec("cut"), authority))

    def test_same_plan_still_blocks_the_full_plan_stage(self):
        """The cut stage must not inherit plan-stage lane vetoes."""
        with self.assertRaisesRegex(PalmierError,
                                    "static punch hold semantics"):
            checkpoint_inputs(self._spec("plan"), self.state)


class CheckpointClient:
    def __init__(self):
        self.active = "parent"
        self.timelines = {"parent": "Source view"}
        self.calls = []
        self.parent_tracks = []

    def call_json(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        if tool == "get_projects":
            return {"projects": [{"id": "project", "name": "demo",
                                   "path": "/demo.palmier", "isActive": True}]}
        if tool == "get_timeline":
            tracks = self.parent_tracks if self.active == "parent" else []
            return {"id": self.active, "name": self.timelines[self.active],
                    "fps": 24, "width": 1920, "height": 1080,
                    "totalFrames": 0, "tracks": tracks}
        if tool == "create_timeline":
            self.active = "shadow"
            self.timelines["shadow"] = arguments["name"]
            return {"timelineId": "shadow"}
        if tool == "get_media":
            return {"timelines": [{"timelineId": ident, "name": name}
                                    for ident, name in self.timelines.items()]}
        raise AssertionError(tool)

    def call(self, tool, arguments=None):
        self.calls.append((tool, arguments or {}))
        if tool == "set_active_timeline":
            self.active = arguments["timelineId"]
        elif tool == "organize_media":
            for row in arguments.get("renames", []):
                self.timelines[row["item"]] = row["name"]
        return "ok"


def _bindings(*_args):
    return SimpleNamespace(
        refs={"src": "source-ref"}, seconds={"src": 60.0},
        media_map={"src:key": {"ref": "source-ref", "seconds": 60.0}},
        component_status={})


def _executor(*_args):
    return SimpleNamespace(expected_end_frame=24, project_fps=24)


def _verification(*_args):
    return {"ok": True, "timelineId": "shadow",
            "expected": {"totalFrames": 24},
            "actual": {"totalFrames": 24}}


class WorkingCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.plan_path = os.path.join(self.dir, "edit_plan.json")
        self.manifest_path = os.path.join(self.dir, "asset-manifest.json")
        self.plan = {"target": {"mode": "longform"},
                     "cutTrack": [{"sourceId": "src", "start": 0, "end": 1}]}
        self.manifest = {"sources": [{"id": "src", "role": "primary",
                                      "path": "/source.mp4", "fps": 24,
                                      "resolution": [1920, 1080]}]}
        self._write(self.plan_path, self.plan)
        self._write(self.manifest_path, self.manifest)
        self.client = CheckpointClient()
        self._write(os.path.join(self.dir, "palmier.sync.json"), {
            "schemaVersion": 4, "ownership": "sniper",
            "workspaceMode": "managed-draft", "mirrorMode": None,
            "projectId": "project", "projectName": "demo",
            "projectPath": "/demo.palmier", "latestTimelineId": "parent",
            "timelineIds": [{"id": "parent", "name": "Source view"}],
            "mediaMap": {}})
        record_authority(
            self.dir, snapshot("project", self.client.call_json("get_timeline", {})),
            "sniper-bootstrap")
        self.spec = CheckpointInput(
            self.dir, self.plan_path, self.manifest_path, "plan", 0)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _write(path, value):
        with open(path, "w") as handle:
            json.dump(value, handle)

    def _publish(self, authority_current=None):
        patches = [
            patch("palmier.checkpoint.MediaLibrary",
                  side_effect=lambda *_a: SimpleNamespace(ensure=_bindings)),
            patch("palmier.checkpoint._apply_all", side_effect=_executor),
            patch("palmier.checkpoint.verify_generated_timeline",
                  side_effect=_verification),
        ]
        if authority_current is not None:
            patches.append(patch("palmier.checkpoint._authority_current",
                                 side_effect=authority_current))
        with patches[0], patches[1], patches[2]:
            if len(patches) == 4:
                with patches[3]:
                    return publish_checkpoint(self.client, self.spec)
            return publish_checkpoint(self.client, self.spec)

    def test_creates_new_labeled_checkpoint_and_binds_readback(self):
        result = self._publish()
        self.assertEqual(result["status"], "checkpoint_ready")
        self.assertEqual(self.client.active, "shadow")
        self.assertEqual(self.client.timelines["parent"], "Source view")
        self.assertIn("Plan authored", self.client.timelines["shadow"])
        with open(os.path.join(self.dir, "palmier.sync.json")) as handle:
            state = json.load(handle)
        checkpoint = state["workingCheckpoint"]
        expected = _authority(self.spec, self.plan)
        self.assertEqual(checkpoint["key"], expected.checkpoint_key)
        self.assertEqual(checkpoint["planHash"], expected.plan_hash)
        self.assertEqual(checkpoint["readback"]["timelineId"], "shadow")
        self.assertFalse(checkpoint["authoritative"])
        self.assertEqual(state["workspaceMode"], "managed-draft")
        self.assertNotIn("verification", state)

    def test_manual_parent_drift_advances_the_head_without_a_shadow(self):
        self.client.parent_tracks = [{"id": "manual", "clips": []}]
        result = self._publish()
        self.assertEqual(result["status"], "checkpoint_superseded")
        self.assertEqual(result["timelineId"], "parent")
        self.assertEqual(result["authority"], "palmier")
        self.assertIn("visible revision is now", result["reason"])
        creates = [row for row in self.client.calls if row[0] == "create_timeline"]
        self.assertEqual(creates, [])
        self.assertEqual(load_authority(self.dir)["origin"], "palmier-manual")

    def test_stale_plan_restores_parent_and_never_commits_sidecar(self):
        sidecar = os.path.join(self.dir, "palmier.sync.json")
        with open(sidecar) as handle:
            before = handle.read()
        with self.assertRaisesRegex(PalmierError, "changed during"):
            self._publish(authority_current=[True, False])
        self.assertEqual(self.client.active, "parent")
        self.assertTrue(self.client.timelines["shadow"].endswith("-FAILED"))
        with open(sidecar) as handle:
            self.assertEqual(handle.read(), before)
        self.assertEqual(load_authority(self.dir)["timelineId"], "parent")

    def test_parent_cas_adopts_a_concurrent_manual_change(self):
        sidecar = os.path.join(self.dir, "palmier.sync.json")
        with open(sidecar) as handle:
            before = handle.read()

        def mutate_parent(*_args):
            self.client.parent_tracks = [{"id": "manual", "clips": []}]
            return _executor()

        with patch("palmier.checkpoint.MediaLibrary",
                   side_effect=lambda *_a: SimpleNamespace(ensure=_bindings)), \
                patch("palmier.checkpoint._apply_all", side_effect=mutate_parent), \
                patch("palmier.checkpoint.verify_generated_timeline",
                      side_effect=_verification):
            result = publish_checkpoint(self.client, self.spec)
        self.assertEqual(result["status"], "checkpoint_superseded")
        self.assertIn("parent content-changed", result["reason"])
        self.assertEqual(self.client.active, "parent")
        self.assertEqual(load_authority(self.dir)["origin"], "palmier-manual")
        with open(sidecar) as handle:
            self.assertEqual(handle.read(), before)

    def test_generated_cas_adopts_an_edit_during_verification(self):
        sidecar = os.path.join(self.dir, "palmier.sync.json")
        with open(sidecar) as handle:
            before = handle.read()

        def mutate_generated(*_args):
            self.client.timelines["shadow"] = "My live revision"
            return _verification()

        with patch("palmier.checkpoint.MediaLibrary",
                   side_effect=lambda *_a: SimpleNamespace(ensure=_bindings)), \
                patch("palmier.checkpoint._apply_all", side_effect=_executor), \
                patch("palmier.checkpoint.verify_generated_timeline",
                      side_effect=mutate_generated):
            result = publish_checkpoint(self.client, self.spec)
        self.assertEqual(result["status"], "checkpoint_superseded")
        self.assertIn("changed during verification", result["reason"])
        self.assertEqual(self.client.active, "shadow")
        self.assertEqual(load_authority(self.dir)["origin"], "palmier-manual")
        with open(sidecar) as handle:
            self.assertEqual(handle.read(), before)

    def test_plan_subset_keeps_simple_and_smooth_aliveness_motion(self):
        plan = {**self.plan,
                "target": {"mode": "longform",
                           "lanes": {"transitions": "operator"}},
                "transitions": [{"outTime": 0.5, "kind": "flash"}],
                "captions": {"burn": True},
                "punchIns": [{"outStart": 0, "outEnd": 0.5, "zoom": 1.1,
                              "attackS": 0.1, "releaseS": 0.1},
                             {"outStart": 0.5, "outEnd": 1, "kind": "ramp",
                              "role": "aliveness", "ease": "smooth",
                              "ramp": {"direction": "in",
                                       "ratePctPerS": 0.8}}]}
        prepared = prepare_checkpoint_plan(plan, render_graphics=False)
        self.assertNotIn("transitions", prepared.plan)
        self.assertNotIn("captions", prepared.plan)
        self.assertEqual(len(prepared.plan["punchIns"]), 2)
        lanes = {row["lane"] for row in prepared.omissions}
        self.assertTrue({"transitions", "captions"} <= lanes)
        self.assertNotIn("motion", lanes)

    def test_untranslatable_requested_motion_blocks_checkpoint(self):
        plan = {**self.plan, "punchIns": [{
            "outStart": 0, "outEnd": 1, "kind": "bracket",
            "bracket": True, "zoom": 1.2, "holdS": 0.6}]}
        with self.assertRaisesRegex(PalmierError, "required motion.*bracket"):
            prepare_checkpoint_plan(plan, render_graphics=False)

    def test_static_punch_blocks_without_proven_hold_semantics(self):
        plan = {**self.plan, "punchIns": [{
            "outStart": 0, "outEnd": 1, "zoom": 1.1}]}
        with self.assertRaisesRegex(PalmierError, "static punch hold semantics"):
            prepare_checkpoint_plan(plan, render_graphics=False)

    def test_cream_rail_checkpoint_stamps_a_rightward_face_pan(self):
        plan = {**self.plan,
                "cutTrack": [{"sourceId": "src", "start": 0, "end": 4}],
                "faceBBoxNorm": [0.47, 0.28, 0.16, 0.20],
                "graphicsTrack": [{
                    "kind": "nateherk-rail", "anchor": "free-band",
                    "outStart": 1.0, "outEnd": 3.0, "spec": {},
                    "reason": "Cream rail proves the edit stages."}]}
        prepared = prepare_checkpoint_plan(plan, render_graphics=False)
        (motion,) = [row for row in prepared.plan["punchIns"]
                     if row.get("role") == "recompose"]
        landed = rc.face_out_x(0.55, motion["zoom"], motion["centerX"])
        self.assertGreater(landed, 0.55)
        self.assertAlmostEqual(landed, rc.clear_center([0.3302, 1.0]), places=3)
        request = TranslateRequest(
            fps=24, source_path="/source.mp4", graphics_paths={},
            project_name="demo", width=1920, height=1080)
        lanes = parse_steps(translate(prepared.plan, request))
        self.assertEqual(len(lanes["keyframes"]), 2)
        position = next(row for row in lanes["keyframes"]
                        if row["property"] == "position")
        self.assertLess(min(row[1] for row in position["rows"]), 0.0)

    def test_cream_rail_without_measured_face_blocks_checkpoint(self):
        plan = {**self.plan, "graphicsTrack": [{
            "kind": "nateherk-bullet-bars", "anchor": "free-band",
            "outStart": 0, "outEnd": 1, "spec": {}, "reason": "proof"}]}
        with self.assertRaisesRegex(PalmierError, "faceBBoxNorm"):
            prepare_checkpoint_plan(plan, render_graphics=False)

    def test_working_graphics_normalize_to_a_source_sized_canvas(self):
        plan = {**self.plan, "graphicsTrack": [{
            "kind": "glass-lower-third", "outStart": 0, "outEnd": 1,
        }]}
        request = TranslateRequest(
            fps=24, source_path="/source.mp4", graphics_paths={0: "/g.mov"},
            project_name="demo", width=3840, height=2160,
            normalize_graphics_to_canvas=True)
        steps = translate(plan, request)
        overlay = next(row for row in steps if row["op"] == "overlays")
        self.assertEqual(overlay["entries"][0]["transform"], {
            "width": 1.0, "height": 1.0, "centerX": 0.5, "centerY": 0.5})

        calls = []
        client = SimpleNamespace(
            call_json=lambda *_a, **_k: {
                "clips": [{"id": "overlay", "track": 0}],
                "removedClipIds": []},
            call=lambda tool, args: calls.append((tool, args)))
        executor = Executor(client)
        executor.project_fps = 24
        executor.media = {"gfx:0": "media"}
        executor.media_s = {"gfx:0": 1.0}
        executor._place_overlay(overlay["entries"][0], 0, None)
        self.assertIn(("set_clip_properties", {
            "clipIds": ["overlay"],
            "transform": overlay["entries"][0]["transform"]}), calls)

    def test_selected_graphic_render_failure_blocks_checkpoint(self):
        plan = {**self.plan, "graphicsTrack": [{
            "kind": "statement-card", "outStart": 0, "outEnd": 1,
            "spec": {"variant": "classic", "text": "Required copy"},
        }]}
        with patch("palmier.checkpoint_plan.render_entry",
                   side_effect=RuntimeError("render failed")):
            with self.assertRaisesRegex(
                    PalmierError, r"required graphicsTrack\[0\].*render failed"):
                prepare_checkpoint_plan(plan)
        self.assertEqual(len(plan["graphicsTrack"]), 1)

    def test_selected_graphic_missing_proof_blocks_checkpoint(self):
        plan = {**self.plan, "graphicsTrack": [{
            "kind": "statement-card", "outStart": 0, "outEnd": 1,
            "spec": {"variant": "classic", "text": "Required copy"},
        }]}
        rendered = {"path": "/graphic.mp4", "cached": False,
                    "kind": "statement-card"}
        with patch("palmier.checkpoint_plan.render_entry",
                   return_value=rendered):
            with self.assertRaisesRegex(PalmierError, "no rendered asset proof"):
                prepare_checkpoint_plan(plan)
        self.assertEqual(len(plan["graphicsTrack"]), 1)


if __name__ == "__main__":
    unittest.main()
