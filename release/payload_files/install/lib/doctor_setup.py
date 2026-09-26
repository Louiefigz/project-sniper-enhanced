"""Doctor checks for how this install is set up: Node, Sniper's own tools, media admission.

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
APP = PKG_ROOT   # the app is the package folder itself
ADMISSION_SELFTEST = APP / "scripts/producer/headless/native_admission_selftest.py"
ADMISSION_TIMEOUT_S = 600
# Sniper's own tools (install/lib/runtime_tools.sh): name, arguments that make it report
# itself, and what refuses to run without it.
RUNTIME_TOOLS = (("ffmpeg", ["-hide_banner", "-version"], "every render"),
                 ("ffprobe", ["-hide_banner", "-version"], "every render"),
                 ("whisper-cli", ["--help"], "local transcription"),
                 ("tesseract", ["--version"], "reference study (reading on-screen text)"),
                 ("yt-dlp", ["--version"], "adding a reference from a URL"),
                 ("node", ["--version"], "rendering and Sniper's scripts"),
                 (("python.exe" if os.name == "nt" else "python3"), ["--version"], "the editing engine"),
                 ("git", ["--version"], "Sniper's tool set (unused since Sniper stopped installing its own Codex/Claude; dropped at the next tool refresh)"))
# What the tools write after installation; must match deps_tree_excludes in runtime_tools.sh.
RUNTIME_EXCLUDES = {"var/cache/fontconfig", ".sniper-users", "name:__pycache__", "file:.sniper-runtime-complete"}
Record = Callable[[str, str, str], None]
SETUP_COMMAND = "sniper.cmd setup" if os.name == "nt" else "install/install.command"


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
    expected = "node.exe" if os.name == "nt" else "node"
    if (os.name != "nt" and any(ch.isspace() for ch in path)) or os.path.basename(path).lower() != expected:
        return f"{path} must name Sniper's {expected} executable"
    return None


def check_node(record: Record) -> None:
    """The ONE Node the installer validated: present, new enough, and what PATH finds."""
    floor = release()["components"]["node_floor"]
    pinned = os.environ.get("SNIPER_NODE_PATH", "")
    problem = node_problem(pinned, floor)
    if problem:
        record("FAIL", "node", f"{problem} — run {SETUP_COMMAND}")
        return
    found = shutil.which("node") or ""
    if os.path.realpath(found) != os.path.realpath(pinned):
        record("FAIL", "node", f"PATH finds {found or 'no node'}, not the installed {pinned}; "
               f"Sniper's commands and renders would run a different Node — run {SETUP_COMMAND}")
        return
    _, out, _ = run([pinned, "--version"], 30)
    prefix = os.environ.get("SNIPER_DEPS_PREFIX", "")
    if not prefix or os.path.commonpath((os.path.realpath(pinned), os.path.realpath(prefix))) != os.path.realpath(prefix):
        record("FAIL", "node", f"{pinned} is not Sniper's own Node — run {SETUP_COMMAND}")
        return
    record("PASS", "node", f"{out.strip()} at {pinned} (needs {floor}+); Sniper's commands and renders use it")


def check_runtime_tools(record: Record) -> None:
    """Sniper's own tools: exactly as installed, found first on the app's PATH, and each runs."""
    import install_tools  # noqa: PLC0415  (same folder; stdlib only)
    prefix = Path(os.environ.get("SNIPER_DEPS_PREFIX", "/nonexistent"))
    fix = f"run {SETUP_COMMAND} (it reinstalls Sniper's tools)"
    try:
        want = json.loads((prefix.parent / f"{prefix.name}.tree.json").read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError):
        record("FAIL", "Sniper's own tools", f"not installed at {prefix} — {fix}")
        return
    have = install_tools.tree_digests(prefix, RUNTIME_EXCLUDES) if prefix.is_dir() else {}
    changed = sum(1 for k, v in want.items() if have.get(k) != v) + sum(1 for k in have if k not in want)
    record("FAIL" if changed else "PASS", "Sniper's own tools",
           f"{changed} file(s) differ from what was installed — {fix}" if changed
           else f"{len(want)} files verified in {prefix}")
    for tool, args, feature in RUNTIME_TOOLS:
        found = shutil.which(tool) or ""
        real = os.path.realpath(found) if found else ""
        if not real or os.path.commonpath((real, os.path.realpath(prefix))) != os.path.realpath(prefix):
            record("FAIL", tool, f"PATH finds {found or 'nothing'}, not Sniper's own — needed for {feature}: {fix}")
            continue
        code, out, err = run([found, *args], 60)
        first = ((out or err).strip().splitlines() or [""])[0][:80]
        record("PASS" if code == 0 else "FAIL", tool, f"{first} ({real})" if code == 0 else f"does not run: {first} — {fix}")


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

    PASS only when scripts/producer/headless/native_admission_selftest.py exists,
    exits 0 and prints a JSON object whose "ok" is true. Anything else FAILS.
    """
    name = "media admission (real sample)"
    if not ADMISSION_SELFTEST.is_file():
        record("FAIL", name, f"{ADMISSION_SELFTEST.relative_to(PKG_ROOT)} is not in this package; "
               "footage admission is unverified")
        return
    python = APP / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python3")
    code, out, err = run([str(python), "-B", str(ADMISSION_SELFTEST), "--json"], ADMISSION_TIMEOUT_S, APP)
    result = _last_json_object(out)
    if code == 0 and result is not None and result.get("ok") is True:
        record("PASS", name, str(result.get("detail", "admitted")))
        return
    detail = (result or {}).get("detail") or (err.strip().splitlines() or ["no result"])[-1]
    record("FAIL", name, f"exit {code}: {detail}")
