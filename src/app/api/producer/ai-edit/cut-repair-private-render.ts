import {
  readFileSync,
  renameSync,
  rmSync,
} from "node:fs";
import path from "node:path";
import {
  canonicalJsonSha256,
  fileSha256,
} from "@/lib/server/auto-edit-hash";
import { planObjectContentHash } from "@/lib/server/auto-edit-authority";
import { CURRENT_RENDER_GRAPH } from
  "@/lib/server/current-render-graph-command";
import { parseRenderGraphV1 } from
  "@/lib/producer/contracts/render-graph";
import {
  observeStagedRenderGraphAuthoritySync,
  type StagedRenderGraphAuthority,
  type StagedRenderGraphExpectation,
} from "@/lib/server/staged-render-graph-authority";
import { sha256 } from "@/lib/producer/contracts/validation";
import { readAuthorityJsonSync } from
  "@/lib/server/producer-authority-files";
import {
  runCutRepairPython,
  type CutRepairProcessResult,
} from "./cut-repair-route-runner";
import { renderCutRepairPrivatePicture } from
  "./cut-repair-private-picture-render";
import type { PreparedMediaResult } from "./cut-repair-preparation-plan";
import {
  buildCutRepairPrivateRenderLayout,
  type CutRepairPrivateRenderInput,
  type PrivateRenderLayout,
} from "./cut-repair-private-render-layout";

const RENDER_TIMEOUT_MS = 90 * 60 * 1000;

export type { CutRepairPrivateRenderInput } from
  "./cut-repair-private-render-layout";

export interface CutRepairPrivateRenderResult {
  artifactDir: string;
  planPath: string;
  basePath: string | null;
  candidatePath: string;
  candidateSha256: string;
  graphHash: string;
  graphReceiptHash: string;
  candidatePointerHash: string;
  previousGraphHash: string | null;
  previousGraphReceiptHash: string | null;
}

export type CutRepairRenderExecutor = (
  script: string,
  args: string[],
  label: string,
  timeoutMs: number,
) => Promise<CutRepairProcessResult>;
export type CutRepairGraphObserver = (
  input: StagedRenderGraphExpectation,
) => StagedRenderGraphAuthority;

interface PictureRenderInvocation {
  input: CutRepairPrivateRenderInput;
  prepared: PreparedMediaResult;
  layout: PrivateRenderLayout;
  execute: CutRepairRenderExecutor;
  observe: CutRepairGraphObserver;
}

async function pictureRender(
  invocation: PictureRenderInvocation,
): Promise<CutRepairPrivateRenderResult> {
  const { input, prepared, layout, execute, observe } = invocation;
  const authority = prepared.picturePlanAuthority;
  if (!authority || !layout.preparedPath) {
    throw new Error("picture repair prepared authority is absent");
  }
  const result = await renderCutRepairPrivatePicture({
    producerDir: input.producerDir,
    manifestPath: input.manifestPath,
    planPath: layout.sourcePlan,
    preparedPath: layout.preparedPath,
    artifactDir: layout.artifactDir,
    candidatePath: layout.candidatePath,
    planObjectHash: input.planObjectHash,
    planContentHash: input.planContentHash,
    prepared,
    pictureAuthority: authority,
  }, execute, observe);
  return {
    artifactDir: layout.artifactDir,
    planPath: layout.sourcePlan,
    basePath: null,
    ...result,
  };
}

function failure(result: CutRepairProcessResult, label: string): void {
  if (result.code === 0) return;
  const detail = result.stderr.trim() || result.stdout.trim().slice(-1000);
  throw new Error(`${label} failed${detail ? `: ${detail}` : ""}`);
}

