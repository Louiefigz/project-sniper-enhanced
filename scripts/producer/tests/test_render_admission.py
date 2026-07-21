"""Attempt-only admission binding for closed render artifacts."""

from __future__ import annotations

import dataclasses
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from headless import render_admission as admission_module
from headless import render_admission_artifact as artifact_module
from headless.admission_registry import (
    AdmissionError,
    AdmissionRequest,
    IdempotencyConflict,
    admit,
    locate_admission,
)
from headless.durability_controller import admit_attempt
from headless.render_admission import (
    AdmittedRenderRef,
    RenderAdmissionError,
    RenderAdmissionMetadata,
    admit_render_artifact,
    load_admitted_render,
)
from headless.render_admission_artifact import (
    RenderArtifactRequest,
    store_render_admission_artifact,
)
from headless.render_runtime import RendererRuntime

PRODUCER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PRODUCER_DIR.parents[1]
KEY = "11111111-1111-4111-8111-111111111111"
ATTEMPT = "22222222-2222-4222-8222-222222222222"
UNIT = "33333333-3333-4333-8333-333333333333"
BUILD = {"schemaVersion": 1, "policy": "admission-test", "implementation": []}


def _request(label: str = "A") -> dict:
    entry = {
        "kind": "section-marker",
        "outStart": 0,
        "outEnd": 2.5,
        "anchor": "free-band",
        "spec": {
            "num": "System No.1",
            "line1": label,
            "line2": "Rule",
            "side": "left",
            "accent": "#054BC9",
        },
    }
    return {
        "schemaVersion": 1,
        "operation": "render-overlays",
        "overlays": [{"overlayId": "overlay-1", "entry": entry}],
    }


