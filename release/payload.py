"""Buyer-facing payload: installer, doctor, manual, licence and release metadata.

The files themselves live under `release/payload_files/` so they are ordinary
reviewable source. This module copies them into the staging tree and generates
the two things that must be computed at build time: `RELEASE.json` and the
pinned `requirements.lock.txt`.
"""
from __future__ import annotations

import json
import subprocess
import re
import shutil
from pathlib import Path

from release import pins
from release.node_floor import node_requirements
from release.stage import StageReport, StagingError

PAYLOAD = Path(__file__).resolve().parent / "payload_files"
_APP = "app"
_CHROME_RE = re.compile(r'CHROME_VERSION\s*=\s*"([0-9.]+)"')
# The app's own model defaults (ai-provider.ts). The installer writes them into the
# settings so the editor window and the app are given the same model explicitly.
_MODEL_DEFAULTS = {
    "claude_model_default": r'DEFAULT_CLAUDE_MODEL\s*=\s*"([^"]+)"',
    "codex_model_default": r'safeCliValue\("SNIPER_CODEX_MODEL",\s*"([^"]+)"\)',
    "codex_reasoning_default": r'safeCliValue\("SNIPER_CODEX_REASONING",\s*"([^"]+)"\)',
}


def _read_json(path: Path) -> dict:
    """Parse one JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def chrome_version(root: Path) -> str:
    """The `chrome-headless-shell` build the installed HyperFrames CLI requires.

    Args:
        root: Release source root.

    Returns:
        The version string compiled into the HyperFrames dist.

    Raises:
        StagingError: The pin could not be read, so the installer cannot
            provision a browser deterministically.
    """
    dist = root / "templates/motion/node_modules/hyperframes/dist"
    for name in ("cli.js", "fontLocalizeCli.js"):
        candidate = dist / name
        if not candidate.exists():
            continue
        found = _CHROME_RE.search(candidate.read_text(encoding="utf-8", errors="ignore"))
        if found:
            return found.group(1)
    raise StagingError("cannot read the HyperFrames chrome-headless-shell pin; "
                       "install templates/motion dependencies before building")


def model_defaults(root: Path) -> dict[str, str]:
    """The app's default Claude/Codex model and Codex reasoning, read from ai-provider.ts."""
    source = (root / "src/app/api/_lib/ai-provider.ts").read_text(encoding="utf-8")
    found = {key: re.search(pattern, source) for key, pattern in _MODEL_DEFAULTS.items()}
    missing = [key for key, match in found.items() if not match]
    if missing:
        raise StagingError(f"cannot read the app's model defaults from ai-provider.ts: {', '.join(missing)}")
    return {key: match.group(1) for key, match in found.items()}


def component_versions(root: Path) -> dict[str, object]:
    """Exact component versions and pins this release was built against.

    The Node floor is derived from both lockfiles (``release/node_floor.py``), the
    browser archive hashes come from ``release/pins/`` and must match the version
    the installed HyperFrames requires, and the CLI and Python locks are checked
    against the admission pins before anything is written.
    """
    root_pkg = _read_json(root / "package.json")
    motion_pkg = _read_json(root / "templates/motion/package.json")
    policy = (root / "src/app/api/_lib/subscription-policy.ts").read_text(encoding="utf-8")
    codex = re.search(r'codex:\s*"([^"]+)"', policy)
    claude = re.search(r'claude:\s*"([^"]+)"', policy)
    if not codex or not claude:
        raise StagingError("cannot read the subscription CLI admission pins")
    chrome = chrome_version(root)
    node = node_requirements(root)
    pins.check_cli_lock(PAYLOAD / "install/cli", codex.group(1), claude.group(1))
    pins.check_python_lock(PAYLOAD / "install/requirements.lock.txt")
    return {
        "app_version": root_pkg["version"],
        "next": root_pkg["dependencies"]["next"],
        "react": root_pkg["dependencies"]["react"],
        "hyperframes_sdk": root_pkg["dependencies"]["@hyperframes/sdk"],
        "hyperframes_cli": motion_pkg["dependencies"]["hyperframes"],
        "chrome_headless_shell": chrome,
        "chrome_headless_shell_sha256": pins.browser_hashes(chrome),
        "codex_cli_admitted": codex.group(1),
        "claude_cli_admitted": claude.group(1),
        **model_defaults(root),
        "node_floor": node["floor"],
        "node_floor_set_by": node["set_by"],
        "node_unsupported_majors": node["unsupported_majors"],
        "node_recommended": "24",
        "python_floor": "3.12",
        "python_tested": "3.14.4",
        "whisper_model": "ggml-small.en.bin",
        "supported_platform": "macOS on Apple silicon (arm64); only a developer Mac on macOS 26 has run it",
    }