function stagedGraphHash(result: CutRepairProcessResult): string {
  const events = result.stdout.split(/\r?\n/u).flatMap((line) => {
    try {
      const value = JSON.parse(line) as unknown;
      return value && typeof value === "object" && !Array.isArray(value)
        ? [value as Record<string, unknown>] : [];
    } catch {
      return [];
    }
  }).filter((row) => row.status === "render_graph_candidate_staged");
  if (events.length !== 1) {
    throw new Error("cut repair render did not stage exactly one graph");
  }
  return sha256(events[0].graphHash, "staged cut repair graph hash");
}

function assertRenderedPlan(
  outputPlan: string,
  input: CutRepairPrivateRenderInput,
): void {
  const plan = JSON.parse(readFileSync(outputPlan, "utf8")) as unknown;
  if (canonicalJsonSha256(plan) !== input.planObjectHash
      || planObjectContentHash(plan) !== input.planContentHash) {
    throw new Error("rendered cut repair plan changed identity");
  }
}

function assertGraphPlanBinding(
  input: CutRepairPrivateRenderInput,
  authority: StagedRenderGraphAuthority,
): void {
  const graphPath = path.join(
    input.producerDir, ".render-graph-v1", "generations",
    authority.graphHash, "graph.json");
  const graphValue = readAuthorityJsonSync(graphPath);
  if (canonicalJsonSha256(graphValue) !== authority.graphHash) {
    throw new Error("cut repair staged graph changed exact identity");
  }
  const graph = parseRenderGraphV1(graphValue);
  const root = graph.nodes.find((node) => node.nodeId === graph.rootNodeId);
  if (root?.inputDigests["final.plan"] !== input.planContentHash
      || root.outputArtifactHash !== authority.candidateMediaHash) {
    throw new Error(
      "cut repair staged graph does not bind the rendered review plan");
  }
}

/**
 * Render the exact review plan in private artifacts and stage, but never
 * activate, its current-render graph generation.
 */
export async function renderCutRepairPrivatePlan(
  input: CutRepairPrivateRenderInput,
  execute: CutRepairRenderExecutor = runCutRepairPython,
  observe: CutRepairGraphObserver = observeStagedRenderGraphAuthoritySync,
): Promise<CutRepairPrivateRenderResult> {
  const { layout, prepared } = buildCutRepairPrivateRenderLayout(input);
  try {
    if (prepared?.picturePlanAuthority) {
      return await pictureRender(
        { input, prepared, layout, execute, observe });
    }
    const base = await execute(CURRENT_RENDER_GRAPH, layout.baseArgs.slice(1),
      "cut repair private base render", RENDER_TIMEOUT_MS);
    failure(base, "cut repair private base render");
    assertRenderedPlan(layout.outputPlan, input);
    renameSync(layout.candidatePath, layout.basePath);
    const assembled = await execute(
      CURRENT_RENDER_GRAPH, layout.assembleArgs.slice(1),
      "cut repair private assemble", RENDER_TIMEOUT_MS);
    failure(assembled, "cut repair private assemble");
    const candidateSha256 = fileSha256(layout.candidatePath);
    if (!candidateSha256) throw new Error(
      "cut repair private render produced no candidate");
    const graphHash = stagedGraphHash(assembled);
    const authority = observe({
      producerDir: input.producerDir,
      candidatePath: layout.candidatePath,
      expectedCandidateHash: candidateSha256,
    });
    if (authority.graphHash !== graphHash
        || authority.candidateMediaHash !== candidateSha256) {
      throw new Error("cut repair staged graph observation changed identity");
    }
    assertGraphPlanBinding(input, authority);
    return {
      artifactDir: layout.artifactDir,
      planPath: layout.outputPlan,
      basePath: layout.basePath,
      candidatePath: layout.candidatePath,
      candidateSha256,
      graphHash,
      graphReceiptHash: authority.receiptHash,
      candidatePointerHash: authority.candidatePointerHash,
      previousGraphHash: authority.previousGraphHash,
      previousGraphReceiptHash: authority.previousReceiptHash,
    };
  } finally {
    rmSync(layout.workDir, { recursive: true, force: true });
  }
}
