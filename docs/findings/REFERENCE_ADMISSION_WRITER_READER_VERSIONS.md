# An admitted reference can disappear when its reader expects an older receipt

The LF01 long-form study exposed a writer/reader mismatch. The importer completed
an isolated decode of the 927.359-second, 55,637-frame reference and wrote a
`sniper-external-media-probe-v3` receipt. The TypeScript library reader accepted
only v2. `findReferenceById()` consequently reported an unknown reference even
though its source, transcript, hashes and registration were present.

The current Python writer documents v3 as the four-CPU/four-thread validation
decode policy. Its receipt schema and the reference reader's checked isolation,
limits and source bindings remain compatible. The reader now explicitly accepts
v2 and v3 while preserving those checks. Unknown versions still fail.

The regression exercises both versions, an unknown v4 receipt with a valid
hash, and modified receipt bytes. The real LF01 then passed the normal library
reader, profile persistence and complete strategy-reference-input construction.
No receipt was edited to impersonate an older policy and no new admission was
fabricated.

When changing an evidence writer's version, find every reader before handoff.
Test the emitted version through the actual read path; writer-only tests cannot
prove that downstream consumers can use its output. Do not accept every future
version by prefix. A policy that changes receipt semantics or weakens isolation
needs a deliberate reader change and may require fresh admission.

Relevant code: `scripts/producer/headless/external_media_probe.py`,
`src/app/api/_lib/reference-admission-verifier.ts`, and
`src/lib/producer/__tests__/reference-admission-verifier.test.ts`.
