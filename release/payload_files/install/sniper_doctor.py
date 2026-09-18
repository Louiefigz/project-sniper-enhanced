#!/usr/bin/env python3
"""Check this install by asking the product's own code what it would do.

    install/doctor.command [--json] [--provider-only] [--skip-transcription]

Nothing is re-implemented here. Render tools come from `graphics.render_tools`,
transcription from `local_whisper.transcribe_media`, the render runtime from
`studio.native_runtime`, and the provider check from the same
`admitSubscriptionInvocation` every real edit uses (via
`scripts/infra/provider-admission.ts`). A check passes on what the tool
actually did, never on an exit code alone.

Exit 0 = every required check passed. Optional features are reported as
available / gated and never change the exit code.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
APP = PKG_ROOT / "app"
RECEIPTS = PKG_ROOT / "runtime" / "state" / "receipts"
MODEL_SHA = "c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d"
FILTERS = ("rubberband", "zscale", "subtitles", "ass", "drawtext", "arnndn", "loudnorm", "ebur128",
           "afftdn", "acompressor", "alimiter", "sidechaincompress", "aresample", "amix", "overlay", "crop")
SPOKEN = "Sniper checks that local transcription works on this Mac."
_RESULTS: list[dict] = []


def record(state: str, name: str, detail: str) -> None:
    """state: PASS, FAIL, INFO or GATED."""
    _RESULTS.append({"state": state, "check": name, "detail": detail})


def _run(argv: list[str], timeout: int = 60, cwd: Path | None = None) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False, cwd=cwd)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, type(error).__name__
    return done.returncode, f"{done.stdout}{done.stderr}"


def _sha(path: Path) -> str:
    import hashlib  # noqa: PLC0415
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _product_paths() -> None:
    for extra in (APP / "scripts", APP / "scripts/producer"):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))


def check_foundations() -> None:
    """Install path, Node, both dependency roots, tsx, venv and the pinned Python set."""
    bad = [ch for ch in (",", "'", ":", "\\") if ch in str(PKG_ROOT)]
    record("FAIL" if bad else "PASS", "install path",
           f"contains {' '.join(bad)}: voice-rnn cleanup cannot run" if bad else str(PKG_ROOT))
    code, out = _run(["node", "--version"])
    major = out.strip().lstrip("v").split(".")[0]
    record("PASS" if code == 0 and major.isdigit() and int(major) >= 22 else "FAIL", "node", out.strip() or "missing")
    for root, receipt in ((APP, "npm-app"), (APP / "templates/motion", "npm-motion")):
        ok = (root / "node_modules").is_dir() and (RECEIPTS / receipt).exists()
        record("PASS" if ok else "FAIL", f"dependencies {root.relative_to(PKG_ROOT)}",
               "installed and receipted" if ok else "incomplete — run install.command")
    record("PASS" if (APP / "node_modules/tsx/dist/cli.mjs").exists() else "FAIL", "tsx runtime", "background edits need it")
    venv = APP / ".venv/bin/python3"
    lock = PKG_ROOT / "install/requirements.lock.txt"
    if not venv.exists():
        record("FAIL", "python packages", "no environment — run install.command"); return
    wanted = dict(l.split("==", 1) for l in lock.read_text().splitlines() if "==" in l and not l.startswith("#"))
    _, frozen = _run([str(venv), "-m", "pip", "freeze", "--disable-pip-version-check"], 120)
    have = dict(l.split("==", 1) for l in frozen.splitlines() if "==" in l)
    drift = [f"{k} {have.get(k, 'missing')}≠{v}" for k, v in wanted.items() if have.get(k) != v]
    record("PASS" if not drift else "FAIL", "python packages",
           f"{len(wanted)} pinned packages match" if not drift else "drift: " + "; ".join(drift[:4]))


def check_media() -> None:
    """ffmpeg features, and the tools a render would actually resolve."""
    ffmpeg = os.environ.get("HYPERFRAMES_FFMPEG_PATH") or shutil.which("ffmpeg") or ""
    _, filters = _run([ffmpeg, "-hide_banner", "-filters"]) if ffmpeg else (1, "")
    _, encoders = _run([ffmpeg, "-hide_banner", "-encoders"]) if ffmpeg else (1, "")
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
    pin = json.loads((PKG_ROOT / "RELEASE.json").read_text())["components"]["chrome_headless_shell"]
    ok = pin in tools["browser"] and str(PKG_ROOT) in tools["browser"]
    record("PASS" if ok else "FAIL", "render browser",
           tools["browser"] if ok else f"expected {pin} inside this folder, resolved {tools['browser']}")


def check_runtime_and_build() -> None:
    _product_paths()
    try:
        from studio.native_runtime import install_runtime  # noqa: PLC0415
        record("PASS", "render runtime", f"verified from the shipped patch set: {install_runtime().name}")
    except Exception as error:
        record("FAIL", "render runtime", f"{type(error).__name__}: {error}")
    build = APP / ".next/BUILD_ID"
    ok = build.exists() and (RECEIPTS / "build").exists()
    record("PASS" if ok else "FAIL", "app build", build.read_text().strip() if ok else "not built — run install.command")


def check_transcription(skip: bool) -> None:
    """Model hash, then an actual transcription through the product's own path."""
    _product_paths()
    try:
        from local_whisper import LocalTranscribeRequest, resolve_whisper_model, transcribe_media  # noqa: PLC0415
        model = Path(resolve_whisper_model())
    except Exception as error:
        record("FAIL", "speech model", str(error)); return
    if _sha(model) != MODEL_SHA:
        record("FAIL", "speech model", f"{model} does not match the expected checksum — delete it and reinstall"); return
    record("PASS", "speech model", f"{model.name} checksum verified")
    if skip:
        record("INFO", "transcription", "skipped by request"); return
    with tempfile.TemporaryDirectory(prefix="sniper-doctor-") as tmp:
        speech = Path(tmp) / "speech.aiff"
        if _run(["say", "-o", str(speech), SPOKEN], 60)[0] != 0:
            record("FAIL", "transcription", "could not create the local speech sample with macOS 'say'"); return
        try:
            result = transcribe_media(LocalTranscribeRequest(path=str(speech)))
        except Exception as error:
            record("FAIL", "transcription", f"{type(error).__name__}: {error}"); return
    words = [w for seg in result.get("transcript", result.get("segments", [])) for w in seg.get("words", [])] \
        if isinstance(result, dict) else []
    text = " ".join(str(w.get("word", w.get("text", ""))) for w in words).lower()
    starts = [float(w.get("start", 0)) for w in words]
    heard = sum(token in text for token in ("sniper", "checks", "local", "transcription", "mac"))
    ok = heard >= 4 and starts == sorted(starts) and len(words) >= 6
    record("PASS" if ok else "FAIL", "transcription",
           f"{len(words)} timed words, {heard}/5 expected words heard" if ok
           else f"output unusable: {len(words)} words, {heard}/5 expected words, ordered={starts == sorted(starts)}")


