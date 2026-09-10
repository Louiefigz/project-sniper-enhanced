"""Explicit large-UHD observation contracts; pure/inert tests, no media jobs."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import tempfile
import unittest
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from _grade_observation_v2_fixture import retained_test_execution, v2_context, v2_request
from color import grade_observation_read as reader
from color import grade_project_worker as owner
from color.grade_contract import parse_declaration, parse_source_binding
from color.grade_frame_adapter import validate_records
from color.grade_observation_profile import V1, V2, V2_PROFILE, admitted_facts, parse_request
from cut_preview_io import digest
from test_grade_frame_adapter import decoder_terminal, text_frame


def validate(context: tuple):
    """Pure complete record replay only, not source or invocation authentication."""
    source, declaration, probe, rows = context
    lines = (line for row in rows for line in text_frame(row))
    return validate_records((source, declaration, probe), lines, decoder_terminal(len(rows)), V2_PROFILE)


class GradeObservationV2Tests(unittest.TestCase):
    """Bounds, whole EOF, unchanged exact clocks and explicit missing metadata."""

    def test_actual_c0679_metadata_class_without_reading_any_source_media(self) -> None:
        facts = {"mediaKind": "timed-media", "videoStreams": 1, "streamCount": 3, "declaredFrames": 20_004,
            "sizeBytes": 10_280_473_262, "width": 3840, "height": 2160}
        admitted_facts(facts, V2)
        with self.assertRaises(ValueError):
            admitted_facts(facts, V1)
        for key, bad in (("sizeBytes", 16 * 1024 ** 3 + 1), ("width", 3842),
                         ("height", 2162), ("declaredFrames", 24_001), ("width", 3839), ("streamCount", 33)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                admitted_facts({**facts, key: bad}, V2)

    def test_request_has_one_explicit_version_and_no_ambient_limit_upgrade(self) -> None:
        self.assertEqual(parse_request(v2_request()), v2_request())
        for key, value in (("schemaVersion", True), ("schemaVersion", 1), ("profile", None),
                           ("timeoutSeconds", 1201), ("timeoutSeconds", 29),
                           ("frameCount", True), ("frameCount", 24_001), ("threads", 4)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_request({**v2_request(), key: value})
        legacy = {key: value for key, value in v2_request().items() if key not in ("profile", "schemaVersion")}
        with self.assertRaises(ValueError):
            parse_request(legacy)
        self.assertEqual(parse_request({**legacy, "timeoutSeconds": 120})["timeoutSeconds"], 120)

    def test_full_source_clock_and_chroma_facts_are_bound_without_transfer_relabel(self) -> None:
        result = validate(v2_context())
        facts = result.stream.source_metadata.record()
        self.assertEqual(facts["transfer"], "iec61966-2-4")
        self.assertEqual(facts["streamChromaLocation"], "left")
        self.assertEqual(facts["decodedSampleAspectRatio"], "1:1")
        self.assertIsNone(facts["rotationDegrees"])
        self.assertFalse(facts["transformApplicable"])
        self.assertEqual(str(result.source.fps), "30000/1001")
        self.assertEqual(result.decoded_record_count, 3)
        self.assertFalse(result.grade_applicable)
        self.assertFalse(result.decoder_execution_proved)
        self.assertEqual(result.validator_policy, "sniper-private-grade-frame-records-v3")

    def test_unknown_source_history_is_observed_but_cannot_enter_legacy_grade_contract(self) -> None:
        context = v2_context()
        validate(context)
        with self.assertRaises(ValueError):
            parse_declaration(context[1], parse_source_binding(context[0]))
        for key, value in (("sourceProfile", "bt709-sdr"), ("historyState", "inferred")):
            source, declaration, probe, rows = copy.deepcopy(context)
            declaration[key] = value
            source["declarationSha256"] = digest(declaration)
            with self.assertRaises(ValueError):
                validate((source, declaration, probe, rows))

    def test_unavailable_siting_sar_stays_unavailable_not_camera_defaults(self) -> None:
        source, declaration, probe, rows = v2_context()
        probe["streams"][0].pop("chroma_location")
        for row in rows:
            row.pop("chroma_location")
            row.pop("sample_aspect_ratio")
        result = validate((source, declaration, probe, rows))
        facts = result.stream.source_metadata.record()
        self.assertEqual(facts["decodedChromaLocation"], "unavailable")
        self.assertEqual(facts["decodedSampleAspectRatio"], "unavailable")
        self.assertEqual(facts["streamSampleAspectRatio"], "1:1")

    def test_late_siting_sar_color_clock_or_geometry_change_rejects(self) -> None:
        for key, bad in (("chroma_location", "center"), ("sample_aspect_ratio", "2:1"),
                         ("color_transfer", "bt709"), ("width", 1920), ("interlaced_frame", 1),
                         ("pkt_pts", 4), ("pkt_duration", 5)):
            context = v2_context()
            context[3][-1][key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(context)

    def test_signaled_rotation_unknown_side_data_or_known_stream_mismatch_rejects(self) -> None:
        for fields in ({"tags": {"rotate": "0"}}, {"codec_name": "hevc"},
                       {"chroma_location": "center"}, {"sample_aspect_ratio": "2:1"},
                       {"side_data_list": [{"side_data_type": "Display Matrix", "rotation": 90}]}):
            context = v2_context()
            context[2]["streams"][0].update(fields)
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                validate(context)

    def test_truncated_warning_and_extra_frame_cannot_finish_v2(self) -> None:
        source, declaration, probe, rows = v2_context()
        lines = [line for row in rows for line in text_frame(row)]
        for raw, terminal in ((lines[:-1], decoder_terminal(3)),
                              (lines, {**decoder_terminal(3), "stderrBytes": 1}),
                              (lines + text_frame(rows[-1]), decoder_terminal(4))):
            with self.assertRaises(ValueError):
                validate_records((source, declaration, probe), raw, terminal, V2_PROFILE)

    def test_owner_handshake_cap_is_explicit_and_cannot_renew_parent_time(self) -> None:
        sample = 10_000_000_000
        for profile, seconds, valid in ((None, 121, False), (V2_PROFILE, 1200, True),
                                         (V2_PROFILE, 1201, False), (V2_PROFILE, -1, False)):
            request = json.dumps({"deadlineMonotonicNs": str(sample + seconds * 10 ** 9)}) + "\n"
            with patch.object(owner.time, "monotonic_ns", return_value=sample), \
                    patch.object(owner.sys, "stdin", io.StringIO(request)), redirect_stdout(io.StringIO()):
                if valid:
                    self.assertEqual(owner._handshake(profile), 1210)
                else:
                    with self.assertRaises(RuntimeError):
                        owner._handshake(profile)


class GradeObservationV2ReadTests(unittest.TestCase):
    """Actual metadata files, with TEST-only execution/approval dependencies."""

    def test_strong_reader_binds_raw_probe_and_v2_command_and_limits(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            held, context, approval = retained_test_execution(directory)
            execution_sha = hashlib.sha256((directory / "execution.json").read_bytes()).hexdigest()
            with patch.object(reader, "implementation_sources", return_value=[]), \
                    patch.object(reader, "_read_approval", return_value=approval):
                result = reader.read_observation(directory, context, held)
                self.assertEqual(result.execution_sha256, execution_sha)
                self.assertEqual(result.raw_probe_sha256, held["worker"]["probe"]["sha256"])
                self.assertEqual(result.records.stream.source_metadata.codec, "h264")
                self.assertFalse(result.grade_applicable)
                held["worker"]["invocation"]["args"][5] = "1"
                held["artifactHash"] = digest({k: v for k, v in held.items() if k != "artifactHash"})
                (directory / "execution.json").write_text(json.dumps(held))
                with self.assertRaisesRegex(RuntimeError, "command/tool"):
                    reader.read_observation(directory, context, held)

    def test_worker_upgraded_legacy_or_boolean_limit_is_never_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            held, context, _approval = retained_test_execution(Path(raw).resolve())
            worker = held["worker"]
            with self.assertRaises(RuntimeError):
                reader._worker_state(worker, context[0])
            worker["limits"]["cpus"] = True
            with self.assertRaisesRegex(RuntimeError, "limits"):
                reader._worker_state(worker, context[0], V2_PROFILE)

    def test_late_probe_replacement_cannot_return_an_earlier_valid_observation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            held, context, approval = retained_test_execution(directory)
            original = reader.validate_records
            def mutate(*args):
                result = original(*args)
                (directory / "result/probe.json").write_text('{"streams":[]}')
                return result
            with patch.object(reader, "implementation_sources", return_value=[]), \
                    patch.object(reader, "_read_approval", return_value=approval), \
                    patch.object(reader, "validate_records", side_effect=mutate), self.assertRaises(RuntimeError):
                reader.read_observation(directory, context, held)

    def _reject_final_execution_change(self, mutation: Callable[[Path], object]) -> None:
        """Change real receipt files at the final current-code observation."""
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw).resolve()
            held, context, approval = retained_test_execution(directory)
            calls = []

            def implementation() -> list:
                calls.append(None)
                if len(calls) == 2:
                    mutation(directory / "execution.json")
                return []

            with patch.object(reader, "implementation_sources", side_effect=implementation), \
                    patch.object(reader, "_read_approval", return_value=approval), \
                    self.assertRaises((RuntimeError, OSError)):
                reader.read_observation(directory, context, held)
            self.assertEqual(len(calls), 2)

    def test_final_execution_atomic_replacement_rejects_instead_of_returning_new_sha(self) -> None:
        def replace(path: Path) -> None:
            replacement = path.with_name("TEST-replacement.json")
            replacement.write_text('{"TEST_tampered_after_final_receipt_read":true}\n')
            replacement.replace(path)
        self._reject_final_execution_change(replace)

    def test_final_execution_same_json_different_raw_bytes_rejects(self) -> None:
        self._reject_final_execution_change(lambda path: path.write_bytes(path.read_bytes() + b"\n"))

    def test_final_execution_missing_file_rejects(self) -> None:
        self._reject_final_execution_change(lambda path: path.unlink())

    def test_final_execution_symlink_to_same_bytes_rejects(self) -> None:
        def link(path: Path) -> None:
            target = path.with_name("TEST-linked-execution.json")
            path.rename(target)
            path.symlink_to(target)
        self._reject_final_execution_change(link)


if __name__ == "__main__":
    unittest.main()
