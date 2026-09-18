"""Byte-level adversarial tests for the retained render-input archive."""
from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from headless import container_io
from headless.sealed_archive import verify_archive_file


def _base_entries() -> dict[str, bytes]:
    return {"motion/compositions/card.html": b"<html></html>",
            "motion/hyperframes.json": b"{}",
            "motion/index.html": b"<html></html>",
            "motion/package.json": b"{}",
            "request/asset-bindings.json": b"[]",
            "request/variables.json": b"{}"}


def _write(path: Path, entries: dict[str, bytes], *, areg: bool = False,
           pax: bool = False) -> tuple[str, tuple[dict, ...]]:
    manifest = tuple({"path": name, "sizeBytes": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()}
                     for name, data in sorted(entries.items()))
    encoded = json.dumps(manifest, ensure_ascii=True, separators=(",", ":"),
                         sort_keys=True).encode("ascii")
    all_entries = {**entries, "request/input-manifest.json": encoded}
    archive_format = tarfile.PAX_FORMAT if pax else tarfile.USTAR_FORMAT
    with tarfile.open(path, "w", format=archive_format) as archive:
        for index, (name, data) in enumerate(sorted(all_entries.items())):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o444, 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            if areg and index == 0:
                info.type = tarfile.AREGTYPE
            if pax and index == 0:
                info.pax_headers = {"comment": "hidden"}
            archive.addfile(info, io.BytesIO(data))
    path.chmod(0o600)
    return hashlib.sha256(path.read_bytes()).hexdigest(), manifest


class SealedArchiveAdversarialTests(unittest.TestCase):
    def _reject(self, mutate=None, **options) -> str:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "input.tar"
            digest, manifest = _write(path, _base_entries(), **options)
            if mutate:
                digest = mutate(path, digest)
            with self.assertRaises(RuntimeError) as raised:
                verify_archive_file(str(path), digest, manifest)
            return str(raised.exception)

    def test_asset_bindings_member_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "input.tar"
            entries = _base_entries()
            entries.pop("request/asset-bindings.json")
            digest, manifest = _write(path, entries)
            with self.assertRaisesRegex(RuntimeError, "manifest closure"):
                verify_archive_file(str(path), digest, manifest)

    def test_areg_and_hidden_pax_metadata_are_rejected(self) -> None:
        self.assertIn("member closure", self._reject(areg=True))
        self.assertIn("member closure", self._reject(pax=True))

    def test_trailing_bytes_and_public_outer_mode_are_rejected(self) -> None:
        def trailing(path: Path, _digest: str) -> str:
            with path.open("ab") as handle:
                handle.write(b"TRAILING")
            return hashlib.sha256(path.read_bytes()).hexdigest()

        self.assertIn("canonical USTAR", self._reject(trailing))

        def public(path: Path, digest: str) -> str:
            path.chmod(0o666)
            return digest

        self.assertIn("bounded regular", self._reject(public))

    def test_request_json_must_be_semantically_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "input.tar"
            entries = _base_entries()
            entries["request/variables.json"] = b'{"z":1, "a":2}'
            digest, manifest = _write(path, entries)
            with self.assertRaisesRegex(RuntimeError, "canonical JSON"):
                verify_archive_file(str(path), digest, manifest)

    def test_failed_verification_does_not_poison_retry(self) -> None:
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as stage:
            motion = Path(root) / "templates" / "motion"
            (motion / "compositions").mkdir(parents=True)
            for name, data in (("hyperframes.json", "{}"),
                               ("index.html", "<html></html>"),
                               ("package.json", "{}")):
                (motion / name).write_text(data)
            html = ("<main data-composition-id=\"x\" data-duration=\"1\" "
                    "data-composition-variables='[]'></main>")
            (motion / "compositions" / "card.html").write_text(html)
            composition = container_io.CompositionInput(
                "compositions/card.html", html)
            with mock.patch("headless.container_io.verify_archive_file",
                            side_effect=RuntimeError("injected")), \
                    self.assertRaisesRegex(RuntimeError, "injected"):
                container_io.create_snapshot(root, composition, {}, stage)
            self.assertFalse((Path(stage) / "render-input.tar").exists())
            sealed = container_io.create_snapshot(root, composition, {}, stage)
            self.assertTrue(Path(sealed.path).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
