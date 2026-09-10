"""Exact render-build receipt and closed-manifest semantic tests."""

from __future__ import annotations

import dataclasses
import json
import unittest
from unittest import mock

from _common import pl  # noqa: F401
from _assembly_receipt_fixture import canonical
from _current_build_release_fixture import current_receipt
from _build_manifest_import_closure import (
    dynamic_import_calls,
    local_import_closure,
)
from _build_receipt_semantics_fixture import (
    recanonical_receipt,
    render_manifest_document,
    render_receipt_bytes,
)
from headless import render_build
from headless import render_build_manifest_semantics as manifest_semantics
from headless.render_build import render_build_manifest_digest
from headless.render_build_manifest_v1_contract import (
    RENDER_BUILD_V1_IMPLEMENTATION_PATHS,
)
from headless.render_build_manifest_v3_contract import RENDER_BUILD_V3_IMPLEMENTATION_PATHS
from headless.render_build_receipt_v3_semantics import parse_render_build_receipt_v3
from headless.render_build_receipt_semantics import (
    RenderBuildReceiptSchemaError,
    parse_render_build_receipt_v1,
    validate_render_build_receipt_v1,
)


class _AlwaysEqual:
    def __eq__(self, value: object) -> bool:
        return True


def _document(raw: bytes) -> dict:
    return json.loads(raw)


def _receipt() -> bytes:
    return render_receipt_bytes(render_manifest_document("2" * 64, "3" * 64))


def _rehash(document: dict) -> bytes:
    document["buildDigest"] = render_build_manifest_digest(
        document["manifest"]
    )
    return recanonical_receipt(document)


def _live_manifest(paths: tuple[str, ...], reader: object) -> dict:
    request = render_build.RenderBuildRequest(
        render_build._LOADED_ROOT,
        render_build._LOADED_ROOT,
        paths[3],
        paths[0],
        "/opt/sniper/docker.sock",
        "sha256:" + "1" * 64,
        "501:20",
        paths[1],
        paths[2],
        30,
    )
    socket = {
        "path": "/opt/sniper/docker.sock",
        "device": 1,
        "inode": 2,
        "mode": 49152,
        "ownerUid": 501,
    }
    loaded = list(render_build._LOADED_IMPLEMENTATION)
    with mock.patch.object(
        render_build, "_implementation_rows", return_value=loaded
    ), mock.patch.object(
        render_build, "_read_stable", side_effect=reader
    ), mock.patch.object(
        render_build, "_socket_row", return_value=socket
    ):
        return render_build.render_build_manifest(request)


