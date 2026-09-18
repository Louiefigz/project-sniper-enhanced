"""Adversarial regressions for the closed pre-admission render artifact."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from _current_build_release_fixture import current_manifest
from headless import render_admission_artifact as artifact_module
from headless import render_admission_artifact_reader as artifact_reader
from headless.render_admission_artifact import (
    RenderArtifactLocator,
    RenderArtifactRequest,
    load_render_admission_artifact,
    store_render_admission_artifact,
)
from headless.render_admission_schema import (
    ARTIFACTS_DIR,
    MANIFEST_NAME,
    _artifact_digest,
    _canonical,
    _selection_directory,
)
from headless.render_runtime import RendererRuntime
from headless.request_artifact import canonical_request_document

PRODUCER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PRODUCER_DIR.parents[1]
BUILD_A = current_manifest("test-a")
BUILD_B = current_manifest("test-b")


def _entry(label: str = "A", duration: float = 2.5) -> dict:
    return {
        "kind": "section-marker",
        "outStart": 0,
        "outEnd": duration,
        "anchor": "free-band",
        "spec": {
            "num": "Part 1",
            "line1": label,
            "line2": "Basics",
            "side": "left",
            "accent": "#054BC9",
        },
    }


def _request(*rows: tuple[str, dict]) -> dict:
    overlays = [
        {"overlayId": overlay_id, "entry": entry} for overlay_id, entry in rows
    ]
    return {
        "schemaVersion": 1,
        "operation": "render-overlays",
        "overlays": overlays,
    }


class RenderAdmissionArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.authority = self._authority("authority")
        self.runtime = RendererRuntime(
            str(REPO_ROOT),
            str(REPO_ROOT),
            "/test/python",
            "/test/docker",
            "/test/docker.sock",
            "sha256:" + "1" * 64,
            "501:20",
            "/test/ffmpeg",
            "/test/ffprobe",
            30,
        )

    def _authority(self, name: str) -> Path:
        path = self.root / name
        path.mkdir(mode=0o700)
        os.chmod(path, 0o700)
        return path

    def _store(
        self,
        request: dict,
        authority: Path | None = None,
        manifest: dict = BUILD_A,
    ) -> RenderArtifactLocator:
        target = authority or self.authority
        build = mock.patch.object(
            artifact_module,
            "current_render_build_manifest",
            return_value=manifest,
        )
        with build:
            return store_render_admission_artifact(
                RenderArtifactRequest(
                    str(target), "authority-mp4-v1", request, self.runtime
                )
            )

    @staticmethod
    def _artifact_root(
        authority: Path, locator: RenderArtifactLocator
    ) -> Path:
        return authority / ARTIFACTS_DIR / locator.artifact_digest

    def _readdress(
        self, locator: RenderArtifactLocator, mutate
    ) -> RenderArtifactLocator:
        root = self._artifact_root(self.authority, locator)
        manifest_path = root / MANIFEST_NAME
        manifest = json.loads(manifest_path.read_bytes())
        mutate(root, manifest)
        raw = _canonical(manifest)
        manifest_path.write_bytes(raw)
        os.chmod(manifest_path, 0o600)
        changed = RenderArtifactLocator(_artifact_digest(raw))
        root.rename(root.with_name(changed.artifact_digest))
        return changed

    @staticmethod
    def _update_row(manifest: dict, name: str, raw: bytes) -> None:
        row = next(item for item in manifest["files"] if item["path"] == name)
        row["sha256"] = hashlib.sha256(raw).hexdigest()
        row["sizeBytes"] = len(raw)

    def test_multi_overlay_case_ids_freeze_and_idempotence(self) -> None:
        request = _request(
            ("Overlay-A", _entry("First", 2.5)),
            ("overlay-a", _entry("Second", 3.0)),
        )
        first = self._store(request)
        request["overlays"][0]["entry"]["spec"]["line1"] = "MUTATED"
        with mock.patch(
            "headless.overlay_source_seal._read_composition",
            side_effect=AssertionError("live source reread"),
        ):
            resolved = load_render_admission_artifact(
                str(self.authority), first
            )
        second = self._store(
            _request(
                ("Overlay-A", _entry("First", 2.5)),
                ("overlay-a", _entry("Second", 3.0)),
            )
        )
        other = self._store(
            _request(
                ("Overlay-A", _entry("First", 2.5)),
                ("overlay-a", _entry("Second", 3.0)),
            ),
            self._authority("other"),
        )
        self.assertEqual(first, second)
        self.assertEqual(first.artifact_digest, other.artifact_digest)
        self.assertEqual(
            [row.overlay_id for row in resolved.overlays],
            ["Overlay-A", "overlay-a"],
        )
        self.assertEqual(
            resolved.overlays[0].resolved.expected_copy[1], "First"
        )
        children = os.listdir(
            self._artifact_root(self.authority, first) / "overlays"
        )
        self.assertEqual(
            set(children),
            {
                _selection_directory("Overlay-A"),
                _selection_directory("overlay-a"),
            },
        )

    def test_request_is_frozen_before_build_capture(self) -> None:
        request = _request(("overlay-1", _entry("Original")))

        def mutate_after_freeze(_runtime):
            request["overlays"][0]["entry"]["spec"]["line1"] = "Late mutation"
            return BUILD_A

        with mock.patch.object(
            artifact_module,
            "current_render_build_manifest",
            side_effect=mutate_after_freeze,
        ):
            locator = store_render_admission_artifact(
                RenderArtifactRequest(
                    str(self.authority),
                    "authority-mp4-v1",
                    request,
                    self.runtime,
                )
            )
        resolved = load_render_admission_artifact(str(self.authority), locator)
        self.assertEqual(
            resolved.overlays[0].resolved.expected_copy[1], "Original"
        )

    def test_request_and_build_changes_change_artifact_identity(self) -> None:
        first = self._store(_request(("overlay-1", _entry("A"))))
        changed_request = self._store(_request(("overlay-1", _entry("B"))))
        changed_build = self._store(
            _request(("overlay-1", _entry("A"))), manifest=BUILD_B
        )
        self.assertEqual(
            len(
                {
                    first.artifact_digest,
                    changed_request.artifact_digest,
                    changed_build.artifact_digest,
                }
            ),
            3,
        )

    def test_build_drift_cleans_pending_and_retry_succeeds(self) -> None:
        request = _request(("overlay-1", _entry()))
        with mock.patch.object(
            artifact_module,
            "current_render_build_manifest",
            side_effect=[BUILD_A, BUILD_B],
        ):
            with self.assertRaisesRegex(RuntimeError, "build changed"):
                store_render_admission_artifact(
                    RenderArtifactRequest(
                        str(self.authority),
                        "authority-mp4-v1",
                        request,
                        self.runtime,
                    )
                )
        artifacts = self.authority / ARTIFACTS_DIR
        self.assertFalse(
            any(
                path.name.startswith(".pending-")
                for path in artifacts.iterdir()
            )
        )
        self.assertIsInstance(self._store(request), RenderArtifactLocator)

    def test_uuid_collision_never_deletes_foreign_pending_directory(
        self,
    ) -> None:
        self._store(_request(("existing", _entry())))
        artifacts = self.authority / ARTIFACTS_DIR
        collision = artifacts / (".pending-" + "a" * 32)
        collision.mkdir(mode=0o700)
        os.chmod(collision, 0o700)
        marker = collision / "foreign"
        marker.write_bytes(b"keep")
        os.chmod(marker, 0o600)
        fixed = uuid.UUID(hex="a" * 32)
        with mock.patch.object(
            artifact_module.uuid, "uuid4", return_value=fixed
        ), self.assertRaises(FileExistsError):
            self._store(_request(("overlay-1", _entry())))
        self.assertEqual(marker.read_bytes(), b"keep")

    def test_payload_cap_stops_before_second_overlay(self) -> None:
        request = _request(("one", _entry()), ("two", _entry("B")))
        source = {
            "snapshotManifest": [],
            "composition": "x.html",
            "sourceCompositionSha256": "0" * 64,
        }
        tar = {
            "mode": 0o400,
            "path": "ignored",
            "sha256": "0" * 64,
            "sizeBytes": artifact_module._MAX_TOTAL_PAYLOAD_BYTES + 1,
        }
        with mock.patch.object(
            artifact_module,
            "current_render_build_manifest",
            return_value=BUILD_A,
        ), mock.patch.object(
            artifact_module, "_capture_one", return_value=(b"{}\n", source)
        ) as capture, mock.patch.object(
            artifact_module, "_tar_row", return_value=tar
        ):
            with self.assertRaisesRegex(RuntimeError, "512 MiB"):
                store_render_admission_artifact(
                    RenderArtifactRequest(
                        str(self.authority),
                        "authority-mp4-v1",
                        request,
                        self.runtime,
                    )
                )
        self.assertEqual(capture.call_count, 1)

    def test_root_and_leaf_tampering_fail_closed(self) -> None:
        cases = ("extra", "wrong-mode", "hardlink", "tar-bytes", "symlink")
        for index, attack in enumerate(cases):
            with self.subTest(attack=attack):
                authority = self._authority(f"tamper-{index}")
                locator = self._store(
                    _request(("overlay-1", _entry())), authority
                )
                root = self._artifact_root(authority, locator)
                child = root / "overlays" / _selection_directory("overlay-1")
                if attack == "extra":
                    extra = root / "extra"
                    extra.write_bytes(b"x")
                    os.chmod(extra, 0o600)
                elif attack == "wrong-mode":
                    os.chmod(child / "source-seal.json", 0o644)
                elif attack == "hardlink":
                    os.link(child / "source-seal.json", authority / "alias")
                elif attack == "tar-bytes":
                    os.chmod(child / "render-input.tar", 0o600)
                    (child / "render-input.tar").write_bytes(b"changed")
                    os.chmod(child / "render-input.tar", 0o400)
                else:
                    source = child / "source-seal.json"
                    source.unlink()
                    source.symlink_to(root / "request.json")
                with self.assertRaises(RuntimeError):
                    load_render_admission_artifact(str(authority), locator)

    def test_same_size_tar_swap_after_first_proof_is_rejected(self) -> None:
        locator = self._store(_request(("overlay-1", _entry())))
        original = artifact_reader.resolve_overlay_source

        def swap_after_resolve(*args, **kwargs):
            resolved = original(*args, **kwargs)
            path = Path(resolved.snapshot.path)
            replacement = path.with_name("replacement.tar")
            replacement.write_bytes(b"x" * path.stat().st_size)
            os.chmod(replacement, 0o400)
            os.replace(replacement, path)
            return resolved

        with mock.patch.object(
            artifact_reader,
            "resolve_overlay_source",
            side_effect=swap_after_resolve,
        ), self.assertRaisesRegex(RuntimeError, "digest mismatch"):
            load_render_admission_artifact(str(self.authority), locator)

    def test_coherent_request_rewrite_cannot_rebind_old_source(self) -> None:
        locator = self._store(_request(("overlay-1", _entry("Original"))))

        def rewrite(root: Path, manifest: dict) -> None:
            request = json.loads((root / "request.json").read_bytes())
            request["overlays"][0]["entry"]["spec"]["line1"] = "Forged"
            frozen, raw, digest = canonical_request_document(request)
            self.assertEqual(frozen, request)
            (root / "request.json").write_bytes(raw)
            os.chmod(root / "request.json", 0o600)
            manifest["requestDocumentDigest"] = digest
            self._update_row(manifest, "request.json", raw)

        forged = self._readdress(locator, rewrite)
        with self.assertRaisesRegex(RuntimeError, "does not match request"):
            load_render_admission_artifact(str(self.authority), forged)

    def test_malformed_rows_boolean_schema_ids_and_locators_reject(
        self,
    ) -> None:
        locator = self._store(_request(("overlay-1", _entry())))
        malformed = self._readdress(
            locator, lambda _root, manifest: manifest.update(files=[0])
        )
        with self.assertRaisesRegex(RuntimeError, "file rows"):
            load_render_admission_artifact(str(self.authority), malformed)
        for value in (True, 1, None):
            request = _request(("overlay-1", _entry()))
            request["overlays"][0]["overlayId"] = value
            with self.subTest(overlay_id=value), self.assertRaises(
                RuntimeError
            ):
                self._store(request, self._authority(f"id-{value!s}"))
        request = _request(("overlay-1", _entry()))
        request["schemaVersion"] = True
        with self.assertRaises(RuntimeError):
            self._store(request, self._authority("boolean-schema"))
        for digest in (None, 1, True, "not-a-digest"):
            with self.subTest(digest=digest), self.assertRaises(RuntimeError):
                load_render_admission_artifact(
                    str(self.authority), RenderArtifactLocator(digest)
                )

    def test_public_locator_exposes_only_the_closed_digest(self) -> None:
        fields = {
            field.name for field in dataclasses.fields(RenderArtifactLocator)
        }
        self.assertEqual(fields, {"artifact_digest"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
