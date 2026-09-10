"""Pre-copy parent verification and post-copy surgical activation proofs."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from current_render_graph_candidate import (
    activate_candidate,
    verify_candidate,
)
from current_render_graph_store import load_active, publish
from tests._p2_repair_media_fixture import FFMPEG, FFPROBE
from tests._p2_surgical_terminal_fixture import (
    prepare_and_stage,
    publish_parent_active,
)
from tests.test_p2_cut_repair_picture_prepare_media import _PictureFixture


def _copy_candidate(candidate: Path, destination: str) -> Path:
    final = Path(destination)
    final.write_bytes(candidate.read_bytes())
    return final


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg and ffprobe required")
class CutRepairSurgicalActivationTests(unittest.TestCase):
    def test_parent_media_mutation_after_stage_fails_pre_copy_verify(self) -> None:
        fixture = _PictureFixture(captions=False)
        try:
            publish_parent_active(fixture)
            _prepared, candidate, result = prepare_and_stage(fixture)
            with open(fixture.parent, "ab") as stream:
                stream.write(b"parent-mutated-during-review")
            with self.assertRaisesRegex(
                    RuntimeError, "cached render artifact is corrupt"):
                verify_candidate(
                    Path(fixture.producer), candidate,
                    result["candidateSha256"])
        finally:
            fixture.clean()

    def test_post_copy_activation_uses_verified_parent_cas(self) -> None:
        fixture = _PictureFixture(captions=False)
        try:
            publish_parent_active(fixture)
            _prepared, candidate, result = prepare_and_stage(fixture)
            producer = Path(fixture.producer)
            expected = result["candidateSha256"]
            verify_candidate(producer, candidate, expected)
            final = _copy_candidate(candidate, fixture.parent)
            self.assertEqual(
                activate_candidate(producer, candidate, final, expected),
                result["graphHash"])
        finally:
            fixture.clean()

    def test_receipt_pointer_change_after_verify_blocks_activation(self) -> None:
        fixture = _PictureFixture(captions=False)
        try:
            publish_parent_active(fixture)
            _prepared, candidate, result = prepare_and_stage(fixture)
            producer = Path(fixture.producer)
            expected = result["candidateSha256"]
            verify_candidate(producer, candidate, expected)
            active = load_active(producer)
            self.assertIsNotNone(active)
            graph, receipt = active
            changed = json.loads(json.dumps(receipt))
            changed["executionMode"] = "forced-full"
            publish(producer, graph, changed)
            final = _copy_candidate(candidate, fixture.parent)
            with self.assertRaisesRegex(RuntimeError, "changed after"):
                activate_candidate(producer, candidate, final, expected)
        finally:
            fixture.clean()


if __name__ == "__main__":
    unittest.main(verbosity=2)
