import path from "node:path";
import { existsSync } from "node:fs";
import {
  acquireProjectMutationLease,
  type ProjectMutationLease,
} from "@/lib/server/project-mutation-lease";
import { producerRun } from "@/lib/server/producer-run-registry";

interface GuardInput {
  projectRoot: string;
  producerDir: string;
  operation: string;
}

export type ProjectMutationGuard =
  | { lease: ProjectMutationLease; response?: never }
  | { lease?: never; response: Response };

export function mutationProjectRoot(dir: string): string {
  const clean = dir.replace(/\/$/, "");
  if (existsSync(path.join(clean, "project.json"))) return clean;
  const parent = path.dirname(clean);
  return existsSync(path.join(parent, "project.json")) ? parent : clean;
}

function conflict(message: string, detail: Record<string, unknown>): Response {
  return new Response(JSON.stringify({
    error: message,
    code: "PROJECT_MUTATION_BUSY",
    retryable: true,
    ...detail,
  }), { status: 409, headers: { "Content-Type": "application/json" } });
}

/** Serialize project writers and refuse edits while a detached run owns authority. */
export function guardProjectMutation(input: GuardInput): ProjectMutationGuard {
  const acquired = acquireProjectMutationLease(input.projectRoot, input.operation);
  if (!acquired.lease) {
    const holder = acquired.conflict.operation || "another project update";
    return { response: conflict(
      `This project is busy with ${holder}. Wait for it to finish, then retry ${input.operation}.`,
      { activeOperation: acquired.conflict.operation ?? null },
    ) };
  }
  let run;
  try {
    run = producerRun(input.producerDir);
  } catch (error) {
    acquired.lease.release();
    throw error;
  }
  if (run?.status !== "running") return { lease: acquired.lease };
  acquired.lease.release();
  const phase = run.phase.replaceAll("_", " ");
  return { response: conflict(
    `${run.kind === "auto_edit" ? "Auto Edit" : "Rendering"} is currently ${phase}. `
      + `Choose Stop & keep checkpoint before ${input.operation}, then retry.`,
    { activeRun: { kind: run.kind, phase: run.phase }, action: "stop_keep_checkpoint" },
  ) };
}
