import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { applySetGraphicTextV1, parseSetGraphicTextV1 } from "@/lib/producer/set-graphic-text-v1";
import type { EditPlan } from "@/lib/producer/edit-plan";
import { parseEditRequestV1 } from "@/lib/producer/contracts/edit-request";
import { parseProjectRevision } from "@/lib/producer/contracts/project-revision";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
} from "../producer-authority-files";
import { commitProducerRevisionSync } from "../producer-revision-store";
import { assertRevisionPlanObjectSync } from "../producer-plan-authority";
import {
  bootstrapRevisionFixture,
  cleanRevisionFixture,
  revisionCommitInput,
} from "./_producer-revision-fixture";

interface ShadowFixture {
  fixtureId: string;
  evidenceClass: "synthetic-harness-validation";
  mode: "short" | "longform";
  durationFrames: number;
  fps: { numerator: string; denominator: string };
}

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../..");
const fixtureDir = path.join(root, "scripts", "producer", "tests", "fixtures");
const fixtures = [
  ["p1-baseline-short.json", "a"],
  ["p1-baseline-lf14.json", "b"],
] as const;

function plan(count: number, fixture: ShadowFixture): EditPlan {
  return {
    planVersion: 1,
    target: {
      mode: fixture.mode,
      width: fixture.mode === "short" ? 1080 : 1920,
      height: fixture.mode === "short" ? 1920 : 1080,
      fps: Number(fixture.fps.numerator) / Number(fixture.fps.denominator),
      durationTargetS: fixture.durationFrames
        * Number(fixture.fps.denominator) / Number(fixture.fps.numerator),
    },
    cutTrack: [{ sourceId: "source-a", start: 0, end: 60 }],
    graphicsTrack: Array.from({ length: count }, (_, index) => ({
      id: `g-${(index + 1).toString(36).padStart(8, "0")}`,
      kind: "statement-card" as const,
      outStart: index,
      outEnd: index + 0.75,
      anchor: "own-screen" as const,
      spec: { text: `Old copy ${index + 1}` },
    })),
    compatibilityMarker: fixture.fixtureId,
  } as EditPlan;
}

for (const [name, variant] of fixtures) {
  const fixture = JSON.parse(
    fs.readFileSync(path.join(fixtureDir, name), "utf8"),
  ) as ShadowFixture;
  const authority = bootstrapRevisionFixture();
  try {
    const input = revisionCommitInput(
      authority.producer,
      authority.genesis,
      variant,
      20,
    );
    const committed = commitProducerRevisionSync(input);
    assert.equal(committed.status, "committed");
    const paths = producerAuthorityPaths(authority.producer);
    const revision = parseProjectRevision(assertObjectHashSync(
      paths.objects.revisions,
      committed.childRevisionHash,
    ));
    const outcome = parseEditRequestV1(assertObjectHashSync(
      paths.objects.requests,
      revision.requestLedgerHash,
    ));
    assert.equal(outcome.clauses.length, 20);
    assert.ok(outcome.clauses.every((clause) => clause.state === "committed"));
    const before = plan(20, fixture);
    const original = structuredClone(before);
    // Historical operation records remain readable; committing metadata grants no execution.
    const stored = assertRevisionPlanObjectSync(paths, revision);
    assert.deepEqual(stored, input.planObject);
    const operations = (stored as { graphicsTrack: Array<{ action: unknown }> })
      .graphicsTrack.map(row => parseSetGraphicTextV1(row.action));
    assert.equal(operations.length, 20);
    assert.ok(operations.every(
      (operation, index) => operation.text === `New copy ${variant}-${index + 1}`,
    ));
    assert.deepEqual(operations.map(operation => operation.target.id),
      before.graphicsTrack?.map(entry => entry.id));
    for (const operation of operations) {
      assert.throws(() => applySetGraphicTextV1(before, operation), /retired/);
    }
    assert.deepEqual(before, original, "refused legacy operations preserve every plan field");
    assert.equal(
      (before as Record<string, unknown>).compatibilityMarker,
      fixture.fixtureId,
    );
  } finally {
    cleanRevisionFixture(authority.root);
  }
}

console.log("producer-shadow-fixtures tests passed");
