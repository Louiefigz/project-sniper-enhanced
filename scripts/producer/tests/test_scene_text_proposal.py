"""Installed SDK command integration; no render, server, source media or approval."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from graphics import scene_package_cli, scene_text_proposal
from graphics.scene_bundle import promote_bundle
from graphics.scene_contract import canonical_json
from headless.process_runner import ProcessRequest
from studio import studio_review
from tests.scene_fixtures import bind_test_scene_source, fire_sparkles_scene

_BUNDLE = Path(__file__).parent / "fixtures/fire-sparkles-bundle"


def _hash(value: object) -> str:
    """Use the documented canonical JSON expectation domain."""
    return hashlib.sha256(canonical_json(value)).hexdigest()


class SceneTextProposalTests(unittest.TestCase):
    """Every writable target is a new exact TEMP fixture file, never repository source."""

    def setUp(self) -> None:
        """Publish genuine immutable bundle metadata and explicit supplied state."""
        temporary = tempfile.TemporaryDirectory(prefix="sdk text $() ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.store = self.root / "bundles"
        self.store.mkdir()
        bundle = promote_bundle(str(_BUNDLE.resolve()), str(self.store), select_current=False)
        self.scene = fire_sparkles_scene(bundle.digest)
        self.package = {"schemaVersion": 1, "scene": self.scene,
                        "publicationContext": {"use": "commercial", "platform": "youtube",
                                               "evaluatedAt": "2026-09-08T12:00:00Z"},
                        "assets": [], "readability": {"required": False,
                        "sourceSha256": None, "receipt": None}}
        other = copy.deepcopy(self.scene)
        other["sceneId"] = "scene-unchanged"
        bind_test_scene_source(other)
        self.state = {"plan": {"cutTrack": [{"sourceId": "source-main", "srcStart": 0,
                                          "srcEnd": 60}], "music": {"enabled": False}},
                      "scenes": [self.scene, other], "fps": {"numerator": "30", "denominator": "1"},
                      "total_frames": 1800}
        self.package_path = self._new("package.json", self.package)
        self.state_path = self._new("state.json", self.state)
        self.args = ["propose-text", str(self.package_path), "--bundle-store", str(self.store),
                     "--state", str(self.state_path), "--expected-package-hash", _hash(self.package),
                     "--expected-state-hash", _hash(self.state), "--unit-id", "unit-right",
                     "--element-id", "right-copy", "--variable", "rightTitle", "--expected-text",
                     "Change only this card", "--text", "Keep the original footage until the export passes review",
                     "--expected-scene-version", "1"]

    def _new(self, name: str, value: dict) -> Path:
        """Create one new canonical fixture record without overwriting another file."""
        path = self.root / name
        with path.open("xb") as handle:
            handle.write(canonical_json(value))
        return path

    def _replace_state(self, value: dict) -> None:
        """Fault only the explicitly named owned TEMP state, never a dependency path."""
        path = self.root / "state.json"
        self.assertEqual(path, self.state_path)
        self.assertEqual(path.resolve(), path)
        self.assertTrue(path.is_file())
        self.assertEqual(path.stat().st_nlink, 1)
        path.write_bytes(canonical_json(value))

    def _args(self, option: str, value: str) -> list[str]:
        """Change one literal CLI option without shell interpolation."""
        args = list(self.args)
        args[args.index(option) + 1] = value
        return args

    def _files(self) -> dict[str, bytes]:
        """Observe only this fixture tree, including original immutable bundle bytes."""
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def test_actual_installed_sdk_and_handler_return_unapplied_one_unit_proposal(self) -> None:
        """Real command creates no state/HTML/receipt files and preserves all other fields."""
        before = self._files()
        result = scene_package_cli.run(self.args)
        self.assertEqual(self._files(), before)
        self.assertEqual(result["kind"], "scene-text-proposal")
        self.assertTrue(result["proposalOnly"])
        self.assertTrue(result["suppliedBindingsOnly"])
        self.assertFalse(result["applied"] or result["approved"] or result["renderVerified"])
        self.assertEqual(result["originalStateHash"], _hash(self.state))
        expected = copy.deepcopy(self.scene)
        expected["version"] = 2
        text = self.args[self.args.index("--text") + 1]
        expected["composition"]["variables"]["rightTitle"] = text
        expected["elements"][2]["values"]["rightTitle"] = text
        bind_test_scene_source(expected)
        self.assertEqual(result["candidateScene"], expected)
        self.assertEqual(result["operationReceipt"]["invalidatedNodes"], [
            "composite:scene-045", "palmier-binding:scene-045:unit-right",
            "scene-unit-media:scene-045:unit-right"])
        self.assertEqual(result["operationReceipt"]["dirtyWindows"], [
            {"startFrame": 1350, "endFrameExclusive": 1530}])

    def test_studio_alias_uses_real_package_sdk_and_handler_without_server_or_render(self) -> None:
        """The existing Codex surface does not require a synthetic producer directory."""
        before, output = self._files(), io.StringIO()
        with contextlib.redirect_stdout(output), mock.patch.object(studio_review, "cmd_open") as opened:
            self.assertEqual(studio_review.main(self.args), 0)
        opened.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["operation"]["operation"], "title.setText")
        self.assertEqual(self._files(), before)

    def test_stale_hash_text_version_unit_and_unexposed_target_refuse_before_sdk(self) -> None:
        """Hash and original semantic preconditions cannot be refreshed by the command."""
        changes = [("--expected-state-hash", "0" * 64), ("--expected-package-hash", "0" * 64),
                   ("--expected-text", "stale text"), ("--expected-scene-version", "2"),
                   ("--unit-id", "unit-left"), ("--element-id", "unknown-element"),
                   ("--variable", "unexposed")]
        for option, value in changes:
            with mock.patch.object(scene_text_proposal, "run_text") as child, \
                    self.subTest(option=option), self.assertRaises(ValueError):
                scene_package_cli.run(self._args(option, value))
            child.assert_not_called()

    def test_state_must_contain_exact_package_scene_and_original_clock(self) -> None:
        """A matching supplied hash never excuses a wrong original scene or timing."""
        variants = []
        for field, value in [("extra", True), ("total_frames", True), ("total_frames", 10)]:
            changed = copy.deepcopy(self.state)
            changed[field] = value
            variants.append(changed)
        different = copy.deepcopy(self.state)
        different["scenes"][0]["composition"]["variables"]["rightTitle"] = "Different"
        variants.append(different)
        duplicate = copy.deepcopy(self.state)
        duplicate["scenes"].append(copy.deepcopy(duplicate["scenes"][0]))
        variants.append(duplicate)
        for changed in variants:
            self._replace_state(changed)
            with mock.patch.object(scene_text_proposal, "run_text") as child, self.assertRaises(ValueError):
                scene_package_cli.run(self._args("--expected-state-hash", _hash(changed)))
            child.assert_not_called()

    def test_late_original_state_change_refuses_after_actual_sdk(self) -> None:
        """A successful SDK parse does not rebaseline the caller's changed state."""
        original = scene_text_proposal.run_text

        def changed(request: ProcessRequest) -> subprocess.CompletedProcess:
            """Change only the original TEMP state after the actual SDK has returned."""
            result = original(request)
            value = copy.deepcopy(self.state)
            value["plan"]["music"]["enabled"] = True
            self._replace_state(value)
            return result

        with mock.patch.object(scene_text_proposal, "run_text", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed during"):
                scene_package_cli.run(self.args)

    def test_sdk_output_cannot_change_operation_or_claim_application(self) -> None:
        """Only exact closed operation and false approval/application flags can pass."""
        bad = [{}, {"applied": True}, {"operation": "scene.remove"}, {"value": float("nan")}]
        for value in bad:
            returned = subprocess.CompletedProcess([], 0, json.dumps(value), "")
            with mock.patch.object(scene_text_proposal, "run_text", return_value=returned), self.assertRaises(ValueError):
                scene_package_cli.run(self.args)

    def test_request_is_exact_private_temp_file_with_empty_stdin_and_bounded_output(self) -> None:
        """Production transport is installed Node/SDK only, with no caller factory or preload."""
        original = scene_text_proposal.run_text
        paths = []

        def inspect(request: ProcessRequest) -> subprocess.CompletedProcess:
            """Observe the real child request without substituting its native-free behavior."""
            path = Path(request.command[2])
            paths.append(path)
            raw = path.read_bytes()
            self.assertEqual(request.stdin_text, "")
            self.assertEqual(request.max_output_bytes, 64 * 1024)
            self.assertEqual(request.timeout_seconds, 30)
            self.assertEqual(request.command[3:], (hashlib.sha256(raw).hexdigest(), str(len(raw))))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("NODE_OPTIONS", request.environment)
            self.assertNotIn("factory", json.loads(raw))
            return original(request)

        with mock.patch.object(scene_text_proposal, "run_text", side_effect=inspect):
            scene_package_cli.run(self.args)
        self.assertTrue(paths)
        self.assertTrue(all(not path.exists() for path in paths))

    def test_oversized_input_refuses_before_child_and_failure_removes_only_request_temp(self) -> None:
        """No unbounded input or leaked temporary protocol file follows child refusal."""
        with mock.patch.object(scene_text_proposal, "run_text") as child, self.assertRaisesRegex(ValueError, "1 MiB"):
            scene_text_proposal._sdk({"html": "x" * (1024 * 1024 + 1)})
        child.assert_not_called()
        paths = []

        def failed(request: ProcessRequest) -> subprocess.CompletedProcess:
            """Record the exact temporary request path before an explicit TEST failure."""
            paths.append(Path(request.command[2]))
            raise RuntimeError("TEST child failure")

        with mock.patch.object(scene_text_proposal, "run_text", side_effect=failed), self.assertRaisesRegex(RuntimeError, "TEST child"):
            scene_package_cli.run(self.args)
        self.assertTrue(paths)
        self.assertTrue(all(not path.exists() for path in paths))

    def test_actual_node_entry_rejects_wrong_sha_size_and_symlink(self) -> None:
        """The real command refuses malformed exact TEMP references without SDK edits."""
        path = self._new("sdk-request.json", {"TEST": "not a valid SDK input"})
        raw = path.read_bytes()
        link = self.root / "sdk-link.json"
        link.symlink_to(path)
        node = scene_text_proposal.shutil.which("node")
        bad = [(str(path), "0" * 64, str(len(raw))),
               (str(path), hashlib.sha256(raw).hexdigest(), "1048577"),
               (str(link), hashlib.sha256(raw).hexdigest(), str(len(raw)))]
        for reference in bad:
            result = scene_text_proposal.run_text(ProcessRequest(
                (str(Path(node).resolve()), str(scene_text_proposal._SDK), *reference),
                "", str(scene_text_proposal._ROOT), {"LANG": "C.UTF-8"},
                10, max_output_bytes=64 * 1024))
            self.assertEqual(result.returncode, 65)
            self.assertEqual(result.stdout, "")
        self.assertEqual(path.read_bytes(), raw)

    def test_help_discloses_supplied_state_and_no_apply_and_rejects_receipt_output(self) -> None:
        """Both entry points expose the same narrow proposal, not a save/apply service."""
        for function in (scene_package_cli.run, studio_review.main):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
                function(["propose-text", "--help"])
            self.assertIn("caller-supplied", output.getvalue())
            self.assertIn("no apply", output.getvalue())
        with self.assertRaisesRegex(ValueError, "unrecognized arguments"):
            scene_package_cli.run([*self.args, "--receipt-out", str(self.root / "not-written.json")])
        self.assertFalse((self.root / "not-written.json").exists())


if __name__ == "__main__":
    unittest.main()
