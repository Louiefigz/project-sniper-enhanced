#!/usr/bin/env python3
"""Check this install by asking the product's own code what it would do.

    install/doctor.command [--json] [--skip-transcription]

Nothing is re-implemented here. Render tools come from `graphics.render_tools`,
transcription from `local_whisper.transcribe_media`, the render runtime from
`studio.native_runtime`, and media admission from the product's admission self-test
(`scripts/producer/headless/native_admission_selftest.py`). Your Codex or Claude Code is
not checked: it is yours, signed in to your own subscription, and Sniper's commands never
call it. A check passes on what the tool actually did, never on an exit code alone. Installed files are re-verified against the
SHA-256 records the installer wrote when each step finished.

Exit 0 = every required check passed. Optional features are reported as
available / gated and never change the exit code.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import doctor_setup as setup  # noqa: E402
import install_tools  # noqa: E402

PKG_ROOT = setup.PKG_ROOT
APP = setup.APP
RECEIPTS = PKG_ROOT / "runtime" / "state" / "receipts"
MODEL_SHA = "c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d"
FILTERS = ("rubberband", "zscale", "subtitles", "ass", "drawtext", "arnndn", "loudnorm", "ebur128",
           "afftdn", "acompressor", "alimiter", "sidechaincompress", "aresample", "amix", "overlay", "crop")
SPOKEN = f"Sniper checks that local transcription works on this {'PC' if os.name == 'nt' else 'Mac'}."
SETUP_COMMAND = "sniper.cmd setup" if os.name == "nt" else "install/install.command"
_RESULTS: list[dict] = []


def record(state: str, name: str, detail: str) -> None:
    """state: PASS, FAIL, INFO or GATED."""
    _RESULTS.append({"state": state, "check": name, "detail": detail})


def _product_paths() -> None:
    for extra in (APP / "scripts", APP / "scripts/producer", APP / "scripts/infra"):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))


def _tree_intact(root: Path, receipt: str, exclude: set[str]) -> str | None:
    """None when a finished step's folder still matches its record, else what changed."""
    if not (RECEIPTS / receipt).exists():
        return f"not installed — run {SETUP_COMMAND}"
    want = RECEIPTS / f"{receipt}.tree.json"
    try:
        files = json.loads(want.read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError):
        return f"no record of the finished step — run {SETUP_COMMAND}"
    have = install_tools.tree_digests(root, exclude) if root.is_dir() else {}
    changed = sum(1 for k, v in files.items() if have.get(k) != v) + sum(1 for k in have if k not in files)
    return f"{changed} file(s) differ from what was installed — run {SETUP_COMMAND}" if changed else None


def check_foundations() -> None:
    """Install path, Node, both dependency roots, tsx and the pinned Python set."""
    refused = (",", "'") if os.name == "nt" else (",", "'", ":", "\\")
    bad = [ch for ch in refused if ch in str(PKG_ROOT)]
    record("FAIL" if bad else "PASS", "install path",
           f"contains {' '.join(bad)}: voice-rnn cleanup cannot run" if bad else str(PKG_ROOT))
    setup.check_node(record)
    for root, receipt, label in ((APP, "npm-app", "JavaScript dependencies"),
                                 (APP / "templates/motion", "npm-motion", "rendering-project dependencies")):
        problem = _tree_intact(root / "node_modules", receipt, {".cache"})
        record("FAIL" if problem else "PASS", label, problem or "installed and verified")
    record("PASS" if (APP / "node_modules/tsx/dist/cli.mjs").exists() else "FAIL", "tsx runtime",
           "Sniper's TypeScript commands need it")
    venv = APP / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python3")
    if not venv.exists():
        record("FAIL", "python packages", f"no environment — run {SETUP_COMMAND}")
        return
    code, out, _ = setup.run([str(venv), "-I", str(Path(install_tools.__file__)), "venv-check",
                              str(PKG_ROOT / "install/requirements.lock.txt")], 180)
    record("PASS" if code == 0 else "FAIL", "python packages",
           out.strip() if code == 0 else f"{out.strip()} — run {SETUP_COMMAND}")


def check_media() -> None:
    """ffmpeg features, and the tools a render would actually resolve."""
    ffmpeg = os.environ.get("HYPERFRAMES_FFMPEG_PATH") or shutil.which("ffmpeg") or ""
    filters = setup.run([ffmpeg, "-hide_banner", "-filters"])[1] if ffmpeg else ""
    encoders = setup.run([ffmpeg, "-hide_banner", "-encoders"])[1] if ffmpeg else ""
    names = {l.split()[1] for l in filters.splitlines() if len(l.split()) > 2}
    enc = {l.split()[1] for l in encoders.splitlines() if len(l.split()) > 2}
    missing = [f for f in FILTERS if f not in names] + [e for e in ("libx264", "aac") if e not in enc]
    record("PASS" if ffmpeg and not missing else "FAIL", "ffmpeg features",
           ffmpeg if not missing else f"missing: {' '.join(missing)}")
    _product_paths()
    try:
        from graphics.render_tools import resolve_tools  # noqa: PLC0415
        tools = resolve_tools()
    except Exception as error:  # the resolver raises RuntimeError by design
        record("FAIL", "render tools", str(error)); return
    pin = setup.release()["components"]["chrome_headless_shell"]
    ok = pin in tools["browser"] and str(PKG_ROOT) in tools["browser"]
    problem = _tree_intact(Path(tools["browser"]).parents[1], "browser", set()) if ok else None
    record("PASS" if ok and not problem else "FAIL", "render browser",
           (problem or tools["browser"]) if ok else f"expected {pin} inside this folder, resolved {tools['browser']}")