def source_facts(root: Path) -> dict[str, str]:
    """Recorded provenance of the release source tree, plus the commit and tree actually built.

    Both ids are read from git, never typed into SOURCE.json, and a checkout with
    uncommitted or untracked changes is refused: the recorded commit must be exactly
    what shipped. The build calls this before it writes anything. No timestamp is
    included, so two builds of one commit stay byte-identical.
    """
    record = root / "release/SOURCE.json"
    if not record.exists():
        raise StagingError("release/SOURCE.json is missing; record the source baseline first")
    git = ["git", "-C", str(root)]
    status = subprocess.run([*git, "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
    if status.strip():
        raise StagingError("the release checkout has uncommitted changes; commit them before building")
    head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    tree = subprocess.run([*git, "rev-parse", "HEAD^{tree}"], capture_output=True, text=True, check=True).stdout.strip()
    return {**_read_json(record), "release_checkout_commit": head, "release_checkout_tree": tree}


def check_manual_node_floor(stage: Path, floor: str) -> None:
    """The buyer pages state the Node floor the build derived, so they cannot drift from it."""
    short = floor[:-2] if floor.endswith(".0") else floor
    pages = ("START-HERE.html", "manual/index.html", "manual/install.html")
    stale = [page for page in pages if f"Node {short}" not in (stage / page).read_text(encoding="utf-8")]
    if stale:
        raise StagingError(f"these pages do not state the derived Node floor 'Node {short}': {', '.join(stale)}")


def _lock_lines(root: Path) -> list[str]:
    """Pinned `pip freeze` lines for the venv this release was tested with."""
    lock = root / "release/payload_files/install/requirements.lock.txt"
    if not lock.exists():
        raise StagingError("release/payload_files/install/requirements.lock.txt is missing")
    return [line for line in lock.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]


def _move_app_tree(stage: Path, report: StageReport) -> None:
    """Relocate the staged product under `app/` and re-key the staged file list."""
    app = stage / _APP
    app.mkdir(parents=True, exist_ok=True)
    for entry in sorted(stage.iterdir()):
        if entry.name == _APP:
            continue
        shutil.move(str(entry), str(app / entry.name))
    report.files = [f"{_APP}/{path}" for path in report.files]


def write_payload(root: Path, stage: Path, report: StageReport) -> None:
    """Move the product under `app/` and add every buyer-facing file.

    Args:
        root: Release source root.
        stage: Staging tree already holding the allow-listed product.
        report: Staging report; its file list is re-keyed and extended.

    Raises:
        StagingError: A required payload file is missing.
    """
    _move_app_tree(stage, report)
    if not PAYLOAD.exists():
        raise StagingError("release/payload_files is missing")
    for path in sorted(PAYLOAD.rglob("*")):
        if not path.is_file() or path.name == ".DS_Store":
            continue
        relative = path.relative_to(PAYLOAD).as_posix()
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        target.chmod(0o755 if target.suffix in {".sh", ".command"} else 0o644)
        report.files.append(relative)
    _lock_lines(root)


def write_release_json(stage: Path, version: str, components: dict[str, object],
                       status: dict[str, object]) -> None:
    """Write `RELEASE.json` inside the package.

    It records version, source identity (commit and tree id), platform, component
    versions and pins, and ``sellable: false``. It deliberately contains no hash of
    the archive that carries it and no build time.
    """
    payload = {"product": "Project Sniper", "version": version,
               "components": components, **status,
               "note": "The archive's own SHA-256 is published only in the external "
                       "SHA256SUMS / release-manifest.json beside the download."}
    (stage / "RELEASE.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                                        encoding="utf-8")


OVERRIDES = Path(__file__).resolve().parent / "payload_overrides"


def apply_overrides(stage: Path, report: StageReport) -> None:
    """Replace staged files that must be self-contained in the package.

    The repository's own `AGENTS.md` links to a parent repository that a buyer
    never receives. The packaged copy replaces it with a complete standalone
    instruction chain.

    Args:
        stage: Staging tree, after `write_payload` has moved the product to app/.
        report: Staging report; overridden paths must already be staged.

    Raises:
        StagingError: An override has no staged file to replace.
    """
    if not OVERRIDES.exists():
        return
    for path in sorted(OVERRIDES.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(OVERRIDES).as_posix()
        target = stage / relative
        if not target.exists():
            raise StagingError(f"override has nothing to replace: {relative}")
        shutil.copyfile(path, target)
