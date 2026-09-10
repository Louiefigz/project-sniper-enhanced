"""Actual ordinary caption revision cache versus uncached rendering parity."""
from __future__ import annotations

import contextlib
import copy
import json
import shutil
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import assemble
import test_assemble_source_audio_caption_media as fixture
from audio.audio_mix_picture import packet_signature
from cut_preview_io import bound_json, file_hash


class CaptionCacheRevisionMediaTests(unittest.TestCase):
    """Synthetic NTSC, J-cut, silent/right-only dialogue; no creator approval."""

    @classmethod
    def setUpClass(cls) -> None:
        """Reuse actual original media setup and complete baseline audit."""
        started = time.monotonic()
        fixture.CaptionSourceAudioMediaTests.setUpClass.__func__(cls)
        cls.setup_seconds = time.monotonic() - started

    def _run_revision(self, plan: dict, label: str) -> dict:
        """Retain the full real command output and elapsed attempt duration."""
        Path(self.job.plan_path).write_text(json.dumps(plan))
        started = time.monotonic()
        with (self.root / (label + ".log")).open("w") as log, contextlib.redirect_stdout(log):
            result = assemble.assemble(replace(self.job, plan=plan))
        return {"seconds": time.monotonic() - started, "result": result}

    def _audio_identity(self) -> dict:
        """Compare actual master content; ungraphed paths correctly rebuild it."""
        pointer = bound_json(self.output / "program_audio.v2.json")
        master = bound_json(Path(pointer["programMasterReceiptPath"]))
        return {"audioProgramInputHash": master["audioProgramInputHash"],
                "sourceBusReceiptHash": master["sourceBusReceiptHash"],
                "totalSamples": master["totalSamples"],
                "masteredAudioSha256": master["masteredAudio"]["sha256"]}

    def test_one_changed_cue_reuses_other_shard_with_exact_uncached_picture(self) -> None:
        """Never equate a stable key with a real cache hit or output parity."""
        base_hash = file_hash(self.base)
        old_shards = bound_json(self.output / "caption_shards.json")["entries"]
        old_master = self._audio_identity()
        changed = copy.deepcopy(self.plan)
        changed["captionsTrack"]["groups"][0]["placement"] = "top-center"
        cached = self._run_revision(changed, "caption-revision-cached")
        cached_output = self.root / "caption-revision-cached.mp4"
        shutil.copyfile(self.job.out, cached_output)
        new_shards = bound_json(self.output / "caption_shards.json")["entries"]
        result = cached["result"]
        self.assertEqual(result["captions"]["cacheHits"], 1)
        self.assertEqual(result["captions"]["renderedShards"], 1)
        self.assertTrue(result["delivery"]["qualified"])
        self.assertEqual(file_hash(self.base), base_hash)
        self.assertEqual(old_shards[1], new_shards[1])
        self.assertNotEqual(old_shards[0]["mediaKey"], new_shards[0]["mediaKey"])
        self.assertFalse(result["programMasterReused"], "ungraphed pointer cannot authorize reuse")
        self.assertEqual(self._audio_identity(), old_master)
        with patch("audio.assemble_source_audio.stage_caption_shards", return_value=None):
            uncached = self._run_revision(changed, "caption-revision-uncached-control")
        self.assertEqual(uncached["result"]["captions"]["cacheHits"], 0)
        self.assertEqual(uncached["result"]["captions"]["renderedShards"], 2)
        self.assertTrue(uncached["result"]["delivery"]["qualified"])
        for stream in ("v:0", "a:0"):
            self.assertEqual(packet_signature(str(cached_output), stream),
                             packet_signature(self.job.out, stream))
        self.assertEqual(file_hash(self.base), base_hash)
        self.assertFalse(uncached["result"]["programMasterReused"])
        self.assertEqual(self._audio_identity(), old_master)
        (self.root / "caption-cache-revision-evidence.json").write_text(json.dumps({
            "setupSeconds": self.setup_seconds, "baseline": self.result,
            "cached": cached, "uncachedControl": uncached,
            "sameVideoPackets": True, "sameAudioPackets": True,
            "baseSha256": base_hash, "masterContent": old_master,
            "subjectiveAudioOrCreatorApproval": False}, indent=2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