def check_runtime() -> None:
    """The render runtime through the product's own installer."""
    _product_paths()
    try:
        from studio.native_runtime import install_runtime  # noqa: PLC0415
        record("PASS", "render runtime", f"verified from the shipped patch set: {install_runtime().name}")
    except Exception as error:
        record("FAIL", "render runtime", f"{type(error).__name__}: {error}")


def _make_speech_sample(path: Path) -> int:
    """Create a deterministic local TTS sample with the operating system voice."""
    if os.name != "nt":
        return setup.run(["say", "-o", str(path), SPOKEN], 60)[0]
    script = ("Add-Type -AssemblyName System.Speech; "
              "$voice=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "$voice.SetOutputToWaveFile($args[0]); $voice.Speak($args[1]); $voice.Dispose()")
    return setup.run(["powershell.exe", "-NoProfile", "-Command", script, str(path), SPOKEN], 60)[0]


def check_transcription(skip: bool) -> None:
    """Model hash, then an actual transcription through the product's own path."""
    _product_paths()
    try:
        from local_whisper import LocalTranscribeRequest, resolve_whisper_model, transcribe_media  # noqa: PLC0415
        model = Path(resolve_whisper_model())
    except Exception as error:
        record("FAIL", "speech model", str(error)); return
    if install_tools.file_digest(model) != MODEL_SHA:
        record("FAIL", "speech model", f"{model} does not match the expected checksum — run {SETUP_COMMAND}"); return
    record("PASS", "speech model", f"{model.name} checksum verified")
    if skip:
        record("INFO", "transcription", "skipped by request"); return
    with tempfile.TemporaryDirectory(prefix="sniper-doctor-") as tmp:
        speech = Path(tmp) / ("speech.wav" if os.name == "nt" else "speech.aiff")
        if _make_speech_sample(speech) != 0:
            record("FAIL", "transcription", "could not create the local speech sample"); return
        try:
            result = transcribe_media(LocalTranscribeRequest(path=str(speech)))
        except Exception as error:
            record("FAIL", "transcription", f"{type(error).__name__}: {error}"); return
    words = [w for seg in result.get("transcript", result.get("segments", [])) for w in seg.get("words", [])] \
        if isinstance(result, dict) else []
    text = " ".join(str(w.get("word", w.get("text", ""))) for w in words).lower()
    starts = [float(w.get("start", 0)) for w in words]
    last = "pc" if os.name == "nt" else "mac"
    heard = sum(token in text for token in ("sniper", "checks", "local", "transcription", last))
    ok = heard >= 4 and starts == sorted(starts) and len(words) >= 6
    record("PASS" if ok else "FAIL", "transcription",
           f"{len(words)} timed words, {heard}/5 expected words heard" if ok
           else f"output unusable: {len(words)} words, {heard}/5 expected words, ordered={starts == sorted(starts)}")


def check_workspace() -> None:
    """The video workspace is writable with room for a render, and ./sniper is in place."""
    root = Path(os.environ.get("SNIPER_WORKSPACE_ROOT") or PKG_ROOT / "projects")
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / ".sniper-doctor-probe").write_text("ok"); (root / ".sniper-doctor-probe").unlink()
        free = shutil.disk_usage(root).free / 1e9
        record("PASS" if free >= 20 else "FAIL", "workspace", f"{root} — {free:.0f} GB free"
               + ("" if free >= 20 else "; long-form renders need at least 20 GB"))
    except OSError as error:
        record("FAIL", "workspace", f"{root} not writable: {error.strerror}")
    wrapper = PKG_ROOT / ("sniper.cmd" if os.name == "nt" else "sniper")
    ok = wrapper.is_file() and (os.name == "nt" or os.access(wrapper, os.X_OK))
    record("PASS" if ok else "FAIL", wrapper.name, "runs Sniper's commands for your Codex or Claude Code" if ok
           else f"{wrapper} is missing or not executable — this folder is incomplete")


def check_optional() -> None:
    """Optional features: reported, never failing the doctor."""
    demucs_rel = "scripts/producer/audio/.demucs-venv/Scripts/python.exe" if os.name == "nt" \
        else "scripts/producer/audio/.demucs-venv/bin/python3"
    demucs = (APP / demucs_rel).exists()
    record("PASS" if demucs else "GATED", "audio preset: separate",
           "available" if demucs else "not installed (needs Demucs); voice, voice-strong, voice-rnn work")
    record("GATED", "Palmier Pro mirror", "optional separate app; not configured in this package")


def _hold_install() -> bool:
    """Hold the install shared for this run, so no installer or uninstall runs under it."""
    _product_paths()
    import sniper_lock  # noqa: PLC0415
    try:
        sniper_lock.hold_for_process(APP, "doctor")
    except sniper_lock.LockBusy as error:
        record("FAIL", "install in use", str(error))
        return False
    return True


def main() -> int:
    """Run the checks; exit 0 only when every required one passed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--skip-transcription", action="store_true")
    args = parser.parse_args()
    if _hold_install():
        check_foundations(); setup.check_runtime_tools(record); check_media(); check_runtime()
        setup.check_media_admission(record); check_transcription(args.skip_transcription)
    check_workspace(); check_optional()
    failed = [r["check"] for r in _RESULTS if r["state"] == "FAIL"]
    if args.json:
        print(json.dumps({"ok": not failed, "failed": failed, "checks": _RESULTS}))
        return 1 if failed else 0
    width = max(len(r["check"]) for r in _RESULTS)
    for r in _RESULTS:
        print(f"[{r['state']:5}] {r['check'].ljust(width)}  {r['detail']}")
    print(f"\n{len(failed)} required check(s) failed: {', '.join(failed)}" if failed else "\nAll required checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
