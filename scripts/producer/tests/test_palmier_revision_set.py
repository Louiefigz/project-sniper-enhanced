"""Long-form multi-element Palmier revision contracts."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from _common import *  # noqa: F401,F403
import fingerprints as fpr
from palmier.desktop_revision import (DesktopRevisionContext,
                                      prepare_revision)
from palmier.desktop_revision_progress import (
    authorize_revision_binding, initialize_revision_progress,
    record_revision_binding, revision_complete)
from palmier.desktop_manifest import prepare_desktop_manifest
from palmier.desktop_state import DesktopStageInput
from palmier.mcp_client import PalmierError
from palmier.revision_diff import RevisionDiffInput, build_revision
from palmier.revision_schema import validate_revision
from palmier.revision_qc_frames import revision_frame_refs


def _graphic(index, text=None, start=None):
    at = float(start if start is not None else index * 5 + 1)
    return {"id": f"g-{index:08x}", "kind": "statement-card",
            "outStart": at, "outEnd": at + 3,
            "spec": {"text": text or f"Card {index}"}}


def _plan(count=4):
    return {"target": {"mode": "longform"},
            "cutTrack": [{"id": "cut-main", "sourceId": "src",
                          "start": 0, "end": 840}],
            "graphicsTrack": [_graphic(index) for index in range(count)]}


def _ledger(plan):
    return {"schemaVersion": 2, "tombstones": {}, "elements": {
        row["id"]: {"status": "current", "lane": "graphics",
                    "clipId": f"clip-{row['id']}",
                    "mediaRef": f"media-{row['id']}",
                    "assetHash": f"hash-{row['id']}",
                    "assetPath": f"/{row['id']}.mov",
                    "startFrame": round(row["outStart"] * 24),
                    "endFrame": round(row["outEnd"] * 24),
                    "trackIndex": 2, "version": 1, "generation": 1}
        for row in plan["graphicsTrack"]}}


class RevisionDiffTests(unittest.TestCase):
    def test_fifty_element_plan_changes_only_requested_ids(self):
        old = _plan(50)
        new = json.loads(json.dumps(old))
        for index in (2, 19, 41):
            new["graphicsTrack"][index]["spec"]["text"] = f"Changed {index}"
        new["graphicsTrack"][7].update({"outStart": 40, "outEnd": 43})
        removed = new["graphicsTrack"].pop(30)["id"]
        new["graphicsTrack"].append(_graphic(99, start=700))
        revision = build_revision(RevisionDiffInput(
            old, new, _ledger(old), "candidate-fingerprint"))
        actions = [row["action"] for row in revision["operations"]]
        self.assertEqual(actions.count("replace"), 3)
        self.assertEqual(actions.count("move"), 1)
        self.assertEqual(actions.count("remove"), 1)
        self.assertEqual(actions.count("add"), 1)
        ids = {row["elementId"] for row in revision["operations"]}
        self.assertIn(removed, ids)
        self.assertIn("g-00000063", ids)
        self.assertLess(revision["dependencies"]["dirtyCoverage"], 0.1)

    def test_cut_ripple_and_zero_change_fail_closed(self):
        old = _plan()
        with self.assertRaisesRegex(PalmierError, "no element changes"):
            build_revision(RevisionDiffInput(old, old, _ledger(old), "candidate"))
        changed = json.loads(json.dumps(old))
        changed["cutTrack"][0]["end"] = 800
        with self.assertRaisesRegex(PalmierError, "broader rebuild"):
            build_revision(RevisionDiffInput(old, changed, _ledger(old), "candidate"))

    def test_conflicting_operations_for_one_id_are_rejected(self):
        rows = [{"lane": "nativeText", "action": action,
                 "elementId": "banner", "expectedVersion": 1,
                 "before": {"text": "A"}, "after": {"text": "B"}}
                for action in ("update", "remove")]
        with self.assertRaisesRegex(PalmierError, "conflicting"):
            validate_revision({"operations": rows})

    def test_addressing_and_legacy_text_do_not_change_render_hashes(self):
        plan = _plan()
        migrated = json.loads(json.dumps(plan))
        migrated["cutTrack"][0].update({"version": 2, "generation": 1})
        migrated["persistentText"] = [{"id": "legacy", "text": "ignored"}]
        self.assertEqual(fpr.plan_content_hash(plan),
                         fpr.plan_content_hash(migrated))
        self.assertEqual(fpr.base_fingerprint(plan),
                         fpr.base_fingerprint(migrated))


class RevisionPlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.asset = os.path.join(self.tmp.name, "changed.mov")
        with open(self.asset, "wb") as handle:
            handle.write(b"revision asset")

    def tearDown(self):
        self.tmp.cleanup()

    def _context(self, plan, ledger=None):
        return DesktopRevisionContext(
            plan, 24, 24 * 840, self.tmp.name,
            {"id": "src", "path": "/source.mp4"}, ledger or {
                "schemaVersion": 2, "elements": {}, "tombstones": {}})

    def test_render_count_equals_changed_pixel_assets(self):
        old = _plan(8)
        new = json.loads(json.dumps(old))
        new["graphicsTrack"][1]["spec"]["text"] = "Changed one"
        new["graphicsTrack"][2].update({"outStart": 100, "outEnd": 103})
        new["graphicsTrack"].pop(3)
        new["graphicsTrack"].append(_graphic(20, start=200))
        ledger = _ledger(old)
        revision = build_revision(RevisionDiffInput(old, new, ledger, "candidate"))
        rendered = {"path": self.asset, "proof": {"schemaVersion": 1}}
        with patch("palmier.desktop_revision.render_entry",
                   return_value=rendered) as call:
            prepared = prepare_revision(revision, self._context(new, ledger))
        self.assertEqual(call.call_count, 2)
        ops = [row["op"] for row in prepared["steps"]]
        self.assertEqual(ops.count("import"), 2)
        self.assertEqual(ops.count("replace-overlay"), 1)
        self.assertEqual(ops.count("add-overlay"), 1)
        self.assertEqual(ops.count("move-element"), 1)
        self.assertEqual(ops.count("remove-element"), 1)

    def test_stale_element_version_blocks_before_render(self):
        old = _plan(1)
        new = _plan(1)
        new["graphicsTrack"][0]["spec"]["text"] = "Changed"
        ledger = _ledger(old)
        revision = build_revision(RevisionDiffInput(old, new, ledger, "candidate"))
        ledger["elements"]["g-00000000"]["version"] = 2
        with self.assertRaisesRegex(PalmierError, "version is stale"):
            prepare_revision(revision, self._context(new, ledger))

    def test_thirty_text_additions_page_at_twenty_four_mutations(self):
        operations = [{"lane": "nativeText", "action": "add",
                       "elementId": f"text-{index}", "expectedVersion": 0,
                       "before": None,
                       "after": {"text": f"Label {index}",
                                 "outStart": index, "outEnd": index + 1}}
                      for index in range(30)]
        prepared = prepare_revision(
            {"operations": operations}, self._context(_plan()))
        self.assertEqual([len(row["mutationIds"]) for row in prepared["pages"]],
                         [24, 6])


class RevisionProgressTests(unittest.TestCase):
    def test_later_pages_wait_and_resume_without_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "operations.json")
            revision = {"revisionSetId": "rev-1234567890abcdef", "pages": [
                {"index": 0, "mutationIds": ["a", "b"]},
                {"index": 1, "mutationIds": ["c"]}]}
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"revision": revision}, handle)
            state = {"stage": "revision", "operations": {"path": path}}
            initialize_revision_progress(state, revision)
            authorize_revision_binding(state, {"mutationId": "a"})
            with self.assertRaisesRegex(PalmierError, "outside the current page"):
                authorize_revision_binding(state, {"mutationId": "c"})
            record_revision_binding(state, {"mutationIds": ["a", "b"]})
            authorize_revision_binding(state, {"mutationId": "c"})
            record_revision_binding(state, {"mutationId": "c"})
            self.assertTrue(revision_complete(state))
            with self.assertRaisesRegex(PalmierError, "already verified"):
                authorize_revision_binding(state, {"mutationId": "a"})

    def test_dirty_islands_get_before_through_after_qc_frames(self):
        authority = {"revisionSet": {"dependencies": {
            "dirtyWindows": [[10.0, 12.0], [400.0, 403.0]]}}}
        refs = revision_frame_refs(authority, 840.0)
        self.assertEqual(len(refs), 10)
        self.assertEqual(refs[0].label, "revision0_before")
        self.assertEqual(refs[-1].label, "revision1_after")


class RevisionManifestIntegrationTests(unittest.TestCase):
    def test_auto_diff_persists_candidate_bound_revision_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            old, new = _plan(2), _plan(2)
            new["graphicsTrack"][1]["spec"]["text"] = "New words"
            source = os.path.join(tmp, "source.mp4")
            asset = os.path.join(tmp, "changed.mov")
            old_path = os.path.join(tmp, "old.json")
            new_path = os.path.join(tmp, "new.json")
            manifest_path = os.path.join(tmp, "manifest.json")
            for path, value in ((old_path, old), (new_path, new)):
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(value, handle)
            with open(source, "wb") as handle:
                handle.write(b"source")
            with open(asset, "wb") as handle:
                handle.write(b"changed")
            manifest = {"sources": [{"id": "src", "role": "primary",
                                      "path": source, "fps": 24,
                                      "resolution": [1920, 1080]}]}
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle)
            state = {"projectSettings": {"fps": 24, "width": 1920,
                                          "height": 1080},
                     "plan": {"path": old_path},
                     "exactMasterReference": {"status": "ready", "startFrame": 0,
                         "endFrame": 20160, "hidden": True, "muted": True,
                         "assetPath": source, "assetHash": fpr.file_sha256(source)},
                     "expectedFingerprint": "candidate",
                     "elementLedger": _ledger(old)}
            inputs = DesktopStageInput(
                tmp, tmp, new_path, manifest_path, "revision")
            rendered = {"path": asset, "proof": {"schemaVersion": 1}}
            with patch("palmier.desktop_revision.render_entry",
                       return_value=rendered):
                result = prepare_desktop_manifest(inputs, state)
            revision = result["content"]["revision"]
            self.assertEqual(result["content"]["stage"], "revision")
            self.assertEqual(len(revision["pages"]), 1)
            self.assertTrue(os.path.isfile(revision["path"]))
            with open(revision["path"], encoding="utf-8") as handle:
                sidecar = json.load(handle)
            self.assertEqual(sidecar["baseCandidateFingerprint"], "candidate")
            self.assertEqual(sidecar["operations"][0]["elementId"],
                             "g-00000001")


if __name__ == "__main__":
    unittest.main()
