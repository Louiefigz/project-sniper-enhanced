# Reuse the held full-program master, not the opening's AAC

The private opening renderer already prepares the whole graphics-free picture
base and a measured full-program float audio master. Rendering those again for
the body wastes work and can change the audio the opening was approved against.
The right bridge is the **actual returned master-selection event plus its
independently held byte hash**, not a search for a plausible `program_audio`
pointer or a fabricated render-graph completion.

## Implemented internal primitive

`AssembleJob.held_program_selection` accepts `(selection_event_path, raw_sha256)`.
`audio/held_program_preparation.py` reuses `read_master_selection`, which checks
the original plan, manifest, base, admitted source bus, whole float master, and
current implementation. The import requires the unchanged full plan bytes,
original base/fingerprint/manifest, and a new empty canonical 0700 body output
directory outside the opening base root. A stale explicit import fails; it does
not silently rebuild or normalize again.

`audio/assemble_source_audio.py` uses that actual source bus and full master.
It runs the existing compositor, one final AAC delivery, complete Audit B and
guarded publication into the separate private body output. Known timeline and
cut support are copied byte-for-byte. Original receipts are not moved or
re-sealed. The optional `program_master_delivery.receipt_root` keeps the new
delivery receipt in the body candidate; otherwise ordinary callers retain
their existing location. Imported timing spans also belong to the body, not
the opening's timing journal.

This is a media reuse primitive, **not body/opening/delivery approval**. The
authenticated server must supply the separately held reference after checking
the actual opening selection, cleanup, human approval, journal and lease.
There is no new public CLI switch and no synthetic `PENDING_BASE` or `done`
event. Current render-graph import and exact-frame graphics/body continuation
remain separate integration work.

### Cache ownership correction

The first positive media fixture had no graphics. Independent review found that
the imported `job.cache_dir` could still name the original opening directory;
a graphic render would then add new cache files there despite all existing
receipt hashes remaining correct. Checking known files does not prove an
unchanged directory inventory.

Imported staging now derives a **new `graphics-cache` directory inside that
attempt's private assembly candidate** and ignores the caller cache, including
`None` (which otherwise selects a shared default). The directory is created
0700 with no reuse/overwrite; a pre-existing file, directory or symlink rejects.
Ordinary non-imported assembly preserves its existing cache behavior.

The focused cache regression invokes the actual `_composite → GraphicsJob`
boundary with a nonempty statement-card track. An explicitly test-only writer
writes one cache artifact and aborts before any renderer/media invocation. It
proves retained-root, new-descendant and default cache requests are redirected,
and that the original directory inventory and job/plan stay unchanged. It does
not claim a successfully rendered graphic, visual quality or approval. Nine
cache/publication unit tests passed in **1.18 seconds wall**; their log is
`/private/tmp/sniper-held-cache-pure-20260907.log`. The existing real-media cohort
independently checks exact source/base/master reuse.

After this correction, the combined held-preparation and publication cohort
passed **16/16 tests in 27.95 seconds wall** (26.911 seconds test time). It
includes the three graphics-cache boundary tests and the real-media reuse
checks below: no recut/remaster call, exact 192,192 presented samples/native
picture packets, and unchanged original file inventory and bytes. The log is
`/private/tmp/sniper-held-cache-media-20260907.log`; its retained synthetic
fixture is `/private/tmp/sniper-held-preparation-xysbtfyq`.

That fixture verifies its consumed master-selection implementation closure,
not an immutable snapshot of the whole Producer tree. Concurrent changes to
unimported study/legacy harness modules are outside that evidence; the held
selection inventory contains no study or harness paths. No closure-drift
failure occurred, and no broader source-freeze qualification is claimed.

This intentionally forgoes caller-selected mutable cache reuse for imported
attempts. Future cross-attempt reuse must import independently held, validated
graphic artifacts; it must not restore writable access to the opening tree.

## Evidence

The focused real-media cohort uses a 4.004-second synthetic NTSC program with
multiple cuts, right-only audio, silent source material and synthetic music.
No provider, Docker, creator input or perceptual approval is involved.

- `test_held_program_preparation`: 7/7 passed, **29.04 seconds wall** including
  source/preparation setup and adversarial cases. Actual ordinary assembly
  preserves 192,192 presented samples and native picture packets; base renderer
  and master builder are patched only to raise if called. Neither is called.
- Every original opening file, including its timing journal and master
  directory inventory, remains byte-identical after body assembly.
- Stale source/master/plan/receipt, wrong output ownership, and post-composite
  support drift reject without publishing a body final.
- Existing ordinary assembly/publication cohort: 11/11 passed,
  **26.35 seconds wall**, including normal no-import music rebuild behavior,
  full-QC failure preservation, and publication races/rollback.

Logs: `/private/tmp/sniper-held-preparation-first-20260907.log` and
`/private/tmp/sniper-held-preparation-compat-20260907.log`.
Retained import fixture: `/private/tmp/sniper-held-preparation-atgg7m84`.

An unrelated actual UI opening attempt reported **241.089 seconds full-base
preparation + 31.687 seconds whole-program mastering = 272.776 seconds**. That
attempt failed server selection because its required process ledger was absent;
its media is not an approved import fixture. These numbers identify the cost
that should not be repeated, not a measured 272.776-second speedup: strong
source/artifact revalidation still takes time.

## Limits and next work

Do not use this import after any plan change, even a seemingly audio-neutral
copy/graphic edit: the existing held event binds exact whole-plan bytes.
Do not use base AAC as the audible body source. Whole-master delivery still
encodes the held float master once, with existing clock/LUFS/peak checks.

The opening preparation still creates a legacy picture-transport AAC and a
base audible master that is not selected downstream. Some of that audio work
can later be removed, but the master stage also encodes required picture; its
entire duration is not removable. That optimization needs independent picture
payload/frame and source-audio proofs, after the body bridge is connected.

The current primitive does not establish exact opening/body graphics parity,
full-program creative approval, graph activation, a two-hour SLA, or long/short
creator qualification. It intentionally leaves those gates intact.