class RenderAdmissionTests(unittest.TestCase):
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

    def _artifact(self, label: str = "A", authority: Path | None = None):
        target = authority or self.authority
        with mock.patch.object(
            artifact_module,
            "current_render_build_manifest",
            return_value=BUILD,
        ):
            return store_render_admission_artifact(
                RenderArtifactRequest(
                    str(target),
                    "authority-mp4-v1",
                    _request(label),
                    self.runtime,
                )
            )

    def _metadata(
        self,
        authority: Path | None = None,
        attempt: str = ATTEMPT,
        key: str = KEY,
    ):
        return RenderAdmissionMetadata(
            str(authority or self.authority),
            "authority-mp4-v1",
            key,
            attempt,
            UNIT,
            "2026-07-19T12:00:00+00:00",
            "release-test",
            "policy-test",
            None,
        )

    def test_admission_derives_outer_artifact_and_build_identities(
        self,
    ) -> None:
        artifact = self._artifact()
        created = admit_render_artifact(self._metadata(), artifact, "boot-a")
        replay = admit_render_artifact(self._metadata(), artifact, "boot-a")
        self.assertTrue(created.admission.created)
        self.assertFalse(replay.admission.created)
        self.assertEqual(
            created.admission.record["requestIdentityDigest"],
            artifact.artifact_digest,
        )
        resolved = load_admitted_render(
            AdmittedRenderRef(str(self.authority), ATTEMPT), "boot-a"
        )
        self.assertEqual(
            created.admission.record["buildId"], resolved.artifact.build_digest
        )
        self.assertEqual(
            resolved.artifact.artifact_digest, artifact.artifact_digest
        )
        self.assertEqual(
            resolved.attempt_root, str(self.authority / "attempts" / ATTEMPT)
        )
        self.assertEqual(
            created.reference, AdmittedRenderRef(str(self.authority), ATTEMPT)
        )

    def test_replay_reference_uses_original_attempt_not_proposed_attempt(
        self,
    ) -> None:
        artifact = self._artifact()
        admitted = admit_render_artifact(self._metadata(), artifact, "boot-a")
        proposed = dataclasses.replace(
            self._metadata(),
            attempt_id="44444444-4444-4444-8444-444444444444",
            first_submitted_at="2026-07-19T12:01:00+00:00",
        )
        replay = admit_render_artifact(proposed, artifact, "boot-a")
        self.assertEqual(admitted.reference, replay.reference)
        self.assertEqual(replay.reference.attempt_id, ATTEMPT)

    def test_attempt_reference_cannot_select_another_artifact(self) -> None:
        first = self._artifact("A")
        second = self._artifact("B")
        admit_render_artifact(self._metadata(), first, "boot-a")
        changed = self._metadata(
            attempt="44444444-4444-4444-8444-444444444444",
            key="55555555-5555-4555-8555-555555555555",
        )
        admit_render_artifact(changed, second, "boot-a")
        resolved = load_admitted_render(
            AdmittedRenderRef(str(self.authority), ATTEMPT), "boot-a"
        )
        self.assertEqual(
            resolved.artifact.artifact_digest, first.artifact_digest
        )
        fields = {
            field.name for field in dataclasses.fields(AdmittedRenderRef)
        }
        self.assertEqual(fields, {"authority_root", "attempt_id"})

    def test_changed_artifact_conflicts_under_same_idempotency_key(
        self,
    ) -> None:
        first = self._artifact("A")
        second = self._artifact("B")
        admit_render_artifact(self._metadata(), first, "boot-a")
        with self.assertRaises(IdempotencyConflict):
            admit_render_artifact(self._metadata(), second, "boot-a")

    def test_artifact_loss_during_admission_never_returns_acceptance(
        self,
    ) -> None:
        artifact = self._artifact()
        source = (
            self.authority
            / "render-admission-artifacts"
            / artifact.artifact_digest
        )
        displaced = self.authority / "displaced-render-artifact"
        original = admission_module.admit_attempt

        def admit_then_displace(request, boot_id):
            outcome = original(request, boot_id)
            source.rename(displaced)
            return outcome

        with mock.patch.object(
            admission_module, "admit_attempt", side_effect=admit_then_displace
        ), self.assertRaisesRegex(
            RenderAdmissionError, "unavailable during admission"
        ):
            admit_render_artifact(self._metadata(), artifact, "boot-a")
        outcome = admission_module.resolve_attempt(
            str(self.authority), ATTEMPT, "boot-a"
        )
        self.assertEqual(outcome.terminal_manifest["disposition"], "BLOCKED")
        self.assertEqual(
            outcome.terminal_manifest["result"]["errorCode"],
            "RENDER_ARTIFACT_UNAVAILABLE",
        )

    def test_generic_wrong_build_admission_is_rejected_on_resolution(
        self,
    ) -> None:
        artifact = self._artifact()
        request = AdmissionRequest(
            str(self.authority),
            "authority-mp4-v1",
            KEY,
            artifact.artifact_digest,
            ATTEMPT,
            UNIT,
            "2026-07-19T12:00:00+00:00",
            "release-test",
            "0" * 64,
            "policy-test",
            None,
        )
        admit_attempt(request, "boot-a")
        reference = AdmittedRenderRef(str(self.authority), ATTEMPT)
        with self.assertRaisesRegex(RenderAdmissionError, "build"):
            load_admitted_render(reference, "boot-a")

    def test_unadmitted_cross_authority_and_wrong_boot_reject(self) -> None:
        reference = AdmittedRenderRef(str(self.authority), ATTEMPT)
        with self.assertRaises(AdmissionError):
            load_admitted_render(reference, "boot-a")
        artifact = self._artifact()
        admit_render_artifact(self._metadata(), artifact, "boot-a")
        other = self._authority("other")
        with self.assertRaises(AdmissionError):
            load_admitted_render(
                AdmittedRenderRef(str(other), ATTEMPT), "boot-a"
            )
        resolved = load_admitted_render(reference, "boot-b")
        self.assertEqual(resolved.admission.trace_state.boot_id, "boot-a")

    def test_load_uses_retained_source_and_not_live_templates(self) -> None:
        artifact = self._artifact()
        admit_render_artifact(self._metadata(), artifact, "boot-a")
        with mock.patch(
            "headless.overlay_source_seal._read_composition",
            side_effect=AssertionError("live source read"),
        ):
            resolved = load_admitted_render(
                AdmittedRenderRef(str(self.authority), ATTEMPT), "boot-a"
            )
        self.assertEqual(resolved.artifact.overlays[0].overlay_id, "overlay-1")

    def test_lookup_rejects_wrong_filenames_and_unknown_entries(self) -> None:
        for index, attack in enumerate(("filename", "unknown")):
            with self.subTest(attack=attack):
                authority = self._authority(f"records-{index}")
                request = AdmissionRequest(
                    str(authority),
                    "authority-mp4-v1",
                    KEY,
                    hashlib.sha256(b"request").hexdigest(),
                    ATTEMPT,
                    UNIT,
                    "2026-07-19T12:00:00+00:00",
                    "release-test",
                    "build-test",
                    "policy-test",
                    None,
                )
                admit(request)
                admissions = authority / "admissions"
                if attack == "filename":
                    record = next(admissions.glob("*.json"))
                    record.rename(admissions / "wrong.json")
                else:
                    extra = admissions / "unexpected"
                    extra.write_bytes(b"x")
                    os.chmod(extra, 0o600)
                with self.assertRaises(AdmissionError):
                    locate_admission(str(authority), ATTEMPT)
                with self.assertRaises(AdmissionError):
                    admit(request)


if __name__ == "__main__":
    unittest.main(verbosity=2)
