import { NextRequest, NextResponse } from "next/server";
import { canonicalPalmierDir, localPalmierRejection } from "../request";
import { activatePalmierView } from "./activate";
import { loadViewTarget } from "./target";
import { ensurePalmierApp } from "../workspace/launch";
import { recoverQuarantinedParent } from "./recovery";
import { palmierCandidateQcState } from "@/lib/server/palmier-candidate-qc";
import { candidateActionLabel } from "@/lib/producer/candidate-qc-action";

export const dynamic = "force-dynamic";

/** Open a managed Palmier view. This never changes handoff ownership. */
export async function POST(req: NextRequest) {
  if (process.platform !== "darwin") {
    return NextResponse.json({ error: "Palmier launching is only supported on macOS." }, { status: 400 });
  }
  const rejection = localPalmierRejection(req);
  if (rejection) return NextResponse.json({ error: rejection.error }, { status: rejection.status });
  const body = await req.json().catch(() => null) as { dir?: unknown } | null;
  let dir: string;
  try { dir = canonicalPalmierDir(body?.dir); } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 400 });
  }
  const candidateAction = palmierCandidateQcState(dir).run;
  if (candidateAction.active) {
    return NextResponse.json({
      error: `${candidateActionLabel(candidateAction.action)} Palmier stays locked until this durable action finishes. You may leave this page and keep watching its saved status.`,
    }, { status: 409 });
  }
  let target = loadViewTarget(dir);
  if ("error" in target) {
    return NextResponse.json({ error: target.error }, { status: target.status });
  }
  try {
    await ensurePalmierApp();
    const recovered = target.kind === "quarantined-candidate";
    if (recovered) {
      await recoverQuarantinedParent(dir);
      target = loadViewTarget(dir);
      if ("error" in target) throw new Error(target.error);
    }
    const timeline = await activatePalmierView(target);
    const description = target.kind === "pending-candidate" ? "copied AI candidate awaiting QC"
      : target.kind === "approved-candidate" ? "QC-approved candidate awaiting deliberate promotion"
      : target.kind === "rejected-candidate" ? "verified parent preserved after candidate rejection"
      : target.kind === "working-head" ? "current Palmier working revision"
      : target.kind === "working-draft"
      ? target.workingAssetKind === "saved-cut" ? "latest saved cut" : "working source view"
      : target.kind === "verified-mirror"
        ? "verified approved edit" : "previous approved snapshot";
    return NextResponse.json({
      ok: true,
      viewOnly: false,
      ownership: target.ownership,
      ownershipChanged: false,
      kind: target.kind,
      verified: target.verified,
      timelineId: timeline.id,
      timelineName: timeline.name,
      message: recovered
        ? "Restored and verified the preserved Palmier parent. The failed candidate remains quarantined as diagnostic history."
        : `Opened the ${description} in Palmier. Opening alone changes nothing; manual edits become the working source of truth and are never overwritten by a stale plan.`,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Could not open Palmier.";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