def check_provider() -> None:
    """The selected provider, through production admission. Never prints auth output."""
    selected = os.environ.get("SNIPER_PROVIDER") or ("codex" if os.environ.get("SNIPER_BRAIN_PROVIDER") == "codex" else "claude")
    code, out = _run(["node", "--import", "tsx", "scripts/infra/provider-admission.ts", "--provider", selected], 90, APP)
    try:
        report = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        record("FAIL", f"editor brain ({selected})", "the admission check did not run"); return
    advice = {"not-signed-in-or-not-subscription": "sign in: install/sign-in.command",
              "wrong-version": "reinstall the pinned CLI: install/install.command",
              "cli-missing": "reinstall: install/install.command"}.get(report["reason"], report["detail"])
    record("PASS" if report["ready"] else "FAIL", f"editor brain ({selected})",
           f"{report['admittedVersion']} admitted and signed in" if report["ready"] else f"{report['reason']} — {advice}")


def check_workspace_and_port() -> None:
    root = Path(os.environ.get("SNIPER_WORKSPACE_ROOT") or Path.home() / "ProjectSniper")
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / ".sniper-doctor-probe").write_text("ok"); (root / ".sniper-doctor-probe").unlink()
        free = shutil.disk_usage(root).free / 1e9
        record("PASS" if free >= 20 else "FAIL", "workspace", f"{root} — {free:.0f} GB free"
               + ("" if free >= 20 else "; long-form renders need at least 20 GB"))
    except OSError as error:
        record("FAIL", "workspace", f"{root} not writable: {error.strerror}")
    port = os.environ.get("SNIPER_PORT", "3000")
    _, out = _run(["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], 15)
    record("INFO", f"port {port}", "free" if not out.strip() else f"in use by pid {' '.join(out.split())}")


def check_optional() -> None:
    demucs = (APP / "scripts/producer/audio/.demucs-venv/bin/python3").exists()
    record("PASS" if demucs else "GATED", "audio preset: separate",
           "available" if demucs else "not installed (needs Demucs); voice, voice-strong, voice-rnn work")
    record("GATED", "Frame Review", "needs your own paid Anthropic API key — not part of this purchase")
    record("GATED", "Palmier Pro mirror", "optional separate app; not configured in this package")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--provider-only", action="store_true")
    parser.add_argument("--skip-transcription", action="store_true")
    args = parser.parse_args()
    if not args.provider_only:
        check_foundations(); check_media(); check_runtime_and_build()
        check_transcription(args.skip_transcription)
    check_provider()
    if not args.provider_only:
        check_workspace_and_port(); check_optional()
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
