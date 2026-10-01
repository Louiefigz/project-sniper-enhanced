"""The export watchdog's relay of its child's output (split from ``process_watch`` at P1-RP5, X218 F-m5).

``OutputRelay`` copies the exporter child's stdout and stderr to the watchdog's own, at most
``OUTPUT_LIMIT_BYTES`` in all; past the bound it writes one marker and nothing more. ``process_watch``
re-exports both names.
"""
from __future__ import annotations

import os
import selectors
import subprocess
import sys
import time

from studio.production import process

OUTPUT_LIMIT_BYTES = 4 * 1024 ** 2


class OutputRelay:
    """The child's stdout and stderr copied to this process's, at most ``OUTPUT_LIMIT_BYTES`` in all."""

    def __init__(self, child: subprocess.Popen) -> None:
        """Watch both pipes of ``child``."""
        self.selector, self.written, self.cut = selectors.DefaultSelector(), 0, False
        for pipe, target in ((child.stdout, sys.stdout), (child.stderr, sys.stderr)):
            os.set_blocking(pipe.fileno(), False)
            self.selector.register(pipe, selectors.EVENT_READ, target)

    def pump(self, timeout: float) -> None:
        """Copy what the child wrote within ``timeout`` seconds (bounded); with both pipes closed, just wait."""
        if not self.selector.get_map():
            time.sleep(timeout)
            return
        for key, _mask in self.selector.select(timeout):
            chunk = os.read(key.fileobj.fileno(), 65536)
            if not chunk:
                self.selector.unregister(key.fileobj)
                continue
            self._write(key.data, chunk)

    def _write(self, target: object, chunk: bytes) -> None:
        """Forward what fits under the bound; past it, one marker and nothing more."""
        kept = chunk[:max(OUTPUT_LIMIT_BYTES - self.written, 0)]
        binary = getattr(target, 'buffer', None)
        if kept and binary is None:
            target.write(kept.decode('utf-8', errors='replace'))
        elif kept:
            binary.write(kept)
        target.flush()
        self.written += len(kept)
        if len(kept) < len(chunk) and not self.cut:
            self.cut = True
            sys.stderr.write(f'[export output past {OUTPUT_LIMIT_BYTES} bytes is not shown]\n')

    def drain(self) -> None:
        """Copy what is left once the child's group has ended (bounded: the pipes close with it)."""
        deadline = time.monotonic() + process.REAP_SECONDS
        while self.selector.get_map() and time.monotonic() < deadline:
            self.pump(0.2)
        for key in list(self.selector.get_map().values()):
            self.selector.unregister(key.fileobj)
            key.fileobj.close()
