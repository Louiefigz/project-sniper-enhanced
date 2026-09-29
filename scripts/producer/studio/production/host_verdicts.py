"""Observed host capabilities from the 2026-09-27 §6 host capability gate (data catalog).

Source: ``docs/producer/HOST_CAPABILITY_GATE.md`` and ``host-capability-gate/gate-verdicts.json``
(unit host-gate, branch shorts-sla/host-gate, commit 76b1d7f). PASS is ``supported``, FAIL
``unsupported``, UNPROVEN ``unproven``. The gate's decision adds two rows: absolute AI expiry
and enrolment of the already-running director are unsupported on both hosts. Neither host
passes the gate; the builds bundled in the desktop apps (Claude 2.1.281, Codex 0.155.0-alpha)
were not probed. Re-run the gate and replace this catalog when a host changes.
"""
from __future__ import annotations

GATE = 'docs/producer/HOST_CAPABILITY_GATE.md'
EVIDENCE = 'docs/producer/host-capability-gate/'
SOURCE = 'host capability gate 2026-09-27 (docs/producer/HOST_CAPABILITY_GATE.md)'


def _row(verdict: str, evidence: tuple[str, ...], caveat: str | None = None) -> dict:
    """One capability verdict with its evidence files."""
    return {'verdict': verdict, 'evidence': [EVIDENCE + name + '.json' if name != GATE else GATE
                                             for name in evidence], 'caveat': caveat}


CLAUDE_CODE = {
    'host': 'claude-code', 'version': '2.1.247', 'concurrency': None,
    'capabilities': {
        'subscriptionIdentityWithoutApiFallback': _row('unsupported', (
            'host-status', 'claude-identity-no-key', 'claude-session-binding'),
            'logged out on this Mac; a provider key in the child environment silently switches to API-key billing'),
        'launchIdempotencyCallerSessionId': _row('supported', ('claude-session-binding',)),
        'attachExclusiveWhileLive': _row('unsupported', ('claude-resume-while-live',)),
        'knownHostConcurrency': _row('unproven', ()),
        'exactChildHandle': _row('supported', ('claude-control-interrupt',),
                                 'tool processes are not reported in the stream and run in their own process group'),
        'eventReplayAfterDisconnect': _row('unsupported', ('claude-coordinator-death',),
                                           'only the undocumented on-disk transcript; no terminal result replay'),
        'interruptWithTerminalConfirmation': _row('supported', (
            'claude-control-interrupt', 'claude-control-interrupt-recheck-final-code', 'claude-signal-sigint')),
        'toolCleanupAfterCooperativeInterrupt': _row('supported', ('claude-control-interrupt', 'claude-signal-sigint')),
        'toolCleanupAfterHostProcessKilled': _row('unsupported', ('claude-signal-sigkill',)),
        'nestedSubagentCleanup': _row('unproven', ()),
        'coordinatorDeathDelayedRestart': _row('unsupported', (
            'claude-coordinator-death', 'claude-coordinator-death-run1-stub-reasked'),
            'the orphaned child keeps calling the model past the deadline'),
        'separatedUsageAttribution': _row('supported', ('claude-session-binding', 'claude-control-interrupt'),
                                          'plumbing measured with stub-reported usage'),
        'absoluteAiExpiry': _row('unsupported', ('claude-coordinator-death', GATE)),
        'directorEnrollment': _row('unsupported', (GATE,),
                                   'the operator conversation is desktop-hosted; a launched child cannot govern it'),
    },
}

CODEX = {
    'host': 'codex', 'version': '0.144.1', 'concurrency': None,
    'capabilities': {
        'subscriptionIdentityWithoutApiFallback': _row('supported', ('host-status', 'codex-identity')),
        'launchIdempotencyCallerSessionId': _row('unsupported', ('codex-turn-duplicate',),
                                                 'a retried turn/start returns a turn id that never completes'),
        'attachExclusiveWhileLive': _row('unproven', ('codex-socket-coordinator-death',),
                                         'thread/resume attach works; exclusivity was not tested'),
        'knownHostConcurrency': _row('unproven', ('codex-turn-duplicate', 'codex-identity'),
                                     'one active turn per thread observed; no declared limit'),
        'exactChildHandle': _row('supported', ('codex-interrupt', 'codex-turn-duplicate'),
                                 'commandExecution.processId is a PTY session id, not an OS pid'),
        'eventReplayAfterDisconnect': _row('supported', ('codex-socket-coordinator-death', 'codex-coordinator-death'),
                                           'persisted state, not re-delivery of missed notifications'),
        'interruptWithTerminalConfirmation': _row('supported', ('codex-interrupt', 'codex-socket-coordinator-death')),
        'toolCleanupAfterCooperativeInterrupt': _row('unsupported', ('codex-interrupt', 'codex-socket-coordinator-death')),
        'toolCleanupAfterHostProcessKilled': _row('unproven', ('codex-coordinator-death',),
                                                  'SIGKILL of the app-server was not tested'),
        'nestedSubagentCleanup': _row('unproven', ()),
        'coordinatorDeathDelayedRestart': _row('unsupported', ('codex-coordinator-death', 'codex-socket-coordinator-death'),
                                               'no expiry field; a surviving socket server keeps the turn running'),
        'separatedUsageAttribution': _row('supported', ('codex-interrupt',)),
        'absoluteAiExpiry': _row('unsupported', ('codex-socket-coordinator-death', GATE)),
        'directorEnrollment': _row('unsupported', (GATE,),
                                   'the operator conversation is desktop-hosted; a launched child cannot govern it'),
    },
}

HOST_RECORDS = {'claude-code': CLAUDE_CODE, 'codex': CODEX}
