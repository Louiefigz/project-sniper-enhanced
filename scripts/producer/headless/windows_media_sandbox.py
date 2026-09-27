"""Bounded supervisor for one Windows AppContainer media-jail invocation."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace


@dataclass
class WindowsWatchdog:
    """Compatibility object consumed by native_media_sandbox's classifier."""

    exceeded: str = ""
    peak_bytes: int = 0


_ENVIRONMENT_NAMES = (
    "ALLUSERSPROFILE", "APPDATA", "CommonProgramFiles", "CommonProgramFiles(x86)", "CommonProgramW6432",
    "ComSpec", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "NUMBER_OF_PROCESSORS", "OS", "PATHEXT",
    "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL", "PROCESSOR_REVISION", "ProgramData",
    "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "PUBLIC", "SystemDrive", "SystemRoot", "TEMP", "TMP",
    "USERDOMAIN", "USERDOMAIN_ROAMINGPROFILE", "USERNAME", "USERPROFILE", "WINDIR",
)


def _child_environment() -> dict[str, str]:
    """Non-secret Windows variables needed to initialize an AppContainer process."""
    environment = {name: os.environ[name] for name in _ENVIRONMENT_NAMES if name in os.environ}
    system_root = environment.get("SystemRoot") or environment.get("WINDIR")
    if system_root:
        environment["PATH"] = str(Path(system_root) / "System32")
    return environment


def _reader(stream, parts: list[bytes], state: dict, bound: int) -> None:
    """Drain one pipe while enforcing a shared stdout+stderr byte ceiling."""
    while block := stream.read(65536):
        with state["lock"]:
            state["size"] += len(block)
            if state["size"] > bound:
                state["overflow"] = True
                return
        parts.append(block)


def _command(runtime, step, arguments: tuple[str, ...], attest: str) -> list[str]:
    """Helper arguments and the exact AppContainer child command."""
    helper = runtime.identity["launcher"]["path"]
    common = [helper, "run", step.input_path, attest, str(step.limits.memory_mib * 1024 * 1024),
              str(step.limits.cpu_seconds), str(max(1, int(step.limits.wall_seconds))),
              runtime.identity["profileSha256"], step.decoder,
              "inspect" if step.inspect_limits is not None else "exec", "--"]
    if step.inspect_limits is None:
        return [*common, *arguments]
    limits = step.inspect_limits
    inspector = runtime.identity["inspector"]["path"]
    return [*common, inspector, step.input_path, str(limits["maxBytes"]),
            str(limits["maxWidth"]), str(limits["maxHeight"])]


def launch(runtime, step, arguments: tuple[str, ...]):
    """Return completed-process, attestation and watchdog with bounded captured output."""
    with tempfile.TemporaryDirectory(prefix="sniper-windows-jail-") as directory:
        attest = str(Path(directory) / "attestation.json")
        process = subprocess.Popen(_command(runtime, step, arguments, attest), cwd=directory,
                                   env=_child_environment(), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out: list[bytes] = []
        err: list[bytes] = []
        state = {"lock": threading.Lock(), "size": 0, "overflow": False}
        threads = [threading.Thread(target=_reader, args=(stream, parts, state, step.limits.max_output_bytes),
                                    daemon=True) for stream, parts in ((process.stdout, out), (process.stderr, err))]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + step.limits.wall_seconds + 5
        timed_out = False
        while process.poll() is None and not state["overflow"]:
            if time.monotonic() >= deadline:
                timed_out = True
                break
            time.sleep(0.02)
        if timed_out or state["overflow"]:
            process.kill()
        process.wait(timeout=10)
        for thread in threads:
            thread.join(timeout=2)
        stdout, stderr = b"".join(out), b"".join(err)
        if timed_out:
            raise TimeoutError(f"exceeded {step.limits.wall_seconds:g} s")
        if state["overflow"]:
            raise BufferError("decoder output exceeded its bound")
        try:
            attestation = json.loads(Path(attest).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            attestation = None
        watchdog = WindowsWatchdog("MEMORY_LIMIT" if process.returncode == 137 else "")
        if not step.limits.binary_stdout:
            stdout = stdout.decode("utf-8")
        done = SimpleNamespace(returncode=process.returncode, stdout=stdout,
                               stderr=stderr.decode("utf-8", "replace"))
        return done, attestation, watchdog
