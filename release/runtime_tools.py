"""Sniper's private tool runtime: the lock the installer follows, and its build-time checks.

    python -m release.runtime_tools solve        # specs.txt -> install/deps/osx-arm64.lock (+ .json)
    python -m release.runtime_tools pin-ffmpeg   # record a fresh build of the Sniper ffmpeg
    python -m release.runtime_tools measure ~/.project-sniper/runtimes/<id>   # the binaries' macOS floor
    python -m release.runtime_tools check        # what the package build runs

A package's metadata can understate the macOS it needs (conda-forge's nodejs 24.21.0 declares
``__osx >=11.0``, but its bin/node is built for 13.5), so the lock's ``min-macos`` also covers
the floor measured from every Mach-O file of an installed runtime of the same packages.

Buyers never install Node, Python, ffmpeg, whisper.cpp, tesseract or yt-dlp themselves.
The installer (install/lib/runtime_tools.sh) downloads exactly the rows of the lock with
curl, checks every SHA-256, and installs them with a hash-pinned micromamba, offline,
into ~/.project-sniper/runtimes/<lock id>/. The one binary not from conda-forge is
Sniper's own ffmpeg build (release/runtime_deps/build_ffmpeg.sh), which ships inside the
package with its complete corresponding source.

Lock rows (whitespace separated, read by bash):  kind sha256 bytes path source
  micromamba      the micromamba package archive       tools/<file>          its URL
  micromamba-bin  the bin/micromamba inside it          bin/micromamba        -
  conda           one conda-forge package               conda-forge/<subdir>/<file>  its URL
  local           a file shipped inside this package    <file>                install/deps/<file>
"""
from __future__ import annotations

import argparse
import hashlib
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

HERE = Path(__file__).resolve().parent
DEPS = HERE / "runtime_deps"
DIST = DEPS / "dist"
SPECS = DEPS / "specs.txt"
FFMPEG_PIN = DEPS / "sniper-ffmpeg.json"
MEASURED = DEPS / "measured-min-macos.json"
LOCK = HERE / "payload_files/install/deps/osx-arm64.lock"
LOCK_JSON = LOCK.with_suffix(".json")
CHANNEL = "https://conda.anaconda.org/conda-forge"
MICROMAMBA = {"version": "2.9.0", "file": "micromamba-2.9.0-0.tar.bz2", "bytes": 6648894,
              "sha256": "500f5074feb8d02c4296ef9921c3650ed2874171805a9fbb8fbb53896433646b"}
TOOLS = ("python", "nodejs", "whisper.cpp", "tesseract", "yt-dlp", "git")
HEADER = "# sniper-runtime-lock-v1"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_KINDS = {"micromamba", "micromamba-bin", "conda", "local"}


class LockError(Exception):
    """The lock, the Sniper ffmpeg pin or a shipped runtime file does not verify."""


def file_sha256(path: Path) -> str:
    """SHA-256 of one file, streamed."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_lock(path: Path = LOCK) -> tuple[dict[str, str], list[dict[str, str]]]:
    """The lock's header values and rows; raises LockError on anything malformed."""
    header: dict[str, str] = {}
    rows: list[dict[str, str]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].split(" —")[0] != HEADER:
        raise LockError(f"{path.name} does not start with '{HEADER}'")
    for line in lines[1:]:
        if line.startswith("# ") and " " in line[2:]:
            key, value = line[2:].split(" ", 1)
            header[key] = value
            continue
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 5 or parts[0] not in _KINDS or not _SHA.match(parts[1]) or not parts[2].isdigit():
            raise LockError(f"malformed lock row: {line}")
        rows.append(dict(zip(("kind", "sha256", "bytes", "path", "source"), parts)))
    return header, rows


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


def micromamba_binary() -> tuple[Path, str]:
    """The pinned micromamba, extracted under dist/tools; returns (binary, binary sha256)."""
    archive = _download(f"{CHANNEL}/osx-arm64/{MICROMAMBA['file']}",
                        DIST / "tools" / MICROMAMBA["file"], MICROMAMBA["sha256"])
    folder = DIST / "tools" / f"micromamba-{MICROMAMBA['version']}"
    binary = folder / "bin/micromamba"
    if not binary.exists():
        with tarfile.open(archive, "r:bz2") as bundle:
            bundle.extractall(folder, filter="data")
    return binary, file_sha256(binary)


def _solve(binary: Path, specs: list[str]) -> list[dict]:
    """micromamba's dry-run solve of ``specs`` for osx-arm64, isolated from any user config."""
    with tempfile.TemporaryDirectory(prefix="sniper-solve-") as scratch:
        env = {"HOME": scratch, "PATH": "/usr/bin:/bin", "MAMBA_ROOT_PREFIX": f"{scratch}/root"}
        done = subprocess.run([str(binary), "create", "--no-rc", "-y", "--dry-run", "--json",
                               "-p", f"{scratch}/env", "--override-channels", "-c", "conda-forge",
                               "--platform", "osx-arm64", *specs],
                              capture_output=True, text=True, env=env, check=False)
    try:
        return json.loads(done.stdout)["actions"]["LINK"]
    except (ValueError, KeyError) as error:
        raise LockError(f"the solve failed: {done.stdout[-600:]}{done.stderr[-600:]}") from error


