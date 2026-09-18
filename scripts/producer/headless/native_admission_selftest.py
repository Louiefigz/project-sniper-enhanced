"""Installed-doctor check: real media admission of a generated sample on this Mac.

    python3 -B scripts/producer/headless/native_admission_selftest.py --json

Generates a two-second clip with the install's own ffmpeg, admits it through
the production path (``admit_external_media``), reads the receipt back through
the production readers, then proves the jail is enforced here: a jailed decoder
cannot read another file, cannot open a network connection (a loopback decoy
must see zero connections) and is killed above its memory limit. Prints one
JSON object; exits 0 only when every step passed.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from headless.admission_receipt import validate_admission_receipt  # noqa: E402
from headless.external_media_probe import admit_external_media  # noqa: E402
from headless.native_media_sandbox import JailLimits, JailRejection, run_decoder, verified_runtime  # noqa: E402
from ingest_admission_contract import receipt_snapshot  # noqa: E402


def _sample(runtime, root: Path) -> Path:
    """Two seconds of test picture and tone, made by the trusted host ffmpeg."""
    path = root / "doctor-sample.mp4"
    subprocess.run([runtime.ffmpeg, "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=320x180:rate=30:duration=2", "-f", "lavfi", "-i", "sine=duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
                   capture_output=True, timeout=60, check=True, stdin=subprocess.DEVNULL)
    return path


def _admission(runtime, root: Path) -> dict:
    """Production admission and both production receipt readers."""
    sample, store = _sample(runtime, root), root / "store"
    store.mkdir()
    receipt = admit_external_media(str(sample), str(store))
    _limits, decoded = validate_admission_receipt(receipt)
    kind = receipt_snapshot(receipt, store)[3]
    if kind != "timed-media" or decoded["facts"]["videoStreams"] != 1:
        raise RuntimeError("admitted sample facts are wrong")
    return {"policy": receipt["policy"], "mediaKind": kind, "decoderRuns": len(receipt["isolation"]["decoderRuns"])}


def _denied(runtime, arguments: tuple[str, ...], allowed: str) -> str:
    """A jailed ffmpeg run that must be refused; returns the refusal code."""
    try:
        run_decoder(runtime, runtime.ffmpeg, ("-nostdin", "-v", "error", *arguments), (allowed, JailLimits(30, 30)))
    except JailRejection as error:
        return error.code if "Operation not permitted" in str(error) or error.code == "MEMORY_LIMIT" else ""
    return ""


def _network_denied(runtime, allowed: str) -> bool:
    """The jailed decoder cannot reach a loopback listener, which sees nothing."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(0.5)
    try:
        refused = _denied(runtime, ("-rw_timeout", "3000000", "-i",
                                    f"http://127.0.0.1:{listener.getsockname()[1]}/x", "-f", "null", "-"), allowed)
        try:
            listener.accept()[0].close()
            return False
        except (TimeoutError, socket.timeout):
            return bool(refused)
    finally:
        listener.close()


def _enforcement(runtime, root: Path) -> dict:
    """The three jail properties, observed on this Mac."""
    allowed = str(root / "doctor-sample.mp4")
    other = root / "not-admitted.mp4"
    shutil.copyfile(allowed, other)
    memory = ""
    try:
        run_decoder(runtime, runtime.ffmpeg, ("-nostdin", "-v", "error", "-f", "lavfi", "-i",
                                              "color=size=3840x2160:rate=30", "-t", "2", "-vf", "tmix=frames=16",
                                              "-f", "null", "-"), (allowed, JailLimits(60, 60, memory_mib=64)))
    except JailRejection as error:
        memory = error.code
    return {"otherFileReadDenied": bool(_denied(runtime, ("-i", str(other), "-f", "null", "-"), allowed)),
            "networkDenied": _network_denied(runtime, allowed),
            "memoryLimitEnforced": memory == "MEMORY_LIMIT"}


def run() -> dict:
    """Every check, with a single ok verdict and a readable detail."""
    started = time.monotonic()
    result: dict = {"ok": False}
    try:
        runtime = verified_runtime()
        result["ffmpeg"] = runtime.identity["tools"]["ffmpeg"]["version"]
        result["jail"] = runtime.identity["policy"]
        with tempfile.TemporaryDirectory(prefix="sniper-doctor-admission-") as temporary:
            root = Path(temporary).resolve()
            result["admission"] = _admission(runtime, root)
            result["enforcement"] = _enforcement(runtime, root)
        failed = [name for name, value in result["enforcement"].items() if value is not True]
        result["ok"] = not failed
        result["detail"] = ("generated sample admitted in the native jail; reads, network and memory limit enforced"
                            if not failed else "jail property not enforced: " + ", ".join(failed))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        result["detail"] = f"{type(error).__name__}: {error}"[:500]
    result["elapsedMs"] = round((time.monotonic() - started) * 1000)
    return result


def main() -> int:
    if sys.argv[1:] not in ([], ["--json"]):
        print("usage: native_admission_selftest.py [--json]", file=sys.stderr)
        return 2
    result = run()
    print(json.dumps(result, sort_keys=True) if "--json" in sys.argv else result["detail"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
