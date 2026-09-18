"""Generated coverage for every canonical current-render effect row."""
from __future__ import annotations

import copy
import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _render_effect_fixtures import fixture
from current_render_graph_build import GraphBuildInputs, compile_graph
from fingerprints import base_fingerprint
from graphics.exit_on_cut import effective_out_end, seams_from_plan
from graphics.graphics_render import format_for
from render_effect_discovery import (
    _import_candidates,
    discovery_gaps,
    referenced_python_paths,
    renderer_import_closure,
)
from render_effect_registry import (
    PROJECT_ROOT,
    RenderEffectError,
    effects,
    load_registry,
    validate_render_documents,
)
from render_stage_roots import changed_stage_roots


def _set_pointer(plan: dict, manifest: dict, pointer: str, after: object) -> None:
    parts = [part.replace("~1", "/").replace("~0", "~")
             for part in pointer.removeprefix("/").split("/")]
    target: object = plan
    if parts[0] == "manifest":
        target, parts = manifest, parts[1:]
    for index, part in enumerate(parts[:-1]):
        following = parts[index + 1]
        if isinstance(target, list):
            target = target[int(part)]
            continue
        if part not in target:
            target[part] = [] if following.isdigit() else {}
        target = target[part]
    leaf = parts[-1]
    if isinstance(target, list):
        target[int(leaf)] = after
    else:
        target[leaf] = after


def _entry_format(plan: dict) -> str:
    row = plan["graphicsTrack"][0]
    return format_for(
        row["kind"], row.get("anchor", "free-band"), row.get("spec"))[0]


