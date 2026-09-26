"""Resolve and identify the approved Windows AppContainer admission runtime."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

POLICY = "sniper-windows-appcontainer-v1"
HERE = Path(__file__).resolve().parent
APPROVAL = HERE / "windows_media_runtime_approval.json"
SOURCES = (HERE / "windows_media_jail.cs", HERE / "windows_media_inspect.cs")
_TOOLS = {"ffprobe": "HYPERFRAMES_FFPROBE_PATH", "ffmpeg": "HYPERFRAMES_FFMPEG_PATH"}
_CACHE = None


def _sha(path: Path) -> str:
    """SHA-256 of one regular file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_from_env(name: str, variable: str) -> Path:
    """Resolve an absolute executable named by an installer setting."""
    value = Path(os.environ.get(variable, ""))
    if not value.is_absolute() or not value.is_file():
        raise RuntimeError(f"{name} is missing at {value}; run sniper.cmd setup")
    return value.resolve()


def _approved_sources() -> dict[str, str]:
    """Verify the shipped C# sources against the maintainer approval."""
    value = json.loads(APPROVAL.read_text(encoding="utf-8"))
    approved = value.get("approved", {})
    if value.get("schemaVersion") != 1 or value.get("policy") != POLICY:
        raise RuntimeError("Windows media runtime approval is invalid")
    found = {path.name: _sha(path) for path in SOURCES}
    if found != approved:
        raise RuntimeError("Windows media jail source is not approved")
    return found


def required_windows_runtime(runtime_type):
    """Return a NativeMediaRuntime compatible object, or fail closed."""
    global _CACHE
    ffprobe = _file_from_env("ffprobe", _TOOLS["ffprobe"])
    ffmpeg = _file_from_env("ffmpeg", _TOOLS["ffmpeg"])
    jail = _file_from_env("Windows media jail", "SNIPER_WINDOWS_MEDIA_JAIL")
    inspect = _file_from_env("Windows media inspector", "SNIPER_WINDOWS_MEDIA_INSPECT")
    source_hashes = _approved_sources()
    key = tuple((str(path), path.stat().st_size, path.stat().st_mtime_ns)
                for path in (ffprobe, ffmpeg, jail, inspect, *SOURCES, APPROVAL))
    if _CACHE and _CACHE[0] == key:
        return _CACHE[1]
    sid = subprocess.run([str(jail), "sid"], capture_output=True, text=True, timeout=30, check=False)
    if sid.returncode or not sid.stdout.strip().startswith("S-1-15-2-"):
        raise RuntimeError(f"Windows media AppContainer is unavailable: {sid.stderr.strip()}")
    files = {str(path): _sha(path) for path in (ffprobe, ffmpeg, jail, inspect)}
    policy_hash = hashlib.sha256(json.dumps({"sources": source_hashes, "files": files},
                                            sort_keys=True).encode()).hexdigest()
    identity = {
        "kind": "windows-appcontainer", "policy": POLICY, "profileSha256": policy_hash,
        "platform": {"system": platform.system(), "release": platform.release(),
                     "version": platform.version(), "machine": platform.machine()},
        "appContainerSid": sid.stdout.strip(), "sourceSha256": source_hashes,
        "launcher": {"path": str(jail), "sha256": files[str(jail)]},
        "inspector": {"path": str(inspect), "sha256": files[str(inspect)]},
        "tools": {"ffprobe": {"path": str(ffprobe), "sha256": files[str(ffprobe)]},
                  "ffmpeg": {"path": str(ffmpeg), "sha256": files[str(ffmpeg)]}},
    }
    runtime = runtime_type(str(ffprobe), str(ffmpeg), "", identity)
    _CACHE = (key, runtime)
    return runtime
