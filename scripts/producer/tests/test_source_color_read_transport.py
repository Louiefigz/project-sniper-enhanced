"""Pure transport tests; literal TEST paths are never opened or authenticated."""
from __future__ import annotations

from contextlib import ExitStack
from copy import copy
from dataclasses import FrozenInstanceError
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from guided_source_color_read_transport import (
    SourceColorReadTransport, parse_source_color_read_transport as parse,
    validate_source_color_read_transport as validate,
)


def fields() -> tuple[str, str, str, str]:
    """Return inert explicit sidecar/archive arguments, without creating files."""
    return ("/TEST-unopened/read/input.json", "a" * 64,
            "/TEST-unopened/read/reservation.json", "b" * 64)


class SourceColorReadTransportTests(unittest.TestCase):
    """Parsing and original-value holds confer no source or native authority."""

    def test_no_flags_preserves_only_the_explicit_legacy_route(self) -> None:
        """Exactly four absent flags produce no transport and require no work."""
        self.assertIsNone(parse((None,) * 4))
        self.assertIsNone(validate(None))

    def test_all_four_fields_remain_exact_and_frozen(self) -> None:
        """Original strings become lexical Paths; no policy/approval flag is added."""
        values = fields()
        result = parse(values)
        self.assertIs(type(result), SourceColorReadTransport)
        self.assertEqual((str(result.input_path), result.input_sha256,
                          str(result.archive_path), result.archive_sha256), values)
        self.assertEqual(set(vars(result)), {"input_path", "input_sha256", "archive_path", "archive_sha256"})
        validate(result)
        with self.assertRaises(FrozenInstanceError):
            result.input_sha256 = "c" * 64

    def test_every_partial_combination_is_rejected(self) -> None:
        """All fourteen nonempty incomplete combinations fail instead of falling back."""
        values = fields()
        for present in range(1, 15):
            partial = tuple(value if present & (1 << index) else None for index, value in enumerate(values))
            self.assertRaisesRegex(ValueError, "four.*together", parse, partial)

    def test_invalid_outer_type_or_arity_is_rejected(self) -> None:
        """Lists, arbitrary objects and missing/extra positions are not tuples of flags."""
        for value in (None, [], list(fields()), {}, (), fields()[:3], (*fields(), None)):
            self.assertRaisesRegex(ValueError, "exactly four", parse, value)

    def test_noncanonical_path_spellings_are_rejected_without_normalization(self) -> None:
        """Check both path roles before pathlib can erase supplied lexical aliases."""
        invalid = ("relative/input.json", "~/input.json", "/", "//TEST/input.json", "/TEST//input.json",
                   "/TEST/./input.json", "/TEST/../input.json", "/TEST/input.json/", "/TEST\\input.json",
                   "/TEST/\x00input.json", "/TEST/\ninput.json", "/" + "x" * 4096, Path(fields()[0]), True)
        for index in (0, 2):
            for value in invalid:
                changed = list(fields())
                changed[index] = value
                self.assertRaises(ValueError, parse, tuple(changed))

    def test_each_hash_requires_exact_lowercase_sha256(self) -> None:
        """No truthy values, byte strings, whitespace or uppercase digest aliases."""
        for index in (1, 3):
            for value in ("", "a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 64 + "\n", b"a" * 64, True):
                changed = list(fields())
                changed[index] = value
                self.assertRaises(ValueError, parse, tuple(changed))

    def test_direct_construction_requires_exact_path_and_hash_types(self) -> None:
        """Validate direct Python calls without a parser or a filesystem check."""
        value = fields()
        for location in (value[0], PurePosixPath(value[0]), Path("relative/input.json")):
            self.assertRaises(ValueError, SourceColorReadTransport, location, value[1], Path(value[2]), value[3])
        self.assertRaises(ValueError, SourceColorReadTransport, Path(value[0]), True, Path(value[2]), value[3])

    def test_each_original_field_mutation_is_rejected(self) -> None:
        """Even forced dataclass writes cannot replace the original read transport."""
        changed = {"input_path": Path("/TEST-unopened/other/input.json"), "input_sha256": "c" * 64,
                   "archive_path": Path("/TEST-unopened/other/reservation.json"), "archive_sha256": "d" * 64}
        for name, replacement in changed.items():
            value = parse(fields())
            object.__setattr__(value, name, replacement)
            self.assertRaisesRegex(RuntimeError, "original read transport changed", validate, value)

    def test_equal_valued_path_replacement_cannot_rebaseline_original(self) -> None:
        """Retain original Path identity as well as spelling, matching media transport."""
        value = parse(fields())
        replacement = Path(str(value.archive_path))
        self.assertIsNot(replacement, value.archive_path)
        object.__setattr__(value, "archive_path", replacement)
        self.assertRaisesRegex(RuntimeError, "original read transport changed", validate, value)

    def test_dto_clone_extra_field_and_unregistered_object_are_not_original_transport(self) -> None:
        """Only the actual constructor registration may satisfy direct-call validation."""
        value = parse(fields())
        for invalid in ({**vars(value)}, SimpleNamespace(**vars(value)), object(), copy(value)):
            self.assertRaises((ValueError, RuntimeError), validate, invalid)
        object.__setattr__(value, "approved", False)
        self.assertRaises(ValueError, validate, value)

    def test_parser_and_validator_perform_no_filesystem_clock_or_native_work(self) -> None:
        """Make forbidden effects fail even for apparently valid literal TEST paths."""
        forbidden = ("builtins.open", "os.open", "os.stat", "os.lstat", "pathlib.Path.resolve",
                     "time.monotonic", "time.time", "subprocess.run", "subprocess.Popen")
        with ExitStack() as stack:
            checks = [stack.enter_context(patch(name, side_effect=AssertionError("forbidden transport effect")))
                      for name in forbidden]
            validate(parse(fields()))
            validate(parse((None,) * 4))
            for checked in checks:
                checked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