class RenderEffectRegistryTests(unittest.TestCase):
    def test_registry_is_closed_complete_and_every_evidence_path_exists(
            self) -> None:
        registry = load_registry()
        self.assertEqual(registry["schemaVersion"], 1)
        cases = []
        for row in registry["effects"]:
            cases.extend(item["caseId"] for item in row["mutations"])
            for relative in row["readerFiles"]:
                self.assertTrue((PROJECT_ROOT / relative).exists(), relative)
        self.assertEqual(len(cases), len(set(cases)))
        self.assertEqual(len(registry["effects"]), len(effects()))

    def test_static_renderer_import_closure_has_no_unregistered_reader(
            self) -> None:
        self.assertEqual(discovery_gaps(), [])

    def test_caption_page_exceptions_are_exact_and_do_not_allow_asset_roots(
            self) -> None:
        registry = copy.deepcopy(load_registry())
        registry["discovery"]["nonAssetManifestReads"] = {
            "scripts/producer/captions/caption_pages.py": ["fps", "stale"]
        }
        reads = [{"document": "manifest", "key": "fps", "line": 1,
                  "path": path} for path in (
                      "scripts/producer/captions/caption_pages.py",
                      "scripts/producer/render.py")]
        with mock.patch("render_effect_discovery.load_registry",
                        return_value=registry), mock.patch(
                "render_effect_discovery.discover_root_reads",
                return_value=reads):
            gaps = discovery_gaps()
        self.assertEqual(gaps, [
            "scripts/producer/render.py:1 reads unregistered manifest.fps",
            "stale non-asset manifest exclusion: "
            "scripts/producer/captions/caption_pages.py:stale",
        ])
        for key in ("authorityHash", "captionAuthorityHash", "compositorHash", "destination", "entries", "fps",
                    "kind", "maxPageFrames", "schemaVersion", "shardManifestHash", "totalFrames"):
            with self.subTest(key=key), self.assertRaisesRegex(
                    RenderEffectError, "unregistered"):
                validate_render_documents({}, {key: []})

    def test_relative_import_resolves_inside_producer_package(self) -> None:
        node = ast.parse(
            "from .sealed_tar_format import canonical_tar_bytes"
        ).body[0]
        self.assertIsInstance(node, ast.ImportFrom)
        path = (
            PROJECT_ROOT / "scripts" / "producer" / "headless"
            / "sealed_archive.py"
        )
        self.assertIn(
            "headless.sealed_tar_format", _import_candidates(path, node))

    def test_subprocess_renderer_entrypoints_join_static_closure(self) -> None:
        closure = set(renderer_import_closure())
        observed = {path.relative_to(PROJECT_ROOT).as_posix()
                    for path in closure}
        expected = {
            "scripts/producer/headless/sealed_tar_format.py",
            "scripts/producer/motion/punch_in.py",
            "scripts/producer/motion/reframe_split.py",
            "scripts/producer/motion/face_track.py",
            "scripts/producer/motion/reframe.py",
            "scripts/producer/graphics/graphics_stage.py",
            "scripts/producer/audio/audio_enhance.py",
            "scripts/producer/audio/audio_gain.py",
            "scripts/producer/audit/audit_render.py",
        }
        self.assertTrue(expected.issubset(observed))
        self.assertTrue(referenced_python_paths().issubset(closure))

    def test_unknown_and_unreleased_root_fields_fail_before_render(self) -> None:
        plan, manifest = fixture("short-basic")
        with self.assertRaisesRegex(RenderEffectError, "unregistered"):
            validate_render_documents({**plan, "futureVisualLane": []}, manifest)
        with self.assertRaisesRegex(RenderEffectError, "unregistered"):
            validate_render_documents(plan, {**manifest, "mysteryAssets": []})
        with self.assertRaisesRegex(RenderEffectError, "unreleased"):
            validate_render_documents({**plan, "presenter": {"enabled": True}},
                                      manifest)
        for value in (None, [], False, [{"assetId": "TEST-unreleased"}]):
            with self.assertRaisesRegex(RenderEffectError, "unreleased"):
                validate_render_documents({**plan, "presenterLayouts": value}, manifest)

    def test_every_registry_mutation_moves_exact_compiler_roots(self) -> None:
        covered: set[str] = set()
        for row in effects():
            for mutation in row["mutations"]:
                with self.subTest(effect=row["effectId"],
                                  case=mutation["caseId"]):
                    before_plan, before_manifest = fixture(mutation["fixture"])
                    after_plan = copy.deepcopy(before_plan)
                    after_manifest = copy.deepcopy(before_manifest)
                    _set_pointer(
                        after_plan, after_manifest,
                        mutation["pointer"], mutation["after"])
                    if mutation.get("expectedRejected"):
                        with self.assertRaises(RenderEffectError):
                            changed_stage_roots(
                                before_plan, after_plan,
                                before_manifest, after_manifest)
                        covered.add(row["effectId"])
                        continue
                    changed = changed_stage_roots(
                        before_plan, after_plan,
                        before_manifest, after_manifest)
                    self.assertEqual(
                        changed, mutation["expectedChangedRoots"])
                    if "expectedBaseReuse" in mutation:
                        reusable = (
                            base_fingerprint(before_plan)
                            == base_fingerprint(after_plan))
                        self.assertEqual(
                            reusable, mutation["expectedBaseReuse"])
                    if "expectedFormats" in mutation:
                        self.assertEqual([
                            _entry_format(before_plan),
                            _entry_format(after_plan),
                        ], mutation["expectedFormats"])
                    if "expectedEffectiveEnd" in mutation:
                        row_after = after_plan["graphicsTrack"][0]
                        observed = effective_out_end(
                            row_after, seams_from_plan(after_plan))
                        self.assertEqual(
                            observed, mutation["expectedEffectiveEnd"])
                    covered.add(row["effectId"])
        self.assertEqual(covered, {row["effectId"] for row in effects()})

    def test_render_graph_nodes_bind_compiler_owned_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            producer, cache = root / "producer", root / "cache"
            producer.mkdir()
            cache.mkdir()
            plan_path, manifest_path = (
                producer / "edit_plan.json", root / "manifest.json")
            plan_path.write_text(json.dumps({
                "target": {"mode": "longform"},
                "cutTrack": [],
                "graphicsTrack": [],
            }))
            manifest_path.write_text("{}")
            for name in ("timeline_map.json", "base.mp4", "final.mp4"):
                (producer / name).write_bytes(name.encode())
            receipt = root / "source-set.json"
            receipt.write_bytes(b"source")
            inputs = GraphBuildInputs(
                producer, plan_path, manifest_path, producer / "base.mp4",
                producer / "final.mp4", cache)
            with mock.patch(
                "current_render_graph_build.source_authority",
                return_value=({
                    "source.manifest": "1" * 64,
                    "source.set": "2" * 64,
                    "source.stageRoot": "3" * 64,
                }, receipt),
            ), mock.patch(
                "current_render_graph_build.probe_video",
                return_value={"r_frame_rate": "24/1"},
            ), mock.patch(
                "current_render_graph_build.current_toolchain_hash",
                return_value="4" * 64,
            ):
                graph, _ = compile_graph(inputs, [], None)
            nodes = {row["nodeId"]: row for row in graph["nodes"]}
            self.assertIn("timeline.stageRoot",
                          nodes["node-timeline"]["inputDigests"])
            self.assertIn("base.stageRoot", nodes["node-base"]["inputDigests"])
            self.assertIn("base.manifestStageRoot",
                          nodes["node-base"]["inputDigests"])
            self.assertIn("composite.stageRoot",
                          nodes["node-composite"]["inputDigests"])
            self.assertIn("final.stageRoot",
                          nodes["node-final"]["inputDigests"])
            self.assertIn("final.manifestStageRoot",
                          nodes["node-final"]["inputDigests"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
