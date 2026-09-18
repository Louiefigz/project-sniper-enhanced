import assert from "node:assert/strict";
import fs from "node:fs";
import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import { planObjectContentHash } from "../auto-edit-authority";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
} from "../producer-authority-files";
import { initializeAutoEditProducerAuthoritySync } from
  "../producer-auto-edit-genesis";
import { resolveProducerAuthorityHeadSync } from
  "../producer-revision-head";
import {
  autoEditGenesisFixture,
  rerenderAutoEditGenesisFixture,
} from "./_producer-auto-edit-genesis-fixture";

function renderedSuccessor(): void {
  const item = autoEditGenesisFixture("successor");
  try {
    const genesis = initializeAutoEditProducerAuthoritySync(item.input);
    const next = rerenderAutoEditGenesisFixture(item, "successor-next");
    const advanced = initializeAutoEditProducerAuthoritySync(next.input);
    assert.equal(advanced.status, "advanced");
    const paths = producerAuthorityPaths(item.producer);
    const revision = parseProjectRevision(assertObjectHashSync(
      paths.objects.revisions, advanced.revisionHash));
    assert.equal(revision.schemaVersion, 2);
    if (revision.schemaVersion !== 2) throw new Error("expected V2 successor");
    assert.equal(revision.parentRevisionHash, genesis.revisionHash);
    assert.equal(revision.planObjectHash, canonicalJsonSha256(next.plan));
    assert.equal(revision.planContentHash, planObjectContentHash(next.plan));
    assert.equal(revision.renderGraphHash, next.graphHash);
    assert.equal(
      revision.authoritativeSidecars.renderedCandidateMedia,
      next.input.expectedCandidateHash,
    );
    assert.match(
      revision.authoritativeSidecars.autoEditRenderedTransitionV1,
      /^[0-9a-f]{64}$/u,
    );
    const evidence = assertObjectHashSync(
      paths.objects.receipts,
      revision.authoritativeSidecars.autoEditRenderedTransitionV1,
    ) as Record<string, unknown>;
    assert.equal(evidence.candidateMediaHash, next.input.expectedCandidateHash);
    assert.equal(
      (evidence.candidatePointer as Record<string, unknown>).candidatePath,
      next.candidatePath,
    );
    assert.deepEqual(
      initializeAutoEditProducerAuthoritySync(next.input),
      { status: "reused", revisionHash: advanced.revisionHash },
    );
    fs.rmSync(paths.activeHead);
    assert.equal(
      initializeAutoEditProducerAuthoritySync(next.input).revisionHash,
      advanced.revisionHash,
    );
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

function renderedSuccessorRecovers(): void {
  for (const boundary of [
    "after-materialized",
    "after-advance",
  ] as const) {
    const item = autoEditGenesisFixture(`recover-${boundary}`);
    try {
      const genesis = initializeAutoEditProducerAuthoritySync(item.input);
      const next = rerenderAutoEditGenesisFixture(
        item, `recover-next-${boundary}`);
      assert.throws(
        () => initializeAutoEditProducerAuthoritySync(next.input, {
          after: (current) => {
            if (current === boundary) throw new Error(`fault at ${boundary}`);
          },
        }),
        new RegExp(`fault at ${boundary}`),
      );
      if (boundary === "after-materialized") {
        assert.equal(
          resolveProducerAuthorityHeadSync(item.producer),
          genesis.revisionHash,
        );
      }
      const recovered = initializeAutoEditProducerAuthoritySync(next.input);
      assert.equal(
        resolveProducerAuthorityHeadSync(item.producer),
        recovered.revisionHash,
      );
      assert.equal(
        recovered.status,
        boundary === "after-materialized" ? "advanced" : "reused",
      );
    } finally {
      fs.rmSync(item.root, { recursive: true, force: true });
    }
  }
}

function renderedSuccessorParentCas(): void {
  const item = autoEditGenesisFixture("successor-cas");
  try {
    initializeAutoEditProducerAuthoritySync(item.input);
    const next = rerenderAutoEditGenesisFixture(item, "successor-loser");
    let winner = "";
    assert.throws(
      () => initializeAutoEditProducerAuthoritySync(next.input, {
        after: (boundary) => {
          if (boundary !== "after-materialized") return;
          const foreign = rerenderAutoEditGenesisFixture(
            item, "successor-winner");
          winner = initializeAutoEditProducerAuthoritySync(
            foreign.input).revisionHash;
        },
      }),
      /immutable authority conflict/,
    );
    assert.equal(resolveProducerAuthorityHeadSync(item.producer), winner);
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

renderedSuccessor();
renderedSuccessorRecovers();
renderedSuccessorParentCas();
console.log("producer Auto Edit genesis successor tests passed");
