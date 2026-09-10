"""Actual TEST metadata; runtime admission and Docker leaves are explicit stubs.

The executable and approval are inert TEST artifacts, not installed-tool or
image admission. Real claim/runtime metadata checks, cold reads and coordinator
logic run. The socket is a regular TEST token, with socket-role classification
and full original runtime admission stubbed. No socket or daemon is opened.
"""
from __future__ import annotations

import hashlib
import tempfile
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from unittest.mock import Mock, patch

from _source_color_reservation_fixture import SourceColorReservationFixture
from _source_color_staging_read_fixture import _raw
from cut_preview_io import digest
from guided_opening_cleanup import cleanup
from guided_source_color_cleanup_execution import SourceColorCleanupRequest
import guided_source_color_cleanup_execution as execution
from headless import grade_batch_cleanup as batch


class SourceColorCleanupExecutionFixture:
    """One independently allocated TEST root and unchanged virtual cleanup clock."""

    def __init__(self, orders: tuple[int, ...] = ()) -> None:
        """Create bounded inert control metadata before any read or original hold."""
        temporary = partial(tempfile.TemporaryDirectory, dir="/private/tmp")
        with patch("_source_color_staging_read_fixture.tempfile.TemporaryDirectory", temporary):
            self.base = SourceColorReservationFixture()
        self.root, self.now = self.base.root, 1000.0
        self.stack, self.events, self.present = ExitStack(), [], set()
        self.before_inspect, self.before_remove = Mock(), Mock()
        self._controls()
        self.base.staging.claim["selectedGraphicOrders"] = list(orders)
        self.base.staging.documents["frameBindings"]["graphics"] = [{"order": order, "startFrame": 0} for order in orders]
        self._documents()
        self.base.refresh()
        self.output = Path(self.base.staging.claim["outputRoot"])
        self.output.mkdir(mode=0o700)
        self.paths = (self.base.input_path, self.output)
        self.refs = (self.base.context.opening.value["inputSha256"], self.base.claim_path, self.base.context.opening.sha256)
        self.request = SourceColorCleanupRequest(*self.base.reference, self.base.context.source_color_hash)
        self.names = tuple(row["containerName"] for row in self.base.reservation["jobs"])
        self.runtime = None
        self.stack.enter_context(patch.object(batch.time, "monotonic", side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(batch.time, "sleep", side_effect=self.sleep))
        self.stack.enter_context(patch.object(batch, "_is_absent", side_effect=self.inspect))
        self.stack.enter_context(patch.object(batch, "_force_remove", side_effect=self.remove))
        control = execution._control
        self.stack.enter_context(patch.object(execution, "_control", side_effect=lambda path, socket=False:
                                              (str(path), socket, *control(path, False)[2:])))
        self.admission = self.stack.enter_context(patch("guided_opening_claim.verify_claim_runtime"))
        self.final_admission = self.stack.enter_context(patch.object(execution, "verify_runtime_controls"))
        self.stack.enter_context(patch("subprocess.Popen", side_effect=AssertionError("TEST forbids actual process creation")))

    def _controls(self) -> None:
        """Use exact inert socket-token bytes; actual socket/runtime admission is stubbed."""
        snapshot = self.root / "snapshot"
        self.docker = self.root / "TEST-inert-docker"
        self.approval = snapshot / "scripts/producer/headless/render_image_approval.json"
        self.socket_path = self.root / "TEST-daemon.sock"
        self.base.staging.allowed |= frozenset((self.docker, self.approval, self.socket_path))
        image = "sha256:" + "a" * 64
        docker_sha = self.base.staging.write(self.docker, b"TEST NOT AN EXECUTABLE IMPLEMENTATION\n")
        self.docker.chmod(0o700)
        approval_sha = self.base.staging.write(self.approval, _raw({"schemaVersion": 1, "imageId": image, "TEST": True}))
        self.base.staging.write(self.socket_path, b"TEST socket identity token, not a daemon\n")
        info = self.socket_path.lstat()
        controls = {"dockerPath": str(self.docker), "dockerSha256": docker_sha, "dockerSocketPath": str(self.socket_path),
                    "dockerSocketDevice": str(info.st_dev), "dockerSocketInode": str(info.st_ino), "imageId": image,
                    "userId": "501:20", "imageApprovalPath": str(self.approval), "imageApprovalSha256": approval_sha,
                    "runtimeRepoRoot": str(snapshot)}
        self.base.staging.reservation["runtime"] = controls
        self.base.staging.claim["runtime"] = dict(controls)
        self.base.staging.input["pipeline"] = {"snapshotRoot": str(snapshot)}

    def _documents(self) -> None:
        """Publish only actual clock/order metadata, not a full fourteen-document intake."""
        original = self.base.staging
        for name in ("authority", "frameBindings"):
            path = Path(original.input["documents"][name]["path"])
            original.allowed |= frozenset((path,))
            raw = _raw(original.documents[name])
            original.input["documents"][name]["sha256"] = original.write(path, raw)
        original.input["executionInputHash"] = digest({key: value for key, value in original.input.items() if key != "executionInputHash"})

    def sleep(self, duration: float) -> None:
        """Advance the one original virtual clock without sleeping or renewing it."""
        self.now += duration

    def _native(self, runtime: object, config: str, name: str) -> None:
        """Check exact original object/controls and newly owned private config path."""
        if self.runtime is None:
            self.runtime = runtime
        path = Path(config)
        expected = self.base.staging.claim["runtime"]
        if runtime is not self.runtime or runtime.docker != expected["dockerPath"] or runtime.socket != expected["dockerSocketPath"] \
                or runtime.image_id != expected["imageId"] or runtime.user_id != expected["userId"] \
                or path.parent != self.output or not path.name.startswith("source-color-cleanup-") or name not in self.names:
            raise AssertionError("TEST native leaf differs from original controls/names/config")

    def inspect(self, runtime: object, config: str, name: str) -> bool:
        """Observe one exact virtual name; never contact the fixture socket."""
        self._native(runtime, config, name)
        self.events.append(("inspect", name, self.now))
        self.before_inspect(runtime, config, name)
        return name not in self.present

    def remove(self, runtime: object, config: str, name: str) -> bool:
        """Remove only an entry from a Python set, not any actual resource."""
        self._native(runtime, config, name)
        self.events.append(("remove", name, self.now))
        self.before_remove(runtime, config, name)
        existed = name in self.present
        self.present.discard(name)
        return existed

    def run(self, timeout: float = 30.0) -> dict:
        """Call actual explicit V2 entry using only TEST-authored metadata authority."""
        return cleanup(self.paths, self.refs, timeout, self.request)

    def retained(self) -> tuple[bytes, ...]:
        """Read exact original TEST reservation/claim/input bytes for nondeletion checks."""
        return tuple(path.read_bytes() for path in (self.base.reservation_path, self.base.claim_path, self.base.input_path))

    def mutate_control(self, path: Path) -> None:
        """Mutate only exact fixture-owned regular files, never arbitrary dependencies."""
        if path not in (self.docker, self.approval) or not path.is_relative_to(self.root):
            raise AssertionError("TEST control mutation escaped named fixture files")
        original = path.read_bytes()
        self.base.staging.write(path, original)
        if path == self.docker:
            path.chmod(0o700)
        if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(original).digest():
            raise AssertionError("TEST same-byte mutation changed content")

    def close(self) -> None:
        """Release only virtual patches and this fixture's exact metadata temp tree."""
        self.stack.close()
        self.base.close()
