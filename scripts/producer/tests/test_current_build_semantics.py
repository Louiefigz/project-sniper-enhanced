"""Adversarial pure-parser tests for current build versions; no media launch."""
from __future__ import annotations

import dataclasses
import json
import unittest
from collections.abc import Callable
from unittest.mock import patch

from _common import pl  # noqa: F401
from _current_build_release_fixture import (
    canonical, current_compositor_manifest, current_compositor_receipt,
    current_manifest, current_receipt,
)
from headless.compositor_build_manifest_v3_semantics import (
    parse_compositor_build_manifest_v3, validate_compositor_build_manifest_v3,
)
from headless.compositor_build_receipt_semantics import parse_compositor_build_receipt_v1
from headless.compositor_build_receipt_v3_semantics import (
    parse_compositor_build_receipt_v3, validate_compositor_build_receipt_v3,
)
from headless.render_build_manifest_v4_semantics import (
    parse_render_build_manifest_v4, validate_render_build_manifest_v4,
)
from headless.render_build_receipt_semantics import parse_render_build_receipt_v1
from headless.render_build_receipt_v2_semantics import parse_render_build_receipt_v2
from headless.render_build_receipt_v4_semantics import (
    parse_render_build_receipt_v4, validate_render_build_receipt_v4,
)


class _AlwaysEqual:
    """Model caller-defined equality that must never confer validation authority."""

    def __eq__(self, other: object) -> bool:
        """Claim equality with everything, including different wire identities."""
        return True


CASES = (
    (current_compositor_manifest, current_compositor_receipt,
     parse_compositor_build_receipt_v3, validate_compositor_build_receipt_v3),
    (current_manifest, current_receipt, parse_render_build_receipt_v4, validate_render_build_receipt_v4),
)


