"""Read local tool metadata for context discovery without installing or probing media."""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

MAX_METADATA_BYTES = 2 * 1024 * 1024
VERSION = re.compile(r"\d+\.\d+(?:\.\d+)?(?:[-+][a-zA-Z0-9.]+)?")
VERSION_OUTPUT = re.compile(r"(?<![\w.])v?(" + VERSION.pattern + r")(?![\w.])")
TOOLS = {"node": "--version", "ffmpeg": "-version", "ffprobe": "-version",
         "codex": "--version", "claude": "--version", "whisper-cli": None}
SKILLS = ("hyperframes", "general-video", "hyperframes-core", "hyperframes-cli",
          "hyperframes-registry", "hyperframes-animation", "hyperframes-audio",
          "hyperframes-creative", "hyperframes-keyframes", "media-use")


def file_record(path: Path) -> dict[str, Any]:
    """Distinguish path states with a one-byte readability check; never emit contents."""
    row = {"path": str(path), "status": "readable"}
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            return {**row, "status": "not-file"}
        with path.open("rb") as handle:
            handle.read(1)
        return {**row, "bytes": info.st_size}
    except FileNotFoundError:
        return {**row, "status": "broken-link" if path.is_symlink() else "missing"}
    except OSError as error:
        return {**row, "status": "unreadable", "errorType": type(error).__name__}


def json_record(path: Path) -> tuple[dict[str, Any], Any]:
    """Read bounded metadata; never include file content or exception text in errors."""
    row = file_record(path)
    if row["status"] != "readable":
        return row, None
    if row["bytes"] > MAX_METADATA_BYTES:
        return {**row, "status": "too-large"}, None
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_METADATA_BYTES + 1)
        if len(data) > MAX_METADATA_BYTES:
            return {**row, "status": "too-large"}, None
        return row, json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {**row, "status": "invalid-json"}, None
    except OSError as error:
        return {**row, "status": "unreadable", "errorType": type(error).__name__}, None


def package_record(path: Path) -> dict[str, Any]:
    """Report a package's installed version, not its declared dependency range."""
    row, data = json_record(path)
    value = data.get("version") if isinstance(data, dict) else None
    version = value if isinstance(value, str) and VERSION.fullmatch(value) else None
    return {**row, "version": version, "scope": "installed-metadata-only"}


def tool_record(name: str, probe: bool) -> dict[str, Any]:
    """Resolve PATH and optionally run a fixed bounded local version command."""
    path = shutil.which(name)
    row = {"name": name, "path": path, "status": "found" if path else "missing",
           "version": None, "versionProbe": "not-requested"}
    if not probe or not path or TOOLS[name] is None:
        return row
    try:
        result = subprocess.run([path, TOOLS[name]], capture_output=True,
                                timeout=3, check=False, text=True)
        match = VERSION_OUTPUT.search((result.stdout + result.stderr)[:4096])
        row["versionProbe"] = "pass" if result.returncode == 0 and match else "unavailable"
        row["version"] = match[1] if row["versionProbe"] == "pass" else None
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
        row["versionProbe"] = type(error).__name__
    return row


def codex_root() -> Path:
    """Use one configured absolute Codex root for global instructions and skills."""
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()


def skill_inventory(repo: Path) -> list[dict[str, Any]]:
    """Locate installed domain skills separately from archived vendored references."""
    home = Path.home()
    roots = (home / ".agents/skills", codex_root() / "skills")
    rows = [dict(name=name, origin="installed", **file_record(root / name / "SKILL.md"))
            for root in roots for name in SKILLS]
    rows.append(dict(name="hyperframes", origin="archived-reference",
                     **file_record(repo / "vendor/hyperframes-skills/hyperframes/SKILL.md")))
    return rows


