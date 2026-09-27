"""Exercise Windows-only Python paths before the full buyer installation."""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


def _load(package: Path) -> tuple[object, object, object, object]:
    """Import product modules from the staged package, never the source tree."""
    sys.path[:0] = [str(package / "scripts"), str(package / "scripts/producer")]
    from producer.headless.external_media_snapshot import capture_external_media_snapshot
    from producer.headless.process_runner import ProcessRequest, run_text
    import local_whisper
    del local_whisper
    doctor = package / "install/sniper_doctor.py"
    sys.path.insert(0, str(doctor.parent / "lib"))
    spec = importlib.util.spec_from_file_location("sniper_windows_doctor_preflight", doctor)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the staged Windows Doctor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return capture_external_media_snapshot, ProcessRequest, run_text, module._make_speech_sample


def _snapshot(capture: object) -> None:
    """Publish and reverify a real content-addressed snapshot on Windows."""
    with tempfile.TemporaryDirectory(prefix="sniper-windows-snapshot-") as root:
        folder = Path(root)
        source, store = folder / "source.bin", folder / "store"
        source.write_bytes(b"project-sniper\nwindows-media\x1a-preflight\n")
        store.mkdir()
        snapshot = capture(str(source), str(store))
        if Path(snapshot.path).read_bytes() != source.read_bytes():
            raise RuntimeError("Windows external-media snapshot bytes changed")


def _process(request_type: object, run: object) -> None:
    """Run a bounded child through the Windows Job Object implementation."""
    with tempfile.TemporaryDirectory(prefix="sniper-windows-process-") as root:
        request = request_type(
            (sys.executable, "-c", "print('windows-runner-ok')"), "", root,
            dict(os.environ), 30, max_output_bytes=128)
        result = run(request)
    if result.returncode != 0 or result.stdout.strip() != "windows-runner-ok":
        raise RuntimeError(
            "Windows bounded process runner returned the wrong result: "
            f"code={result.returncode}; stdout={result.stdout!r}; stderr={result.stderr!r}")


def _speech(make_sample: object) -> None:
    """Run Doctor TTS without relying on a PowerShell entry in PATH."""
    with tempfile.TemporaryDirectory(prefix="sniper-windows-speech-") as root:
        sample = Path(root) / "speech.wav"
        previous = os.environ.get("PATH")
        os.environ["PATH"] = str(Path(root) / "missing")
        try:
            code, detail = make_sample(sample)
        finally:
            if previous is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = previous
        if code != 0 or not sample.is_file() or sample.stat().st_size <= 44:
            raise RuntimeError(f"Windows Doctor could not create its local speech sample: {detail}")


def _jailed_media(package: Path, jail: Path, tools: tuple[Path, Path]) -> None:
    """Launch real media tools through the same captured-pipe supervisor as Doctor."""
    sys.path[:0] = [str(package / "scripts"), str(package / "scripts/producer")]
    from producer.headless.windows_media_sandbox import launch
    runtime = SimpleNamespace(identity={"launcher": {"path": str(jail)}, "profileSha256": "preflight"})
    limits = SimpleNamespace(memory_mib=768, cpu_seconds=15, wall_seconds=20,
                             max_output_bytes=1024 * 1024, binary_stdout=False)
    for tool in tools:
        step = SimpleNamespace(input_path=os.devnull, limits=limits, decoder=str(tool), inspect_limits=None)
        done, attestation, watchdog = launch(runtime, step, (str(tool), "-hide_banner", "-version"))
        proof = attestation or {}
        valid = (done.returncode == 0 and not watchdog.exceeded and proof.get("tokenIsAppContainer") is True
                 and proof.get("networkCapabilities") == 0
                 and (proof.get("job") or {}).get("memoryLimitBytes") == 768 * 1024 * 1024)
        if not valid:
            raise RuntimeError(f"{tool.name} AppContainer preflight failed: code={done.returncode}; "
                               f"stderr={done.stderr[-500:]!r}; attestation={proof!r}")


def main() -> int:
    """Validate staged imports, Windows snapshot publication and child ownership."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--media-jail", type=Path)
    parser.add_argument("--ffmpeg", type=Path)
    parser.add_argument("--ffprobe", type=Path)
    args = parser.parse_args()
    package = args.package.resolve()
    if os.name != "nt" or not package.is_dir():
        raise RuntimeError("Windows runtime preflight needs a staged package on Windows")
    capture, request_type, run, make_sample = _load(package)
    _snapshot(capture)
    _process(request_type, run)
    _speech(make_sample)
    media = (args.media_jail, args.ffmpeg, args.ffprobe)
    if any(media) and not all(path and path.is_file() for path in media):
        raise RuntimeError("media preflight requires existing jail, ffmpeg and ffprobe files")
    if all(media):
        _jailed_media(package, args.media_jail, (args.ffmpeg, args.ffprobe))
    print("Windows Python runtime preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
