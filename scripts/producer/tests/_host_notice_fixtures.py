"""Verbatim host words from the M-080a probe (Claude Code 2.1.281): test data only, no logic.

Copied from evidence/host-probe/20260929T021606Z: host-words-case1.txt (2) and (3) and host-words-case2.txt.
The evidence files are never read at test time. The two note hashes were computed from those files' bytes (the
text between ``<note>`` and ``</note>``), so a test that pins them is not circular (X63 m2).
"""

CLAUDE = ('claude-code', '2.1.281')
INTERIM_NOTE_SHA256 = 'f1afd85e33329468ecb4ae2e076dc8f50492624f1d01dcc9b77d7d83facb526a'
FINAL_NOTE_SHA256 = '6c1f654991fa137c33f703ff24cd9990c66620a887bb8557d8be2eba858cd8b8'
BACKGROUND_NOTE = ('<note>This agent stopped with background work of its own still running. It may resume on its '
                   'own when that work completes or reports, and the same task-id notifies again if it does; the '
                   'result below may be interim.</note>')
FINAL_NOTE = ('<note>A task-notification fires each time this agent stops with no live background children of its '
              'own. The user can send it another message and resume it, so the same task-id may notify more than '
              'once.</note>')
CASE1 = ('<task-notification>', '<task-id>a928cf82f8f21adc4</task-id>', '<status>completed</status>',
         '<summary>Agent "Host probe case 1 natural end" finished</summary>')
INTERIM_NOTICE = '\n'.join((*CASE1, BACKGROUND_NOTE, '</task-notification>'))
FINAL_NOTICE = '\n'.join((*CASE1, FINAL_NOTE, '<result>...report delivered as a message...</result>',
                          '<usage><subagent_tokens>64799</subagent_tokens><tool_uses>4</tool_uses>'
                          '<duration_ms>249506</duration_ms></usage>', '</task-notification>'))
KILLED_NOTICE = '\n'.join(('<task-notification>', '<task-id>a475c0287b60f97d5</task-id>', '<status>killed</status>',
                           '<summary>Agent "Host probe case 2 stop" was stopped by Claude</summary>', FINAL_NOTE,
                           '</task-notification>'))
TASKSTOP_RESULT = ('{"message":"Successfully stopped task: a475c0287b60f97d5 (Host probe case 2 stop)",'
                   '"task_id":"a475c0287b60f97d5","task_type":"local_agent","command":"Host probe case 2 stop"}')