def runtime_inventory(repo: Path) -> dict[str, Any]:
    """Read runtime metadata without calling the runtime installer or choosing a cache."""
    motion = repo / "templates/motion"
    patches, patch_data = json_record(repo / "scripts/producer/studio/runtime/patches.json")
    expected = patch_data.get("sdkVersion") if isinstance(patch_data, dict) else None
    expected = expected if isinstance(expected, str) and VERSION.fullmatch(expected) else None
    cache = motion / ".sniper-native-runtime"
    try:
        children = sorted(cache.iterdir())
        records = [package_record(child / "hyperframes/package.json") for child in children]
        cache_status = "readable"
    except FileNotFoundError:
        records, cache_status = [], "missing"
    except OSError:
        records, cache_status = [], "unreadable"
    return {"stock": package_record(motion / "node_modules/hyperframes/package.json"),
            "sdk": package_record(repo / "node_modules/@hyperframes/sdk/package.json"),
            "patches": patches, "expectedSdkVersion": expected,
            "adaptedRuntimeDirectory": str(cache), "adaptedRuntimeStatus": cache_status,
            "adaptedRuntimes": records, "selectedRuntime": None,
            "qualification": "not-checked; metadata presence is not render admission"}


def catalog_sources(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep merged executable source paths distinct from every upstream mirror source."""
    sources, mirror = [], []
    for row in records:
        sources.append(dict(ref=row["ref"], provenance=row["provenance"],
                            **file_record(Path(row["source"]["path"]))))
        upstream = row.get("upstream")
        if upstream:
            mirror.append(dict(ref="mirror:" + upstream["name"],
                               **file_record(Path(upstream["reference"]["absolutePath"]))))
    return sources, mirror


def source_counts(rows: list[dict]) -> dict[str, int]:
    """Count actual file read states rather than treating existence as readability."""
    return {status: sum(row["status"] == status for row in rows)
            for status in sorted({row["status"] for row in rows})}


def mirror_snapshot(mirror: dict) -> dict[str, Any]:
    """Expose recorded counts only; old boundary prose is not current route authority."""
    snapshot = {key: mirror.get(key) for key in ("itemsListed", "itemsInstalled", "files")
                if isinstance(mirror.get(key), int)}
    value = mirror.get("mirroredAt")
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        snapshot["mirroredAt"] = value
    snapshot["scope"] = "historical lock counts; not current availability or upstream freshness"
    return snapshot


def catalog_inventory(repo: Path) -> dict[str, Any]:
    """Reuse Producer's complete catalog loader and keep source read failures explicit."""
    from graphics.catalog_discovery import load_catalog
    from graphics.catalog_discovery_sources import DiscoveryPaths

    root = repo / "vendor/hyperframes-catalog"
    paths = DiscoveryPaths(str(root), str(repo / "docs/producer/catalog-study/catalog-study.json"))
    inputs = [file_record(root / name) for name in
              ("catalog-index.json", "hyperframes-catalog-lock.json")]
    inputs.append(file_record(Path(paths.study_path)))
    if any(row["status"] != "readable" for row in inputs):
        return {"status": "unavailable", "inputs": inputs}
    try:
        catalog = load_catalog(paths)
        sources, mirror = catalog_sources(catalog.records)
    except (OSError, ValueError, RuntimeError) as error:
        return {"status": "unavailable", "inputs": inputs, "errorType": type(error).__name__}
    return {"status": "read", "inputs": inputs, "items": len(catalog.records),
            "sourceStates": source_counts(sources),
            "mirrorSnapshot": mirror_snapshot(catalog.provenance["mirror"]),
            "currentMirrorSourceStates": source_counts(mirror),
            "currentMirrorSourceCount": len(mirror),
            "issueCount": len(catalog.provenance["issues"]),
            "disagreementCount": len(catalog.provenance["disagreements"]),
            "unavailableSources": [row for row in sources if row["status"] != "readable"],
            "unavailableMirrorSources": [row for row in mirror if row["status"] != "readable"],
            "scope": "local-recorded-inventory; not upstream freshness or native approval"}


def inventory(repo: Path, probe_tools: bool) -> dict[str, Any]:
    """Collect local inventory; provider authentication and environment secrets are unread."""
    return {"python": {"path": sys.executable, "version": sys.version.split()[0]},
            "venv": file_record(repo / ".venv/bin/python3"),
            "tools": [tool_record(name, probe_tools) for name in TOOLS],
            "hyperframes": runtime_inventory(repo), "skills": skill_inventory(repo),
            "catalog": catalog_inventory(repo)}