def _wheels_min_macos() -> str:
    """The macOS floor of the pinned Python wheels, as their lock's header states it."""
    header = (HERE / "payload_files/install/requirements.lock.txt").read_text(encoding="utf-8")[:600]
    match = re.search(r"macOS (\d+)\+ arm64", header)
    if not match:
        raise LockError("install/requirements.lock.txt does not state its arm64 macOS floor")
    return f"{match.group(1)}.0"


def min_macos(packages: list[dict]) -> str:
    """The newest macOS any package requires (``__osx >=``), or the Python wheels need."""
    found = ["11.0", _wheels_min_macos()]
    for package in packages:
        for dep in package.get("depends", []):
            match = re.match(r"__osx\s*>=\s*([\d.]+)$", dep)
            if match:
                found.append(match.group(1))
    return max(found, key=lambda v: tuple(int(p) for p in v.split(".")))


def _ffmpeg_row() -> list[str]:
    """The lock row for the shipped Sniper ffmpeg, or none before its first pinned build."""
    artifact = json.loads(FFMPEG_PIN.read_text(encoding="utf-8"))["artifact"]
    if not artifact["sha256"]:
        return []
    return [f"local {artifact['sha256']} {artifact['bytes']} {artifact['file']} install/deps/{artifact['file']}"]


