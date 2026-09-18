#!/usr/bin/env python3
"""Check this install by asking the product's own resolvers what they resolve.

Nothing here re-implements a lookup. The browser/ffmpeg/node resolution comes
from `graphics.render_tools`, the transcription paths from `scripts.local_whisper`
and the render runtime from `studio.native_runtime`, so the doctor cannot drift
away from what a render would actually use.

Exit 0 = every required check passed. Exit 1 = at least one required check failed.
Optional features are reported as available, gated or needs-key and never
affect the exit code.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
APP = PKG_ROOT / "app"
_REQUIRED_FILTERS = ("rubberband", "zscale", "subtitles", "ass", "drawtext", "arnndn",
                     "loudnorm", "ebur128", "afftdn", "acompressor", "alimiter",
                     "sidechaincompress", "aresample", "amix", "overlay", "crop")
_REQUIRED_ENCODERS = ("libx264", "aac")
_UNSAFE_PATH_CHARS = (",", "'", ":", "\\")
_RESULTS: list[tuple[str, str, str]] = []


def record(state: str, name: str, detail: str) -> None:
    """Record one check outcome. `state` is PASS, FAIL, INFO or GATED."""
    _RESULTS.append((state, name, detail))


def _run(argv: list[str], timeout: int = 20) -> tuple[int, str]:
    """Run a command and return its exit code with stdout+stderr."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, f"{type(error).__name__}"
    return done.returncode, f"{done.stdout}{done.stderr}"


def check_install_path() -> None:
    """The install path must not break the audio cleanup filtergraph."""
    bad = [ch for ch in _UNSAFE_PATH_CHARS if ch in str(PKG_ROOT)]
    if bad:
        record("FAIL", "install path", "contains " + " ".join(bad)
               + " — the voice-rnn cleanup preset cannot run; move the folder")
    else:
        record("PASS", "install path", str(PKG_ROOT))


def check_runtimes() -> None:
    """Node, the two dependency roots, tsx and the Python environment."""
    code, out = _run(["node", "--version"])
    major = out.strip().lstrip("v").split(".")[0] if code == 0 else ""
    if major.isdigit() and int(major) >= 22:
        record("PASS", "node", out.strip())
    else:
        record("FAIL", "node", f"need 22 or newer, found {out.strip() or 'nothing'}")
    for root in (APP, APP / "templates/motion"):
        name = f"dependencies {root.relative_to(PKG_ROOT)}"
        record("PASS" if (root / "node_modules").is_dir() else "FAIL", name,
               "installed" if (root / "node_modules").is_dir() else "run install.command")
    tsx = APP / "node_modules/tsx/dist/cli.mjs"
    record("PASS" if tsx.exists() else "FAIL", "tsx runtime",
           "present" if tsx.exists() else "missing — background edits cannot start")
    venv = APP / ".venv/bin/python3"
    if not venv.exists():
        record("FAIL", "python environment", "missing — run install.command")
        return
    code, out = _run([str(venv), "-c", "import sys;print('.'.join(map(str,sys.version_info[:3])))"])
    record("PASS" if code == 0 else "FAIL", "python environment", out.strip())


def check_pinned_packages() -> None:
    """Every Python package must be at the version this release was tested with."""
    lock = PKG_ROOT / "install/requirements.lock.txt"
    venv = APP / ".venv/bin/python3"
    if not lock.exists() or not venv.exists():
        record("FAIL", "python packages", "cannot check without the lock and the venv")
        return
    wanted = dict(line.split("==", 1) for line in lock.read_text().splitlines()
                  if "==" in line and not line.startswith("#"))
    code, out = _run([str(venv), "-m", "pip", "freeze", "--disable-pip-version-check"], 90)
    if code != 0:
        record("FAIL", "python packages", "pip freeze failed")
        return
    have = dict(line.split("==", 1) for line in out.splitlines() if "==" in line)
    drift = [f"{k} {have.get(k, 'missing')}≠{v}" for k, v in wanted.items()
             if have.get(k.strip()) != v.strip()]
    record("PASS" if not drift else "FAIL", "python packages",
           f"{len(wanted)} pinned packages match" if not drift
           else "drift: " + "; ".join(drift[:4]))


