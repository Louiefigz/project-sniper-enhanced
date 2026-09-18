"""Adversarial sealed-input and no-follow promotion tests."""

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


def _motion_tree(root: str) -> Path:
    motion = Path(root) / "templates" / "motion"
    (motion / "compositions").mkdir(parents=True)
    (motion / "vendor" / "gsap").mkdir(parents=True)
    (motion / "node_modules").mkdir()
    html = (
        "<html data-composition-variables='[]'><head>"
        '<link href="/tokens.css"><script src="/vendor/gsap/gsap.min.js">'
        "</script></head></html>"
    )
    (motion / "compositions" / "card.html").write_text(html)
    (motion / "tokens.css").write_text("original-tokens")
    (motion / "vendor" / "gsap" / "gsap.min.js").write_text("gsap")
    (motion / "hyperframes.json").write_text("{}")
    (motion / "index.html").write_text("<html></html>")
    (motion / "package.json").write_text("{}")
    (motion / ".env").write_text("OPENAI_API_KEY=poison")
    (motion / "node_modules" / "poison").write_text("poison")
    return motion


class ContainerInputTests(unittest.TestCase):
    @staticmethod
    def _write_archive(
        path: Path, entries: dict[str, bytes], mode: int = 0o444
    ) -> tuple[str, tuple[dict, ...]]:
        manifest = tuple(
            {
                "path": name,
                "sizeBytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in sorted(entries.items())
        )
        encoded = json.dumps(
            manifest, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode()
        archive_entries = {**entries, "request/input-manifest.json": encoded}
        with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as archive:
            for name, data in sorted(archive_entries.items()):
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(data), mode, 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                archive.addfile(info, io.BytesIO(data))
        path.chmod(0o600)
        return hashlib.sha256(path.read_bytes()).hexdigest(), manifest

    def test_snapshot_is_minimal_and_immune_to_later_source_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as stage:
            motion = _motion_tree(root)
            composition = container_io.CompositionInput(
                "compositions/card.html",
                (motion / "compositions" / "card.html").read_text(),
            )
            sealed = container_io.create_snapshot(root, composition, {}, stage)
            (motion / "tokens.css").write_text("mutated-after-seal")
            with tarfile.open(sealed.path) as archive:
                names = archive.getnames()
                tokens = archive.extractfile("motion/tokens.css").read()
            self.assertEqual(tokens, b"original-tokens")
            self.assertNotIn("motion/.env", names)
            self.assertFalse(any("node_modules" in name for name in names))
            self.assertIn("request/input-manifest.json", names)

    def test_same_inputs_create_identical_archives(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            _motion_tree(root)
            html = (
                Path(root) / "templates" / "motion" / "compositions" / "card.html"
            ).read_text()
            composition = container_io.CompositionInput("compositions/card.html", html)
            left = container_io.create_snapshot(root, composition, {"x": 1}, first)
            right = container_io.create_snapshot(root, composition, {"x": 1}, second)
            self.assertEqual(left.sha256, right.sha256)
            self.assertEqual(left.manifest, right.manifest)

    def test_asset_binding_is_frozen_with_the_snapshot_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as stage:
            motion = _motion_tree(root)
            icons = motion / "icons"
            icons.mkdir()
            asset = icons / "proof.svg"
            asset.write_bytes(b"ASSET-A")
            composition = container_io.CompositionInput(
                "compositions/card.html",
                (motion / "compositions" / "card.html").read_text(),
            )
            resolved = [
                {"field": "iconFile", "selector": "proof.svg", "path": str(asset)}
            ]
            with mock.patch(
                "headless.container_io.resolved_assets", return_value=resolved
            ):
                sealed = container_io.create_snapshot(
                    root, composition, {"iconFile": "proof.svg"}, stage
                )
            expected = hashlib.sha256(b"ASSET-A").hexdigest()
            asset.write_bytes(b"ASSET-B")
            self.assertEqual(
                sealed.asset_bindings,
                (
                    {
                        "field": "iconFile",
                        "selector": "proof.svg",
                        "path": "motion/icons/proof.svg",
                        "sha256": expected,
                    },
                ),
            )
            row = next(
                item
                for item in sealed.manifest
                if item["path"] == "motion/icons/proof.svg"
            )
            self.assertEqual(row["sha256"], expected)

    def test_symlink_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as stage:
            motion = _motion_tree(root)
            (motion / "tokens.css").unlink()
            (motion / "tokens.css").symlink_to("package.json")
            composition = container_io.CompositionInput(
                "compositions/card.html",
                (motion / "compositions" / "card.html").read_text(),
            )
            with self.assertRaises((OSError, RuntimeError)):
                container_io.create_snapshot(root, composition, {}, stage)

    def test_stale_supplied_composition_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as stage:
            _motion_tree(root)
            composition = container_io.CompositionInput(
                "compositions/card.html", "<html>stale</html>"
            )
            with self.assertRaisesRegex(RuntimeError, "named source"):
                container_io.create_snapshot(root, composition, {}, stage)

    def test_multi_file_source_epoch_change_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as stage:
            motion = _motion_tree(root)
            composition = container_io.CompositionInput(
                "compositions/card.html",
                (motion / "compositions" / "card.html").read_text(),
            )
            original = container_io.PinnedSourceRoot.read
            changed = False

            def mutate_after_read(reader, relative: str) -> bytes:
                nonlocal changed
                data = original(reader, relative)
                if relative == "tokens.css" and not changed:
                    (motion / relative).write_text("new-epoch")
                    changed = True
                return data

            with mock.patch.object(
                container_io.PinnedSourceRoot,
                "read",
                autospec=True,
                side_effect=mutate_after_read,
            ), self.assertRaisesRegex(RuntimeError, "closure changed"):
                container_io.create_snapshot(root, composition, {}, stage)

    def test_remote_composition_dependency_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as stage:
            motion = _motion_tree(root)
            html = (
                '<html><script src="https://example.invalid/gsap.js"></script></html>'
            )
            (motion / "compositions" / "card.html").write_text(html)
            composition = container_io.CompositionInput("compositions/card.html", html)
            with self.assertRaisesRegex(RuntimeError, "remote render dependency"):
                container_io.create_snapshot(root, composition, {}, stage)

    def test_symlinked_asset_selector_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as stage:
            motion = _motion_tree(root)
            icons = motion / "icons"
            icons.mkdir()
            (icons / "target.svg").write_text("target")
            alias = icons / "alias.svg"
            alias.symlink_to("target.svg")
            composition = container_io.CompositionInput(
                "compositions/card.html",
                (motion / "compositions" / "card.html").read_text(),
            )
            assets = [
                {"field": "iconFile", "selector": "alias.svg", "path": str(alias)}
            ]
            with mock.patch(
                "headless.container_io.resolved_assets", return_value=assets
            ), self.assertRaises(OSError):
                container_io.create_snapshot(root, composition, {}, stage)

    def test_traversal_member_and_noncanonical_metadata_are_rejected(self) -> None:
        required = {
            "motion/compositions/card.html": b"<html></html>",
            "motion/hyperframes.json": b"{}",
            "motion/index.html": b"<html></html>",
            "motion/package.json": b"{}",
            "request/asset-bindings.json": b"[]",
            "request/variables.json": b"{}",
        }
        with tempfile.TemporaryDirectory() as stage:
            path = Path(stage) / "unsafe.tar"
            digest, manifest = self._write_archive(
                path, {**required, "../escape": b"x"}
            )
            with self.assertRaisesRegex(RuntimeError, "manifest row"):
                container_io.verify_snapshot_archive(str(path), digest, manifest)
            digest, manifest = self._write_archive(path, required, mode=0o600)
            with self.assertRaisesRegex(RuntimeError, "member closure"):
                container_io.verify_snapshot_archive(str(path), digest, manifest)

    def test_path_swap_is_rejected_before_snapshot_returns(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as stage:
            motion = _motion_tree(root)
            composition = container_io.CompositionInput(
                "compositions/card.html",
                (motion / "compositions" / "card.html").read_text(),
            )
            target = os.path.join(stage, "render-input.tar")
            real_fsync = container_io.os.fsync
            swapped = False

            def swap_path(fd: int) -> None:
                nonlocal swapped
                real_fsync(fd)
                if not swapped:
                    attacker = os.path.join(stage, "attacker.tar")
                    Path(attacker).write_bytes(b"attacker-archive")
                    os.replace(attacker, target)
                    swapped = True

            with mock.patch.object(
                container_io.os, "fsync", side_effect=swap_path
            ), self.assertRaisesRegex(RuntimeError, "digest mismatch|bounded"):
                container_io.create_snapshot(root, composition, {}, stage)

    def test_retained_snapshot_revalidates_digest_and_exact_members(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as stage:
            motion = _motion_tree(root)
            composition = container_io.CompositionInput(
                "compositions/card.html",
                (motion / "compositions" / "card.html").read_text(),
            )
            sealed = container_io.create_snapshot(root, composition, {}, stage)
            proof = container_io.verify_snapshot_archive(
                sealed.path, sealed.sha256, sealed.manifest
            )
            self.assertIn("request/input-manifest.json", proof["members"])
            os.chmod(sealed.path, 0o600)
            with open(sealed.path, "r+b") as handle:
                handle.seek(0)
                handle.write(b"corrupt")
            with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
                container_io.verify_snapshot_archive(
                    sealed.path, sealed.sha256, sealed.manifest
                )
