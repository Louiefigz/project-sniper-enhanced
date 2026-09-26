"""Build, read and verify Sniper's locked private tool runtimes.

Each target lock pins micromamba, every conda archive, and FFmpeg by byte size and
SHA-256. macOS carries the custom FFmpeg archive; Windows downloads the pinned
BtbN archive. The installer checks every byte before offline installation.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from release import macho_floor
from release.runtime_lock import (
    LockFormatError,
    conda_rows_sha256,
    file_sha256,
    read_lock,
)
from release.runtime_target import RuntimeTarget, SUPPORTED, target as runtime_target

HERE = Path(__file__).resolve().parent
DEPS = HERE / "runtime_deps"
DIST = DEPS / "dist"
SPECS = DEPS / "specs.txt"
CHANNEL = "https://conda.anaconda.org/conda-forge"
MICROMAMBA = {
    "osx-arm64": {"version": "2.9.0", "file": "micromamba-2.9.0-0.tar.bz2", "bytes": 6648894,
                   "sha256": "500f5074feb8d02c4296ef9921c3650ed2874171805a9fbb8fbb53896433646b"},
    "osx-64": {"version": "2.9.0", "file": "micromamba-2.9.0-0.tar.bz2", "bytes": 6804238,
               "sha256": "0426ecdc41636d369f57b8fe6acbf4385a69eca45b56d9ee7d3a840a9965d44f"},
    "win-64": {"version": "2.9.0", "file": "micromamba-2.9.0-0.tar.bz2", "bytes": 4572807,
               "sha256": "97a336f4ab794bd96a6a4da5e6ed63e75a1d31830414a182419b23d3b36f3fe0"},
}
TOOLS = ("python", "nodejs", "whisper.cpp", "tesseract", "yt-dlp", "git")
HEADER = "# sniper-runtime-lock-v1"
_DEFAULT_TARGET = runtime_target("osx-arm64")
# Compatibility aliases used by retained release tests and downstream tooling.
LOCK, LOCK_JSON = _DEFAULT_TARGET.lock, _DEFAULT_TARGET.lock_json
FFMPEG_PIN, MEASURED = _DEFAULT_TARGET.ffmpeg_pin, _DEFAULT_TARGET.measured
LockError = LockFormatError


def _micromamba_rel(platform: str) -> str:
    """Executable path inside the platform's conda package."""
    return "Library/bin/micromamba.exe" if platform == "win-64" else "bin/micromamba"


def _download(url: str, target: Path, sha256: str) -> Path:
    """Fetch ``url`` to ``target`` unless an identical file is there; verify the hash."""
    if target.exists() and file_sha256(target) == sha256:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response, target.open("wb") as handle:
        handle.write(response.read())
    if file_sha256(target) != sha256:
        target.unlink()
        raise LockError(f"{url} does not match its pinned SHA-256")
    return target


def micromamba_binary(target: RuntimeTarget) -> tuple[Path, str]:
    """The pinned micromamba, extracted under dist/tools; returns (binary, binary sha256)."""
    pin = MICROMAMBA[target.platform]
    archive = _download(f"{CHANNEL}/{target.platform}/{pin['file']}",
                        DIST / "tools" / target.platform / pin["file"], pin["sha256"])
    folder = DIST / "tools" / target.platform / f"micromamba-{pin['version']}"
    binary = folder / _micromamba_rel(target.platform)
    if not binary.exists():
        with tarfile.open(archive, "r:bz2") as bundle:
            bundle.extractall(folder, filter="data")
    return binary, file_sha256(binary)


def _solve(binary: Path, specs: list[str], platform: str) -> list[dict]:
    """Dry-run solve ``specs`` for one target, isolated from user config."""
    with tempfile.TemporaryDirectory(prefix="sniper-solve-") as scratch:
        env = {"HOME": scratch, "PATH": "/usr/bin:/bin", "MAMBA_ROOT_PREFIX": f"{scratch}/root"}
        done = subprocess.run([str(binary), "create", "--no-rc", "-y", "--dry-run", "--json",
                               "-p", f"{scratch}/env", "--override-channels", "-c", "conda-forge",
                               "--platform", platform, *specs],
                              capture_output=True, text=True, env=env, check=False)
    try:
        return json.loads(done.stdout)["actions"]["LINK"]
    except (ValueError, KeyError) as error:
        raise LockError(f"the solve failed: {done.stdout[-600:]}{done.stderr[-600:]}") from error


