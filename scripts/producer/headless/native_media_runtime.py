"""Identity of the native (macOS Seatbelt) media admission runtime.

The container route bound every receipt to one approved image. The native route
binds it to what actually ran: the approved jail profile and launcher (hashes
listed in ``native_media_runtime_approval.json``), the buyer's decoder
executables and every non-OS library they load (hashed, read from the Mach-O
headers), and the macOS release. Decoders come from the local install
(``HYPERFRAMES_FFPROBE_PATH`` / ``HYPERFRAMES_FFMPEG_PATH``, which the installer
writes), so the identity is recorded per admission rather than pinned in advance.

    python3 -m headless.native_media_runtime --write-approval   # maintainer only
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from headless.native_macho import MachOError, dependency_closure

POLICY = "sniper-native-media-jail-v1"
HERE = Path(__file__).resolve().parent
PROFILE = HERE / "native_media_probe.sb"
LAUNCHER = HERE / "native_media_jail.py"
APPROVAL = HERE / "native_media_runtime_approval.json"
MIN_FFMPEG_MAJOR = 6  # -fps_mode (5.1+) and the decoders the probe relies on
_TOOL_ENV = {"ffprobe": "HYPERFRAMES_FFPROBE_PATH", "ffmpeg": "HYPERFRAMES_FFMPEG_PATH"}
_DEFAULT_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
_CACHE: dict[tuple, "NativeMediaRuntime"] = {}


class NativeRuntimeError(RuntimeError):
    """The native admission runtime is unavailable or not the approved one."""


@dataclass(frozen=True)
class NativeMediaRuntime:
    """Resolved decoder paths, jail roots and the identity bound into receipts."""

    ffprobe: str
    ffmpeg: str
    library_root: str
    link_root: str
    identity: dict


def file_sha256(path: str | Path) -> str:
    """SHA-256 of one regular file, read without following a final symlink."""
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise NativeRuntimeError(f"{path} is not a regular file")
        while chunk := os.read(descriptor, 1 << 20):
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def read_approval() -> dict:
    """The maintainer-generated list of approved jail profile/launcher hashes."""
    value = json.loads(APPROVAL.read_text(encoding="utf-8"))
    rows = value.get("approved") if isinstance(value, dict) else None
    if value.get("schemaVersion") != 1 or value.get("policy") != POLICY or not isinstance(rows, list) or not rows:
        raise NativeRuntimeError("native media runtime approval is invalid")
    return value


def approved_pair(profile_sha256: str, launcher_sha256: str) -> bool:
    """Whether a profile/launcher hash pair is listed in the shipped approval."""
    return any(row.get("profileSha256") == profile_sha256 and row.get("launcherSha256") == launcher_sha256
               for row in read_approval()["approved"])


def _tool(name: str) -> str:
    """Absolute real path of one decoder executable."""
    configured = os.environ.get(_TOOL_ENV[name], "").strip()
    candidates = [configured] if configured else [os.path.join(d, name) for d in _DEFAULT_DIRS]
    for candidate in candidates:
        if os.path.isabs(candidate) and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return os.path.realpath(candidate)
    where = configured or " or ".join(candidates)
    raise NativeRuntimeError(f"{name} is not an executable at {where}; install ffmpeg (brew install ffmpeg)")


def _roots(tools: tuple[str, str], closure: dict[str, str]) -> tuple[str, str]:
    """Library/link roots the jail may read; refuse layouts it cannot contain."""
    for prefix in ("/opt/homebrew", "/usr/local"):
        cellar = prefix + "/Cellar/"
        if all(path.startswith(cellar) for path in closure):
            return prefix + "/Cellar", prefix + "/opt"
    own = os.path.dirname(os.path.dirname(tools[0]))
    if own != "/" and all(path.startswith(own + "/") for path in closure):
        return own, own
    raise NativeRuntimeError("ffmpeg loads libraries from outside its own install tree; "
                             "use the Homebrew build (brew install ffmpeg)")


def _closure_digest(closure: dict[str, str]) -> tuple[str, dict[str, str]]:
    """Digest over every image in the closure, in path order."""
    hashes = {path: file_sha256(path) for path in sorted(closure)}
    digest = hashlib.sha256()
    for path, value in hashes.items():
        digest.update(f"{path}\0{value}\n".encode("utf-8"))
    return digest.hexdigest(), hashes


def _cache_key(tools: tuple[str, str]) -> tuple:
    """Invalidate the cached identity when either executable or the policy files change."""
    rows = []
    for path in (*tools, str(PROFILE), str(LAUNCHER), str(APPROVAL)):
        info = os.stat(path)
        rows.append((path, info.st_ino, info.st_size, info.st_mtime_ns))
    return tuple(rows)


def _identity(tools: tuple[str, str], roots: tuple[str, str], closure: dict[str, str]) -> dict:
    """The JSON identity recorded in every native admission receipt."""
    closure_sha, hashes = _closure_digest(closure)
    return {
        "kind": "macos-seatbelt",
        "policy": POLICY,
        "profileSha256": file_sha256(PROFILE),
        "launcherSha256": file_sha256(LAUNCHER),
        "platform": {"system": platform.system(), "release": os.uname().release,
                     "macos": platform.mac_ver()[0], "machine": os.uname().machine},
        "tools": {name: {"path": path, "sha256": hashes[path]} for name, path in zip(("ffprobe", "ffmpeg"), tools)},
        "libraryRoot": roots[0],
        "linkRoot": roots[1],
        "closureSha256": closure_sha,
        "closureCount": len(closure),
    }


def required_native_runtime() -> NativeMediaRuntime:
    """Resolve and identify the native admission runtime, or refuse with the reason."""
    if sys.platform != "darwin":
        raise NativeRuntimeError("native media admission needs macOS")
    tools = (_tool("ffprobe"), _tool("ffmpeg"))
    key = _cache_key(tools)
    if key in _CACHE:
        return _CACHE[key]
    try:
        closure = dependency_closure(tools)
    except (MachOError, OSError, UnicodeDecodeError) as error:
        raise NativeRuntimeError(f"cannot read the decoder's libraries: {error}") from error
    roots = _roots(tools, closure)
    identity = _identity(tools, roots, closure)
    if not approved_pair(identity["profileSha256"], identity["launcherSha256"]):
        raise NativeRuntimeError("the native admission jail files are not the approved ones")
    runtime = NativeMediaRuntime(tools[0], tools[1], roots[0], roots[1], identity)
    _CACHE[key] = runtime
    return runtime


def write_approval() -> dict:
    """Maintainer tool: approve the current profile and launcher text."""
    row = {"profileSha256": file_sha256(PROFILE), "launcherSha256": file_sha256(LAUNCHER)}
    document = {"schemaVersion": 1, "policy": POLICY, "approved": [row]}
    APPROVAL.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


if __name__ == "__main__":
    if sys.argv[1:] != ["--write-approval"]:
        raise SystemExit("usage: python3 -m headless.native_media_runtime --write-approval")
    print(json.dumps(write_approval(), indent=2, sort_keys=True))
