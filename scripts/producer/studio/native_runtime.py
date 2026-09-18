"""Install the qualified local SDK adaptation from exact, reversible byte patches.

The stock package stays untouched. No downloads, package upgrades or provider
calls occur. A different stock SDK requires a separately qualified patch set.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PATCH_ROOT = Path(__file__).resolve().parent / 'runtime'
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


def install_runtime() -> Path:
    """Materialize a content-addressed runtime beside the installed dependencies."""
    manifest_path = PATCH_ROOT / 'patches.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['exportGuardSha256'] = digest(PATCH_ROOT / GUARD)
    stock = REPO / 'templates/motion/node_modules/hyperframes'
    if json.loads((stock / 'package.json').read_text())['version'] != manifest['sdkVersion']:
        raise ValueError('Installed SDK version has not been qualified for native Shorts')
    identity = hashlib.sha256((digest(manifest_path) + manifest['exportGuardSha256'] + WRAPPER).encode()).hexdigest()
    parent = REPO / 'templates/motion/.sniper-native-runtime' / identity
    directory = parent / 'hyperframes'
    if directory.exists():
        verify_runtime(directory, manifest)
        return directory
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / 'installing'
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


if __name__ == '__main__':
    print(install_runtime())
