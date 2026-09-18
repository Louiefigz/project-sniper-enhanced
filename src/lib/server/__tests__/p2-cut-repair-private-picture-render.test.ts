import assert from "node:assert/strict";
import fs from "node:fs";
import {
  renderCutRepairPrivatePlan,
} from "@/app/api/producer/ai-edit/cut-repair-private-render";
import { fileSha256 } from "../auto-edit-hash";
import { captureCutRepairPreparedRenderSync } from
  "../cut-repair-prepared-render-authority";
import {
  addUnsupportedPictureLane,
  privatePictureFixture,
  privatePictureInput,
} from "./_p2-cut-repair-private-picture-input-fixture";
import { privatePictureExecutor } from
  "./_p2-cut-repair-private-picture-graph-fixture";

async function run(): Promise<void> {
  const item = privatePictureFixture();
  const calls: string[] = [];
  try {
    const result = await renderCutRepairPrivatePlan(
      privatePictureInput(item), privatePictureExecutor(item, calls));
    assert.equal(calls.length, 1);
    assert.match(calls[0], /cut_repair_surgical_terminal\.py$/u);
    assert.equal(result.basePath, null);
    assert.equal(result.candidateSha256, fileSha256(item.composite));
    assert.equal(result.previousGraphHash, item.parentGraphHash);
    captureCutRepairPreparedRenderSync(item.producer, result);
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }

  const malformed = privatePictureFixture();
  try {
    await assert.rejects(renderCutRepairPrivatePlan(
      privatePictureInput(malformed), async () => ({
        code: 0, stderr: "", stdout: JSON.stringify({
          status: "render_graph_candidate_staged",
        }),
      })), /missing fields/);
  } finally {
    fs.rmSync(malformed.root, { recursive: true, force: true });
  }

  const overlaid = privatePictureFixture();
  addUnsupportedPictureLane(overlaid);
  try {
    await assert.rejects(renderCutRepairPrivatePlan(
      privatePictureInput(overlaid),
      privatePictureExecutor(overlaid, [])),
    /SURGICAL_TERMINAL_PLAN_LANE_UNSUPPORTED:captions/);
  } finally {
    fs.rmSync(overlaid.root, { recursive: true, force: true });
  }
}

run().then(() => {
  console.log("p2-cut-repair-private-picture-render tests passed");
}).catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
