/** Compatibility render URLs enter the same saved-plan review/QC controller as the GUI. */
import { NextRequest } from "next/server";
import path from "node:path";
import { POST as controllerPost } from "./route";

type EntryKind = "render" | "assemble";
type Controller = (request: NextRequest) => Promise<Response>;

function controllerBody(value: unknown, kind: EntryKind): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Render request must be an object");
  const body = value as Record<string, unknown>;
  const allowed = kind === "render" ? ["outDir", "planPath"] : ["dir"];
  if (Object.keys(body).some(key => !allowed.includes(key))) {
    throw new Error("Save the plan through /api/producer/save-plan first. Render accepts only the saved project; review/QC overrides and inline plans are unsupported.");
  }
  const dir = body[kind === "render" ? "outDir" : "dir"];
  if (typeof dir !== "string" || !path.isAbsolute(dir) || /[\0\r\n]/u.test(dir)) {
    throw new Error("Render requires an absolute saved Producer project directory");
  }
  const normalized = path.resolve(dir);
  if (body.planPath !== undefined && body.planPath !== path.join(normalized, "edit_plan.json")) {
    throw new Error("Render can review only this project's saved edit_plan.json");
  }
  return { dir: normalized, reviewSavedPlan: true, deliveryPolicy: "mp4-only" };
}

/** Injected controller is a fixed test seam; request JSON can never choose it. */
export async function reviewedRenderEntry(
  request: NextRequest,
  kind: EntryKind,
  controller: Controller = controllerPost,
): Promise<Response> {
  let body: Record<string, unknown>;
  try {
    body = controllerBody(await request.json(), kind);
  } catch (error) {
    return rejectedRequest(error);
  }
  // Preserve origin/host headers. The controller owns local-request policy,
  // canonical workspace checks, source/intent authority, mutation leases,
  // independent planning review, isolated rendering and final QC promotion.
  const forwarded = new NextRequest(new URL("/api/producer/auto-edit", request.url), {
    method: "POST", headers: request.headers, body: JSON.stringify(body),
  });
  return controller(forwarded);
}

function rejectedRequest(error: unknown): Response {
  return new Response(JSON.stringify({
    error: error instanceof Error ? error.message : String(error),
    code: "REVIEWED_RENDER_REQUIRED",
  }), { status: 409, headers: { "Content-Type": "application/json" } });
}
