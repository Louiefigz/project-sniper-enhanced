"""Doctor checks for how this install is set up: Node, provider settings, tools, admission.

Imported by ``install/sniper_doctor.py``, which owns the result list and output.
Each check calls ``record(state, name, detail)``; nothing here prints.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

PKG_ROOT = Path(__file__).resolve().parents[2]
APP = PKG_ROOT / "app"
ADMISSION_SELFTEST = APP / "scripts/producer/headless/native_admission_selftest.py"
ADMISSION_TIMEOUT_S = 600
BRAIN_FOR = {"codex": "codex", "claude": "legacy"}
REASONING = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
# tool, Homebrew formula, the feature that refuses to run without it
EXTERNAL = (("whisper-cli", "whisper-cpp", "local transcription"),
            ("tesseract", "tesseract", "reference study (reading on-screen text)"),
            ("yt-dlp", "yt-dlp", "adding a reference from a URL"))
Record = Callable[[str, str, str], None]


def release() -> dict:
    """This package's RELEASE.json."""
    return json.loads((PKG_ROOT / "RELEASE.json").read_text(encoding="utf-8"))


def version_tuple(text: str) -> tuple[int, ...]:
    """(22, 13, 0) from '22.13.0' or 'v22.13.0'; () when unparseable."""
    parts = text.strip().lstrip("v").split(".")
    return tuple(int(p) for p in parts) if all(p.isdigit() for p in parts) and len(parts) == 3 else ()


def run(argv: list[str], timeout: int = 60, cwd: Path | None = None) -> tuple[int, str, str]:
    """Run a command; (exit code, stdout, stderr). Never raises for a missing tool or a timeout."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False, cwd=cwd)
    except subprocess.TimeoutExpired:
        return 124, "", f"did not finish within {timeout} s"
    except OSError as error:
        return 127, "", f"{type(error).__name__}: {error.strerror or error}"
    return done.returncode, done.stdout, done.stderr


def node_problem(path: str, floor: str) -> str | None:
    """Why this Node executable cannot serve this release, or None."""
    if not path or not os.path.isabs(path) or not os.access(path, os.X_OK):
        return f"no executable Node at {path or '(SNIPER_NODE_PATH unset)'}"
    code, out, _ = run([path, "--version"], 30)
    version = version_tuple(out)
    if code != 0 or not version:
        return f"{path} does not report a Node version"
    if version < version_tuple(floor):
        return f"Node {out.strip()} at {path} is older than {floor}, the oldest version every dependency accepts"
    if any(ch.isspace() for ch in path) or os.path.basename(path) != "node":
        return f"{path} must be a whitespace-free path to an executable named node (Studio needs it)"
    return None


def check_node(record: Record) -> None:
    """The ONE Node the installer validated: present, new enough, and what PATH finds."""
    floor = release()["components"]["node_floor"]
    pinned = os.environ.get("SNIPER_NODE_PATH", "")
    problem = node_problem(pinned, floor)
    if problem:
        record("FAIL", "node", f"{problem} — run install/install.command")
        return
    found = shutil.which("node") or ""
    if os.path.realpath(found) != os.path.realpath(pinned):
        record("FAIL", "node", f"PATH finds {found or 'no node'}, not the installed {pinned}; "
               "the CLIs and workers would run a different Node — run install/install.command")
        return
    _, out, _ = run([pinned, "--version"], 30)
    components = release()["components"]
    major = out.strip().lstrip("v").split(".")[0]
    if major.isdigit() and int(major) in components.get("node_unsupported_majors", []):
        record("FAIL", "node", f"{out.strip()} is not supported by this release — install Node "
               f"{components['node_recommended']} (LTS), then run install/install.command")
        return
    record("PASS", "node", f"{out.strip()} at {pinned} (needs {floor}+); the CLIs and workers use it")


def check_provider_settings(record: Record) -> str:
    """Provider, app brain and models agree; returns the configured provider."""
    provider = os.environ.get("SNIPER_PROVIDER", "")
    brain = os.environ.get("SNIPER_BRAIN_PROVIDER", "")
    reasoning = os.environ.get("SNIPER_CODEX_REASONING", "")
    model = os.environ.get("SNIPER_CODEX_MODEL" if provider == "codex" else "SNIPER_CLAUDE_MODEL", "")
    if BRAIN_FOR.get(provider) != brain or not model or reasoning not in REASONING:
        record("FAIL", "editor brain settings", f"provider '{provider}', app brain '{brain}', model '{model}' "
               "disagree — run install/use-provider.command codex|claude")
        return provider
    record("PASS", "editor brain settings", f"{provider} for the app, the editor window and every edit; model {model}")
    return provider


def check_external_tools(record: Record) -> None:
    """Executables Sniper does not install, each tied to the feature that needs it."""
    for tool, formula, feature in EXTERNAL:
        path = shutil.which(tool)
        works = path is not None and run([path, "--help" if tool == "whisper-cli" else "--version"], 30)[0] == 0
        record("PASS" if works else "FAIL", tool,
               path if works else f"not found or not working — needed for {feature}: brew install {formula}")


def _last_json_object(text: str) -> dict | None:
    """The self-test's single JSON object (whole output, or its last line)."""
    for candidate in (text.strip(), (text.strip().splitlines() or [""])[-1]):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def check_media_admission(record: Record) -> None:
    """Run a generated sample through the product's real media admission.

    PASS only when app/scripts/producer/headless/native_admission_selftest.py exists,
    exits 0 and prints a JSON object whose "ok" is true. Anything else FAILS.
    """
    name = "media admission (real sample)"
    if not ADMISSION_SELFTEST.is_file():
        record("FAIL", name, f"{ADMISSION_SELFTEST.relative_to(PKG_ROOT)} is not in this package; "
               "footage admission is unverified")
        return
    python = APP / ".venv/bin/python3"
    code, out, err = run([str(python), "-B", str(ADMISSION_SELFTEST), "--json"], ADMISSION_TIMEOUT_S, APP)
    result = _last_json_object(out)
    if code == 0 and result is not None and result.get("ok") is True:
        record("PASS", name, str(result.get("detail", "admitted")))
        return
    detail = (result or {}).get("detail") or (err.strip().splitlines() or ["no result"])[-1]
    record("FAIL", name, f"exit {code}: {detail}")


def check_provider_admission(record: Record, provider: str) -> None:
    """The provider, through production admission. Never prints auth output."""
    node = os.environ.get("SNIPER_NODE_PATH") or "node"
    code, out, _ = run([node, "--import", "tsx", "scripts/infra/provider-admission.ts", "--provider", provider], 90, APP)
    try:
        report = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        record("FAIL", f"editor brain ({provider})", f"the admission check did not run (exit {code})")
        return
    advice = {"not-signed-in-or-not-subscription": f"sign in: install/sign-in.command {provider}",
              "wrong-version": "reinstall the pinned CLI: install/install.command",
              "cli-missing": "reinstall: install/install.command"}.get(report["reason"], report["detail"])
    record("PASS" if report["ready"] else "FAIL", f"editor brain ({provider})",
           f"{report['admittedVersion']} admitted and signed in" if report["ready"] else f"{report['reason']} — {advice}")
