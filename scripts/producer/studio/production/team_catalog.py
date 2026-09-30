"""Coordination team catalog: policy data only, no logic (M-088 override C-1; M-106 adds the rest).

``SPECIALIST_CAP`` is the number of specialist assignments per output: a Short gets 2, a Long 1. It is not the
team size and not the number of Long section owners, which P3b's section rule governs. P3b owns the value;
P3a's coordination catalog reads it from here.
"""

SPECIALIST_CAP = {'short': 2, 'long': 1}
