"""Host end-notice formats, per host and probed host version: data only, no logic (X55, X58, X63).

PROVISIONAL DATA TABLE. ``declared_identity`` re-exports ``END_TOOLS`` under its P3b-1 name. A row says what
a director may quote verbatim as an end observation: the host's notification element, the one-line header
elements before the notice's body, and the two note variants the M-080a host-surface probe recorded (X30).
Each note is identified by its literal first sentence, a protocol marker, and carries the sha256 of the full
note text as the probe recorded it. A notice whose note holds neither or both sentences is refused.

Rows come only from that probe: Claude Code 2.1.281, probed 2026-09-29. Codex has no row (not probed), so no
Codex end can be quoted, which is intended (X63 m5). A new host version needs a new probe and a new row. What
counts as end evidence is M-102's HOST_END_EVIDENCE, not this table.
"""

END_TOOLS = {
    'claude-code': {
        '2.1.281': {
            'element': 'task-notification',
            'header': ('task-id', 'status', 'summary', 'note'),
            'notes': {
                'interim': {
                    'sentence': 'This agent stopped with background work of its own still running.',
                    'noteSha256': 'f1afd85e33329468ecb4ae2e076dc8f50492624f1d01dcc9b77d7d83facb526a',
                },
                'final': {
                    'sentence': 'A task-notification fires each time this agent stops with no live background '
                                'children of its own.',
                    'noteSha256': '6c1f654991fa137c33f703ff24cd9990c66620a887bb8557d8be2eba858cd8b8',
                },
            },
        },
    },
    'codex': {},
}