class RenderBuildReceiptSemanticTests(unittest.TestCase):
    def test_current_v3_catalog_covers_every_local_execution_import(self) -> None:
        catalog = frozenset(RENDER_BUILD_V3_IMPLEMENTATION_PATHS)
        closure = local_import_closure(RENDER_BUILD_V3_IMPLEMENTATION_PATHS)
        self.assertFalse(closure - catalog)
        self.assertIn("scripts/producer/headless/render_worker.py", closure)
        self.assertFalse(dynamic_import_calls(closure))

    def test_live_writer_and_current_v3_parser_enforce_the_same_tool_contract(
        self,
    ) -> None:
        paths = tuple(f"/opt/sniper/bin/tool-{index}" for index in range(4))
        manifest = _live_manifest(paths, lambda path: path.encode("utf-8"))
        parsed = parse_render_build_receipt_v3(current_receipt(manifest))
        self.assertEqual(parsed.manifest.document_json, canonical(manifest))
        for bad_paths, reader, message in (
            ((paths[0],) * 4, lambda path: path.encode("utf-8"), "alias"),
            (paths, lambda path: b"", "nonempty"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(
                RuntimeError, message
            ):
                _live_manifest(bad_paths, reader)

    def test_exact_receipt_recomputes_closed_manifest_digest(self) -> None:
        value = parse_render_build_receipt_v1(_receipt())
        self.assertEqual(value.build_digest, value.manifest.build_digest)
        self.assertEqual(
            tuple(row.label for row in value.manifest.tools),
            ("docker", "proof-ffmpeg", "proof-ffprobe", "python"),
        )
        validate_render_build_receipt_v1(value)

    def test_historical_v1_parser_does_not_follow_live_schema_changes(
        self,
    ) -> None:
        raw = _receipt()
        self.assertNotEqual(
            RENDER_BUILD_V1_IMPLEMENTATION_PATHS,
            tuple(render_build._IMPLEMENTATION_FILES),
            "historical V1 does not expand with the current V2 writer",
        )
        with mock.patch.object(
            render_build, "_IMPLEMENTATION_FILES", ("other.py",)
        ), mock.patch.object(
            render_build, "BUILD_POLICY", "future-policy"
        ), mock.patch.object(
            render_build,
            "render_build_manifest_digest",
            side_effect=AssertionError("live digest called"),
        ), mock.patch.object(
            manifest_semantics.posixpath,
            "realpath",
            side_effect=AssertionError("live filesystem consulted"),
        ):
            parsed = parse_render_build_receipt_v1(raw)
        self.assertEqual(parsed.document_json, raw)

    def test_source_reorder_duplicate_or_path_substitution_rejects(
        self,
    ) -> None:
        for case in ("reorder", "duplicate", "substitute"):
            document = _document(_receipt())
            rows = document["manifest"]["implementation"]
            if case == "reorder":
                rows[0], rows[1] = rows[1], rows[0]
            elif case == "duplicate":
                rows[1]["path"] = rows[0]["path"]
            else:
                rows[0][
                    "path"
                ] = "scripts/producer/headless/../render_build.py"
            with self.subTest(case=case), self.assertRaisesRegex(
                RenderBuildReceiptSchemaError, "manifest is invalid"
            ):
                parse_render_build_receipt_v1(_rehash(document))

    def test_tool_order_duplicate_role_and_path_alias_rejects(self) -> None:
        for case in ("order", "role", "path", "socket"):
            document = _document(_receipt())
            rows = document["manifest"]["tools"]
            if case == "order":
                rows[0], rows[1] = rows[1], rows[0]
            elif case == "role":
                rows[1]["label"] = rows[0]["label"]
            elif case == "socket":
                document["manifest"]["dockerSocket"]["path"] = rows[0]["path"]
            else:
                rows[1]["path"] = rows[0]["path"]
            with self.subTest(case=case), self.assertRaisesRegex(
                RenderBuildReceiptSchemaError, "manifest is invalid"
            ):
                parse_render_build_receipt_v1(_rehash(document))

    def test_absolute_path_unicode_and_control_aliases_reject(self) -> None:
        values = ("//host/path", "/bad\\path", "/bad\x01path", "/\ud800")
        for path in values:
            document = _document(_receipt())
            document["manifest"]["runtimeRoot"] = path
            with self.subTest(path=repr(path)), self.assertRaisesRegex(
                RenderBuildReceiptSchemaError, "manifest is invalid"
            ):
                parse_render_build_receipt_v1(_rehash(document))

    def test_noncanonical_duplicate_trailing_and_self_claim_reject(
        self,
    ) -> None:
        raw = _receipt()
        declared = _document(raw)["buildDigest"].encode("ascii")
        duplicate = raw.replace(
            b'{"buildDigest":',
            b'{"buildDigest":"' + declared + b'","buildDigest":',
            1,
        )
        document = _document(raw)
        document["buildDigest"] = "0" * 64
        cases = (
            raw[:-1],
            raw + b"\n",
            duplicate,
            recanonical_receipt(document),
        )
        for forged in cases:
            with self.subTest(raw=forged[:40]), self.assertRaises(
                RenderBuildReceiptSchemaError
            ):
                parse_render_build_receipt_v1(forged)

    def test_manifest_self_claim_can_only_be_structurally_recomputed(
        self,
    ) -> None:
        original = parse_render_build_receipt_v1(_receipt())
        document = _document(_receipt())
        document["manifest"]["implementation"][0]["sha256"] = "9" * 64
        changed = parse_render_build_receipt_v1(_rehash(document))
        self.assertNotEqual(changed.build_digest, original.build_digest)
        self.assertEqual(
            changed.manifest.implementation[0].sha256,
            "9" * 64,
            "receipt recomputation does not reobserve absent source bytes",
        )

    def test_direct_construction_and_hostile_equality_reject(self) -> None:
        value = parse_render_build_receipt_v1(_receipt())
        source = dataclasses.replace(
            value.manifest.implementation[0], sha256=_AlwaysEqual()
        )
        manifest = dataclasses.replace(
            value.manifest,
            implementation=(source, *value.manifest.implementation[1:]),
        )
        cases = (
            dataclasses.replace(value, build_digest=_AlwaysEqual()),
            dataclasses.replace(value, manifest=manifest),
        )
        for forged in cases:
            with self.subTest(value=forged), self.assertRaises(
                RenderBuildReceiptSchemaError
            ):
                validate_render_build_receipt_v1(forged)


if __name__ == "__main__":
    unittest.main(verbosity=2)
