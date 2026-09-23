"""Run one jailed step (a decoder, or the font/SVG inspection) and classify the result.

The launcher (``native_media_jail.py``) confines itself with the generated
Seatbelt profile, then execs the decoder with a kernel memory limit or runs the
inspection. This module writes that profile and the request into a private
directory, starts the launcher through ``process_runner.run_text`` (own session,
bounded output, wall-clock deadline, process-group reap on every interruption,
owned-process ledger), watches the jailed pid's memory and CPU with
``JailWatchdog`` (ceilings that survive exec), and refuses any output that is not
backed by the launcher's attestation for this exact decoder and input.
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
    LAUNCHER, MIN_FFMPEG_MAJOR, NativeMediaRuntime, NativeRuntimeError, required_native_runtime,
)
from headless.native_media_watchdog import JailWatchdog
from headless.process_runner import ProcessDeadlineError, ProcessOutputLimitError, ProcessRequest, run_text

MEMORY_MIB = 768  # same ceiling as the container probe (4K HEVC bound)
INSPECT = "/dev/null"  # DECODER parameter of the inspection step: nothing may be executed
_VERSION = re.compile(r"^ff(?:mpeg|probe) version n?(\d+)\.")
_VERIFIED: dict[str, dict] = {}


class JailRejection(RuntimeError):
    """The jailed step ran and rejected, failed or was killed."""

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
    """Captured output of a step that exited 0, plus the launcher attestation."""

    stdout: str | bytes
    stderr: str
    attestation: dict


@dataclass(frozen=True)
class _Step:
    decoder: str
    input_path: str
    limits: JailLimits
    inspect_limits: dict | None = None


def _write_request(directory: str, runtime: NativeMediaRuntime, step: _Step) -> str:
    """Write the generated profile and the launcher request (paths are parameters)."""
    profile = os.path.join(directory, "jail.sb")
    with open(profile, "x", encoding="utf-8") as handle:
        handle.write(runtime.profile_text)
    request = {"profilePath": profile, "profileSha256": runtime.identity["profileSha256"],
               "mode": "inspect" if step.decoder == INSPECT else "exec",
               "memoryMiB": step.limits.memory_mib, "cpuSeconds": step.limits.cpu_seconds,
               "wallSeconds": step.limits.wall_seconds, "limits": step.inspect_limits or {},
               "inputPath": step.input_path,  # the spelling the receipt names; attested as "input"
               "parameters": {"DECODER": step.decoder, "INPUT": os.path.realpath(step.input_path)}}
    path = os.path.join(directory, "jail-request.json")
    with open(path, "x", encoding="utf-8") as handle:
        json.dump(request, handle, sort_keys=True)
    return path


def _read_attestation(descriptor: int) -> dict | None:
    """Parse the one-line attestation the launcher wrote before exec."""
    raw = os.pread(descriptor, 65536, 0)
    try:
        value = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _classify(returncode: int, stderr: str, watchdog: JailWatchdog) -> JailRejection:
    """Name a nonzero exit the way the container probe named its failures."""
    if watchdog.exceeded:
        return JailRejection(watchdog.exceeded, f"killed by the supervisor watchdog (peak {watchdog.peak_bytes >> 20} MiB)")
    if returncode < 0:
        name = signal.Signals(-returncode).name
        if name == "SIGKILL":
            return JailRejection("MEMORY_LIMIT", f"killed (SIGKILL): kernel memory limit {MEMORY_MIB} MiB or external kill")
        if name in ("SIGXCPU", "SIGALRM"):
            return JailRejection("CPU_LIMIT" if name == "SIGXCPU" else "DECODE_TIMEOUT", f"stopped by {name}")
        return JailRejection(f"DECODER_SIGNAL_{name}", stderr.strip()[-400:])
    if returncode in (64, 70, 71, 72) and stderr.startswith("native-media-jail:"):
        return JailRejection("JAIL_UNAVAILABLE", stderr.strip()[-400:])
    return JailRejection(f"DECODER_EXIT_{returncode}", stderr.strip()[-400:])


def _attested(attestation: dict | None, runtime: NativeMediaRuntime, step: _Step) -> dict:
    """Refuse output unless the launcher proved it confined itself for this decoder and input."""
    valid = (isinstance(attestation, dict) and attestation.get("sandboxed") is True
             and attestation.get("decoder") == step.decoder and attestation.get("input") == step.input_path
             and attestation.get("mode") == ("inspect" if step.decoder == INSPECT else "exec")
             and attestation.get("profileSha256") == runtime.identity["profileSha256"]
             and attestation.get("memoryMiB") == step.limits.memory_mib
             and (attestation.get("rlimits") or {}).get("RLIMIT_FSIZE") == [0, 0])
    if not valid:
        raise JailRejection("JAIL_UNATTESTED", "the launcher did not attest its confinement")
    return attestation


def _launch(runtime: NativeMediaRuntime, step: _Step, arguments: tuple[str, ...]):
    """Start the launcher under the watchdog; return the completed process, attestation and watchdog."""
    with tempfile.TemporaryDirectory(prefix=".sniper-media-jail-") as directory:
        os.chmod(directory, 0o700)
        request = _write_request(directory, runtime, step)
        descriptor = os.open(os.path.join(directory, "attestation"), os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        watchdog = JailWatchdog(descriptor, step.limits.memory_mib * 1024 * 1024, step.limits.cpu_seconds)
        watchdog.start()
        try:
            command = (sys.executable, "-I", "-S", "-B", str(LAUNCHER), request, str(descriptor), "--", *arguments)
            env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC"}
            done = run_text(ProcessRequest(command, "", directory, env, step.limits.wall_seconds,
                                           max_output_bytes=step.limits.max_output_bytes, pass_fds=(descriptor,),
                                           decode_output=not step.limits.binary_stdout))
            return done, _read_attestation(descriptor), watchdog
        except ProcessDeadlineError as error:
            raise JailRejection("DECODE_TIMEOUT", f"exceeded {step.limits.wall_seconds:g} s") from error
        except ProcessOutputLimitError as error:
            raise JailRejection("OUTPUT_LIMIT", "decoder output exceeded its bound") from error
        except UnicodeDecodeError as error:
            raise JailRejection("DECODER_OUTPUT", "decoder output is not UTF-8") from error
        finally:
            watchdog.stop()
            os.close(descriptor)


def _run(runtime: NativeMediaRuntime, step: _Step, arguments: tuple[str, ...]) -> JailResult:
    done, attestation, watchdog = _launch(runtime, step, arguments)
    stderr = done.stderr.decode("utf-8", "replace") if isinstance(done.stderr, bytes) else done.stderr
    if done.returncode != 0 or watchdog.exceeded:
        raise _classify(done.returncode, stderr, watchdog)
    return JailResult(done.stdout, stderr, _attested(attestation, runtime, step))


def run_decoder(runtime: NativeMediaRuntime, decoder: str, arguments: tuple[str, ...],
                spec: tuple[str, JailLimits]) -> JailResult:
    """Run ``decoder arguments`` confined to reading ``spec[0]``; raise on any failure.

    Seatbelt checks the spelling a process opens as well as the resolved file, so
    an argument naming the input is replaced by its resolved path (a project under
    a symlinked folder, e.g. /var -> /private/var, would otherwise be unreadable).
    """
    if decoder not in (runtime.ffprobe, runtime.ffmpeg):
        raise NativeRuntimeError("only the identified decoders may run in the jail")
    resolved = os.path.realpath(spec[0])
    argv = tuple(resolved if argument == spec[0] else argument for argument in arguments)
    return _run(runtime, _Step(decoder, spec[0], spec[1]), (decoder, *argv))


def run_inspect(runtime: NativeMediaRuntime, input_path: str, limits: dict) -> tuple[dict, dict]:
    """Font/SVG recognition of ``input_path`` inside the jail: (result, attestation)."""
    done = _run(runtime, _Step(INSPECT, input_path, JailLimits(30, 20), limits), ("inspect",))
    try:
        return json.loads(done.stdout), done.attestation
    except json.JSONDecodeError as error:
        raise JailRejection("INSPECT_OUTPUT", "inspection output is not JSON") from error


def verified_runtime() -> NativeMediaRuntime:
    """Identify the runtime and prove both decoders start inside the jail."""
    runtime = required_native_runtime()
    cached = _VERIFIED.get(runtime.identity["profileSha256"])
    if cached is None:
        versions = {}
        for name, path in (("ffprobe", runtime.ffprobe), ("ffmpeg", runtime.ffmpeg)):
            done = run_decoder(runtime, path, ("-hide_banner", "-version"), ("/dev/null", JailLimits(30, 10)))
            line = done.stdout.splitlines()[0] if done.stdout else ""
            match = _VERSION.match(line)
            if not match or int(match.group(1)) < MIN_FFMPEG_MAJOR:
                raise NativeRuntimeError(f"{name} {line or 'unknown'} is older than {MIN_FFMPEG_MAJOR}.0")
            versions[name] = line[:200]
        cached = _VERIFIED[runtime.identity["profileSha256"]] = versions
    for name, line in cached.items():
        runtime.identity["tools"][name]["version"] = line
    return runtime
