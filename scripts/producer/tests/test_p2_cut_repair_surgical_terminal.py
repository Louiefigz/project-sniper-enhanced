"""Real-media and source-gate proofs for picture surgical terminals."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from current_render_graph_candidate import verify_candidate
from current_render_graph_contract import object_hash
from current_render_graph_source_gate import verify_graph_source_authority
from current_render_graph_store import load_active
from edit.cut_repair_prepare_media import prepare
from edit.cut_repair_surgical_terminal import (
    SurgicalStageRequest,
    stage,
)
from tests._p2_surgical_terminal_fixture import (
    publish_parent_active,
    terminal_paths,
)
from tests._p2_repair_media_fixture import FFMPEG, FFPROBE
from tests.test_p2_cut_repair_picture_prepare_media import (
    _PictureFixture,
)

_SCRIPT = Path(__file__).resolve().parents[1] / (
    "edit/cut_repair_surgical_terminal.py")


def _cli_stage(
    fixture: _PictureFixture,
    paths: tuple[Path, Path, Path, Path],
) -> dict:
    root, plan, prepared, candidate = paths
    result = subprocess.run([
        sys.executable, str(_SCRIPT),
        "--producer-dir", fixture.producer,
        "--plan", str(plan),
        "--manifest", fixture.manifest,
        "--prepared", str(prepared),
        "--candidate", str(candidate),
        "--artifact-dir", str(root),
    ], capture_output=True, text=True, check=False)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise AssertionError(f"expected one CLI event, got: {lines!r}")
    return json.loads(lines[0])


def _magenta_ratio(path: str) -> float:
    result = subprocess.run([
        str(FFMPEG), "-v", "error", "-i", path,
        "-vf", "select='eq(n,31)',crop=160:12:0:0",
        "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
    ], capture_output=True, check=True)
    pixels = [
        result.stdout[index:index + 3]
        for index in range(0, len(result.stdout), 3)
    ]
    magenta = sum(
        red > 180 and green < 100 and blue > 180
        for red, green, blue in pixels)
    return magenta / len(pixels)


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg and ffprobe required")
class CutRepairSurgicalTerminalTests(unittest.TestCase):
    def test_exact_composite_stages_standard_source_gated_graph(self) -> None:
        fixture = _PictureFixture(captions=False)
        try:
            parent_graph_hash = publish_parent_active(fixture)
            prepared = prepare(
                fixture.producer, fixture.directive,
                fixture.context, fixture.staging)
            root, plan, prepared_path = terminal_paths(fixture, prepared)
            candidate = root / "final.mp4"
            result = _cli_stage(
                fixture, (root, plan, prepared_path, candidate))
            expected = prepared["compositeReceipt"]["output"]["sha256"]
            self.assertEqual(result["candidateSha256"], expected)
            self.assertEqual(candidate.read_bytes(), Path(
                prepared["compositeReceipt"]["output"]["path"]).read_bytes())
            self.assertEqual(
                object_hash(load_active(Path(fixture.producer))[0]),
                parent_graph_hash)
            self.assertEqual(result["previousGraphHash"], parent_graph_hash)
            self.assertEqual(
                result["parentMediaSha256"],
                prepared["compositeReceipt"]["inputs"]["parentSha256"])
            self.assertEqual(
                verify_candidate(
                    Path(fixture.producer), candidate, expected),
                result["graphHash"])
            generation = (
                Path(fixture.producer) / ".render-graph-v1" / "generations"
                / result["graphHash"])
            graph = json.loads(
                (generation / "graph.json").read_text(encoding="utf-8"))
            source = next(
                row for row in graph["nodes"]
                if row["nodeId"] == "node-source")
            final = next(
                row for row in graph["nodes"]
                if row["nodeId"] == graph["rootNodeId"])
            self.assertRegex(
                source["inputDigests"]["source.stageRoot"], r"^[0-9a-f]{64}$")
            self.assertEqual(
                final["inputDigests"]["surgical.terminalReceipt"],
                result["terminalReceiptHash"])
            receipt = json.loads(Path(
                result["terminalReceiptPath"]).read_text(encoding="utf-8"))
            self.assertEqual(
                receipt["deliveryDisposition"]["palmier"],
                "reference-media-only-no-native-editability")
            self.assertEqual(object_hash(graph), result["graphHash"])
        finally:
            fixture.clean()

    def test_source_mutation_after_stage_fails_candidate_gate(self) -> None:
        fixture = _PictureFixture(captions=False)
        try:
            publish_parent_active(fixture)
            prepared = prepare(
                fixture.producer, fixture.directive,
                fixture.context, fixture.staging)
            root, plan, prepared_path = terminal_paths(fixture, prepared)
            candidate = root / "final.mp4"
            result = stage(SurgicalStageRequest(
                Path(fixture.producer), plan, Path(fixture.manifest),
                prepared_path, candidate, root))
            with open(fixture.manifest, encoding="utf-8") as handle:
                manifest = json.load(handle)
            snapshot = Path(manifest["sources"][0]["path"])
            snapshot.write_bytes(b"mutated-after-surgical-stage")
            with self.assertRaisesRegex(RuntimeError, "snapshot"):
                verify_candidate(
                    Path(fixture.producer), candidate,
                    result["candidateSha256"])
        finally:
            fixture.clean()

    def test_rendered_caption_lane_remains_explicitly_blocked(self) -> None:
        fixture = _PictureFixture(captions=True, burned_visual=True)
        try:
            publish_parent_active(fixture)
            prepared = prepare(
                fixture.producer, fixture.directive,
                fixture.context, fixture.staging)
            composite = prepared["compositeReceipt"]["output"]["path"]
            self.assertGreater(_magenta_ratio(fixture.parent), 0.95)
            self.assertLess(_magenta_ratio(composite), 0.80)
            root, plan, prepared_path = terminal_paths(fixture, prepared)
            with self.assertRaisesRegex(
                    RuntimeError,
                    "SURGICAL_TERMINAL_PLAN_LANE_UNSUPPORTED:"
                    "captionsTrack,dialogueCaptionAuthority"):
                stage(SurgicalStageRequest(
                    Path(fixture.producer), plan, Path(fixture.manifest),
                    prepared_path, root / "final.mp4", root))
        finally:
            fixture.clean()

    def test_missing_source_stage_root_fails_current_gate(self) -> None:
        fixture = _PictureFixture(captions=False)
        try:
            publish_parent_active(fixture)
            prepared = prepare(
                fixture.producer, fixture.directive,
                fixture.context, fixture.staging)
            root, plan, prepared_path = terminal_paths(fixture, prepared)
            candidate = root / "final.mp4"
            result = stage(SurgicalStageRequest(
                Path(fixture.producer), plan, Path(fixture.manifest),
                prepared_path, candidate, root))
            generation = (
                Path(fixture.producer) / ".render-graph-v1" / "generations"
                / result["graphHash"])
            graph_path = generation / "graph.json"
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            receipt = json.loads((
                generation / "receipts" / f"{result['receiptHash']}.json"
            ).read_text(encoding="utf-8"))
            source = next(
                row for row in graph["nodes"]
                if row["nodeId"] == "node-source")
            del source["inputDigests"]["source.stageRoot"]
            with self.assertRaisesRegex(
                    RuntimeError, "source stage root is malformed"):
                verify_graph_source_authority(graph, receipt)
        finally:
            fixture.clean()

    def test_absent_active_parent_fails_before_candidate_copy(self) -> None:
        fixture = _PictureFixture(captions=False)
        try:
            prepared = prepare(
                fixture.producer, fixture.directive,
                fixture.context, fixture.staging)
            root, plan, prepared_path = terminal_paths(fixture, prepared)
            candidate = root / "final.mp4"
            with self.assertRaisesRegex(
                    RuntimeError, "ACTIVE_PARENT_REQUIRED"):
                stage(SurgicalStageRequest(
                    Path(fixture.producer), plan, Path(fixture.manifest),
                    prepared_path, candidate, root))
            self.assertFalse(candidate.exists())
        finally:
            fixture.clean()

    def test_foreign_active_root_media_fails_parent_binding(self) -> None:
        fixture = _PictureFixture(captions=False)
        try:
            prepared = prepare(
                fixture.producer, fixture.directive,
                fixture.context, fixture.staging)
            foreign = Path(fixture.producer) / "foreign-parent.mov"
            foreign.write_bytes(Path(fixture.parent).read_bytes() + b"foreign")
            publish_parent_active(fixture, foreign)
            root, plan, prepared_path = terminal_paths(fixture, prepared)
            candidate = root / "final.mp4"
            with self.assertRaisesRegex(
                    RuntimeError, "ACTIVE_PARENT_MISMATCH"):
                stage(SurgicalStageRequest(
                    Path(fixture.producer), plan, Path(fixture.manifest),
                    prepared_path, candidate, root))
            self.assertFalse(candidate.exists())
        finally:
            fixture.clean()

    def test_stale_active_root_bytes_fail_before_parent_binding(self) -> None:
        fixture = _PictureFixture(captions=False)
        try:
            publish_parent_active(fixture)
            prepared = prepare(
                fixture.producer, fixture.directive,
                fixture.context, fixture.staging)
            with open(fixture.parent, "ab") as stream:
                stream.write(b"stale-active-parent")
            root, plan, prepared_path = terminal_paths(fixture, prepared)
            candidate = root / "final.mp4"
            with self.assertRaisesRegex(
                    RuntimeError, "cached render artifact is corrupt"):
                stage(SurgicalStageRequest(
                    Path(fixture.producer), plan, Path(fixture.manifest),
                    prepared_path, candidate, root))
            self.assertFalse(candidate.exists())
        finally:
            fixture.clean()


if __name__ == "__main__":
    unittest.main(verbosity=2)
