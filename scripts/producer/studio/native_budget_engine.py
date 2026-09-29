"""Content identity of the engine a batch is frozen to.

A running batch records one engine identity at start. Every budgeted launch
recomputes it and refuses on mismatch, so a repair or unrelated development in
the checkout cannot silently alter (or invalidate) a batch that is in
progress: engine changes need an explicit, recorded migration instead. The
file set is the executable engine and catalog, not tests, dependencies,
runtime caches or render outputs. Hashing it costs about 0.3 s (2,117 files,
16.5 MB measured on the baseline).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

CODE_ROOTS = (('scripts', ('*.py', '*.mjs', '*.ts', '*.json', '*.sb', '*.sh')),
              ('src/lib', ('*.ts',)), ('src/app', ('*.ts',)), ('schemas', ('*.json',)))
EXCLUDED_PARTS = frozenset({'tests', '__tests__', 'node_modules', '__pycache__',
                            '.sniper-native-runtime', 'renders'})


def engine_files(repo: Path) -> list[Path]:
    """The executable engine and catalog inventory, sorted and de-duplicated."""
    files = set()
    for base, patterns in CODE_ROOTS:
        for pattern in patterns:
            files.update(path for path in (repo / base).rglob(pattern) if _included(repo, path))
    motion = repo / 'templates/motion'
    files.update(path for path in motion.rglob('*') if path.is_file() and _included(repo, path))
    return sorted(files)


def _included(repo: Path, path: Path) -> bool:
    """Skip tests, caches, dependencies and generated outputs by path component."""
    return not EXCLUDED_PARTS.intersection(path.relative_to(repo).parts) and not path.is_symlink()


def engine_identity(repo: Path) -> dict:
    """Hash every engine file's relative path and bytes into one identity."""
    total, count = hashlib.sha256(), 0
    for path in engine_files(repo):
        content = hashlib.sha256(path.read_bytes()).digest()
        total.update(str(path.relative_to(repo)).encode() + b'\0' + content)
        count += 1
    return {'root': str(repo), 'identity': total.hexdigest(), 'files': count}
