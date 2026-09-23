"""Read-only import must reconstruct original V1/V2 bytes with the shared SDK batch."""
from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_studio_hf_ids as fixtures
import test_studio_pending_edits as pending
from studio import StudioProjectError, comp_hf_ids, sync_files
from studio.sync_diff import load_state

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src/app/api/producer/studio/import"))
from bridge import baseline


class StudioImportBaselineTests(unittest.TestCase):
    """Only existing inert base probe leaves are replaced; actual SDK/reader logic runs."""

    def setUp(self) -> None:
        """Reuse fresh allowed TEST views, never a creator project or retained receipt."""
        self.fixture = fixtures.StudioHfIdsTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        probe = self.fixture.probe
        self.probe = SimpleNamespace(width=probe.width, height=probe.height, duration=probe.duration,
                                     fps=probe.fps, rotation=0, audio_present=False)

    def _snapshot(self) -> dict[Path, bytes]:
        """Observe the original finite fixture files without writing a baseline."""
        return {file: file.read_bytes() for file in self.fixture.allowed}

    def _read(self) -> dict:
        """Keep real version, host, instance and hash checks around inert media leaves."""
        with patch("assemble._base_state", return_value="current"), \
                patch("studio.index_semantics.probe_media", return_value=self.probe):
            return baseline({"dir": str(self.fixture.root)})

    def test_new_view_uses_one_exact_sdk_batch_and_leaves_all_files_unchanged(self) -> None:
        """Original upgraded generation, not raw template HTML, is the authority."""
        self.fixture._generate()
        before = self._snapshot()
        with patch.object(comp_hf_ids, "run_text", wraps=comp_hf_ids.run_text) as run:
            value = self._read()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(value["host"], (self.fixture.studio / "index.html").read_text())
        for relative, text in value["instances"].items():
            self.assertEqual(text, (self.fixture.studio / relative).read_text())
        self.assertEqual(self._snapshot(), before)

    def test_legacy_view_retains_original_bytes_without_launching_node(self) -> None:
        """V1 history must never borrow V2 IDs or a relabeled manifest."""
        self.fixture._legacy()
        before = self._snapshot()
        with patch.object(comp_hf_ids, "run_text", side_effect=AssertionError("legacy Node forbidden")):
            value = self._read()
        state = load_state(str(self.fixture.studio))
        self.assertEqual(len(value["instances"]), len(state.manifest["entries"]))
        self.assertEqual(len(value["instances"]), 4)
        self.assertEqual(self._snapshot(), before)

    def test_unknown_or_mixed_generation_refuses_before_rebuild_or_sdk(self) -> None:
        """No installed version inference can repair an original generation mismatch."""
        self.fixture._generate()
        state = load_state(str(self.fixture.studio))
        unknown = {**state.manifest, "generator": "studio-project-v99"}
        cases = [replace(state, manifest=unknown), replace(state, fingerprint={"generator": "studio-project-v1"})]
        for supplied in cases:
            with patch.object(sync_files, "_rebuild_instance", side_effect=AssertionError("rebuild forbidden")), \
                    self.assertRaises(StudioProjectError):
                sync_files.rebuild_original_instances(supplied)

    def test_changed_original_instance_hash_is_not_repaired_by_normalization(self) -> None:
        """A new SDK value cannot rebaseline the original manifest digest."""
        self.fixture._generate()
        before = self._snapshot()
        state = load_state(str(self.fixture.studio))
        manifest = copy.deepcopy(state.manifest)
        manifest["files"][manifest["entries"][0]["file"]] = "0" * 64
        with patch("studio.sync_diff.load_state", return_value=replace(state, manifest=manifest)), \
                self.assertRaisesRegex(ValueError, "Original composition source"):
            self._read()
        self.assertEqual(self._snapshot(), before)

    def test_empty_new_view_uses_no_normalizer_batch(self) -> None:
        """No-graphics views do not send an invalid empty SDK batch."""
        self.fixture._generate()
        state = load_state(str(self.fixture.studio))
        state = replace(state, manifest={**state.manifest, "entries": []}, plan={**state.plan, "graphicsTrack": []})
        with patch.object(comp_hf_ids, "run_text", side_effect=AssertionError("empty Node forbidden")):
            self.assertEqual(sync_files.rebuild_original_instances(state), {})


    def test_genuine_deletion_retains_original_head_on_import(self) -> None:
        """Actual sync keeps its head dependency even after its last user is removed."""
        fixture = pending.StudioPendingEditTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture._retained_split_text_head()
        pending.fixtures._remove_slot(str(fixture.index), "gfx-01")
        code, output = pending.fixtures._run_main([str(fixture.studio), "--apply"])
        self.assertEqual(code, 0, output)
        state = load_state(str(fixture.studio))
        self.assertIs(state.manifest["indexNeedsSplitText"], True)
        before = fixture._snapshot()
        with patch("assemble._base_state", return_value="current"):
            value = baseline({"dir": str(fixture.root)})
        self.assertEqual(value["host"], fixture.index.read_text())
        self.assertEqual(fixture._snapshot(), before)


if __name__ == "__main__":
    unittest.main()
