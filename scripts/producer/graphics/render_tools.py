"""Executable resolution for HyperFrames render spawns (live vs sealed).

Live default: each of node/browser/ffmpeg/ffprobe honors an explicit env pin
when set, otherwise resolves deterministically at spawn to an absolute path —
``shutil.which`` for the CLI tools, the hyperframes/puppeteer browser caches
for chrome-headless-shell. The resolution is memoized per environment and
logged once, so one render session never mixes tool identities mid-flight.

Sealed mode (``SNIPER_RENDER_IMAGE_ID`` set): every pin is REQUIRED and
hard-fails when absent or non-executable. Sealed-render determinism guarantees
must never weaken — no discovery fallback exists on that path.
"""
from __future__ import annotations

import glob
import hashlib
import os
import platform
import shutil
import sys

_PINNED_TOOL_ENV = {
    "node": "SNIPER_NODE_PATH",
    "browser": "HYPERFRAMES_BROWSER_PATH",
    "ffmpeg": "HYPERFRAMES_FFMPEG_PATH",
    "ffprobe": "HYPERFRAMES_FFPROBE_PATH",
}
# Mirrors hyperframes' own cache resolution (its cache first, then puppeteer's).
_BROWSER_CACHE_ROOTS = (
    os.path.join("~", ".cache", "hyperframes", "chrome", "chrome-headless-shell"),
    os.path.join("~", ".cache", "puppeteer", "chrome-headless-shell"),
)
_memo: tuple[tuple[str, ...], dict[str, str]] | None = None


def _validated_pin(env_key: str, raw: str) -> str:
    """Validate one explicit env pin: absolute, real, executable — or raise."""
    if not raw or not os.path.isabs(raw):
        raise RuntimeError(f"{env_key} must be an absolute executable path")
    path = os.path.realpath(raw)
    if not os.path.isfile(path) or not os.access(path, os.X_OK):
        raise RuntimeError(f"{env_key} is not an executable file: {raw}")
    return path


def pinned_tools() -> dict[str, str]:
    """Resolve all four executables strictly from env pins (sealed mode)."""
    return {name: _validated_pin(env_key, os.environ.get(env_key, "").strip())
            for name, env_key in _PINNED_TOOL_ENV.items()}


def _platform_token() -> str:
    """This machine's cache-dir platform prefix (hyperframes/puppeteer layout)."""
    if sys.platform == "darwin":
        arm = platform.machine().lower() in ("arm64", "aarch64")
        return "mac_arm" if arm else "mac_x64"
    return "linux"


def _browser_rank(path: str) -> tuple[int, tuple[int, ...], str]:
    """Sort key: platform-matching build first, then numeric version, then path.

    The versioned dir two levels up is ``<platform>-<version>`` (e.g.
    ``mac_arm-152.0.7928.2``); numeric comparison keeps a future 4-digit
    Chrome major ordering correctly where lexicographic max would not.
    """
    version_dir = os.path.basename(os.path.dirname(os.path.dirname(path)))
    prefix, _, version = version_dir.partition("-")
    numbers = tuple(int(n) for n in version.split(".") if n.isdigit())
    return (1 if prefix == _platform_token() else 0, numbers, path)


def _discover_browser() -> str:
    """Best cached chrome-headless-shell binary from the known cache roots.

    Candidates are ranked by ``_browser_rank`` — a build matching this
    machine's platform always beats a foreign-arch one, newest numeric
    version wins within a platform — so the pick is deterministic for a
    given cache state. Raises when no cache holds a browser — Sniper never
    auto-downloads one mid-render.
    """
    for root in _BROWSER_CACHE_ROOTS:
        pattern = os.path.join(os.path.expanduser(root), "*", "*",
                               "chrome-headless-shell")
        found = [p for p in glob.glob(pattern)
                 if os.path.isfile(p) and os.access(p, os.X_OK)]
        if found:
            return os.path.realpath(max(found, key=_browser_rank))
    raise RuntimeError(
        "no cached chrome-headless-shell found; in the installed app run "
        "install/install.command to put the rendering browser back (in a developer "
        "checkout, run a hyperframes render once in templates/motion), or set "
        "HYPERFRAMES_BROWSER_PATH")


def _discovered_tool(name: str) -> str:
    """Absolute path for one tool via discovery (live default, no pin set)."""
    if name == "browser":
        return _discover_browser()
    found = shutil.which(name)
    if not found:
        raise RuntimeError(
            f"'{name}' not found on PATH and {_PINNED_TOOL_ENV[name]} is unset")
    return os.path.realpath(found)


def _resolve_live() -> dict[str, str]:
    """Per-tool: an explicit env pin wins; otherwise absolute discovery."""
    resolved: dict[str, str] = {}
    for name, env_key in _PINNED_TOOL_ENV.items():
        raw = os.environ.get(env_key, "").strip()
        resolved[name] = _validated_pin(env_key, raw) if raw else \
            _discovered_tool(name)
    return resolved


def live_tools_identity() -> bytes:
    """Cache-key digest of the resolved live tool set.

    Binds each resolved executable's absolute realpath plus its on-disk file
    identity (size + mtime_ns) so a render cache key can never alias across
    tool drift: a brew upgrade (new Cellar realpath), a newer cached
    chrome-headless-shell (new version dir), or an in-place binary swap all
    change this digest and force a re-render instead of a stale cache hit.
    """
    digest = hashlib.sha256(b"sniper-live-render-tools-v1\0")
    for name, path in sorted(resolve_tools().items()):
        info = os.stat(path)
        digest.update(
            f"{name}\0{path}\0{info.st_size}\0{info.st_mtime_ns}\0".encode())
    return digest.digest()


def resolve_tools() -> dict[str, str]:
    """Executable set for one render spawn (see module docstring).

    Returns:
        Mapping of ``node``/``browser``/``ffmpeg``/``ffprobe`` to resolved
        absolute executable paths.

    Raises:
        RuntimeError: sealed mode with a missing/invalid pin, an invalid
            explicit live pin, or a live tool that discovery cannot find.
    """
    global _memo
    if os.environ.get("SNIPER_RENDER_IMAGE_ID"):
        return pinned_tools()
    key = tuple(os.environ.get(k, "")
                for k in (*_PINNED_TOOL_ENV.values(), "PATH"))
    if _memo is not None and _memo[0] == key:
        return dict(_memo[1])
    resolved = _resolve_live()
    _memo = (key, resolved)
    if os.environ.get("SNIPER_DEBUG", "1") != "0":
        pairs = " ".join(f"{n}={p}" for n, p in sorted(resolved.items()))
        print(f"[SNIPER:graphics] render tools resolved: {pairs}",
              file=sys.stderr)
    return dict(resolved)