def _wheels_min_macos(platform: str) -> str:
    """The macOS floor of the pinned Python wheels, as their lock's header states it."""
    header = (HERE / "payload_files/install/requirements.lock.txt").read_text(encoding="utf-8")[:600]
    architecture = "arm64" if platform == "osx-arm64" else "x86_64"
    match = re.search(rf"macOS (\d+)\+ {architecture}", header)
    if not match:
        raise LockError("install/requirements.lock.txt does not state its arm64 macOS floor")
    return f"{match.group(1)}.0"


def min_macos(packages: list[dict], platform: str = "osx-arm64") -> str:
    """The newest macOS any package requires (``__osx >=``), or the Python wheels need."""
    found = ["11.0", _wheels_min_macos(platform)]
    for package in packages:
        for dep in package.get("depends", []):
            match = re.match(r"__osx\s*>=\s*([\d.]+)$", dep)
            if match:
                found.append(match.group(1))
    return max(found, key=lambda v: tuple(int(p) for p in v.split(".")))


def _ffmpeg_row(target: RuntimeTarget) -> list[str]:
    """The lock row for the shipped Sniper ffmpeg, or none before its first pinned build."""
    artifact = json.loads(target.ffmpeg_pin.read_text(encoding="utf-8"))["artifact"]
    if not artifact["sha256"]:
        return []
    source = artifact.get("source_url", f"install/deps/{artifact['file']}")
    kind = "download" if "source_url" in artifact else "local"
    return [f"{kind} {artifact['sha256']} {artifact['bytes']} {artifact['file']} {source}"]


