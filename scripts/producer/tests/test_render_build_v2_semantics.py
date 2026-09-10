"""Current V2/version-separation regressions; no execution proof is fabricated."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from _build_receipt_semantics_fixture import render_manifest_document, render_receipt_bytes
from _current_render_build_fixture import canonical, current_manifest, current_receipt
from headless import render_build
from headless.render_build_manifest_v2_contract import RENDER_BUILD_V2_IMPLEMENTATION_PATHS
from headless.render_build_manifest_v2_semantics import (
    parse_render_build_manifest_v2,
    validate_render_build_manifest_v2,
)
from headless.render_build_receipt import (
    RenderBuildLocator,
    encode_render_build_receipt,
    load_render_build,
    store_render_build,
)
from headless.render_build_receipt_semantics import parse_render_build_receipt_v1
from headless.render_build_receipt_v2_semantics import (
    parse_render_build_receipt_v2,
    validate_render_build_receipt_v2,
)


class _AlwaysEqual:
    def __eq__(self, other: object) -> bool:
        return True


def _historical() -> bytes:
    return render_receipt_bytes(render_manifest_document("2" * 64, "3" * 64))


class RenderBuildV2SemanticTests(unittest.TestCase):
    def test_current_receipt_has_distinct_version_and_exact_guard_closure(self) -> None:
        raw = current_receipt()
        parsed = parse_render_build_receipt_v2(raw)
        validate_render_build_receipt_v2(parsed)
        validate_render_build_manifest_v2(parsed.manifest)
        self.assertEqual(encode_render_build_receipt(current_manifest()), raw)
        paths = tuple(row.path for row in parsed.manifest.implementation)
        self.assertEqual(paths, RENDER_BUILD_V2_IMPLEMENTATION_PATHS)
        self.assertEqual(len(paths), len(set(paths)))
        self.assertIn("scripts/producer/headless/render_log_guard.py", paths)
        self.assertEqual(render_build.BUILD_SCHEMA_VERSION, 2)
        self.assertEqual(render_build._IMPLEMENTATION_FILES, paths)
        with self.assertRaises(RuntimeError):
            parse_render_build_receipt_v1(raw)

    def test_historical_wire_bytes_and_parser_remain_reproducible(self) -> None:
        raw = _historical()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "627aecccadde9541180e53269f1e9eb4c1098e4f46f3519da6fe01867494a8e0")
        with mock.patch.object(render_build, "BUILD_POLICY", "future"), mock.patch.object(
            render_build, "_IMPLEMENTATION_FILES", ("future.py",),
        ):
            parsed = parse_render_build_receipt_v1(raw)
        self.assertEqual(parsed.document_json, raw)
        with self.assertRaises(RuntimeError):
            parse_render_build_receipt_v2(raw)

    def test_frozen_historical_sources_are_not_rewritten(self) -> None:
        root = Path(__file__).resolve().parents[1]
        hashes = {
            "headless/render_build_manifest_v1_contract.py": "5897fff747834e9d8c4338bcb68e249878b9f979f76c0ac2b7c43e083f9c9a06",
            "headless/render_build_manifest_semantics.py": "85eb2a0621ff31c0e828be2588b041d83d78173067f0e5a6122256908b6ccf72",
            "headless/render_build_receipt_semantics.py": "f2dfe4c82be1724a50d51d762bf8ae11c3c29f967c2ebf4d6b1066870b2c79e1",
            "tests/_build_receipt_semantics_fixture.py": "1081647a3f56b8b5829bdb72a6a41bd45688c26cbc8c8a8ac058b2ac0c3cb634",
        }
        for path, digest in hashes.items():
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256((root / path).read_bytes()).hexdigest(), digest)

    def test_missing_reordered_duplicated_or_extra_source_rows_reject(self) -> None:
        for case in ("missing", "reordered", "duplicate", "extra", "alias", "zero", "bool"):
            document = current_manifest()
            rows = document["implementation"]
            if case == "missing":
                rows[:] = [row for row in rows if not row["path"].endswith("render_log_guard.py")]
            elif case == "reordered":
                rows[0], rows[1] = rows[1], rows[0]
            elif case == "duplicate":
                rows[1] = dict(rows[0])
            elif case == "extra":
                rows.append(dict(rows[0]))
            elif case == "alias":
                rows[0]["path"] = "scripts/producer/../producer/captions/__init__.py"
            else:
                rows[0]["sizeBytes"] = 0 if case == "zero" else True
            with self.subTest(case=case), self.assertRaises(RuntimeError):
                parse_render_build_receipt_v2(current_receipt(document))

    def test_envelope_and_runtime_metadata_are_closed(self) -> None:
        cases = (("schemaVersion", True), ("schemaVersion", 1), ("policy", "future"),
                 ("timeoutSeconds", 0), ("timeoutSeconds", 3601), ("timeoutSeconds", True),
                 ("imageId", "latest"), ("userId", "0:0"), ("pythonFlags", []),
                 ("pipelineRoot", "/a/../b"), ("runtimeRoot", "/bad\ud800"))
        for key, value in cases:
            document = current_manifest()
            document[key] = value
            with self.subTest(key=key, value=repr(value)), self.assertRaises(RuntimeError):
                parse_render_build_receipt_v2(current_receipt(document))
        for case in ("source-key", "tool-alias", "tool-digest", "socket-alias", "socket-type"):
            document = current_manifest()
            if case == "source-key":
                document["implementation"][0]["ignored"] = True
            elif case == "tool-alias":
                document["tools"][1]["path"] = document["tools"][0]["path"]
            elif case == "tool-digest":
                document["tools"][1]["sha256"] = document["tools"][0]["sha256"]
            elif case == "socket-alias":
                document["dockerSocket"]["path"] = document["tools"][0]["path"]
            else:
                document["dockerSocket"]["mode"] = 32768
            with self.subTest(case=case), self.assertRaises(RuntimeError):
                parse_render_build_receipt_v2(current_receipt(document))

    def test_wire_noncanonical_mixed_versions_and_digest_forgery_reject(self) -> None:
        raw = current_receipt()
        document = json.loads(raw)
        document["schemaVersion"] = 1
        mixed = canonical(document) + b"\n"
        document = json.loads(raw)
        document["buildDigest"] = "0" * 64
        forged = canonical(document) + b"\n"
        duplicate = raw.replace(b'{"buildDigest":', b'{"schemaVersion":2,"buildDigest":', 1)
        cases = (raw[:-1], raw + b"\n", raw + b" ", raw.replace(b':2,', b':2.0,'),
                 mixed, forged, duplicate, b"x" * (2 * 1024 * 1024 + 1))
        for candidate in cases:
            with self.subTest(prefix=candidate[:30]), self.assertRaises(RuntimeError):
                parse_render_build_receipt_v2(candidate)

    def test_direct_construction_and_hostile_equality_reject(self) -> None:
        parsed = parse_render_build_receipt_v2(current_receipt())
        row = dataclasses.replace(parsed.manifest.implementation[0], sha256=_AlwaysEqual())
        manifest = dataclasses.replace(parsed.manifest, implementation=(row, *parsed.manifest.implementation[1:]))
        for value in (dataclasses.replace(parsed, build_digest=_AlwaysEqual()),
                      dataclasses.replace(parsed, manifest=manifest)):
            with self.assertRaises(RuntimeError):
                validate_render_build_receipt_v2(value)

    def test_self_hash_does_not_claim_live_source_observation(self) -> None:
        document = current_manifest()
        document["implementation"][0]["sha256"] = "f" * 64
        changed = parse_render_build_receipt_v2(current_receipt(document))
        self.assertEqual(changed.manifest.implementation[0].sha256, "f" * 64)
        self.assertNotEqual(changed.build_digest,
                            parse_render_build_receipt_v2(current_receipt()).build_digest)

    def test_current_store_and_loader_reject_historical_v1(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            attempt = Path(directory).resolve()
            attempt.chmod(0o700)
            with self.assertRaises(RuntimeError):
                store_render_build(str(attempt), json.loads(_historical())["manifest"])
            self.assertEqual(list(attempt.iterdir()), [])
            current = store_render_build(str(attempt), current_manifest())
            historical = parse_render_build_receipt_v1(_historical())
            old_path = Path(current.path).with_name(historical.build_digest + ".json")
            old_path.write_bytes(_historical())
            old_path.chmod(0o600)
            with self.assertRaises(RuntimeError):
                load_render_build(str(attempt), RenderBuildLocator(str(old_path), historical.build_digest))

    def test_new_manifest_parser_is_pure_and_not_the_live_writer(self) -> None:
        with mock.patch.object(render_build, "render_build_manifest_digest",
                               side_effect=AssertionError("live writer called")):
            parsed = parse_render_build_manifest_v2(canonical(current_manifest()))
        self.assertEqual(parsed.document_json, canonical(current_manifest()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
