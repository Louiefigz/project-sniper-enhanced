import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  classifyPalmierWorkspace,
  maybePalmierNativeEdit,
  nativeStream,
  type PalmierNativeStreamDependencies,
} from "../../../app/api/producer/ai-edit/palmier-native-stream";
import type { PalmierNativePromptInput } from "../../../app/api/producer/ai-edit/palmier-native-prompt";

const DIR = "/tmp/sniper-palmier-native-without-edit-plan";
const BODY: PalmierNativePromptInput = {
  dir: DIR,
  request: "Denoise the dialogue audio",
  scope: { lanes: ["audio"] },
};
const RESULT = {
  timelineId: "candidate-1",
  fingerprint: "b".repeat(64),
  operationCount: 1,
};

async function routesWithoutPlanFallback(): Promise<void> {
  let releases = 0;
  let runs = 0;
  const guard: NonNullable<PalmierNativeStreamDependencies["guard"]> = () => ({
    lease: { release: () => { releases += 1; } },
  });
  const response = await maybePalmierNativeEdit(BODY, {
    classifyWorkspace: () => ({ state: "managed" }),
    guard,
    run: async (_input, options) => {
      runs += 1;
      options.onEvent?.({
        event: "palmier_native_progress", status: "operation_applied",
        tool: "remove_words", index: 1, total: 1,
      });
      return RESULT;
    },
  });
  assert.ok(response);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("X-Sniper-Edit-Mode"), "palmier-native");
  const text = await response.text();
  assert.match(text, /palmier_native_started/);
  assert.match(text, /palmier_native_progress/);
  assert.match(text, /remove_words/);
  assert.match(text, /palmier_candidate_ready/);
  assert.match(text, /"timelineId":"candidate-1"/);
  assert.match(text, /ai_done/);
  assert.equal(runs, 1);
  assert.equal(releases, 1, "the project mutation lease must release exactly once");
}

async function neverFallsThroughManagedPalmierErrors(): Promise<void> {
  const invalid = await maybePalmierNativeEdit({ dir: DIR, request: "anything" }, {
    classifyWorkspace: () => ({ state: "managed" }),
  });
  assert.ok(invalid, "a managed Palmier project must never return null to the plan route");
  assert.equal(invalid.status, 422);

  let guarded = false;
  const unsupported = await maybePalmierNativeEdit({
    dir: DIR,
    request: "Add b-roll here",
    scope: { lanes: ["broll"] },
  }, {
    classifyWorkspace: () => ({ state: "managed" }),
    guard: () => { guarded = true; throw new Error("guard should not run"); },
  });
  assert.ok(unsupported);
  assert.equal(unsupported.status, 409);
  assert.equal(guarded, false);

  for (const item of [
    {
      request: "Remove the filler word um", scope: { lanes: ["cuts"] },
      code: "PALMIER_NATIVE_CUT_AUTHORITY_UNAVAILABLE",
    },
    {
      request: "Add a full-screen statement card", scope: { lanes: ["graphics"] },
      code: "PALMIER_NATIVE_RICH_GRAPHIC_UNSUPPORTED",
    },
    {
      request: "Add a wipe transition", scope: { lanes: ["motion"] },
      code: "PALMIER_NATIVE_TRANSITION_UNSUPPORTED",
    },
  ] as const) {
    let capabilityGuarded = false;
    const response = await maybePalmierNativeEdit({ dir: DIR, ...item }, {
      classifyWorkspace: () => ({ state: "managed" }),
      guard: () => { capabilityGuarded = true; throw new Error("guard should not run"); },
    });
    assert.ok(response);
    assert.equal(response.status, 409);
    assert.match(await response.text(), new RegExp(item.code));
    assert.equal(capabilityGuarded, false, "unsupported richness must fail before a mutation lease");
  }

  const absent = await maybePalmierNativeEdit(BODY, {
    classifyWorkspace: () => ({ state: "absent" }),
  });
  assert.equal(absent, null, "only projects without Palmier state may use the plan route");
}

async function classifiesManagedStateWithoutOwnershipAuthority(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "palmier-native-routing-"));
  const statePath = path.join(root, "palmier.sync.json");
  const projectPath = path.join(root, "project.palmier");
  try {
    assert.equal(classifyPalmierWorkspace(root).state, "absent");
    mkdirSync(projectPath);
    for (const ownership of ["sniper", "palmier"] as const) {
      writeFileSync(statePath, JSON.stringify({
        schemaVersion: 4,
        ownership,
        workspaceMode: "verified-mirror",
        projectId: "project-1",
        projectPath,
        latestTimelineId: "timeline-1",
      }));
      assert.equal(classifyPalmierWorkspace(root).state, "managed");
      const response = await maybePalmierNativeEdit({ ...BODY, dir: root }, {
        guard: () => ({ lease: { release: () => undefined } }),
        run: async () => RESULT,
      });
      assert.ok(response);
      assert.equal(response.headers.get("X-Sniper-Edit-Mode"), "palmier-native");
      await response.text();
    }
    writeFileSync(statePath, "{broken");
    const corrupt = await maybePalmierNativeEdit({ ...BODY, dir: root });
    assert.ok(corrupt);
    assert.equal(corrupt.status, 409);
    assert.match(await corrupt.text(), /Refusing to fall back/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

async function cancellationKeepsLeaseUntilWorkerStops(): Promise<void> {
  let releases = 0;
  let workerSignal: AbortSignal | undefined;
  const stream = nativeStream(BODY, () => { releases += 1; }, (_input, options) => {
    workerSignal = options.signal;
    return new Promise((_resolve, reject) => {
      options.signal?.addEventListener("abort", () => reject(new Error("cancelled")), { once: true });
    });
  });
  const reader = stream.getReader();
  const first = await reader.read();
  assert.match(new TextDecoder().decode(first.value), /palmier_native_started/);
  assert.equal(releases, 0);
  await reader.cancel();
  assert.equal(workerSignal?.aborted, true);
  assert.equal(releases, 1);
  await reader.cancel();
  assert.equal(releases, 1, "repeated cancellation must not double-release the lease");
}

async function failureStillReleasesOnce(): Promise<void> {
  let releases = 0;
  const stream = nativeStream(BODY, () => { releases += 1; }, async () => {
    throw new Error("critic rejected the candidate");
  });
  const text = await new Response(stream).text();
  assert.match(text, /critic rejected the candidate/);
  assert.doesNotMatch(text, /ai_done/);
  assert.equal(releases, 1);
}

async function main(): Promise<void> {
  await routesWithoutPlanFallback();
  await neverFallsThroughManagedPalmierErrors();
  await classifiesManagedStateWithoutOwnershipAuthority();
  await cancellationKeepsLeaseUntilWorkerStops();
  await failureStillReleasesOnce();
  console.log("palmier-native-stream.test.ts: all assertions passed");
}

void main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
