"""Pure schema2 body replay syntax; no file/clock/source/runtime authority."""
from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from _source_color_staging_fixture import staging_fixture
from guided_body_contract import parse_body_input, parse_current_body_input
from guided_body_source_color_replay import SCOPE, validate_body_source_color_replay
from test_guided_body_contract import body_input


def replay_fixture() -> dict:
    """Syntactic values only; these SHA strings are not observed raw references."""
    sidecar, archive = staging_fixture()
    execution = sidecar["opening"]["claimPath"].rsplit("/", 1)[0]
    return {"schemaVersion": 2, "kind": "guided-body-source-color-replay-references", "scope": SCOPE,
        "opening": {**{key: "a" * 64 for key in ("selectionHash", "claimHash", "cleanupHash", "inputSha256", "executionInputHash",
            "mediaResultSha256", "receiptHash")}, "executionId": sidecar["opening"]["executionId"]},
        "sourceColorHash": archive["sourceColorHash"], "input": {"path": archive["sidecarPath"], "sha256": "b" * 64, "sizeBytes": 1},
        "reservationArchive": {"path": f"{execution}/cleanup-attempts/00000000-0000-4000-8000-000000000003/reservation.json",
            "sha256": "c" * 64, "sizeBytes": 8 * 1024 ** 2}, "executable": False, "bodyApproved": False, "deliveryApproved": False}


class BodySourceColorContractTests(unittest.TestCase):
    """Explicit new wire only; the historical parser remains closed and unchanged."""

    def test_detached_new_wire_keeps_seven_refs_and_legacy_parser_refuses(self) -> None:
        """Parser success produces data, not a live body, grade or cleanup owner."""
        old = body_input()
        self.assertIs(parse_body_input(old), old)
        value = {**old, "schemaVersion": 2, "sourceColorReplay": replay_fixture()}
        parsed = parse_current_body_input(value)
        self.assertEqual(parsed, value)
        self.assertEqual(len(parsed["references"]), 7)
        parsed["sourceColorReplay"]["input"]["sha256"] = "0" * 64
        self.assertNotEqual(parsed, value)
        with self.assertRaises(RuntimeError):
            parse_body_input(value)

    def test_no_file_process_runtime_or_clock_is_used_by_shape_parser(self) -> None:
        """No new observation allowance or decoder can be created by syntax validation."""
        with patch("builtins.open", side_effect=AssertionError("TEST no read")), \
                patch("subprocess.Popen", side_effect=AssertionError("TEST no native")), \
                patch("time.monotonic", side_effect=AssertionError("TEST no clock")):
            self.assertEqual(validate_body_source_color_replay(replay_fixture()), replay_fixture())

    def test_all_required_and_unknown_nested_fields_are_closed(self) -> None:
        """Missing, partial and extra reference/binding fields reject before IO."""
        original = replay_fixture()
        targets = [()] + [(key,) for key in ("opening", "input", "reservationArchive")]
        for target in targets:
            row = original[target[0]] if target else original
            for key in [*row, "TEST-extra"]:
                value = deepcopy(original)
                current = value[target[0]] if target else value
                current.pop(key) if key in current else current.update({key: False})
                self.assertRaises((ValueError, RuntimeError), validate_body_source_color_replay, value)

    def test_version_flags_and_sizes_are_exact_not_bool_or_numeric_coercion(self) -> None:
        """V1 and string/bool variants cannot opt into a partial source2 wire."""
        for version in (True, "2", 1, 3, None):
            value = {**body_input(), "schemaVersion": version, "sourceColorReplay": replay_fixture()}
            with self.assertRaises((ValueError, RuntimeError)):
                parse_current_body_input(value)
        for replacement in (True, 0, "1", 1.5, 8 * 1024 ** 2 + 1):
            value = replay_fixture()
            value["input"]["sizeBytes"] = replacement
            with self.assertRaises(ValueError):
                validate_body_source_color_replay(value)
        for key in ("executable", "bodyApproved", "deliveryApproved"):
            with self.assertRaises(ValueError):
                validate_body_source_color_replay({**replay_fixture(), key: 0})

    def test_same_execution_uuid4_path_role_and_lowercase_hashes_required(self) -> None:
        """A syntactically valid sibling execution is still a different reference root."""
        original = replay_fixture()
        changes = [("input", "sha256", "A" * 64), ("input", "path", "/TEST/../input.json"),
            ("reservationArchive", "path", original["reservationArchive"]["path"].replace("/executions/", "/elsewhere/")),
            ("reservationArchive", "path", original["reservationArchive"]["path"].replace("-4000-", "-1000-")),
            ("opening", "executionId", "00000000-0000-4000-8000-000000000004")]
        for group, key, replacement in changes:
            value = deepcopy(original)
            value[group][key] = replacement
            with self.assertRaises(ValueError):
                validate_body_source_color_replay(value)
