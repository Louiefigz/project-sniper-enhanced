"""Install the qualified local SDK adaptation from exact, reversible byte patches.

The stock package stays untouched. No downloads, package upgrades or provider
calls occur. A different stock SDK requires a separately qualified patch set.

Locking (``scripts/infra/sniper_lock.py``): resolving the runtime holds the
install's maintenance lock SHARED for the rest of the process, so the installer,
uninstall and cache cleaning (EXCLUSIVE) never run under a render that uses it.
Construction additionally holds ``runtime-build.lock`` EXCLUSIVE; a leftover
``installing/`` folder found while holding it can only come from an interrupted
construction and is removed before building again.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PATCH_ROOT = Path(__file__).resolve().parent / 'runtime'
if str(REPO / 'scripts/infra') not in sys.path:
    sys.path.insert(0, str(REPO / 'scripts/infra'))
import sniper_lock  # noqa: E402  (stdlib-only helper shared with the installer)

BUILD_WAIT_SECONDS = 600.0
GUARD = 'native-export-guard.mjs'
WRAPPER = ("#!/usr/bin/env node\nimport { admitNativeCommand } from './native-export-guard.mjs';\n"
           "if (admitNativeCommand()) await import('./native-render-sdk.mjs');\n")


def digest(file: Path) -> str:
    """Hash files without loading source recordings into memory."""
    with file.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def apply_bytes(content: bytes, row: dict) -> bytes:
    """Apply offsets only to the exact qualified input and verify the result."""
    if hashlib.sha256(content).hexdigest() != row['baseSha256']:
        raise ValueError(f"Native runtime base changed: {row['file']}")
    for patch in reversed(row['patches']):
        start, length = patch['offset'], patch['remove']
        if start < 0 or length < 0 or start + length > len(content):
            raise ValueError('Invalid runtime patch interval')
        content = content[:start] + patch['text'].encode() + content[start + length:]
    if hashlib.sha256(content).hexdigest() != row['sha256']:
        raise ValueError(f"Native runtime patch failed: {row['file']}")
    return content


def verify_runtime(directory: Path, manifest: dict) -> dict[str, str]:
    """Cold-read every adapted runtime file before reuse."""
    expected = {row['file']: row['sha256'] for row in manifest['files']}
    expected['frame-source-transport.mjs'] = manifest['transportSha256']
    if manifest.get('exportGuardSha256'):
        expected['native-render-sdk.mjs'] = expected['cli.js']
        expected['cli.js'] = hashlib.sha256(WRAPPER.encode()).hexdigest()
        expected[GUARD] = manifest['exportGuardSha256']
    for name, expected_hash in expected.items():
        if digest(directory / 'dist' / name) != expected_hash:
            raise ValueError(f'Installed native runtime changed: {name}')
    return expected


def _runtime_manifest() -> tuple[dict, str]:
    """The qualified patch manifest and the content identity of the runtime it builds."""
    manifest_path = PATCH_ROOT / 'patches.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['exportGuardSha256'] = digest(PATCH_ROOT / GUARD)
    identity = hashlib.sha256((digest(manifest_path) + manifest['exportGuardSha256'] + WRAPPER).encode()).hexdigest()
    return manifest, identity


def _construct(stock: Path, parent: Path, manifest: dict) -> Path:
    """Build the runtime in ``installing/``, verify it, then rename it into place.

    The caller holds ``runtime-build.lock``, so an ``installing/`` folder that is
    already present was left by an interrupted construction, never by a live one.
    """
    directory = parent / 'hyperframes'
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / 'installing'
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()  # A concurrent/incomplete install must not be overwritten.
    shutil.copyfile(stock / 'package.json', staging / 'package.json')
    shutil.copytree(stock / 'dist', staging / 'dist')
    for row in manifest['files']:
        source = staging / 'dist' / row.get('from', row['file'])
        patched = apply_bytes(source.read_bytes(), row)
        (staging / 'dist' / row['file']).write_bytes(patched)
    shutil.copyfile(PATCH_ROOT / 'frame-source-transport.mjs', staging / 'dist/frame-source-transport.mjs')
    (staging / 'dist/cli.js').rename(staging / 'dist/native-render-sdk.mjs')
    (staging / 'dist/cli.js').write_text(WRAPPER)
    shutil.copyfile(PATCH_ROOT / GUARD, staging / 'dist' / GUARD)
    verify_runtime(staging, manifest)
    (staging / 'SNIPER-RUNTIME.json').write_text(json.dumps(manifest, indent=2))
    staging.rename(directory)
    return directory


def _verified_or_none(directory: Path, manifest: dict, repair: bool) -> Path | None:
    """Reuse a finished runtime after a cold read; with ``repair``, drop a changed one."""
    if not directory.exists():
        return None
    try:
        verify_runtime(directory, manifest)
    except (OSError, ValueError):
        if not repair:
            raise
        shutil.rmtree(directory)
        return None
    return directory


def install_runtime(repair: bool = False, repo: Path | None = None) -> Path:
    """Materialize a content-addressed runtime beside the installed dependencies.

    Args:
        repair: Rebuild a finished runtime whose files no longer verify, instead of
            refusing. Only the installer passes it: it holds the maintenance lock
            EXCLUSIVE, so no render can be using the runtime it replaces.
        repo: Application root (tests); defaults to this checkout or package.

    Raises:
        sniper_lock.LockBusy: A maintenance step holds the install, or another
            process kept the runtime-build lock for longer than the wait.
        ValueError: The stock SDK or the built runtime does not verify.
    """
    root = repo or REPO
    manifest, identity = _runtime_manifest()
    stock = root / 'templates/motion/node_modules/hyperframes'
    if json.loads((stock / 'package.json').read_text())['version'] != manifest['sdkVersion']:
        raise ValueError('Installed SDK version has not been qualified for native Shorts')
    sniper_lock.hold_for_process(root, 'render runtime user')
    parent = root / 'templates/motion/.sniper-native-runtime' / identity
    found = _verified_or_none(parent / 'hyperframes', manifest, repair)
    if found:
        return found
    build_lock = sniper_lock.lock_file(sniper_lock.state_dir(root), sniper_lock.RUNTIME_BUILD)
    with sniper_lock.held(build_lock, 'exclusive', 'render runtime construction', BUILD_WAIT_SECONDS):
        found = _verified_or_none(parent / 'hyperframes', manifest, repair)
        return found or _construct(stock, parent, manifest)


if __name__ == '__main__':
    print(install_runtime(repair='--repair' in sys.argv[1:]))
