"""A minimal extracted-package layout for exercising the real installer scripts.

It copies the shipped ``install/`` folder and the shared lock helper exactly as the
build ships them, adds a RELEASE.json with the fields the scripts read, and puts
stub ``codex``/``claude`` CLIs where the installer would. The stubs never reach a
network or a real login: they record their argv and the provider environment,
and their login/logout behaviour is scripted per test through files.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALL_SRC = ROOT / "release/payload_files/install"
LOCK_SRC = ROOT / "scripts/infra/sniper_lock.py"
FINDER_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
COMPONENTS = {"node_floor": "22.13.0", "node_recommended": "24", "node_unsupported_majors": [23],
              "claude_model_default": "opus", "codex_model_default": "gpt-5.6-sol",
              "codex_reasoning_default": "xhigh", "python_tested": "3.14.4",
              "codex_cli_admitted": "codex-cli 0.144.1", "claude_cli_admitted": "2.1.247 (Claude Code)",
              "chrome_headless_shell": "152.0.7977.30"}

STUB_CLI = r'''#!/bin/bash
# Test stand-in for a provider CLI: records what it was asked, never signs anything in or out.
me="${0##*/}"; log="$STUB_LOG_DIR/$me.calls"
{ printf 'ARGV'; printf ' [%s]' "$@"; printf '\n'
  printf 'ENV SNIPER_PROVIDER=%s SNIPER_BRAIN_PROVIDER=%s SNIPER_CLAUDE_MODEL=%s SNIPER_CODEX_MODEL=%s SNIPER_CODEX_REASONING=%s LOCK=%s\n' \
    "$SNIPER_PROVIDER" "$SNIPER_BRAIN_PROVIDER" "$SNIPER_CLAUDE_MODEL" "$SNIPER_CODEX_MODEL" "$SNIPER_CODEX_REASONING" "$SNIPER_LOCK_MODE"
} >> "$log"
state="$STUB_LOG_DIR/$me.signed-in"
case "$*" in
  "login status") [ -f "$state" ] && { echo "Logged in using ChatGPT"; exit 0; }; echo "Not logged in"; exit 1 ;;
  "auth status --json") [ -f "$state" ] && { echo '{"loggedIn": true}'; exit 0; }; echo '{"loggedIn": false}'; exit 1 ;;
  "logout"|"auth logout")
    [ -f "$STUB_LOG_DIR/$me.logout-fails" ] && { echo "network error: could not reach the sign-out service" >&2; exit 1; }
    rm -f "$state"; echo "Logged out"; exit 0 ;;
  "--version") [ "$me" = codex ] && echo "codex-cli 0.144.1" || echo "2.1.247 (Claude Code)"; exit 0 ;;
esac
exit 0
'''


def make_package(base: Path, name: str = "pkg") -> Path:
    """Create ``base/name`` laid out like an extracted archive; return its root."""
    pkg = base / name
    shutil.copytree(INSTALL_SRC, pkg / "install")
    (pkg / "app/scripts/infra").mkdir(parents=True)
    shutil.copyfile(LOCK_SRC, pkg / "app/scripts/infra/sniper_lock.py")
    (pkg / "RELEASE.json").write_text(json.dumps({"version": "0.1.0-test", "components": COMPONENTS,
                                                  "sellable": False}), encoding="utf-8")
    runtime_bin = pkg / "runtime/bin"
    runtime_bin.mkdir(parents=True)
    (runtime_bin / "node").write_text('#!/bin/bash\necho v24.0.0\n', encoding="utf-8")
    (runtime_bin / "node").chmod(0o755)
    bin_dir = pkg / "runtime/cli/node_modules/.bin"
    bin_dir.mkdir(parents=True)
    for cli in ("codex", "claude"):
        (bin_dir / cli).write_text(STUB_CLI, encoding="utf-8")
        (bin_dir / cli).chmod(0o755)
    return pkg


def bash(pkg: Path, script: str, env: dict[str, str] | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a bash snippet that has sourced the package's real lib/common.sh (and configure.sh)."""
    prelude = '. "$FIXTURE_PKG/install/lib/common.sh" || exit 1\n. "$FIXTURE_PKG/install/lib/configure.sh" || exit 1\n'
    return subprocess.run(["/bin/bash", "-c", prelude + script], capture_output=True, text=True,
                          timeout=timeout, env={**(env or base_env(pkg)), "FIXTURE_PKG": str(pkg)}, check=False)


def base_env(pkg: Path) -> dict[str, str]:
    """An empty-HOME, Finder-PATH environment, plus where the stub CLIs log."""
    home = pkg.parent / "home"
    home.mkdir(exist_ok=True)
    logs = pkg.parent / "stub-logs"
    logs.mkdir(exist_ok=True)
    return {"HOME": str(home), "PATH": FINDER_PATH, "USER": os.environ.get("USER", "test"),
            "STUB_LOG_DIR": str(logs), "TMPDIR": os.environ.get("TMPDIR", "/tmp")}


def write_settings(pkg: Path, provider: str, workspace: str, extra: dict[str, str] | None = None
                   ) -> subprocess.CompletedProcess:
    """Run the installer's own configuration functions with test values for earlier steps."""
    values = {"NODE_BIN": "/opt/homebrew/bin/node", "TOOL_FFMPEG": "/opt/homebrew/bin/ffmpeg",
              "TOOL_FFPROBE": "/opt/homebrew/bin/ffprobe", "TOOL_WHISPER_CLI": "/opt/homebrew/bin/whisper-cli",
              "BROWSER_BIN": str(pkg / "runtime/browser/chrome-headless-shell"),
              "MODEL_PATH": str(pkg / "runtime/whisper/ggml-small.en.bin"),
              "PROVIDER_ARG": provider, "WORKSPACE_ARG": workspace, **(extra or {})}
    assign = "".join(f'{key}="${{T_{key}}}"\n' for key in values)
    env = {**base_env(pkg), **{f"T_{key}": value for key, value in values.items()}}
    script = assign + 'mkdir -p "$RUNTIME_DIR" && choose_provider && write_settings && verify_settings && echo configured\n'
    return bash(pkg, script, env)