def write_lock(packages: list[dict], bin_sha: str, binary: Path) -> None:
    """Write the bash-readable lock and its JSON companion, sorted and stable."""
    packages = sorted(packages, key=lambda p: p["fn"])
    tools = {p["name"]: p["version"] for p in packages if p["name"] in TOOLS}
    lines = [f"{HEADER} — written by python -m release.runtime_tools; do not edit",
             "# platform osx-arm64", f"# min-macos {min_macos(packages)}",
             "# tools " + " ".join(f"{name}={tools[name]}" for name in TOOLS),
             "# kind sha256 bytes path source",
             f"micromamba {MICROMAMBA['sha256']} {MICROMAMBA['bytes']} tools/{MICROMAMBA['file']} "
             f"{CHANNEL}/osx-arm64/{MICROMAMBA['file']}",
             f"micromamba-bin {bin_sha} {binary.stat().st_size} bin/micromamba -"]
    lines += [f"conda {p['sha256']} {p['size']} conda-forge/{p['subdir']}/{p['fn']} {p['url']}" for p in packages]
    lines += _ffmpeg_row()
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text("\n".join(lines) + "\n", encoding="utf-8")
    record = {"platform": "osx-arm64", "min_macos": min_macos(packages), "tools": tools,
              "micromamba": MICROMAMBA["version"],
              "packages": [{"name": p["name"], "version": p["version"], "build": p["build_string"],
                            "license": p.get("license") or "", "file": p["fn"]} for p in packages]}
    LOCK_JSON.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def solve() -> None:
    """Resolve specs.txt once and freeze the result."""
    specs = [line.strip() for line in SPECS.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    binary, bin_sha = micromamba_binary()
    packages = _solve(binary, specs)
    unexpected = [p["name"] for p in packages if p["name"] == "ffmpeg"]
    if unexpected:
        raise LockError("the solve pulled in conda-forge's ffmpeg; the runtime uses the Sniper build only")
    write_lock(packages, bin_sha, binary)
    print(f"{LOCK.relative_to(HERE.parent)}: {len(packages)} packages, "
          f"{sum(p['size'] for p in packages) / 1e6:.0f} MB, macOS {min_macos(packages)}+")


def pin_ffmpeg() -> None:
    """Record the SHA-256 and size of dist/<artifact> in the pin and the lock."""
    pin = json.loads(FFMPEG_PIN.read_text(encoding="utf-8"))
    artifact = DIST / pin["artifact"]["file"]
    if not artifact.exists():
        raise LockError(f"{artifact} is missing; run release/runtime_deps/build_ffmpeg.sh")
    pin["artifact"].update(sha256=file_sha256(artifact), bytes=artifact.stat().st_size)
    FFMPEG_PIN.write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
    header_lines = [line for line in LOCK.read_text(encoding="utf-8").splitlines() if not line.startswith("local ")]
    LOCK.write_text("\n".join(header_lines + _ffmpeg_row()) + "\n", encoding="utf-8")
    print(f"pinned {artifact.name} {pin['artifact']['sha256']}")


def conda_rows_sha256(rows: list[dict[str, str]]) -> str:
    """SHA-256 of the lock's conda rows: the package set a measured floor belongs to."""
    text = "\n".join(f"{row['sha256']} {row['path']}" for row in rows if row["kind"] == "conda")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def measure(prefix: Path) -> None:
    """Measure the macOS floor of ``prefix`` (an installed runtime of this lock's packages) and
    raise the lock's ``min-macos`` to it when the binaries need more than the metadata says."""
    header, rows = read_lock()
    wanted = {row["sha256"] for row in rows if row["kind"] == "conda"}
    installed = {json.loads(meta.read_text(encoding="utf-8")).get("sha256")
                 for meta in (prefix / "conda-meta").glob("*.json")}
    if wanted - installed:
        raise LockError(f"{prefix} is not an install of this lock: {len(wanted - installed)} of its "
                        "packages are missing (install/install.command installs it)")
    floor, set_by, count = macho_floor.folder_floor(prefix)
    if not count:
        raise LockError(f"{prefix} has no Mach-O files to measure")
    MEASURED.write_text(json.dumps({"conda_rows_sha256": conda_rows_sha256(rows), "min_macos": floor,
                                    "set_by": set_by, "macho_files": count}, indent=1) + "\n", encoding="utf-8")
    new = max(header["min-macos"], floor, key=macho_floor.version_key)
    LOCK.write_text(LOCK.read_text(encoding="utf-8").replace(
        f"# min-macos {header['min-macos']}\n", f"# min-macos {new}\n", 1), encoding="utf-8")
    record = json.loads(LOCK_JSON.read_text(encoding="utf-8"))
    record["min_macos"] = new
    LOCK_JSON.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{count} Mach-O files; the newest macOS any needs is {floor} ({', '.join(set_by)}); lock min-macos {new}")


def _check_measured_floor(header: dict[str, str], rows: list[dict[str, str]]) -> None:
    measured = json.loads(MEASURED.read_text(encoding="utf-8")) if MEASURED.exists() else {}
    if measured.get("conda_rows_sha256") != conda_rows_sha256(rows):
        raise LockError("no macOS floor has been measured for this lock's packages; install them and run "
                        "python -m release.runtime_tools measure ~/.project-sniper/runtimes/<id>")
    if macho_floor.version_key(header["min-macos"]) < macho_floor.version_key(measured["min_macos"]):
        raise LockError(f"the lock says macOS {header['min-macos']} but {', '.join(measured['set_by'])} "
                        f"need macOS {measured['min_macos']}")


def shipped_files() -> dict[str, tuple[Path, str]]:
    """Package path -> (source file, sha256) for every runtime file the package carries."""
    pin = json.loads(FFMPEG_PIN.read_text(encoding="utf-8"))
    files = {f"install/deps/{pin['artifact']['file']}": (DIST / pin["artifact"]["file"], pin["artifact"]["sha256"])}
    for source in pin["sources"].values():
        files[f"third-party/sources/{source['file']}"] = (DIST / "sources" / source["file"], source["sha256"])
    return files


def check() -> dict[str, object]:
    """Everything the package build needs verifies; returns the tool versions for RELEASE.json."""
    header, rows = read_lock()
    kinds = [row["kind"] for row in rows]
    if kinds.count("micromamba") != 1 or kinds.count("micromamba-bin") != 1 or kinds.count("local") != 1:
        raise LockError("the lock needs exactly one micromamba, micromamba-bin and local row; "
                        "run python -m release.runtime_tools pin-ffmpeg after building ffmpeg")
    for row in (row for row in rows if row["kind"] == "conda"):
        expected = f"{CHANNEL}/{row['path'].split('/', 1)[1]}"   # conda-forge/<subdir>/<file> under the channel
        if urllib.parse.unquote(row["source"]) != expected:
            raise LockError(f"conda row does not name its conda-forge file: {row['path']}")
    _check_measured_floor(header, rows)
    pin = json.loads(FFMPEG_PIN.read_text(encoding="utf-8"))
    local = next(row for row in rows if row["kind"] == "local")
    if local["sha256"] != pin["artifact"]["sha256"]:
        raise LockError("the lock's Sniper ffmpeg row does not match sniper-ffmpeg.json")
    for package_path, (source, sha256) in shipped_files().items():
        if not source.exists() or file_sha256(source) != sha256:
            raise LockError(f"{package_path}: {source} is missing or does not match its pin; "
                            "run release/runtime_deps/build_ffmpeg.sh")
    record = json.loads(LOCK_JSON.read_text(encoding="utf-8"))
    return {"runtime_lock_sha256": file_sha256(LOCK), "runtime_min_macos": header["min-macos"],
            "runtime_tools": {**record["tools"], "ffmpeg": f"{pin['version']} (Sniper build {pin['build']})"}}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("command", choices=("solve", "pin-ffmpeg", "measure", "check"))
    parser.add_argument("prefix", nargs="?", type=Path, help="measure: an installed runtime folder")
    args = parser.parse_args(argv)
    if (args.command == "measure") != (args.prefix is not None):
        parser.error("measure takes the installed runtime folder; the other commands take nothing")
    try:
        {"solve": solve, "pin-ffmpeg": pin_ffmpeg, "measure": lambda: measure(args.prefix),
         "check": lambda: print(json.dumps(check(), indent=1))}[args.command]()
    except LockError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    os.umask(0o022)
    raise SystemExit(main())
