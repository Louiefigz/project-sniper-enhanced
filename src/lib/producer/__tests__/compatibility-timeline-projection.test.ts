import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  compileCompatibilityProjection,
  parseCompatibilityProjection,
} from "../../../app/api/producer/auto-edit/compatibility-timeline-projection";
import { writeContentAddressedJsonSync } from "../../server/content-addressed-json";

const APPROVED = "a".repeat(64);
const plan = Buffer.from(JSON.stringify({
  cutTrack: [
    { sourceId: "raw", start: 0, end: 4, speed: 1 },
    { sourceId: "raw", start: 5, end: 9, speed: 1, audioLeadMs: 100 },
  ],
  cutDecisions: { schemaVersion: 1, removals: [] },
}));

async function main(): Promise<void> {
  const projection = await compileCompatibilityProjection(plan, APPROVED);
  assert.doesNotThrow(() => parseCompatibilityProjection(projection, APPROVED));

  const tampered = structuredClone(projection);
  tampered.timelineMap.segments[0].source_id = "unreviewed-source";
  assert.throws(
    () => parseCompatibilityProjection(tampered, APPROVED),
    /timelineMapHash does not bind/,
  );

  const discontinuous = structuredClone(projection);
  discontinuous.timelineMap.segments[1].out_start += 0.1;
  assert.throws(
    () => parseCompatibilityProjection(discontinuous, APPROVED),
    /not output-contiguous/,
  );

  const lf14Plan = Buffer.from(JSON.stringify({
    cutTrack: [
      { sourceId: "raw", start: 70.07, end: 733.2325, speed: 1 },
      {
        sourceId: "raw", start: 736.5691666666667,
        end: 913.3707916666667, speed: 1,
      },
    ],
    cutDecisions: { schemaVersion: 1, removals: [] },
  }));
  const precise = await compileCompatibilityProjection(lf14Plan, APPROVED);
  assert.equal(precise.timelineMap.outputDuration, 839.964125);
  assert.equal(precise.timelineMap.segments.at(-1)?.out_end, 839.964125);
  assert.doesNotThrow(
    () => parseCompatibilityProjection(precise, APPROVED),
  );

  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-projection-cas-"));
  try {
    const stored = writeContentAddressedJsonSync(root, projection);
    const reloaded = JSON.parse(readFileSync(stored.path, "utf8")) as unknown;
    assert.doesNotThrow(() => parseCompatibilityProjection(reloaded, APPROVED),
      "CAS reserialization must preserve the embedded map hash");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

void main()
  .then(() => console.log("compatibility-timeline-projection.test.ts: passed"))
  .catch((error) => { console.error(error); process.exitCode = 1; });
