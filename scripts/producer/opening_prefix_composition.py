"""Bind the prefix oracle to one actual private, picture-only composition.

This is an internal adapter to the existing compositor, not a renderer, worker,
publication route or approval. The caller still owns source/approval authority,
the original job deadline and external process-ledger reconciliation.
"""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, replace
from typing import Callable

from graphics.composite_core import CompositeOptions, composite
from headless.process_runner import ProcessRequest, run_text
from opening_prefix_contract import (
    CompositorPrefixRequest, HeldPrefixInput, PrefixOracleError, PrefixOracleRuntime,
    canonical_hash, validate_request, verify_held_input,
)
from opening_prefix_oracle import verify_compositor_prefix
from opening_prefix_output import HeldPictureDirectory, hold_picture_directory, reserve_picture
from opening_prefix_graphs import freeze_request, proof_header, assert_presenter_graph_proof
from opening_prefix_presenter import (compositor_rate, presenter_for_role, assert_presenter_live,
                                     presenter_observation_records)


@dataclass(frozen=True)
class PrefixCompositionJob:
    """Resolved graph and independently held inputs, plus the caller's clock."""

    request: CompositorPrefixRequest
    runtime: PrefixOracleRuntime
    output_path: str
    remaining: Callable[[], float]


class _CallerDeadline:
    """Never turn an oracle allowance into a new full-program work budget."""

    def __init__(self, remaining: Callable[[], float]) -> None:
        self._remaining = remaining
        self._end = time.monotonic() + self._read()

    def _read(self) -> float:
        value = self._remaining()
        if type(value) not in {int, float} or not math.isfinite(value) or not 0 < value <= 3600:
            raise PrefixOracleError("prefix composition requires an unexpired bounded caller deadline")
        return value

    def remaining(self) -> float:
        """Cap even a faulty increasing callback by its original allowance."""
        value = min(self._read(), self._end - time.monotonic())
        if value <= 0:
            raise PrefixOracleError("prefix composition exceeded its original caller allowance")
        return value


def _command(request: CompositorPrefixRequest, runtime: PrefixOracleRuntime, output: str) -> list[str]:
    """Capture the exact ordinary full-picture command; no alternate encoder."""
    commands = []
    span = None if request.full_clips else (0, request.clock.total_frames)
    composite(request.base.path, list(request.full_clips), output, CompositeOptions(
        eof_pass=True, ffmpeg=runtime.ffmpeg.path, ffprobe=runtime.ffprobe.path,
        command_runner=commands.append, frame_rate=compositor_rate(request),
        frame_range=span, video_only=True,
        caption_tail=request.caption_tail[0] if request.caption_tail is not None else None,
        presenter=presenter_for_role(request, "full")))
    if len(commands) != 1:
        raise PrefixOracleError("prefix composition expected one ordinary compositor command")
    return commands[0]


def _identities(rows: tuple[HeldPrefixInput, ...], deadline: _CallerDeadline) -> tuple:
    return tuple(verify_held_input(row, deadline) for row in rows)


def _execute(command: list[str], runtime: PrefixOracleRuntime, deadline: _CallerDeadline, descriptor: int) -> None:
    """Use the existing owned process runner, byte cap and original remainder."""
    environment = {"LANG": "C", "LC_ALL": "C", "TZ": "UTC", "AV_LOG_FORCE_NOCOLOR": "1"}
    result = run_text(ProcessRequest(tuple(command), "", runtime.working_directory, environment,
        deadline.remaining(), termination_grace_seconds=1, max_output_bytes=1024 * 1024,
        pass_fds=(descriptor,)))
    deadline.remaining()
    if result.returncode:
        raise PrefixOracleError("verified prefix composition failed: " + result.stderr[-1200:])


def _transport_command(command: list[str], descriptor: int) -> list[str]:
    """Keep picture encoding exact; defer faststart to the existing delivery mux.

    FFmpeg's faststart second-pass reopen on fd: shares the reserved descriptor's
    offset and can corrupt the MP4 despite exit0. A private intermediate uses a
    normal end-of-file moov instead; no pixel/codec setting changes or extra encode.
"""
    result = [*command[:-1], "-fd", str(descriptor), "-f", "mp4", "fd:"]
    if result.count("-movflags") != 1 or result[result.index("-movflags") + 1] != "+faststart":
        raise PrefixOracleError("prefix compositor changed its expected MP4 storage policy")
    result[result.index("-movflags") + 1] = "0"
    return result


def _compose(job: PrefixCompositionJob, deadline: _CallerDeadline, directory: HeldPictureDirectory) -> dict:
    """Observe, bind, and encode while the original output directory stays held."""
    started = time.monotonic()
    rows = validate_request(job.request, job.runtime)
    request = freeze_request(job.request)
    rows = validate_request(request, job.runtime)
    identities = _identities(rows, deadline)
    by_path = dict(zip((row.path for row in rows), identities))
    runtime = replace(job.runtime, timeout_seconds=min(job.runtime.timeout_seconds, deadline.remaining()))
    proof = verify_compositor_prefix(request, runtime)
    assert_presenter_graph_proof(request, proof)
    observations = presenter_observation_records(request, runtime, by_path, deadline)
    if request.presenter is not None and proof.get("presenterObservations") != observations["presenterObservations"]:
        raise PrefixOracleError("prefix presenter observation proof differs from the live owner")
    command = _command(request, runtime, str(directory.path))
    normalized = [*command[:-1], "unused-oracle-output.mp4"]
    if canonical_hash(normalized) != proof["comparison"]["fullGraphPrefix"]["sharedCompositorCommandHash"]:
        raise PrefixOracleError("actual full compositor command differs from the proved graph")
    implementation = tuple(HeldPrefixInput(**row) for row in proof["implementation"])
    source_identities = _identities(implementation, deadline)
    if _identities(rows, deadline) != identities:
        raise PrefixOracleError("prefix composition held inventory changed before encode")
    with reserve_picture(directory) as output:
        transport = _transport_command(command, output.descriptor)
        assert_presenter_live(request, runtime, by_path)
        _execute(transport, runtime, deadline, output.descriptor)
        encoded = output.observe(deadline)
    if presenter_observation_records(request, runtime, by_path, deadline) != observations:
        raise PrefixOracleError("prefix presenter observations changed during encode")
    if _identities(rows, deadline) != identities \
            or _identities(implementation, deadline) != source_identities:
        raise PrefixOracleError("prefix composition held inventory changed during encode")
    deadline.remaining()
    directory.assert_current()
    deadline.remaining()
    return {**proof_header(request, composition=True),
        "scope": "executed-graph-bound-picture-not-decoded-output-or-approval",
        "outputPath": str(directory.path), "output": asdict(encoded),
        "executedCommandHash": canonical_hash(transport), "ordinaryPathCommandHash": canonical_hash(command),
        "outputTransport": "exclusively-reserved-held-regular-file-descriptor-mp4",
        "privateMoovPlacement": "end-of-file; faststart belongs to existing final delivery mux",
        "prefixOracle": proof, "elapsedMs": (time.monotonic() - started) * 1000,
        "outputDecoded": False, "audioCompared": False, "deliveryApproved": False,
        "cleanupScope": "owned-runner-local-groups; caller-must-reconcile-external-ledger"}


def compose_verified_prefix(job: PrefixCompositionJob) -> dict:
    """Encode only the graph just proved; return no delivery or creative approval."""
    deadline = _CallerDeadline(job.remaining)
    with hold_picture_directory(job.output_path) as directory:
        return _compose(job, deadline, directory)
