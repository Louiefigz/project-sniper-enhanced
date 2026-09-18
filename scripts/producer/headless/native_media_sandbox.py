"""Run one decoder command inside the native admission jail and classify the result.

The launcher (``native_media_jail.py``) confines itself with the approved
Seatbelt profile and execs the decoder with a kernel memory limit. This module
starts it through ``process_runner.run_text`` (own session, bounded output,
wall-clock deadline, process-group reap on every interruption, owned-process
ledger), then requires the launcher's attestation before trusting any output.
"""
from __future__ import annotations

import json
import os
import re
import signal
import sys
import tempfile
from dataclasses import dataclass

from headless.native_media_runtime import (
    LAUNCHER, MIN_FFMPEG_MAJOR, PROFILE, NativeMediaRuntime, NativeRuntimeError, required_native_runtime,
)
from headless.process_runner import ProcessDeadlineError, ProcessOutputLimitError, ProcessRequest, run_text

MEMORY_MIB = 768  # same ceiling as the container probe (4K HEVC bound)
_VERSION = re.compile(r"^ff(?:mpeg|probe) version n?(\d+)\.")
_VERIFIED: dict[str, dict] = {}


class JailRejection(RuntimeError):
    """The decoder ran in the jail and rejected, failed or was killed."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}".rstrip(": "))
        self.code = code


@dataclass(frozen=True)
class JailLimits:
    """Per-invocation ceilings."""

    wall_seconds: float
    cpu_seconds: int
    max_output_bytes: int = 1024 * 1024
    memory_mib: int = MEMORY_MIB
    binary_stdout: bool = False  # raw bytes on stdout (frames); stderr is decoded leniently


@dataclass(frozen=True)
class JailResult:
    """Captured output of a decoder that exited 0, plus the launcher attestation."""

    stdout: str | bytes
    stderr: str
    attestation: dict


def _request_file(directory: str, runtime: NativeMediaRuntime, decoder: str, spec: tuple[str, JailLimits]) -> str:
    """Write the launcher request (parameters are data, never profile text)."""
    input_path, limits = spec
    request = {"profilePath": str(PROFILE), "profileSha256": runtime.identity["profileSha256"],
               "memoryMiB": limits.memory_mib, "cpuSeconds": limits.cpu_seconds,
               "parameters": {"DECODER": decoder, "LIBROOT": runtime.library_root,
                              "LINKROOT": runtime.link_root, "INPUT": input_path}}
    path = os.path.join(directory, "jail-request.json")
    with open(path, "x", encoding="utf-8") as handle:
        json.dump(request, handle, sort_keys=True)
    return path


def _read_attestation(descriptor: int) -> dict | None:
    """Parse the one-line attestation the launcher wrote before exec."""
    os.lseek(descriptor, 0, os.SEEK_SET)
    raw = os.read(descriptor, 65536)
    if not raw:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _classify(returncode: int, stderr: str) -> JailRejection:
    """Name a nonzero exit the way the container probe named its failures."""
    if returncode < 0:
        name = signal.Signals(-returncode).name
        if name == "SIGKILL":
            return JailRejection("MEMORY_LIMIT", f"decoder was killed (SIGKILL): memory above {MEMORY_MIB} MiB "
                                 "or an external kill")
        if name in ("SIGXCPU",):
            return JailRejection("CPU_LIMIT", "decoder exceeded its CPU-time ceiling")
        return JailRejection(f"DECODER_SIGNAL_{name}", stderr.strip()[-400:])
    if returncode in (64, 70, 71, 72) and stderr.startswith("native-media-jail:"):
        return JailRejection("JAIL_UNAVAILABLE", stderr.strip()[-400:])
    return JailRejection(f"DECODER_EXIT_{returncode}", stderr.strip()[-400:])


def _attested(attestation: dict | None, runtime: NativeMediaRuntime, decoder: str, limits: JailLimits) -> dict:
    """Refuse output unless the launcher proved it confined itself first."""
    valid = (isinstance(attestation, dict) and attestation.get("sandboxed") is True
             and attestation.get("decoder") == decoder
             and attestation.get("profileSha256") == runtime.identity["profileSha256"]
             and attestation.get("memoryMiB") == limits.memory_mib
             and (attestation.get("rlimits") or {}).get("RLIMIT_FSIZE") == [0, 0])
    if not valid:
        raise JailRejection("JAIL_UNATTESTED", "the launcher did not attest its confinement")
    return attestation


def run_decoder(runtime: NativeMediaRuntime, decoder: str, arguments: tuple[str, ...],
                spec: tuple[str, JailLimits]) -> JailResult:
    """Run ``decoder arguments`` confined to reading ``spec[0]``; raise on any failure."""
    input_path, limits = spec
    if decoder not in (runtime.ffprobe, runtime.ffmpeg):
        raise NativeRuntimeError("only the identified decoders may run in the jail")
    with tempfile.TemporaryDirectory(prefix=".sniper-media-jail-") as directory:
        os.chmod(directory, 0o700)
        request = _request_file(directory, runtime, decoder, (input_path, limits))
        descriptor = os.open(os.path.join(directory, "attestation"), os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            command = (sys.executable, "-I", "-S", "-B", str(LAUNCHER), request, str(descriptor), "--",
                       decoder, *arguments)
            env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC"}
            try:
                done = run_text(ProcessRequest(command, "", directory, env, limits.wall_seconds,
                                               max_output_bytes=limits.max_output_bytes, pass_fds=(descriptor,),
                                               decode_output=not limits.binary_stdout))
            except ProcessDeadlineError as error:
                raise JailRejection("DECODE_TIMEOUT", f"exceeded {limits.wall_seconds:g} s") from error
            except ProcessOutputLimitError as error:
                raise JailRejection("OUTPUT_LIMIT", "decoder output exceeded its bound") from error
            except UnicodeDecodeError as error:
                raise JailRejection("DECODER_OUTPUT", "decoder output is not UTF-8") from error
            attestation = _read_attestation(descriptor)
        finally:
            os.close(descriptor)
    stderr = done.stderr.decode("utf-8", "replace") if isinstance(done.stderr, bytes) else done.stderr
    if done.returncode != 0:
        raise _classify(done.returncode, stderr)
    return JailResult(done.stdout, stderr, _attested(attestation, runtime, decoder, limits))


def verified_runtime() -> NativeMediaRuntime:
    """Identify the runtime and prove both decoders start inside the jail."""
    runtime = required_native_runtime()
    cached = _VERIFIED.get(runtime.identity["closureSha256"])
    if cached is None:
        versions = {}
        for name, path in (("ffprobe", runtime.ffprobe), ("ffmpeg", runtime.ffmpeg)):
            done = run_decoder(runtime, path, ("-hide_banner", "-version"), ("/dev/null", JailLimits(30, 10)))
            line = done.stdout.splitlines()[0] if done.stdout else ""
            match = _VERSION.match(line)
            if not match or int(match.group(1)) < MIN_FFMPEG_MAJOR:
                raise NativeRuntimeError(f"{name} {line or 'unknown'} is older than {MIN_FFMPEG_MAJOR}.0")
            versions[name] = line[:200]
        cached = _VERIFIED[runtime.identity["closureSha256"]] = versions
    for name, line in cached.items():
        runtime.identity["tools"][name]["version"] = line
    return runtime
