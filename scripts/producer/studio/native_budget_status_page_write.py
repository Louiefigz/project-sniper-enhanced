"""Writing the generated status page (P3b-14): atomic, never inside the budget authority, only over its own page.

Split from ``native_budget_status_page`` (which re-exports every name here) to keep each file within 300 lines.
The authority check compares folder identity as well as spelling (X210 MAJOR-1): ``os.path.samefile`` over every
ancestor of the output's folder, so a case variant on a case-insensitive volume or a firmlink such as
``/System/Volumes/Data`` cannot name an authority folder under another spelling. The only read of an existing
page is its first ``len(MARKER)`` bytes, to refuse overwriting a file that is not a page.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from studio import native_budget_store

MARKER = '<!-- sniper-status-page v1 -->'
INSIDE_AUTHORITY = 'status-page --out must not be inside the budget authority'
FOREIGN_FILE = 'status-page --out names an existing file that is not a status page; choose a new path'


def _inside(path: Path, root: Path) -> bool:
    """Whether ``path`` is ``root`` or under it: as spelled, with every link resolved, or by folder identity."""
    roots = {root.absolute(), root.resolve()}
    if any(candidate == top or top in candidate.parents for candidate in (path, path.resolve()) for top in roots):
        return True
    folder = path.parent.resolve()
    return root.exists() and any(os.path.samefile(parent, root) for parent in (folder, *folder.parents))


def _is_page(path: Path) -> bool:
    """Whether an existing ``path`` is a regular file starting with ``MARKER`` (reads only those bytes).

    A folder, FIFO, socket or device is never a page and is never opened (a FIFO would block the read); a file
    that cannot be read is not a page.
    """
    if not path.is_file():
        return False
    marker = MARKER.encode()
    try:
        with path.open('rb') as handle:
            return handle.read(len(marker)) == marker
    except OSError:
        return False


def write_page(path: Path, text: str) -> None:
    """Atomically replace ``path`` with a rendered page: a temporary file beside it, fsync, ``os.replace``.

    Raises:
        ValueError: ``path`` is relative, its folder does not exist, it is inside the budget authority (under any
            spelling), it names an existing file (or a link) that is not a status page, or ``text`` is not a
            rendered page.
        OSError: The write failed (disk full, permissions); the previous page is left intact.
    """
    if not path.is_absolute() or not path.parent.is_dir():
        raise ValueError('status-page --out is an absolute path in an existing folder')
    if _inside(path, native_budget_store.default_root()):
        raise ValueError(INSIDE_AUTHORITY)
    if (path.exists() or path.is_symlink()) and not _is_page(path):
        raise ValueError(FOREIGN_FILE)
    if not text.startswith(MARKER + '\n'):
        raise ValueError('write_page writes only a page render_page made')
    descriptor, temporary = tempfile.mkstemp(prefix='.status-page-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(text.encode('utf-8'))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)   # gone after a replace; after a failure, the old page stays
