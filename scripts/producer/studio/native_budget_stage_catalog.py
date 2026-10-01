"""Stage names and v2 clock fields for tokens and time by role (a data catalog: literals only, no logic).

M-109 (P3b-12). ``native_budget_roles.media_seconds`` sorts the A6 spans of one output's launches into
``CATEGORIES`` by ``STAGE_CATEGORY`` and ``STAGE_PREFIX`` and lists any other name under ``unmappedStages``. An
``ENVELOPE_PREFIX`` span is no category (counting it would double count its stages), but its residual (the envelope
minus the catalogued and admission-wait spans inside it, same journal and window) is reported per owner label as a
named unmapped line, never dropped (X231 X-R2: owners such as ``preview`` run media work with no inner span).
``time_accounting`` copies ``HANDOFF_FIELDS`` from ``queue_clock.status`` into ``atHandoff`` once the hand-off row is
recorded (``totalAtHandoffSeconds`` is not None; before it, ``countedToHandoffSeconds`` is the running value,
X231 X-R5; N-P1-3).

Every span name the producer code writes is classified here exactly once, and every name here except
``PLANNED_STAGES`` is one the code writes. ``tests/test_native_budget_stage_catalog.py`` checks both directions
with an AST scan of every span call (``stage_span``, ``child_span``, ``span_for_base``, ``timed_stage``,
``journal_event``) in the non-test code under ``scripts/producer``, and checks the clock fields against
``queue_handoff.frozen_times``.
"""
from __future__ import annotations

CATEGORIES = ('captureAndEncode', 'capture', 'encode', 'proofRead', 'audio', 'qc', 'other')

# Spans a native launch journals, by media category. `capture` and `encode` stay null ("not instrumented
# separately; see captureAndEncode") until a separate span exists; P3b does not add spans inside the native SDK.
STAGE_CATEGORY = {
    'native_input_integrity': 'proofRead', 'native_static_preflight': 'proofRead',
    'native_early_static_preflight': 'proofRead',
    'native_publication_proof': 'proofRead',      # span P1/P4 add for LA-04 proof reads (N-P1-4); unknown until then
    'native_dialogue_preparation': 'audio', 'native_dialogue_delivery': 'audio',
    'native_picture_render': 'captureAndEncode',  # capture and encode are one span in the Short worker today
    'native_picture_reuse': 'captureAndEncode',
    'native_capture_and_seek_checks': 'qc', 'native_picture_and_full_decode_checks': 'qc',
    'native_qc_finish': 'qc', 'native_draft_playability': 'qc', 'native_full_context_seam_samples': 'qc',
    'native_color_metadata': 'other', 'native_draft_promotion_copy': 'other',
}
STAGE_PREFIX = {'native_qc_chunk_': 'qc'}
ENVELOPE_PREFIX = ('native_owner_',)   # a whole owner's span; counting it would double count its stages

# In STAGE_CATEGORY ahead of its span, mapped to the plan row that allows it (N-P1-4 makes it optional; until it
# is written, status says proofRead covers input integrity and static preflight only). The test pins this table and
# fails once code writes a planned name, so the commit that adds the span also removes the name from here.
PLANNED_STAGES = {'native_publication_proof': 'N-P1-4'}

# Admission waits that native_run_admission journals inside an owner's span (child_span). A6 attributes them by
# their metadata activity ('native-queue-wait', 'pressure-wait'); they are waits, never media time, and the
# render-capacity wait of an output comes from queue_clock (excludedRenderQueueSeconds).
ADMISSION_WAIT_STAGES = ('native_queue_admission', 'native_pressure_admission')

# Span names of the pre-native producer paths, by the module that writes them (path under scripts/producer). No
# native export launch runs these modules, so they map to no media category. Exception (X231 X-R3): the native Long
# workflow's program-audio preparation (scripts/producer/native_program_audio.py, the prebuild command
# native-longform-request.ts names) calls render() (audio/native_program_audio.py:135), which journals render.py's
# stages into its own attempt's base/stage_timings.jsonl: real Long audio work P3b-12 counts nowhere (routed to P4).
OUTSIDE_LAUNCH_STAGES = {
    'render.py': ('lint_gate', 'compile', 'cut_speed', 'audio_channels', 'baseline_look', 'recompose', 'punch_in',
                  'broll', 'transitions', 'reframe', 'overlays', 'graphics', 'audio_enhance', 'audio_gain',
                  'captions', 'longform_srt', 'master', 'audit'),
    'assemble.py': ('graphics', 'music', 'proxy', 'composite', 'captions', 'audio_mux', 'base_check'),
    'cut_preview.py': ('cut_preview',),
    'audit/audit_frames.py': ('audit_review_frame_extraction',),   # legacy audit and Palmier native QC
}

# Keys queue_handoff.frozen_times adds to queue_clock.status for a v2 Short (M-054, P1 B11). The first three read
# the recorded visible hand-off (commands.cmd_handoff -> record_handoff); the delivery pair is frozen at the first
# delivery and has no P3b-12 reader.
HANDOFF_FIELDS = ('countedToHandoffSeconds', 'totalAtHandoffSeconds', 'handoffOnTime')
DELIVERY_FIELDS = ('totalAtDeliverySeconds', 'countedAtDeliverySeconds')
