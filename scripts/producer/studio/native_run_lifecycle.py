"""Close native attempts and return temporary signal ownership to the caller."""
from __future__ import annotations

import signal
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from studio.native_run import NativeRun

ABORT_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
SignalHandler = Callable[[int, object], None] | signal.Handlers | None


class NativeSignalHandlers:
    """Retain the caller's handlers without overwriting later external ownership."""

    def __init__(self, handler: Callable[[int, object], None]) -> None:
        """Save no process state until this attempt actually reaches preparation."""
        self.handler = handler
        self.previous: dict[int, SignalHandler] = {}

    def install(self) -> None:
        """Record each successful registration so partial setup remains reversible."""
        if self.previous:
            raise RuntimeError('Native abort signal handlers are already installed')
        for number in ABORT_SIGNALS:
            if signal.getsignal(number) is None:
                raise RuntimeError(f'Cannot preserve the unknown {signal.Signals(number).name} handler')
            self.previous[number] = signal.signal(number, self.handler)

    def restore(self) -> None:
        """Attempt every restoration even if an individual signal API call fails."""
        errors = []
        for number, previous in tuple(self.previous.items()):
            try:
                self.restore_one(number, previous)
            except (OSError, RuntimeError, ValueError) as error:
                errors.append(f'{signal.Signals(number).name}: {error}')
        if errors:
            raise RuntimeError('Could not restore native abort signals: ' + '; '.join(errors))

    def restore_one(self, number: int, previous: SignalHandler) -> None:
        """Restore only the handler still owned by this attempt; preserve replacements."""
        if signal.getsignal(number) == self.handler:
            signal.signal(number, previous)
        del self.previous[number]


def finalize_attempt(owner: NativeRun) -> None:
    """Complete the existing cleanup, lease, file and receipt lifecycle in order."""
    try:
        owner.cleanup()
    except Exception as error:
        owner.result['cleanup'] = {'verified': False, 'error': str(error)}
        owner.abort_reason = owner.abort_reason or f'Cleanup failed: {error}'
        try:
            owner.stop_direct_child()
        except Exception as direct_error:
            owner.result['cleanup']['directChildError'] = str(direct_error)
    owner.release_lease()
    for handle in (owner.log, owner.samples):
        if handle is not None:
            handle.close()
    owner.finish()
