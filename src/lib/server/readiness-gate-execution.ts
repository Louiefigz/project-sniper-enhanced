import { PLANNING_GATE_IDS, type GateBundleVerdict } from "@/app/api/producer/auto-edit/planning-gate-contract";
import { combinePlanningGateVerdicts } from "@/app/api/producer/auto-edit/planning-gates";
import type { readinessRenderer, RendererReconciliation } from "./readiness-render-containers";
type RendererCleanup = Pick<NonNullable<ReturnType<typeof readinessRenderer>>, "reconcile"> | null;

export interface ReadinessGateExecution {
  verdict: GateBundleVerdict;
  renderer: RendererReconciliation | null;
  cleanup: "not-configured" | "verified-absence" | "unverified-absence" | "not-run-process-stop-unknown";
  error: string | null;
}

function failedBundle(error: unknown): GateBundleVerdict {
  return combinePlanningGateVerdicts(PLANNING_GATE_IDS.map((gate) => ({
    gate, ok: false, errors: [`Gate bundle failed without complete stop evidence: ${String(error).slice(0, 1000)}`],
    warnings: [], exit: 1, processGroupStopped: false,
  })));
}

function cleanupAfterStop(result: ReadinessGateExecution, renderer: RendererCleanup): void {
  if (result.verdict.processesStopped !== true) {
    result.cleanup = "not-run-process-stop-unknown";
    return;
  }
  if (!renderer) { result.cleanup = "not-configured"; return; }
  try {
    result.renderer = renderer.reconcile();
    result.cleanup = result.renderer.verifiedAbsent ? "verified-absence" : "unverified-absence";
  } catch (error) {
    result.cleanup = "unverified-absence";
    result.error = [result.error, `Owned renderer reconciliation failed: ${String(error).slice(0, 1500)}`].filter(Boolean).join(" | ");
  }
}

/** A timeout/failure is not permission to race Docker cleanup against live gate producers.
 * The real bundle waits every started sibling and carries the owned runner's observations.
 * An unstructured exception cannot prove that; retain unknown cleanup and never pay critics.
 * This proves only outer POSIX-group stop plus the configured exact-name reconciliation,
 * not absence of detached nested sessions or a future Docker create already queued remotely. */
export async function executeReadinessGates(input: {
  run: () => Promise<GateBundleVerdict>;
  renderer: RendererCleanup;
}): Promise<ReadinessGateExecution> {
  const result: ReadinessGateExecution = { verdict: failedBundle("not completed"), renderer: null,
    cleanup: "not-run-process-stop-unknown", error: null };
  try { result.verdict = await input.run(); }
  catch (error) { result.verdict = failedBundle(error); result.error = String(error).slice(0, 2000); }
  finally { cleanupAfterStop(result, input.renderer); }
  return result;
}

export function readinessGatesClean(result: ReadinessGateExecution): boolean {
  return result.verdict.ok && result.verdict.processesStopped === true && result.error === null
    && (result.cleanup === "not-configured" || result.cleanup === "verified-absence");
}

/** Call only AFTER retaining the failed bundle; unknown resource state cannot become a checkpoint. */
export function assertReadinessCleanupSettled(result: ReadinessGateExecution): void {
  if (result.cleanup === "not-run-process-stop-unknown" || result.cleanup === "unverified-absence") {
    throw new Error(`Readiness cleanup is unverified; no critic, checkpoint or retry is authorized: ${result.error ?? result.renderer?.detail ?? result.cleanup}`);
  }
}

/** Historical schema1 bytes remain evidence only, never a current execution capability. */
export function assertCurrentReadinessGateExecution(bundle: Record<string, unknown>): void {
  if (bundle.schemaVersion !== 2) throw new Error("Readiness gate bundle predates owned-process stop proof; a new readiness review is required");
  const result = { verdict: bundle.verdict, renderer: bundle.renderer, cleanup: bundle.cleanup,
    error: bundle.executionError } as ReadinessGateExecution;
  if (!result.verdict || typeof result.verdict.processesStopped !== "boolean"
      || !["not-configured", "verified-absence", "unverified-absence", "not-run-process-stop-unknown"].includes(result.cleanup)
      || (result.error !== null && typeof result.error !== "string")) throw new Error("Readiness gate execution evidence is malformed");
  if (bundle.ok !== true) return;
  const gates = Object.values(result.verdict.gates ?? {}).filter((gate) => gate !== null);
  const required = PLANNING_GATE_IDS.filter((gate) => gate !== "reference_lint");
  if (!readinessGatesClean(result) || required.some((id) => !gates.some((gate) => gate.gate === id))
      || gates.some((gate) => gate.ok !== true || gate.processGroupStopped !== true)
      || (result.cleanup === "verified-absence" ? result.renderer?.verifiedAbsent !== true : result.renderer !== null)) {
    throw new Error("Current readiness requires all owned gate groups stopped and configured renderer cleanup verified");
  }
}
