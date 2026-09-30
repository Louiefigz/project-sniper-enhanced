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
    '_approved_content_fixture.py': OWN_ROOTS,  # gate(): node _isolated_review.ts gets this test's private budget/pool roots
    '_dispatch_fixture.py': OWN_ROOTS,  # launcher()/enter(): every child calls isolate(root) before any engine import
    '_guided_longform_check.py': NO_OWNER,
    '_guided_longform_treatment_check.py': NO_OWNER,
    '_native_current_source_fixture.py': OWN_ROOTS,  # isolated_gates: the gate child runs _isolated_context.py on the test's private roots
    '_native_pool_fixture.py': OWN_ROOTS,
    '_native_service_rate_fixture.py': NO_CHILD,
    '_native_short_draft_fixture.py': NO_CHILD,  # sys.executable only as a pinned path value (7dde85ba blob c80451b)
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
    'test_live_state_child_hardening.py': ('every child is armed with a decoy folder added to its refused prefixes and '
                                           'reports into the test\'s own folder; the one unguarded D2 control writes '
                                           'only a decoy file; no child calls an owner'),
    'test_live_state_child_parity.py': ('spec_from_file_location of the child sitecustomize under another name '
                                        '(nothing installed); no child is started'),
    'test_live_state_child_tripwire.py': ('children that touch live state are armed and refused (exit 97, report into '
                                          'the test\'s own folder; writes only under decoy prefixes); one sets its own '
                                          'root; the nested runs install the isolation; the plain child of (a) and the '
                                          'broken-variable children of (c) are deliberately not armed and call no owner'),
    'test_live_state_isolation.py': DECOY,
    'test_local_asr_callers.py': NO_OWNER,
    'test_local_asr_worker.py': NO_OWNER,
    'test_local_whisper.py': NO_OWNER,
    # deferred row; 7dde85ba blob unchanged (m7): ORPHAN children get the test's registry root (M-020 review)
    'test_managed_preview_launch.py': OWN_ROOTS,
    'test_managed_preview_tree.py': NO_OWNER,
    'test_media_receipt_read_safety.py': NO_OWNER,
    'test_native_audio_owner.py': REFUSED_FIRST,
    'test_native_audio_owner_lifecycle.py': ISOLATED_CHILD,
    'test_native_audio_owner_supervisor.py': ('the child runs only require_owned_audio_worker over this test\'s own '
                                              'receipt and request files; it reads no root'),
    # deferred row re-reviewed on the merged file: LAUNCHER, reserve() and DELIVER each assign their own roots first (M-020 review)
    'test_native_batch_cli.py': OWN_ROOTS,
    # deferred row re-reviewed on the merged file: the child only reads locked_batch(<root argument>) (M-020 review)
    'test_native_budget_authority.py': EXPLICIT_ROOT,
    'test_native_budget_family_delivery.py': NO_CHILD,
    'test_native_media_jail.py': NO_OWNER,
    'test_native_owner_snapshot_race.py': NO_CHILD,
    'test_native_pool_owners.py': OWN_ROOTS,
    'test_native_proof_io.py': NO_OWNER,
    'test_native_review_admission.py': NO_CHILD,
    'test_native_runtime_lock.py': NO_OWNER,
    'test_native_selected_frames.py': NO_OWNER,
    # deferred row; 7dde85ba blob unchanged: sys.executable only inside a NativeRunConfig command value (M-020 review)
    'test_native_short_draft_launch.py': NO_CHILD,
    'test_native_short_picture_reuse.py': NO_CHILD,
    # deferred row; 7dde85ba blob unchanged: HOLD_OWNER holds the cache path it is given (M-020 review)
    'test_native_source_store.py': EXPLICIT_ROOT,
    'test_native_work_lease.py': OWN_ROOTS,
    'test_native_work_pool_interop.py': OWN_ROOTS,
    'test_native_workflow_enforcement.py': NO_CHILD,
    'test_owner_cancellation_deferral.py': NO_OWNER,
    'test_p2_alternate_take_controller.py': NO_OWNER,
    'test_p2_cut_repair_surgical_terminal.py': NO_OWNER,
    'test_p2_dialogue_program_render.py': NO_OWNER,
    'test_palmier_live_acceptance_harness.py': NO_OWNER,
    'test_palmier_native_qc_contract.py': STDLIB,
    'test_palmier_sync_lock.py': NO_OWNER,
    'test_pending_registry.py': ('importlib.import_module of the test modules that use _pending; each installs the '
                                 'test isolation itself (import closure checked)'),
    'test_pool_qualification.py': OWN_ROOTS,
    'test_process_runner.py': NO_OWNER,
    'test_process_runner_bounded.py': NO_OWNER,
    'test_process_runner_fds.py': NO_OWNER,
    # children are a flock holder and sleepers (M-020 review)
    'test_production_dispatch.py': NO_OWNER,
    # children are sleepers; one imports headless.process_runner only (M-020 review)
    'test_production_process.py': NO_OWNER,
    # REPLAY imports _budget_fixture (installs the isolation) and uses the root argument (M-020 review)
    'test_production_recovery.py': ISOLATED_CHILD,
    # the child is a sleeper (M-020 review)
    'test_production_settle.py': NO_OWNER,
    # the child is a TEST time.sleep whose end reconcile observes (W2-D2; L-K, M-042)
    'test_production_task_end_flow.py': NO_OWNER,
    # RACE imports _budget_fixture (installs the isolation) and uses the root argument (M-020 review)
    'test_production_staging.py': ISOLATED_CHILD,
    # RACE imports _budget_fixture (installs the isolation) and uses the root argument (M-020 review)
    'test_production_tasks.py': ISOLATED_CHILD,
    'test_program_mix_registry.py': STDLIB,
    # the child only holds locked_batch(<root argument>) while the test reads credit (W2-D2 deferred; M-053)
    'test_queue_credit_snapshot.py': EXPLICIT_ROOT,
    'test_render_lane.py': NO_OWNER,
    'test_review_packet.py': NO_OWNER,
    # node _isolated_review.ts gets this test's private budget/pool roots (M-020 review)
    'test_role_packet_submission_contract.py': OWN_ROOTS,
    'test_stage_timing.py': NO_OWNER,
    'test_stage_timing_markers.py': NO_OWNER,
    'test_stage_timing_propagation.py': NO_OWNER,
    'test_studio_review_sync.py': NO_CHILD,
    'test_studio_ui_fixture.py': NO_OWNER,
    'test_transcript_timing_correction_cli.py': NO_OWNER,
    'test_transcript_timing_correction_text_safety.py': NO_OWNER,
    'test_transcript_timing_review_safety.py': NO_OWNER,
}
