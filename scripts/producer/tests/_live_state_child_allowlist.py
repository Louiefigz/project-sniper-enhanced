"""Reviewed dynamic imports and child launches in test modules (data; see test_live_state_coverage.py).

The import-closure check cannot follow a dynamic import or code started in a child process,
and a child process never inherits the test isolation. Every tests/test_*.py and tests/_*.py
file that calls ``importlib.import_module``, ``__import__``, ``runpy.run_path``/``run_module``
or ``spec_from_file_location``, or uses ``sys.executable``, is listed here with the reason its
child or import cannot reach the operator's live budget authority or pool state. A file that
starts doing either fails the coverage test until someone reviews it and adds a row. Give a child
that runs budget or pool code its own roots first, as test_native_batch_cli.py does.
"""
from __future__ import annotations

NO_CHILD = 'sys.executable is only a recorded, expected or pinned value; nothing is started'
NO_OWNER = 'the child or imported code cannot import a budget or pool owner (import closure checked)'
OWN_ROOTS = 'the child assigns its own private budget/pool roots before any owner call'
ISOLATED_CHILD = 'the child imports a fixture that installs the test isolation'
EXPLICIT_ROOT = 'the child imports an owner module but only uses a root path passed to it'
REFUSED_FIRST = 'the child is refused (no live owner environment) before any root is read'
STDLIB = 'dynamic import of a standard-library module'
DECOY = ('the children install the isolation over decoy account and pool roots, or only rebind '
         'their own budget root to a private one')

REVIEWED: dict[str, str] = {
    '_guided_longform_check.py': NO_OWNER,
    '_guided_longform_treatment_check.py': NO_OWNER,
    '_native_pool_fixture.py': OWN_ROOTS,
    '_native_current_source_fixture.py': OWN_ROOTS,  # isolated_gates: the gate child runs _isolated_context.py on the test's private roots
    '_native_service_rate_fixture.py': NO_CHILD,
    '_native_short_pipeline_fixture.py': NO_CHILD,
    '_p2_candidate_qc_fixture.py': NO_CHILD,
    '_p2_row10_lifecycle_fixture.py': STDLIB,
    '_p2_visual_lip_sync_fixture.py': NO_CHILD,
    'test_admission_registry.py': NO_OWNER,
    'test_asr_spending_policy.py': NO_OWNER,
    'test_assemble_lock.py': NO_OWNER,
    'test_attempt_trace_process.py': NO_OWNER,
    'test_baseline_timing_coverage.py': NO_OWNER,
    'test_baseline_trace.py': NO_OWNER,
    'test_current_build_release.py': NO_CHILD,
    'test_cut_preview_safety.py': NO_OWNER,
    'test_durable_files_adversarial.py': NO_OWNER,
    'test_edit.py': NO_OWNER,
    'test_external_tool_refusals.py': NO_OWNER,
    'test_grade_project_input.py': NO_OWNER,
    'test_guided_opening_audio_media.py': NO_OWNER,
    'test_guided_picture_decode.py': NO_OWNER,
    'test_guided_v6_short_source.py': NO_CHILD,
    'test_ingest_execution_authority.py': NO_OWNER,
    'test_live_grade_v2_launch.py': STDLIB,
    'test_live_grade_v2_supervisor.py': NO_OWNER,
    'test_live_state_child_tripwire.py': OWN_ROOTS,  # one child is refused by the tripwire; the other sets its own root
    'test_live_state_isolation.py': DECOY,
    'test_local_asr_callers.py': NO_OWNER,
    'test_local_asr_worker.py': NO_OWNER,
    'test_local_whisper.py': NO_OWNER,
    'test_managed_preview_tree.py': NO_OWNER,
    'test_media_receipt_read_safety.py': NO_OWNER,
    'test_native_budget_family_delivery.py': NO_CHILD,
    'test_native_media_jail.py': NO_OWNER,
    'test_native_proof_io.py': NO_OWNER,
    'test_native_review_admission.py': NO_CHILD,
    'test_native_runtime_lock.py': NO_OWNER,
    'test_native_selected_frames.py': NO_OWNER,
    'test_native_short_picture_reuse.py': NO_CHILD,
    'test_native_work_lease.py': OWN_ROOTS,
    'test_native_workflow_enforcement.py': NO_CHILD,
    'test_owner_cancellation_deferral.py': NO_OWNER,
    'test_p2_alternate_take_controller.py': NO_OWNER,
    'test_p2_cut_repair_surgical_terminal.py': NO_OWNER,
    'test_p2_dialogue_program_render.py': NO_OWNER,
    'test_palmier_live_acceptance_harness.py': NO_OWNER,
    'test_palmier_native_qc_contract.py': STDLIB,
    'test_palmier_sync_lock.py': NO_OWNER,
    'test_process_runner.py': NO_OWNER,
    'test_process_runner_bounded.py': NO_OWNER,
    'test_process_runner_fds.py': NO_OWNER,
    'test_program_mix_registry.py': STDLIB,
    'test_render_lane.py': NO_OWNER,
    'test_review_packet.py': NO_OWNER,
    'test_stage_timing.py': NO_OWNER,
    'test_stage_timing_propagation.py': NO_OWNER,
    'test_studio_review_sync.py': NO_CHILD,
    'test_studio_ui_fixture.py': NO_OWNER,
    'test_transcript_timing_correction_cli.py': NO_OWNER,
    'test_transcript_timing_correction_text_safety.py': NO_OWNER,
    'test_transcript_timing_review_safety.py': NO_OWNER,
}
