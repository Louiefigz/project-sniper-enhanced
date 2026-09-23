"""Identity and exact jail profile of the native (macOS Seatbelt) media admission runtime.

The container route bound every receipt to one approved image. The native route
binds it to what actually runs: the approved profile template and launcher
(hashes listed in ``native_media_runtime_approval.json``), the buyer's decoder
executables and every non-OS library they load (hashed, read from the Mach-O
headers), and the macOS release. The jail profile is generated from the template
by listing exactly those files (every path dyld opens and every real path) and
their ancestor directories, so the decoder can read nothing else. Decoders come
from the local install (``HYPERFRAMES_FFPROBE_PATH`` / ``HYPERFRAMES_FFMPEG_PATH``).

    python3 -m headless.native_media_runtime --write-approval   # maintainer only
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from headless.native_macho import MachOError, dependency_paths

POLICY = "sniper-native-media-jail-v2"
HERE = Path(__file__).resolve().parent
PROFILE = HERE / "native_media_probe.sb"
LAUNCHER = HERE / "native_media_jail.py"
APPROVAL = HERE / "native_media_runtime_approval.json"
MIN_FFMPEG_MAJOR = 6  # -fps_mode (5.1+) and the decoders the probe relies on
_TOOL_ENV = {"ffprobe": "HYPERFRAMES_FFPROBE_PATH", "ffmpeg": "HYPERFRAMES_FFMPEG_PATH"}
_DEFAULT_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
_FILES_MARK, _DIRS_MARK = ";;@DECODER-FILES@", ";;@DECODER-DIRECTORIES@"
_UNSAFE = re.compile(r'["\\\x00-\x1f\x7f]')
_CACHE: dict[tuple, "NativeMediaRuntime"] = {}


class NativeRuntimeError(RuntimeError):
    """The native admission runtime is unavailable or not the approved one."""


@dataclass(frozen=True)
class NativeMediaRuntime:
    """Resolved decoders, the generated jail profile and the identity bound into receipts."""

    ffprobe: str
    ffmpeg: str
    profile_text: str
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
    """The maintainer-generated list of approved profile-template/launcher hashes."""
    value = json.loads(APPROVAL.read_text(encoding="utf-8"))
    rows = value.get("approved") if isinstance(value, dict) else None
    if value.get("schemaVersion") != 2 or value.get("policy") != POLICY or not isinstance(rows, list) or not rows:
        raise NativeRuntimeError("native media runtime approval is invalid")
    return value


def approved_pair(template_sha256: str, launcher_sha256: str) -> bool:
    """Whether a profile-template/launcher hash pair is listed in the shipped approval."""
    return any(row.get("profileTemplateSha256") == template_sha256 and row.get("launcherSha256") == launcher_sha256
               for row in read_approval()["approved"])


def _tool(name: str) -> str:
    """Absolute real path of one decoder executable."""
    configured = os.environ.get(_TOOL_ENV[name], "").strip()
    candidates = [configured] if configured else [os.path.join(d, name) for d in _DEFAULT_DIRS]
    for candidate in candidates:
        if os.path.isabs(candidate) and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return os.path.realpath(candidate)
    where = configured or " or ".join(candidates)
    raise NativeRuntimeError(f"{name} is not an executable at {where}; run install/install.command "
                             "(it repairs Sniper's own tools)")


def _ancestors(paths: frozenset[str]) -> list[str]:
    """Every ancestor directory of the listed files (for symlink traversal), excluding '/'."""
    found = set()
    for path in paths:
        parent = os.path.dirname(path)
        while parent not in ("", "/"):
            found.add(parent)
            parent = os.path.dirname(parent)
    return sorted(found)


def generate_profile(template: str, opened: frozenset[str]) -> str:
    """Fill the template with literal rules for exactly the decoder's files and their directories."""
    if template.count(_FILES_MARK) != 1 or template.count(_DIRS_MARK) != 1:
        raise NativeRuntimeError("native media jail template is malformed")
    listed = sorted(opened)
    if any(not os.path.isabs(path) or _UNSAFE.search(path) for path in listed):
        raise NativeRuntimeError("the decoder's library paths contain characters the jail cannot express")
    files = "\n".join(f'  (literal "{path}")' for path in listed)
    directories = "\n".join(f'  (literal "{path}")' for path in _ancestors(opened))
    return template.replace(_FILES_MARK, files).replace(_DIRS_MARK, directories)


def _closure_digest(images: list[str]) -> tuple[str, dict[str, str]]:
    """Digest over every loaded image, in path order."""
    hashes = {path: file_sha256(path) for path in sorted(images)}
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


def _identity(tools: tuple[str, str], profile_text: str, images: list[str], opened: int) -> dict:
    """The JSON identity recorded in every native admission receipt."""
    closure_sha, hashes = _closure_digest(images)
    return {
        "kind": "macos-seatbelt",
        "policy": POLICY,
        "profileTemplateSha256": file_sha256(PROFILE),
        "profileSha256": hashlib.sha256(profile_text.encode("utf-8")).hexdigest(),
        "launcherSha256": file_sha256(LAUNCHER),
        "platform": {"system": platform.system(), "release": os.uname().release,
                     "macos": platform.mac_ver()[0], "machine": os.uname().machine},
        "tools": {name: {"path": path, "sha256": hashes[path]} for name, path in zip(("ffprobe", "ffmpeg"), tools)},
        "closureSha256": closure_sha,
        "closureCount": len(images),
        "openedPathCount": opened,
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
        closure = dependency_paths(tools)
    except (MachOError, OSError, UnicodeDecodeError) as error:
        raise NativeRuntimeError(f"cannot read the decoder's libraries: {error}") from error
    profile_text = generate_profile(PROFILE.read_text(encoding="utf-8"), closure.opened)
    identity = _identity(tools, profile_text, list(closure.images), len(closure.opened))
    if not approved_pair(identity["profileTemplateSha256"], identity["launcherSha256"]):
        raise NativeRuntimeError("the native admission jail files are not the approved ones")
    runtime = NativeMediaRuntime(tools[0], tools[1], profile_text, identity)
    _CACHE[key] = runtime
    return runtime


def write_approval() -> dict:
    """Maintainer tool: approve the current profile template and launcher text."""
    row = {"profileTemplateSha256": file_sha256(PROFILE), "launcherSha256": file_sha256(LAUNCHER)}
    document = {"schemaVersion": 2, "policy": POLICY, "approved": [row]}
    APPROVAL.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


if __name__ == "__main__":
    if sys.argv[1:] != ["--write-approval"]:
        raise SystemExit("usage: python3 -m headless.native_media_runtime --write-approval")
    print(json.dumps(write_approval(), indent=2, sort_keys=True))
