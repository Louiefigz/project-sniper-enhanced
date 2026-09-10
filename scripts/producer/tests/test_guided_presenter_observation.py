"""Owner/refusal tests with explicit fake ffprobe outputs; no real media jobs."""
from __future__ import annotations

import copy
import json
import subprocess
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from _guided_presenter_observation_fixture import ObservationFixture
from guided_presenter_observation import observe_presenter_asset, validate_presenter_observation
from guided_presenter_probe_contract import MAX_FRAME_BYTES, MAX_HEADER_BYTES, canonical_presenter_rate


class PresenterObservationTests(unittest.TestCase):
    """No stub success is reported as real decoder/process/admission qualification."""

    def setUp(self) -> None:
        """Start one independent small fake-media fixture for each owner fault."""
        self.fixture = ObservationFixture()
        self.addCleanup(self.fixture.close)
        self.requests = []

    def run_probe(self, request: object) -> subprocess.CompletedProcess:
        """Return exact TEST JSON while recording the actual ProcessRequest inputs."""
        self.requests.append(request)
        raw = self.fixture.raw()[len(self.requests) - 1]
        return subprocess.CompletedProcess(request.command, 0, raw, "")

    def observe(self) -> object:
        """Execute owner control flow only; the one leaf process hook is stubbed."""
        with patch("guided_presenter_observation.run_text", side_effect=self.run_probe):
            return observe_presenter_asset(self.fixture.selected, self.fixture.source, "30000/1001", self.fixture.runtime)

    def test_video_output_binds_commands_source_and_original_decreasing_deadline(self) -> None:
        """Two capped requests return matching immutable evidence, not a render receipt."""
        result = self.observe()
        self.assertEqual(result.source, self.fixture.source)
        self.assertEqual(result.admission, self.fixture.selected.admission)
        self.assertEqual(result.graph_asset.total_frames, 24)
        self.assertEqual(result.graph_asset.frame_rate, "30000/1001")
        self.assertFalse(result.executable or result.rights_verified)
        self.assertEqual([row.max_output_bytes for row in self.requests], [MAX_HEADER_BYTES, MAX_FRAME_BYTES])
        self.assertLess(self.requests[1].timeout_seconds, self.requests[0].timeout_seconds)
        self.assertTrue(all(row.command[0] == self.fixture.runtime.ffprobe.path and row.stdin_text == "" for row in self.requests))
        self.assertIn("-count_frames", self.requests[1].command)
        self.assertNotIn("-read_intervals", self.requests[1].command)
        self.assertIn("crccheck+explode", self.requests[0].command)
        self.assertTrue(all(row.command[row.command.index("-of") + 1] == "json=compact=1" for row in self.requests))
        validate_presenter_observation(result)

    def test_no_second_source_hash_or_receipt_reader_is_called(self) -> None:
        """A live owner reuses original hash/stat binding and opens no admission files."""
        with patch("os.read", side_effect=AssertionError("unexpected source byte read")):
            self.assertEqual(self.observe().graph_asset.kind, "video")

    def test_known_bad_header_rejects_before_full_frame_process(self) -> None:
        """Unknown color/SAR/HDR/depth/rate never reaches a second decode call."""
        changes = {"color_transfer": None, "color_primaries": "unknown", "color_space": "smpte170m",
            "color_range": "pc", "sample_aspect_ratio": "0:1", "pix_fmt": "yuv420p10le",
            "start_pts": 3, "avg_frame_rate": "30/1", "time_base": "1/1000", "field_order": "tt", "index": -1}
        for key, value in changes.items():
            self.requests.clear()
            header = copy.deepcopy(self.fixture.header)
            header["streams"][0][key] = value
            with patch.object(self.fixture, "header", header), self.assertRaises(ValueError):
                self.observe()
            self.assertEqual(len(self.requests), 1)

    def test_auxiliary_picture_alpha_profile_and_orientation_are_not_defaults(self) -> None:
        """Extra pictures or explicit unsupported paint metadata are refused early."""
        variants = [dict(tags={"rotate": "0"}), dict(tags={"alpha_mode": "1"}),
            dict(side_data_list=[{"side_data_type": "ICC profile"}]),
            dict(side_data_list=[{"side_data_type": "Mastering display metadata"}])]
        for change in variants:
            self.requests.clear()
            header = copy.deepcopy(self.fixture.header)
            header["streams"][0].update(change)
            with patch.object(self.fixture, "header", header), self.assertRaises(ValueError):
                self.observe()
        self.fixture.header["streams"].append(copy.deepcopy(self.fixture.header["streams"][0]))
        self.requests.clear()
        with self.assertRaises(ValueError):
            self.observe()

    def test_malformed_format_metadata_and_noninteger_clock_fail_early(self) -> None:
        """Unexpected JSON shapes are explicit refusals, not defaults or attribute errors."""
        for value in (None, [], {"tags": []}, {"side_data_list": None}):
            self.requests.clear()
            header = copy.deepcopy(self.fixture.header)
            header["format"] = value
            with patch.object(self.fixture, "header", header), self.assertRaises(ValueError):
                self.observe()
            self.assertEqual(len(self.requests), 1)
        self.fixture.header["streams"][0]["start_pts"] = False
        self.requests.clear()
        with self.assertRaises(ValueError):
            self.observe()

    def test_actual_header_transport_cap_is_not_silently_raised(self) -> None:
        """Even a valid-looking oversized JSON object fails before full decode."""
        raw = json.dumps({"streams": self.fixture.header["streams"], "padding": "x" * MAX_HEADER_BYTES})
        with patch.object(self.fixture, "raw", return_value=(raw, raw)), self.assertRaises(ValueError):
            self.observe()
        self.assertEqual(len(self.requests), 1)

    def test_every_decoded_frame_keeps_color_geometry_progressive_and_exact_clock(self) -> None:
        """A single changed middle frame cannot hide behind a correct header/count."""
        changes = {"color_range": "pc", "color_transfer": "smpte2084", "width": 66, "sample_aspect_ratio": "4:3",
            "pts": 6005, "duration": 1000, "best_effort_timestamp": 0, "interlaced_frame": 1, "repeat_pict": 1}
        for key, value in changes.items():
            self.requests.clear()
            frames = copy.deepcopy(self.fixture.frames)
            frames["frames"][6][key] = value
            with patch.object(self.fixture, "frames", frames), self.assertRaises(ValueError):
                self.observe()

    def test_missing_frames_duration_and_real_eof_count_do_not_get_filled(self) -> None:
        """Missing/extra/partial frame evidence cannot become uniform CFR success."""
        variants = [copy.deepcopy(self.fixture.frames) for _ in range(4)]
        variants[0]["frames"].pop()
        variants[1]["frames"].append(copy.deepcopy(variants[1]["frames"][-1]))
        del variants[2]["frames"][0]["duration"]
        del variants[3]["streams"][0]["nb_read_frames"]
        for frames in variants:
            self.requests.clear()
            with patch.object(self.fixture, "frames", frames), self.assertRaises(ValueError):
                self.observe()

    def test_nonzero_or_warning_output_never_returns_an_observation(self) -> None:
        """The owner preserves warnings as unsupported rather than ignoring them."""
        for code, stderr in ((1, "TEST failure"), (0, "TEST warning")):
            with patch("guided_presenter_observation.run_text", return_value=subprocess.CompletedProcess([], code, "{}", stderr)):
                with self.assertRaises(ValueError):
                    observe_presenter_asset(self.fixture.selected, self.fixture.source, "30/1", self.fixture.runtime)

    def test_truncated_duplicate_or_nonfinite_json_never_passes(self) -> None:
        """Malformed transport is terminal even with an otherwise plausible record."""
        for raw in ('{"streams":', '{"streams":[],"streams":[]}', '{"streams":NaN}'):
            with patch.object(self.fixture, "raw", return_value=(raw, raw)), self.assertRaises(ValueError):
                self.observe()
            self.requests.clear()

    def test_source_changes_during_child_fail_after_normal_return(self) -> None:
        """Normal child code0 cannot override an incoming file identity change."""
        def changed(request: object) -> subprocess.CompletedProcess:
            """Replace the original source during the simulated first actual probe."""
            result = self.run_probe(request)
            self.fixture.path.write_bytes(b"changed bytes")
            return result
        with patch("guided_presenter_observation.run_text", side_effect=changed), self.assertRaises(ValueError):
            observe_presenter_asset(self.fixture.selected, self.fixture.source, "30000/1001", self.fixture.runtime)
        self.assertEqual(len(self.requests), 1)

    def test_wrong_hash_and_expired_owner_fail_before_spawn(self) -> None:
        """No late snapshot baseline or admission path is fabricated to repair input."""
        wrong = replace(self.fixture.source, sha256="f" * 64)
        runner = Mock()
        with patch("guided_presenter_observation.run_text", runner), self.assertRaises(ValueError):
            observe_presenter_asset(self.fixture.selected, wrong, "30000/1001", self.fixture.runtime)
        self.fixture.deadline.expired = True
        with patch("guided_presenter_observation.run_text", runner), self.assertRaises(RuntimeError):
            observe_presenter_asset(self.fixture.selected, self.fixture.source, "30000/1001", self.fixture.runtime)
        runner.assert_not_called()

    def test_last_owner_guard_mutation_cannot_return_previously_valid_metadata(self) -> None:
        """Final ownership callbacks run before the final source/tool inode comparison."""
        completed = False
        def guard() -> None:
            """Inject source replacement only after both actual TEST returns exist."""
            nonlocal completed
            if len(self.requests) == 2 and not completed:
                completed = True
                self.fixture.path.write_bytes(b"late change")
        self.fixture.runtime = replace(self.fixture.runtime, guard=guard)
        with self.assertRaises(ValueError):
            self.observe()

    def test_pure_revalidation_rejects_changed_graph_command_or_frame_bytes(self) -> None:
        """Frozen dataclass replacement is not a new observed-media authority."""
        observed = self.observe()
        frames = json.loads(observed.evidence.frames_json)
        frames["frames"][4]["color_transfer"] = "unknown"
        variants = [replace(observed, graph_asset=replace(observed.graph_asset, total_frames=25)),
            replace(observed, evidence=replace(observed.evidence, command_sha256=("f" * 64,) * 2)),
            replace(observed, evidence=replace(observed.evidence, frames_json=json.dumps(frames)))]
        for value in variants:
            with self.assertRaises(ValueError):
                validate_presenter_observation(value)
        with self.assertRaisesRegex(RuntimeError, "expired"):
            validate_presenter_observation(observed, Mock(side_effect=RuntimeError("expired")))

    def test_graph_rate_normalization_changes_spelling_not_rational_clock(self) -> None:
        """Existing guided N/1 normalizes; unreduced, rounded or numeric inputs refuse."""
        self.assertEqual(canonical_presenter_rate("30/1"), "30")
        self.assertEqual(canonical_presenter_rate("30000/1001"), "30000/1001")
        for value in ("60000/2002", "29.97", "030/1", 30, True, " 30", "0/1"):
            with self.assertRaises(ValueError):
                canonical_presenter_rate(value)


if __name__ == "__main__":
    unittest.main()
