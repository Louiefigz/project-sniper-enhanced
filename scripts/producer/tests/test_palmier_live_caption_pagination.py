"""Offline contracts for the separate connected >200-caption probe."""
import copy
import tempfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from _common import *  # noqa: F401,F403
from ingest_probe import MediaProbe
from palmier.live_acceptance_runtime import Deadline
from palmier.live_caption_probe_input import (
    ProbeConfig, validate_probe_config)
from palmier.live_caption_pagination import await_capped_caption_readback
from palmier.mcp_client import PalmierError
from test_palmier_timeline_readback import WindowClient
import live_p5_caption_pagination_acceptance as live_probe


class _Deadline:
    def remaining(self):
        return 30.0


class LiveCaptionPaginationTests(unittest.TestCase):
    def test_waits_for_capped_group_and_returns_exact_connected_proof(self):
        client = WindowClient()
        with patch("palmier.live_caption_pagination.time.sleep"):
            proof = await_capped_caption_readback(client, _Deadline())
        self.assertEqual(
            proof["kind"], "connected-native-caption-pagination")
        self.assertGreater(proof["maximumCaptionCount"], 200)
        self.assertTrue(proof["exactCounts"])
        self.assertTrue(proof["postReadCompactStable"])
        self.assertTrue(proof["coverage"]["closingCompactRead"])

    def test_async_caption_generation_waits_for_stable_compact_counts(self):
        class Delayed(WindowClient):
            def __init__(self):
                super().__init__()
                self.compact_reads = 0

            def call_json(self, tool, arguments=None):
                arguments = arguments or {}
                if not arguments:
                    self.compact_reads += 1
                    if self.compact_reads <= 2:
                        value = copy.deepcopy(self.base)
                        value["tracks"][1]["captionGroups"] = []
                        self.calls.append({})
                        return value
                return super().call_json(tool, arguments)

        client = Delayed()
        with patch("palmier.live_caption_pagination.time.sleep"):
            proof = await_capped_caption_readback(client, _Deadline())
        self.assertGreaterEqual(client.compact_reads, 6)
        self.assertEqual(proof["maximumCaptionCount"], 450)

    def test_deadline_expiry_terminates_polling(self):
        class Empty(WindowClient):
            def call_json(self, tool, arguments=None):
                value = copy.deepcopy(self.base)
                value["tracks"][1]["captionGroups"] = []
                return value

        deadline = SimpleNamespace(
            remaining=unittest.mock.Mock(side_effect=[
                1.0, PalmierError("wall-clock deadline")]))
        with patch("palmier.live_caption_pagination.time.sleep"):
            with self.assertRaisesRegex(PalmierError, "wall-clock"):
                await_capped_caption_readback(Empty(), deadline)

    def test_validation_rejects_unsafe_prefix_and_non_normalized_media(self):
        probe = MediaProbe(
            180.0, 23.976, False, 3840, 2160, 0, True, 2, 48000,
            "24000/1001")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "source.mp4")
            source.write_bytes(b"source")
            bad_prefix = ProbeConfig(
                str(source), str(Path(tmp, "evidence.json")), "../unsafe")
            with self.assertRaisesRegex(PalmierError, "prefix"):
                validate_probe_config(bad_prefix, Deadline(30))
            config = ProbeConfig(
                str(source), str(Path(tmp, "evidence.json")), "Safe")
            with patch(
                    "palmier.live_caption_probe_input.source_authority",
                    return_value={"sha256": "a" * 64}), patch(
                        "palmier.live_caption_probe_input.probe_media",
                        return_value=probe):
                with self.assertRaisesRegex(PalmierError, "normalized"):
                    validate_probe_config(config, Deadline(30))

    def test_late_build_failure_always_invokes_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = ProbeConfig(
                str(Path(tmp, "normalized.mp4")),
                str(Path(tmp, "evidence.json")), "Sniper Test")
            source = {"path": config.source, "sha256": "a" * 64}
            with patch.object(
                    live_probe, "_build",
                    side_effect=PalmierError("late caption failure")), \
                    patch.object(
                        live_probe, "_cleanup", return_value=[]) as cleanup:
                with self.assertRaisesRegex(PalmierError, "late caption"):
                    live_probe._execute(
                        config, source, 4320, Deadline(30))
            cleanup.assert_called_once()
            request = cleanup.call_args.args[1]
            self.assertFalse(request.trash_disposable)
            evidence = json.loads(Path(config.evidence).read_text())
            self.assertEqual(evidence["status"], "failed")

    def test_failed_caption_cohort_cleanup_retains_disposable(self):
        config = ProbeConfig(
            "/tmp/normalized.mp4", "/tmp/evidence.json", "Sniper Test")
        evidence = SimpleNamespace(
            value={"phases": {}}, phase=Mock())
        cleanup_client = Mock()
        cleanup_client.phase.return_value = nullcontext()
        cleanup_client.response_loss_receipts = []
        prior = {"project": None, "surface": {
            "openCount": 0, "openProjects": []}}
        project = {
            "id": "disposable", "name": "Sniper Test 1",
            "path": "/tmp/Sniper Test 1.palmier",
        }
        request = live_probe.CleanupInput(
            Mock(), evidence, Mock(), prior, project, [], False)
        with patch.object(
                live_probe, "fault_client",
                return_value=cleanup_client), patch.object(
                    live_probe, "restore_project",
                    return_value={"openState": prior["surface"]}), patch.object(
                        live_probe, "require_surface",
                        return_value=prior["surface"]), patch.object(
                            live_probe, "trash_disposable") as trash:
            errors = live_probe._cleanup(config, request)
        self.assertEqual(errors, [])
        trash.assert_not_called()
        cleanup = evidence.phase.call_args.args[1]
        self.assertEqual(
            cleanup["retainedForRecovery"], project["path"])