class CurrentBuildSemanticTests(unittest.TestCase):
    """Exercise strict new formats independently from runtime admission."""

    def test_exact_wire_roundtrip_is_pure_and_revalidates(self) -> None:
        """Canonical retained values validate without consulting the filesystem."""
        for make, encode, parse, validate in CASES:
            raw = encode(make())
            with self.subTest(parser=parse.__name__), patch("builtins.open", side_effect=AssertionError("I/O")):
                parsed = parse(raw)
                validate(parsed)
                self.assertEqual(parsed.document_json, raw)
                self.assertEqual(parsed.manifest.build_digest, parsed.build_digest)
        validate_compositor_build_manifest_v3(parse_compositor_build_manifest_v3(
            canonical(current_compositor_manifest())))
        validate_render_build_manifest_v4(parse_render_build_manifest_v4(canonical(current_manifest())))

    def test_historical_parsers_reject_new_wire_versions(self) -> None:
        """A new build receipt cannot enter an old typed receipt lane."""
        checks = ((parse_compositor_build_receipt_v1, current_compositor_receipt()),
                  (parse_render_build_receipt_v1, current_receipt()),
                  (parse_render_build_receipt_v2, current_receipt()))
        for parse, raw in checks:
            with self.subTest(parser=parse.__name__), self.assertRaises(RuntimeError):
                parse(raw)

    def _reject_rows(self, case: tuple, mutate: Callable[[list], None]) -> None:
        """Resealing malformed rows must not make them valid."""
        make, encode, parse, _validate = case
        document = make()
        mutate(document["implementation"])
        with self.assertRaises(RuntimeError):
            parse(encode(document))

    def test_closed_paths_reject_missing_extra_reordered_alias_and_bad_rows(self) -> None:
        """Path order, exact field names, hashes and integer sizes stay closed."""
        mutations = (
            lambda rows: rows.pop(), lambda rows: rows.append(dict(rows[0])),
            lambda rows: rows.reverse(), lambda rows: rows[0].update(path=rows[1]["path"]),
            lambda rows: rows[0].update(path="scripts/producer/../bad.py"),
            lambda rows: rows[0].update(sizeBytes=True), lambda rows: rows[0].update(sizeBytes=0),
            lambda rows: rows[0].update(sha256="x" * 64),
            lambda rows: rows[0].update(extra=True), lambda rows: rows.__setitem__(0, None),
        )
        for case, mutate in ((case, mutate) for case in CASES for mutate in mutations):
            with self.subTest(parser=case[2].__name__, mutation=mutate):
                self._reject_rows(case, mutate)

    def test_mixed_outer_and_inner_versions_or_policies_reject(self) -> None:
        """No mixed envelope, unknown metadata or self-claimed digest is accepted."""
        mutations = (lambda doc: doc.update(schemaVersion=True), lambda doc: doc.update(schemaVersion=1),
            lambda doc: doc["manifest"].update(schemaVersion=1),
            lambda doc: doc["manifest"].update(policy="future"),
            lambda doc: doc.update(unknown=True), lambda doc: doc.update(buildDigest="0" * 64))
        for case, mutate in ((case, mutate) for case in CASES for mutate in mutations):
            document = json.loads(case[1]())
            mutate(document)
            with self.subTest(parser=case[2].__name__, mutation=mutate), self.assertRaises(RuntimeError):
                case[2](canonical(document) + b"\n")

    def test_noncanonical_duplicate_oversized_and_trailing_bytes_reject(self) -> None:
        """Receipt spelling and maximum size are part of the retained contract."""
        for _make, encode, parse, _validate in CASES:
            raw = encode()
            duplicate = raw.replace(b'{"buildDigest":', b'{"schemaVersion":99,"buildDigest":', 1)
            candidates = (raw[:-1], raw + b"\n", raw + b" ", duplicate, b" " * (2 * 1024 * 1024 + 1))
            for value in candidates:
                self.assertRaises(RuntimeError, parse, value)

    def test_all_current_row_metadata_contributes_to_the_digest(self) -> None:
        """V2 compositor and V3 render domains bind source size as well as hash."""
        for make, encode, parse, _validate in CASES:
            document = make()
            previous = parse(encode(document)).build_digest
            document["implementation"][0]["sizeBytes"] += 1
            changed = parse(encode(document))
            self.assertNotEqual(changed.build_digest, previous)

    def test_forged_instances_and_hostile_equality_reject(self) -> None:
        """Exact dataclass type alone cannot approve values changed after parsing."""
        for _make, encode, parse, validate in CASES:
            parsed = parse(encode())
            row = dataclasses.replace(parsed.manifest.implementation[0], sha256=_AlwaysEqual())
            manifest = dataclasses.replace(parsed.manifest, implementation=(row, *parsed.manifest.implementation[1:]))
            for value in (dataclasses.replace(parsed, build_digest=_AlwaysEqual()),
                          dataclasses.replace(parsed, manifest=manifest)):
                self.assertRaises(RuntimeError, validate, value)

    def test_render_envelope_tools_and_socket_remain_closed(self) -> None:
        """Existing runtime metadata checks survive the version extension."""
        mutations = (
            lambda doc: doc.update(timeoutSeconds=True), lambda doc: doc.update(timeoutSeconds=3601),
            lambda doc: doc.update(userId="0:0"), lambda doc: doc.update(imageId="latest"),
            lambda doc: doc.update(pipelineRoot="/a/../b"), lambda doc: doc.update(pythonFlags=[]),
            lambda doc: doc["tools"][0].update(path=doc["tools"][1]["path"]),
            lambda doc: doc["tools"][0].update(sha256=doc["tools"][1]["sha256"]),
            lambda doc: doc["dockerSocket"].update(path=doc["tools"][0]["path"]),
            lambda doc: doc["dockerSocket"].update(mode=32768),
        )
        for mutate in mutations:
            document = current_manifest()
            mutate(document)
            with self.subTest(mutation=mutate), self.assertRaises(RuntimeError):
                parse_render_build_receipt_v4(current_receipt(document))


if __name__ == "__main__":
    unittest.main(verbosity=2)
