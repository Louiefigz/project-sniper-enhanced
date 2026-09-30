#!/usr/bin/env python3
"""Coordinator commands for a deadline-bounded batch of native Shorts.

The batch clock starts at ``start``, when the operator hands over the approved titles and scripts,
and never restarts. One batch is active at a time. Every agent dispatch (author, review,
planReview, repairCycle) is admitted here first; exports and previews are admitted by the exporter
itself against the same authority. While a batch is active, native Short exports of unbound
projects are refused. Closing never releases budgets early and keeps the batch's bindings: later
exports of its Shorts need a new batch that binds them, or the operator's explicit ``archive`` of
the closed batch (run only when the operator asks; its reason is recorded).
Exit codes: 0 ok/admitted, 3 refused by the budget, 2 invalid or corrupt; run-media: the export's.

  native_batch.py start --batch ID --clips A,B,C,D,E (--approval A=FILE ... | --approvals FILE)
                        [--source RECORDING ...] [--pool-slots N] [--ai-slots N] [--ai-reservations N]
      (approvals are required; the clock starts at authorization, with them bound, before source
       hashing; rerun the same start to finish a failed setup. --ai-slots counts the director,
       default 4, at most 16; --ai-reservations at most 256)
  native_batch.py bind --batch ID --clip A /abs/native-project
  native_batch.py admit --batch ID --clip A --kind author|review|planReview|repairCycle [--label TEXT]
  native_batch.py status --batch ID [--full] [--handoff FILE] [--final-review FILE] [--timing JOURNAL]
                         [--transcript FILE]      (each evidence option repeatable)
  native_batch.py wait --batch ID [--clip A] --until change|delivery --timeout SECONDS
  native_batch.py hold --batch ID start|end --reason TEXT
  native_batch.py add-clip --batch ID --clip F --reason TEXT --approval FILE
  native_batch.py change-approval --batch ID --clip A --approval FILE --reason TEXT
  native_batch.py handoff --batch ID --clip A --confirmation VISIBLE-HANDOFF-CONFIRMATION.json
  native_batch.py close --batch ID          (closes, listing unresolved work in its closure; drains instead while
                                            media work is live: run close again once it ends. Nothing is released)
  native_batch.py archive --batch ID --reason TEXT
  native_batch.py staged-starts
  native_batch.py discard-start --name STAGING --reason TEXT
Production tasks (studio/production/cli.py):
  native_batch.py enroll --batch ID --task ID --handle JSON --version V --fingerprint SHA256
  native_batch.py enqueue --batch ID --tasks TASKS.json
  native_batch.py next --batch ID [--task ID] [--peek]
  native_batch.py attach --batch ID --task ID --epoch N --token HEX --handle JSON
  native_batch.py complete --batch ID --task ID --epoch N --token HEX [--artifact FILE ...] [--usage JSON]
  native_batch.py complete --batch ID --task ID --epoch N --token HEX --failure CATEGORY --detail TEXT
                           [--launch-error TEXT]      (launch-failed: the launch tool's own error, verbatim)
  native_batch.py release --batch ID --task ID --epoch N --token HEX [--launch-error TEXT]
      (an AI task's release needs --launch-error: the launch tool's own error, verbatim, 1-512 bytes)
  native_batch.py cancel-request --batch ID --task ID --reason TEXT
  native_batch.py cancelled --batch ID --task ID --epoch N --token HEX [--usage JSON]
  native_batch.py settle-resource --batch ID --task ID --statement TEXT
      (records the operator's statement on unresolved or revoked work, never evidence; releases nothing)
  native_batch.py director-activity --batch ID --task ID --epoch N --token HEX (--clip A ... | --all)
                                    --state working|idle     (the enrolled director's own declaration)
  native_batch.py reconcile --batch ID [--host JSON]
  native_batch.py dispatch --batch ID       (starts the detached media dispatcher, or reports it)
  native_batch.py run-media --batch ID --task ID --epoch N --token HEX
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from studio.production.cli import main as run_command  # noqa: E402
from studio.production.commands import (  # noqa: E402,F401  (the handlers, for callers and tests)
    cmd_admit, cmd_archive, cmd_bind, cmd_close, cmd_handoff, cmd_hold, cmd_start, cmd_status, cmd_wait,
    observed_record, source_digests,
)
from studio.production.handover_commands import (  # noqa: E402,F401
    cmd_add_clip, cmd_change_approval, cmd_discard_start, cmd_staged_starts,
)


def main() -> None:
    """Run one command of the closed vocabulary."""
    run_command(__doc__)


if __name__ == '__main__':
    main()
