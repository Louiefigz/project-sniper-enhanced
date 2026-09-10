"""Probe evidence/publication regressions without launching any renderer."""
from __future__ import annotations

import copy
import json
import tempfile
import time
import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from graphics import comp_capability_artifact as artifact
from graphics import comp_capability_refresh as refresh


class CapabilityRefreshTests(unittest.TestCase):
    def test_only_known_archive_members_are_projected_and_exact_sidecar_is_required(self) -> None:
        """A changed exact TEST sidecar cannot be normalized into proof success."""
        with tempfile.TemporaryDirectory() as temporary:
            sidecar = Path(temporary).resolve() / "proof.json"
            persisted = {"runtimeAttestation": {"retainedInputArchive": {"members": ["a"]}}}
            sidecar.write_text(json.dumps(persisted))
            proof = copy.deepcopy(persisted)
            proof["runtimeAttestation"]["retainedInputArchive"]["members"] = ("a",)
            proof["sidecar"] = str(sidecar)
            rendered = {"proof": proof}
            projected = refresh._render_json(rendered)
            refresh.write_new(sidecar.parent / "result.json", projected)
            self.assertIsInstance(proof["runtimeAttestation"]["retainedInputArchive"]["members"], tuple)
            sidecar.write_text(json.dumps({**persisted, "changed": True}))
            with self.assertRaisesRegex(RuntimeError, "differs from exact persisted"):
                refresh._render_json(rendered)

    def test_complete_synthetic_probe_measure_record_validate_publish_path(self) -> None:
        """Exercise the coordinator with explicit synthetic static/native leaves."""
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary).resolve()
            source = Path(artifact.COMPOSITIONS_DIR, "agenda-slide.html")
            prior = root / "comp_capabilities.json"
            prior.write_bytes(b"old-artifact-must-be-backed-up\n")
            output = root / "attempt"
            output.mkdir()
            runtime = SimpleNamespace(docker="/docker", docker_socket="/socket", image_id="image", user_id="1:1")
            stack.enter_context(patch.object(refresh, "runtime", return_value=runtime))
            stack.enter_context(patch.object(refresh, "MOTION_DIR", str(root)))
            state = {"motionSourceDigest": "synthetic-source", "rootLintValidator": {"TEST": "lint"}}
            stack.enter_context(patch.object(refresh, "source_state", return_value=state))
            lint = {"sourceState": {"motionSourceDigest": "synthetic-source",
                "validator": state["rootLintValidator"], "entries": [{"kind": "agenda-slide"}]}}
            stack.enter_context(patch.object(refresh, "preflight_root_lint", return_value=lint))
            stack.enter_context(patch.object(refresh, "_preflight"))
            stack.enter_context(patch.object(refresh, "composition_paths", return_value=[str(source)]))
            stack.enter_context(patch.object(artifact, "composition_kinds", return_value={"agenda-slide"}))
            for module in (refresh, artifact):
                stack.enter_context(patch.object(module, "current_source_digest", return_value="synthetic-source"))
            stack.enter_context(patch.object(refresh, "container_lease", return_value=nullcontext("owned-test")))
            stack.enter_context(patch.object(refresh, "registered_containers", return_value=()))
            stack.enter_context(patch.object(refresh, "removed_containers", return_value=("owned-test",)))
            stack.enter_context(patch.object(refresh, "render_entry_for_capability_probe", side_effect=synthetic_render))
            stack.enter_context(patch.object(refresh, "_measure_artifact", side_effect=synthetic_measure))
            value = {"probes": []}
            refresh.execute(output, value, time.monotonic(), True)
            self.assertTrue(value["published"])
            self.assertEqual((output / "previous-comp_capabilities.json").read_bytes(), b"old-artifact-must-be-backed-up\n")
            loaded, error = artifact.load_artifact(str(prior))
            self.assertFalse(error)
            self.assertIsNone(artifact.capability_row_issue(loaded["agenda-slide"]))
            self.assertTrue((output / "agenda-slide/actual-render-result.json").is_file())
            self.assertTrue((output / "source-after.json").is_file())

    def test_prior_elapsed_time_is_not_reset_at_probe_boundary(self) -> None:
        """An exhausted original allowance cannot admit another capability probe."""
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError, "safe boundary"):
                refresh.boundary(Path(temporary), {"probes": []}, time.monotonic() - 1501, 53)


def synthetic_render(entry: dict, cache: str, rate: str) -> dict:
    """Synthetic control only, intentionally no decoded-media claim."""
    media = Path(cache) / "synthetic.mov"
    media.write_bytes(b"synthetic-not-media")
    proof = {"asset": {"sha256": refresh.file_hash(media), "frameCount": 75},
        "runtimeAttestation": {"imageId": "image", "containerRemoval": {"canonicalAbsenceProved": True},
            "containerAfterOutput": {"Name": "/owned-test"}, "retainedInputArchive": {"members": ["a"]}}}
    sidecar = Path(str(media) + ".proof.json")
    sidecar.write_text(json.dumps(proof))
    proof["sidecar"] = str(sidecar)
    proof["runtimeAttestation"]["retainedInputArchive"]["members"] = ("a",)
    return {"proof": proof, "path": str(media), "cached": False, "fps": rate}


def synthetic_measure(value: dict, _path: str, _frames: int, _terminal: dict) -> None:
    """Closed known measurement shape, not evidence of any actual render."""
    value.update(terminalAlpha={"maxAlpha8": 255, "meanAlpha8": 255.0}, fadeClass="hold-to-cut",
                 contentBBox=[0, 0, 1919, 1079], contentDims=[1919, 1079])


if __name__ == "__main__":
    unittest.main()