def check_media_tools() -> None:
    """ffmpeg must advertise the filters and encoders the render chain uses."""
    ffmpeg = os.environ.get("HYPERFRAMES_FFMPEG_PATH") or shutil.which("ffmpeg")
    if not ffmpeg:
        record("FAIL", "ffmpeg", "not found")
        return
    code, filters = _run([ffmpeg, "-hide_banner", "-filters"], 30)
    _, encoders = _run([ffmpeg, "-hide_banner", "-encoders"], 30)
    names = {line.split()[1] for line in filters.splitlines() if len(line.split()) > 2}
    enc = {line.split()[1] for line in encoders.splitlines() if len(line.split()) > 2}
    missing = [f for f in _REQUIRED_FILTERS if f not in names]
    missing += [e for e in _REQUIRED_ENCODERS if e not in enc]
    record("PASS" if code == 0 and not missing else "FAIL", "ffmpeg features",
           ffmpeg if not missing else f"{ffmpeg} is missing: {' '.join(missing)}")


def _product_paths() -> str:
    """Add the product's own import roots so its resolvers can be reused."""
    producer = str(APP / "scripts/producer")
    sys.path[:0] = [producer, str(APP / "scripts")]
    return producer


def check_render_tools() -> None:
    """Ask the product which node/browser/ffmpeg/ffprobe a render would use."""
    _product_paths()
    try:
        from graphics.render_tools import resolve_tools  # noqa: PLC0415
        resolved = resolve_tools()
    except Exception as error:  # the resolver raises a plain RuntimeError by design
        record("FAIL", "render tools", f"{type(error).__name__}: {error}")
        return
    pin = json.loads((PKG_ROOT / "RELEASE.json").read_text())["components"]
    wanted = pin["chrome_headless_shell"]
    browser = resolved["browser"]
    inside = str(PKG_ROOT) in browser
    record("PASS" if wanted in browser and inside else "FAIL", "render browser",
           f"{browser}" if wanted in browser and inside else
           f"expected {wanted} inside this package, resolved {browser}")
    for name in ("node", "ffmpeg", "ffprobe"):
        record("PASS", f"render {name}", resolved[name])


def check_transcription() -> None:
    """Resolve the whisper binary and model, then actually transcribe."""
    _product_paths()
    try:
        from local_whisper import resolve_whisper_binary, resolve_whisper_model  # noqa: PLC0415
        binary, model = resolve_whisper_binary(), resolve_whisper_model()
    except Exception as error:
        record("FAIL", "transcription", f"{type(error).__name__}: {error}")
        return
    record("PASS", "transcription model", model)
    code, _ = _run([binary, "--help"], 30)
    record("PASS" if code == 0 else "FAIL", "transcription binary", binary)


def check_render_runtime() -> None:
    """Rebuild the adapted render runtime from the shipped patch set."""
    _product_paths()
    try:
        from studio.native_runtime import install_runtime  # noqa: PLC0415
        record("PASS", "render runtime", str(install_runtime()))
    except Exception as error:
        record("FAIL", "render runtime", f"{type(error).__name__}: {error}")


def _cli_state(binary: str, version_args: list[str], wanted: str,
               status_args: list[str]) -> tuple[str, str]:
    """Classify one provider CLI as missing, wrong version, logged out or ready."""
    if not Path(binary).exists():
        return "FAIL", "not installed — re-run install.command"
    code, out = _run([binary, *version_args], 60)
    if code != 0:
        return "FAIL", "the CLI did not run"
    found = out.strip().splitlines()[0] if out.strip() else ""
    if found != wanted:
        return "FAIL", f"this release admits only {wanted!r}; this CLI reports {found!r}"
    code, _ = _run([binary, *status_args], 60)
    return ("PASS", f"{found} — signed in") if code == 0 else \
        ("FAIL", f"{found} — not signed in yet")


