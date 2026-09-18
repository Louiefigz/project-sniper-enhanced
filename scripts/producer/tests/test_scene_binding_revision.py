"""Fail-closed scene binding to Desktop Palmier revision compilation."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from _ingest_admission_fixture import runner as admission_runner
from fingerprints import plan_content_hash
from ingest_admission import admit_ingest_candidates, collect_ingest_candidates
from palmier.desktop_manifest import prepare_desktop_manifest
from palmier.desktop_revision import DesktopRevisionContext, prepare_revision
from palmier.desktop_state import DesktopStageInput
from palmier.mcp_client import PalmierError
from palmier.revision_schema import write_revision
from palmier.scene_binding_revision import build_scene_binding_revision
from palmier.scene_bindings import scene_binding_delta
from tests.scene_binding_revision_fixture import (
    make_scene_revision_fixture,
    moved_current,
)


def _context(root: Path, fixture: object) -> DesktopRevisionContext:
    return DesktopRevisionContext(
        {}, 30.0, 1800, str(root), {"id": "source"},
        fixture.ledger)


class SceneBindingRevisionCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fixture = make_scene_revision_fixture(self.root)

    def test_one_unit_compiles_to_exact_import_and_replace_work(self) -> None:
        revision = build_scene_binding_revision(self.fixture.request())
        self.assertEqual(len(revision["operations"]), 1)
        operation = revision["operations"][0]
        self.assertEqual(operation["elementId"], "scene-045-unit-right")
        with patch(
            "palmier.desktop_revision.render_entry",
            side_effect=AssertionError("scene media must not re-render"),
        ):
            prepared = prepare_revision(
                revision, _context(self.root, self.fixture))
        self.assertEqual(
            [row["op"] for row in prepared["steps"]],
            ["import", "replace-overlay"])
        imported, replacement = prepared["steps"]
        self.assertEqual(imported["path"], str(self.fixture.new_right))
        self.assertEqual(replacement["oldClipId"], "clip-right-old")
        self.assertEqual(replacement["oldMediaRef"], "media-right-old")
        self.assertEqual(replacement["trackIndex"], 3)
        self.assertEqual(
            (replacement["startFrame"], replacement["endFrame"]),
            (1350, 1530))
        self.assertEqual(
            prepared["pages"][0]["mutationIds"],
            [imported["mutationId"], replacement["mutationId"]])

    def test_missing_or_stale_ledger_binding_fails_closed(self) -> None:
        missing = copy.deepcopy(self.fixture.ledger)
        missing["elements"].pop("scene-045-unit-right")
        with self.assertRaisesRegex(PalmierError, "current Palmier ledger"):
            build_scene_binding_revision(replace(
                self.fixture.request(), element_ledger=missing))
        revision = build_scene_binding_revision(self.fixture.request())
        self.fixture.ledger["elements"]["scene-045-unit-right"]["version"] = 2
        with self.assertRaisesRegex(PalmierError, "version is stale"):
            prepare_revision(revision, _context(self.root, self.fixture))

    def test_timing_or_delivery_format_cannot_hide_in_media_delta(self) -> None:
        scene, bindings = moved_current(self.fixture)
        request = replace(
            self.fixture.request(), current_scene=scene,
            current_bindings=bindings,
            delta=scene_binding_delta(
                self.fixture.previous_bindings, bindings))
        with self.assertRaisesRegex(PalmierError, "exactly one"):
            build_scene_binding_revision(request)
        other = self.root / "format"
        other.mkdir()
        changed_format = make_scene_revision_fixture(other, ".mp4")
        with self.assertRaisesRegex(PalmierError, "delivery format"):
            build_scene_binding_revision(changed_format.request())

    def test_stale_delta_changed_media_and_extra_operations_are_rejected(self) -> None:
        stale = copy.deepcopy(self.fixture.delta)
        stale["preservedBindingIds"] = []
        with self.assertRaisesRegex(PalmierError, "delta is stale"):
            build_scene_binding_revision(replace(
                self.fixture.request(), delta=stale))
        revision = build_scene_binding_revision(self.fixture.request())
        mixed = {key: value for key, value in revision.items()
                 if key not in {"revisionSetId", "digest"}}
        mixed["operations"] = list(mixed["operations"]) + [{
            "lane": "nativeText", "action": "add",
            "elementId": "unrelated-copy", "expectedVersion": 0,
            "before": None,
            "after": {"text": "not part of scene repair",
                      "outStart": 0, "outEnd": 1},
        }]
        with self.assertRaisesRegex(PalmierError, "extra revision"):
            prepare_revision(mixed, _context(self.root, self.fixture))

    def test_media_bytes_are_reproved_when_worklist_is_materialized(self) -> None:
        revision = build_scene_binding_revision(self.fixture.request())
        self.fixture.new_right.write_bytes(b"changed-after-revision")
        with self.assertRaisesRegex(PalmierError, "media bytes changed"):
            prepare_revision(revision, _context(self.root, self.fixture))

    def test_standard_desktop_revision_manifest_consumes_the_sidecar(self) -> None:
        plan = {
            "target": {"mode": "longform"},
            "cutTrack": [{"id": "cut-main", "sourceId": "source",
                          "start": 0, "end": 60}],
        }
        plan_hash = plan_content_hash(plan)
        revision = build_scene_binding_revision(replace(
            self.fixture.request(), base_plan_hash=plan_hash,
            next_plan_hash=plan_hash))
        plan_path = self.root / "plan.json"
        manifest_path = self.root / "manifest.json"
        source = self.root / "source.mp4"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        source.write_bytes(b"source-media")
        admitted = admit_ingest_candidates(
            collect_ingest_candidates([source], None, None),
            self.root, admission_runner)
        media = admitted.media_by_original[str(source)]
        manifest_path.write_text(json.dumps({"sources": [{
            "id": "source", "role": "primary", "path": media.snapshot_path,
            "originalPath": media.original_path,
            "sourceSha256": media.sha256,
            "admissionReceiptPath": media.receipt_path,
            "admissionReceiptSha256": media.receipt_sha256,
            "fps": 30, "resolution": [1920, 1080],
        }], "sourceSetAdmission": admitted.binding}), encoding="utf-8")
        saved = write_revision(str(self.root), revision)
        inputs = DesktopStageInput(
            str(self.root), str(self.root), str(plan_path),
            str(manifest_path), "revision",
            revision_path=saved["path"])
        state = {
            "projectSettings": {"fps": 30, "width": 1920, "height": 1080},
            "plan": {"path": str(plan_path)},
            "expectedFingerprint": "f" * 64,
            "exactMasterReference": {
                "status": "ready", "startFrame": 0, "endFrame": 1800,
                "hidden": True, "muted": True,
                "assetPath": media.snapshot_path,
                "assetHash": media.sha256,
            },
            "elementLedger": self.fixture.ledger,
        }
        result = prepare_desktop_manifest(inputs, state)
        self.assertEqual(
            [row["op"] for row in result["content"]["steps"]],
            ["import", "replace-overlay"])
        self.assertEqual(
            result["content"]["revision"]["revisionSetId"],
            revision["revisionSetId"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
