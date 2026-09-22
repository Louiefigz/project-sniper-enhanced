"""Same-path media replacement and metadata cannot authorize a stale base."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import assemble
from base_reuse import observe_inputs, plan_digests, prepare_base_inputs, seal_binding
from fingerprints import fingerprint_record


def bound_record(base: str | Path, plan: dict, policy: str = "legacy-v1") -> dict:
    """Create byte-bearing dispatch fixtures, without claiming media quality."""
    root = Path(base).parent
    source = root / "fixture-source.mov"
    source.write_bytes(b"original source fixture")
    manifest_path = root / "fixture-manifest.json"
    manifest = {"sources": [{"id": "raw-1", "path": str(source)}]}
    manifest_path.write_text(json.dumps(manifest))
    manifest["_path"] = str(manifest_path)
    binding = seal_binding(str(base), plan, observe_inputs(manifest), policy)
    return {**fingerprint_record(plan, policy), "manifestPath": str(manifest_path),
            "baseReuse": binding}


class BaseReuseTests(unittest.TestCase):
    """Keep valid revision fast paths while proving their actual dependencies."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "final.mp4"
        self.base.write_bytes(b"completed base fixture")
        self.plan = {"cutTrack": [{"sourceId": "raw-1", "start": 0, "end": 2}]}
        self.record = bound_record(self.base, self.plan)
        self.fp = self.root / "base.fingerprint.json"
        self.fp.write_text(json.dumps(self.record))

    def state(self, plan: dict | None = None) -> str:
        return assemble._base_state(str(self.base), plan or self.plan, str(self.fp))

    def test_unchanged_and_graphic_only_plans_reuse(self) -> None:
        self.assertEqual(self.state(), "current")
        self.assertEqual(self.state({**self.plan, "graphicsTrack": [{"kind": "chart-story"}]}), "current")
        self.assertEqual(len(self.record["baseReuse"]["planDigest"]), 64)

    def test_source_replaced_at_same_path_is_stale(self) -> None:
        (self.root / "fixture-source.mov").write_bytes(b"different source fixture")
        self.assertEqual(self.state(), "stale")

    def test_completed_base_replaced_at_same_path_is_stale(self) -> None:
        self.base.write_bytes(b"other completed base")
        self.assertEqual(self.state(), "stale")

    def test_missing_source_is_stale(self) -> None:
        (self.root / "fixture-source.mov").unlink()
        self.assertEqual(self.state(), "stale")

    def test_plan_snapshot_cannot_upgrade_a_legacy_base(self) -> None:
        self.fp.write_text(json.dumps(fingerprint_record(self.plan)))
        (self.root / "base_plan.json").write_text(json.dumps(self.plan))
        self.assertEqual(self.state(), "stale")

    def test_audio_only_edit_remains_eligible(self) -> None:
        edited = {**self.plan, "audioGain": [{"outStart": 0, "outEnd": 1, "dB": -2}]}
        self.assertEqual(self.state(edited), "audio_stale")

    def test_explicit_replacement_manifest_is_checked(self) -> None:
        replacement = self.root / "replacement.json"
        replacement.write_text(json.dumps({"sources": []}))
        options = assemble.BaseManifest(str(replacement))
        self.assertEqual(assemble._base_state(str(self.base), self.plan, str(self.fp), options), "stale")

    def test_v2_finishing_does_not_change_base_digest(self) -> None:
        edited = {**self.plan, "audioGain": [{"outStart": 0, "outEnd": 1, "dB": -2}]}
        self.assertEqual(plan_digests(self.plan, "source-float-v2"),
                         plan_digests(edited, "source-float-v2"))

    def test_resume_does_not_bless_unproven_intermediates(self) -> None:
        manifest = json.loads(Path(self.record["manifestPath"]).read_text())
        manifest["_path"] = self.record["manifestPath"]
        ctx = SimpleNamespace(skip_graphics=True, resume=True, manifest=manifest,
                              plan=self.plan, audio_clock_policy="legacy-v1", out_dir=str(self.root))
        prepare_base_inputs(ctx)
        self.assertTrue(ctx.resume)
        self.base.write_bytes(b"changed base")
        prepare_base_inputs(ctx)
        self.assertFalse(ctx.resume)

    def test_observed_manifest_does_not_alias_mutable_input(self) -> None:
        manifest = {"sources": []}
        observed = observe_inputs(manifest)
        saved = copy.deepcopy(observed)
        manifest["sources"].append({"id": "replacement"})
        self.assertEqual(saved, observed)


if __name__ == "__main__":
    unittest.main()
