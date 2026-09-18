"""Build/test a synthetic AVFrame kernel with installed clang/libavutil only.

No source media, decode, filter execution, Docker, network, installs or source
edits occur. Binaries remain in one fresh private temporary directory. Actual
owned compiler/test processes share one original 30-second engineering cap.
One optimized kernel measurement excludes payload SHA and record framing; it
is deliberately not equivalent to the Python reducer or a video SLA.
"""
from __future__ import annotations

import json
import struct
import tempfile
import time
from pathlib import Path

from color.deadline import require_time
from headless.process_runner import ProcessRequest, run_text

_CLANG = Path("/Library/Developer/CommandLineTools/usr/bin/clang")
_SDK = Path("/Library/Developer/CommandLineTools/SDKs/MacOSX14.4.sdk")
_FFMPEG = Path("/opt/homebrew/Cellar/ffmpeg/8.0_1")
_EDGES = (0, 0x80000000, 1, 0x80000001, 0x007FFFFF, 0x807FFFFF,
          0x3F800000, 0x3F800001, 0x7F7FFFFF, 0xFF7FFFFF, 0x7F800000,
          0xFF800000, 0x7FC00000, 0xFFC00000, 0x7F800001, 0x3F000000)


def _invoke(command: tuple[str, ...], state: dict, label: str) -> str:
    """Keep exact command/status/stdout/stderr and reap under the same cutoff."""
    row = {"label": label, "command": list(command), "status": "running"}
    state["commands"].append(row)
    began = time.monotonic()
    try:
        result = run_text(ProcessRequest(command, "", state["directory"],
            {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TMPDIR": state["directory"]},
            require_time(state["deadline"]), max_output_bytes=256 * 1024))
        row.update(returnCode=result.returncode, stdout=result.stdout, stderr=result.stderr)
        if result.returncode:
            raise RuntimeError(f"{label} exited {result.returncode}")
        if not label.startswith("build-") and result.stderr:
            raise RuntimeError(f"{label} emitted runtime diagnostics")
        require_time(state["deadline"])
        row["status"] = "complete"
        return result.stdout
    except Exception as error:
        row.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        row["elapsedSeconds"] = time.monotonic() - began


def _build(state: dict, sanitized: bool) -> Path:
    """Compile fixed TEST sources into the fresh directory, never installed paths."""
    tests = Path(__file__).resolve().parent
    native = tests.parent / "color" / "native"
    output = Path(state["directory"]) / ("gamut-sanitized" if sanitized else "gamut-optimized")
    flags = ("-O1", "-fsanitize=undefined", "-fno-sanitize-recover=all",
             "-fno-omit-frame-pointer") if sanitized else ("-O3",)
    command = (str(_CLANG), "-isysroot", str(_SDK), "-std=c11", "-Wall", "-Wextra", "-Werror", "-fno-fast-math",
        "-ffp-contract=off", *flags, "-I" + str(native), "-I" + str(_FFMPEG / "include"),
        str(native / "source_gamut_avframe.c"), str(tests / "source_gamut_avframe_test.c"),
        "-L" + str(_FFMPEG / "lib"), "-lavutil", "-o", str(output))
    _invoke(command, state, "build-sanitized" if sanitized else "build-optimized")
    return output


def _expected_channels() -> list[dict]:
    """Use the real framed NumPy/reference validator on matching synthetic bits."""
    from _source_gamut_reducer_fixture import gamut_fixture

    fixture = gamut_fixture(2, (4, 4))
    blue = tuple(0x80000000 if index % 2 else 0 for index in range(16))
    payload = struct.pack("<48I", *(_EDGES + blue + (0xBF000000,) * 16))
    result = fixture.run([payload, payload])
    rows = []
    for channel in ("g", "b", "r"):
        row = dict(result["channels"][channel])
        row["minimumBits"] = struct.unpack("<I", struct.pack("<f", row.pop("minimum")))[0]
        row["maximumBits"] = struct.unpack("<I", struct.pack("<f", row.pop("maximum")))[0]
        rows.append(row)
    return rows


def _correctness(raw: str, expected: list[dict]) -> None:
    """Require exact counts/extrema parity, not approximate decimal agreement."""
    row = json.loads(raw.splitlines()[0])
    if row["status"] != "complete" or row["syntheticCorrectnessPassed"] is not True \
            or row["nativeMediaExecuted"] is not False or row["channels"] != expected:
        raise RuntimeError("native kernel differs from exact supplied-float reference")


def _execute(state: dict) -> dict:
    """Correctness/sanitizers first, then exactly one bounded kernel measurement."""
    for path in (_CLANG, _SDK / "usr/include/errno.h", _FFMPEG / "include/libavutil/frame.h",
                 _FFMPEG / "lib/libavutil.dylib"):
        if not path.is_file():
            raise RuntimeError(f"required installed tool/header/library unavailable: {path}")
    expected = _expected_channels()
    sanitized = _build(state, True)
    _correctness(_invoke((str(sanitized),), state, "sanitized-correctness"), expected)
    optimized = _build(state, False)
    raw = _invoke((str(optimized), "--benchmark"), state, "optimized-correctness-and-one-benchmark")
    _correctness(raw, expected)
    measured = json.loads(raw.splitlines()[1])
    if measured["payloadBytes"] != 402653184 or measured["hashAndFramingIncluded"] is not False:
        raise RuntimeError("TEST kernel benchmark work/scope differs")
    return measured


def main() -> None:
    """Retain failed attempts and all temporary binaries; report no media proof."""
    began = time.monotonic()
    state = {"deadline": began + 30, "commands": [],
             "directory": tempfile.mkdtemp(prefix="sniper-gamut-native-", dir="/private/tmp")}
    report = {"schemaVersion": 1, "kind": "TEST-synthetic-AVFrame-kernel-check",
              "scope": "kernel-only-not-native-media-hash-framing-or-two-hour-proof",
              "originalEngineeringBudgetSeconds": 30, "retainedDirectory": state["directory"],
              "sanitizer": "undefined-only; prior installed ASan initialization aborted",
              "commands": state["commands"], "nativeMediaExecuted": False,
              "gamutQualified": False, "transformApplicable": False, "twoHourProof": False}
    failed = False
    try:
        report["measurement"] = _execute(state)
        require_time(state["deadline"])
        report["status"] = "complete"
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        failed = True
    report["elapsedSeconds"] = time.monotonic() - began
    print(json.dumps(report, allow_nan=False, sort_keys=True), flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
