import { assertPlanVisualSources } from "@/lib/producer/visual-source-policy";
import { NextRequest, NextResponse } from "next/server";
import path from "path";
import { dlog } from "@/lib/debug";
import { guardProjectMutation, mutationProjectRoot } from "../../_lib/project-mutation";
import {
  AmbiguousCutTimebaseError,
  savePlanTransaction,
  StalePlanVersionError,
  type SavePlanTimebase,
} from "./transaction";
import { clearTemplateUsageApproval } from "@/lib/server/template-usage-approval";

export const dynamic = "force-dynamic";

// Persist an editor change to edit_plan.json. Pure direct-manipulation write —
// no AI, no API, $0. Locked to files named edit_plan.json (never a generic
// write primitive). The editor sends the whole plan back; we pretty-print it so
// a human/diff can read it, and bump planVersion so a stale base is detectable.
// Before overwriting, the PREVIOUS plan is snapshotted to <dir>/plan-history/
// (newest 20 kept) so any save is recoverable.
export async function POST(req: NextRequest) {
  const { path: filePath, plan, timebase = "auto" } = await req.json();
  if (!filePath || typeof filePath !== "string") {
    return NextResponse.json({ error: "Missing path" }, { status: 400 });
  }
  if (filePath.split("/").includes("..")) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }
  if (path.basename(filePath) !== "edit_plan.json") {
    return NextResponse.json({ error: "Only edit_plan.json is writable" }, { status: 415 });
  }
  if (!plan || typeof plan !== "object") {
    return NextResponse.json({ error: "Missing plan" }, { status: 400 });
  }
  if (!["auto", "full-plan"].includes(String(timebase))) {
    return NextResponse.json({ error: "timebase must be auto or full-plan" }, { status: 400 });
  }
  try { assertPlanVisualSources(plan); } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 422 });
  }
  const producerDir = path.dirname(filePath);
  const guarded = guardProjectMutation({
    projectRoot: mutationProjectRoot(producerDir),
    producerDir,
    operation: "saving timeline changes",
  });
  if (guarded.response) return guarded.response;
  try {
    const result = await savePlanTransaction({
      filePath,
      plan,
      timebase: timebase as SavePlanTimebase,
    });
    clearTemplateUsageApproval(producerDir);
    dlog("producer:save-plan", "wrote", {
      file: filePath, planVersion: result.planVersion,
      snapshots: result.snapshots, refit: Boolean(result.refit),
    });
    return NextResponse.json({ ok: true, ...result });
  } catch (e) {
    const conflict = e instanceof AmbiguousCutTimebaseError || e instanceof StalePlanVersionError;
    const status = conflict ? 409 : 500;
    return NextResponse.json({ error: (e as Error).message }, { status });
  } finally {
    guarded.lease.release();
  }
}