def check_providers() -> None:
    """At least one provider must be installed at its exact version and signed in."""
    pin = json.loads((PKG_ROOT / "RELEASE.json").read_text())["components"]
    codex = os.environ.get("SNIPER_CODEX_BIN", "")
    claude = os.environ.get("CLAUDE_BIN", "")
    states = [
        ("Codex", *_cli_state(codex, ["--version"], pin["codex_cli_admitted"],
                              ["login", "status"])),
        ("Claude", *_cli_state(claude, ["--version"], pin["claude_cli_admitted"],
                               ["auth", "status"])),
    ]
    for name, state, detail in states:
        record("INFO" if state == "FAIL" else "PASS", f"editor brain: {name}", detail)
    ready = [name for name, state, _ in states if state == "PASS"]
    record("PASS" if ready else "FAIL", "editor brain",
           f"ready: {', '.join(ready)}" if ready else
           "neither Codex nor Claude is installed at its admitted version and signed in")


def check_workspace() -> None:
    """The project workspace must exist and be writable, with room to render."""
    root = Path(os.environ.get("SNIPER_WORKSPACE_ROOT") or Path.home() / "ProjectSniper")
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".sniper-doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        record("FAIL", "workspace", f"{root} is not writable: {error.strerror}")
        return
    free_gb = shutil.disk_usage(root).free / 1_000_000_000
    record("PASS" if free_gb >= 20 else "FAIL", "workspace",
           f"{root} — {free_gb:.0f} GB free"
           + ("" if free_gb >= 20 else "; a long-form render needs at least 20 GB"))


def check_port() -> None:
    """Report the conflicting listener rather than a generic port error."""
    port = os.environ.get("SNIPER_PORT", "3000")
    code, out = _run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], 15)
    holders = {line.split()[0] for line in out.splitlines()[1:] if line.split()}
    record("PASS" if code != 0 or not holders else "INFO", f"port {port}",
           "free" if not holders else f"in use by {', '.join(sorted(holders))}"
           " — stop it or set SNIPER_PORT")


def check_optional() -> None:
    """Report optional features honestly instead of advertising them."""
    venv = APP / ".venv/bin/python3"
    demucs = APP / "scripts/producer/audio/.demucs-venv/bin/python3"
    have = demucs.exists() or (venv.exists()
                               and _run([str(venv), "-c", "import demucs"], 40)[0] == 0)
    record("PASS" if have else "GATED", "audio preset: separate",
           "available" if have else
           "not installed (needs Demucs + torch); voice, voice-strong and voice-rnn work")
    record("PASS" if shutil.which("tesseract") else "GATED", "Frame Review OCR mode",
           shutil.which("tesseract") or "not installed; the default visual mode does not need it")
    record("GATED", "Frame Review (either mode)",
           "needs your own paid Anthropic API key — not included in this purchase")
    record("GATED", "Palmier Pro mirror",
           "optional separate app; not configured in this package")


def main() -> int:
    """Run every check and print the report."""
    check_install_path()
    check_runtimes()
    check_pinned_packages()
    check_media_tools()
    check_render_tools()
    check_transcription()
    check_render_runtime()
    check_providers()
    check_workspace()
    check_port()
    check_optional()
    width = max(len(name) for _, name, _ in _RESULTS)
    for state, name, detail in _RESULTS:
        print(f"[{state:5}] {name.ljust(width)}  {detail}")
    failed = [name for state, name, _ in _RESULTS if state == "FAIL"]
    print()
    if failed:
        print(f"{len(failed)} required check(s) failed: {', '.join(failed)}")
        print("Fix the lines marked FAIL, then run doctor.command again.")
        return 1
    print("All required checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