def write_lock(packages: list[dict], bin_sha: str, binary: Path, target: RuntimeTarget) -> None:
    """Write the bash-readable lock and its JSON companion, sorted and stable."""
    packages = sorted(packages, key=lambda p: p["fn"])
    tools = {p["name"]: p["version"] for p in packages if p["name"] in TOOLS}
    pin = MICROMAMBA[target.platform]
    floor = min_macos(packages, target.platform) if target.is_macos else "10.0.19045"
    floor_key = "min-macos" if target.is_macos else "min-windows"
    lines = [f"{HEADER} — written by python -m release.runtime_tools; do not edit",
             f"# platform {target.platform}", f"# {floor_key} {floor}",
             "# tools " + " ".join(f"{name}={tools[name]}" for name in TOOLS),
             "# kind sha256 bytes path source",
             f"micromamba {pin['sha256']} {pin['bytes']} tools/{pin['file']} "
             f"{CHANNEL}/{target.platform}/{pin['file']}",
             f"micromamba-bin {bin_sha} {binary.stat().st_size} "
             f"{_micromamba_rel(target.platform)} -"]
    lines += [f"conda {p['sha256']} {p['size']} conda-forge/{p['subdir']}/{p['fn']} {p['url']}" for p in packages]
    lines += _ffmpeg_row(target)
    target.lock.parent.mkdir(parents=True, exist_ok=True)
    target.lock.write_text("\n".join(lines) + "\n", encoding="utf-8")
    floor_record = {"min_macos": floor} if target.is_macos else {"min_windows": floor}
    record = {"platform": target.platform, **floor_record, "tools": tools,
              "micromamba": pin["version"],
              "packages": [{"name": p["name"], "version": p["version"], "build": p["build_string"],
                            "license": p.get("license") or "", "file": p["fn"]} for p in packages]}
    target.lock_json.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def solve(target: RuntimeTarget = _DEFAULT_TARGET) -> None:
    """Resolve specs.txt once and freeze the result."""
    specs_path = DEPS / ("specs-win-64.txt" if target.platform == "win-64" else "specs.txt")
    specs = [line.strip() for line in specs_path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    binary, bin_sha = micromamba_binary(target)
    solver = binary if target.platform != "win-64" else micromamba_binary(_DEFAULT_TARGET)[0]
    packages = _solve(solver, specs, target.platform)
    unexpected = [p["name"] for p in packages if p["name"] == "ffmpeg"]
    if unexpected:
        raise LockError("the solve pulled in conda-forge's ffmpeg; the runtime uses the Sniper build only")
    write_lock(packages, bin_sha, binary, target)
    floor = min_macos(packages, target.platform) if target.is_macos else "10.0.19045"
    print(f"{target.lock.relative_to(HERE.parent)}: {len(packages)} packages, "
          f"{sum(p['size'] for p in packages) / 1e6:.0f} MB, minimum OS {floor}")


def pin_ffmpeg(target: RuntimeTarget = _DEFAULT_TARGET) -> None:
    """Record the SHA-256 and size of dist/<artifact> in the pin and the lock."""
    pin = json.loads(target.ffmpeg_pin.read_text(encoding="utf-8"))
    artifact = DIST / pin["artifact"]["file"]
    if not artifact.exists():
        raise LockError(f"{artifact} is missing; run release/runtime_deps/build_ffmpeg.sh")
    pin["artifact"].update(sha256=file_sha256(artifact), bytes=artifact.stat().st_size)
    target.ffmpeg_pin.write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
    header_lines = [line for line in target.lock.read_text(encoding="utf-8").splitlines()
                    if not line.startswith("local ")]
    target.lock.write_text("\n".join(header_lines + _ffmpeg_row(target)) + "\n", encoding="utf-8")
    print(f"pinned {artifact.name} {pin['artifact']['sha256']}")


def measure(prefix: Path, target: RuntimeTarget = _DEFAULT_TARGET) -> None:
    """Measure the macOS floor of ``prefix`` (an installed runtime of this lock's packages) and
    raise the lock's ``min-macos`` to it when the binaries need more than the metadata says."""
    if not target.is_macos:
        raise LockError("binary minimum-OS measurement is currently defined only for macOS targets")
    header, rows = read_lock(target.lock)
    wanted = {row["sha256"] for row in rows if row["kind"] == "conda"}
    installed = {json.loads(meta.read_text(encoding="utf-8")).get("sha256")
                 for meta in (prefix / "conda-meta").glob("*.json")}
    if wanted - installed:
        raise LockError(f"{prefix} is not an install of this lock: {len(wanted - installed)} of its "
                        "packages are missing (install/install.command installs it)")
    floor, set_by, count = macho_floor.folder_floor(prefix, target.platform)
    if not count:
        raise LockError(f"{prefix} has no Mach-O files to measure")
    target.measured.write_text(json.dumps({"conda_rows_sha256": conda_rows_sha256(rows), "min_macos": floor,
                                           "set_by": set_by, "macho_files": count}, indent=1) + "\n",
                               encoding="utf-8")
    new = max(header["min-macos"], floor, key=macho_floor.version_key)
    target.lock.write_text(target.lock.read_text(encoding="utf-8").replace(
        f"# min-macos {header['min-macos']}\n", f"# min-macos {new}\n", 1), encoding="utf-8")
    record = json.loads(target.lock_json.read_text(encoding="utf-8"))
    record["min_macos"] = new
    target.lock_json.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{count} Mach-O files; the newest macOS any needs is {floor} ({', '.join(set_by)}); lock min-macos {new}")


def _check_measured_floor(header: dict[str, str], rows: list[dict[str, str]], target: RuntimeTarget) -> None:
    if not target.is_macos:
        return
    measured_path = MEASURED if target.platform == "osx-arm64" else target.measured
    measured = json.loads(measured_path.read_text(encoding="utf-8")) if measured_path.exists() else {}
    if measured.get("conda_rows_sha256") != conda_rows_sha256(rows):
        raise LockError("no macOS floor has been measured for this lock's packages; install them and run "
                        "python -m release.runtime_tools measure ~/.project-sniper/runtimes/<id>")
    if macho_floor.version_key(header["min-macos"]) < macho_floor.version_key(measured["min_macos"]):
        raise LockError(f"the lock says macOS {header['min-macos']} but {', '.join(measured['set_by'])} "
                        f"need macOS {measured['min_macos']}")


def shipped_files(platforms: tuple[str, ...] = ("osx-arm64",)) -> dict[str, tuple[Path, str]]:
    """Package path -> (source file, sha256) for every runtime file the package carries."""
    files: dict[str, tuple[Path, str]] = {}
    for platform in platforms:
        pin = json.loads(runtime_target(platform).ffmpeg_pin.read_text(encoding="utf-8"))
        artifact = pin["artifact"]
        if "source_url" not in artifact:
            files[f"install/deps/{artifact['file']}"] = (DIST / artifact["file"], artifact["sha256"])
        for source in pin["sources"].values():
            files[f"third-party/sources/{source['file']}"] = (DIST / "sources" / source["file"], source["sha256"])
    return files


def check(platform: str = "osx-arm64") -> dict[str, object]:
    """Everything the package build needs verifies; returns the tool versions for RELEASE.json."""
    target = runtime_target(platform)
    header, rows = read_lock(target.lock)
    kinds = [row["kind"] for row in rows]
    artifacts = kinds.count("local") + kinds.count("download")
    if kinds.count("micromamba") != 1 or kinds.count("micromamba-bin") != 1 or artifacts != 1:
        raise LockError("the lock needs exactly one micromamba, micromamba-bin and ffmpeg archive row; "
                        "run python -m release.runtime_tools pin-ffmpeg after building ffmpeg")
    for row in (row for row in rows if row["kind"] == "conda"):
        expected = f"{CHANNEL}/{row['path'].split('/', 1)[1]}"   # conda-forge/<subdir>/<file> under the channel
        if urllib.parse.unquote(row["source"]) != expected:
            raise LockError(f"conda row does not name its conda-forge file: {row['path']}")
    _check_measured_floor(header, rows, target)
    pin = json.loads(target.ffmpeg_pin.read_text(encoding="utf-8"))
    artifact_row = next(row for row in rows if row["kind"] in ("local", "download"))
    if artifact_row["sha256"] != pin["artifact"]["sha256"]:
        raise LockError("the lock's Sniper ffmpeg row does not match sniper-ffmpeg.json")
    for package_path, (source, sha256) in shipped_files((platform,)).items():
        if not source.exists() or file_sha256(source) != sha256:
            raise LockError(f"{package_path}: {source} is missing or does not match its pin; "
                            "run release/runtime_deps/build_ffmpeg.sh")
    record = json.loads(target.lock_json.read_text(encoding="utf-8"))
    floor = header.get("min-macos", header.get("min-windows", "unknown"))
    publisher = pin.get("publisher", "Sniper")
    result = {"runtime_lock_sha256": file_sha256(target.lock), "runtime_min_os": floor,
              "runtime_tools": {**record["tools"], "ffmpeg": f"{pin['version']} ({publisher} {pin['build']})"}}
    if target.is_macos:
        result["runtime_min_macos"] = floor
    else:
        result["runtime_min_windows"] = floor
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--platform", choices=SUPPORTED, default="osx-arm64")
    parser.add_argument("command", choices=("solve", "pin-ffmpeg", "measure", "check"))
    parser.add_argument("prefix", nargs="?", type=Path, help="measure: an installed runtime folder")
    args = parser.parse_args(argv)
    if (args.command == "measure") != (args.prefix is not None):
        parser.error("measure takes the installed runtime folder; the other commands take nothing")
    target = runtime_target(args.platform)
    try:
        {"solve": lambda: solve(target), "pin-ffmpeg": lambda: pin_ffmpeg(target),
         "measure": lambda: measure(args.prefix, target),
         "check": lambda: print(json.dumps(check(args.platform), indent=1))}[args.command]()
    except LockError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    os.umask(0o022)
    raise SystemExit(main())
