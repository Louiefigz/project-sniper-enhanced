import { NextRequest, NextResponse } from "next/server";
import { acceptGuidedCut, retryAcceptedCutContinuation, readAcceptedCutStatus,
  HumanCutAcceptanceError } from "@/lib/server/human-cut-acceptance";
import { parseAcceptedCutStatus } from "@/lib/producer/cut-accepted-status-client";
import { parseCutAcceptanceResult } from "@/lib/producer/cut-acceptance-client";
import { RequestFailure } from "../auto-edit/request-failure";
import { CutReviewError } from "./state";
import { cutAcceptanceInput } from "./accept-request";
import { cutReviewRequestRejection } from "./response";

const dependencies = { accept: acceptGuidedCut, retry: retryAcceptedCutContinuation, status: readAcceptedCutStatus };
const HEADERS = { "Cache-Control": "private, no-store" };

function acceptedStatus(req: NextRequest, read: typeof readAcceptedCutStatus) {
  const query = req.nextUrl.searchParams;
  if ([...query.keys()].length !== 1 || query.getAll("dir").length !== 1) {
    throw new CutReviewError("Accepted cut status requires only dir", 400);
  }
  const value = read(query.get("dir"));
  return parseAcceptedCutStatus({ ok: value.ok, cutAccepted: value.cutAccepted, scope: value.scope,
    state: value.state, acceptanceHash: value.acceptanceHash, requestHash: value.requestHash,
    previewAttempt: value.previewAttempt, continuationAttempt: value.continuationAttempt,
    canRetryContinuation: value.canRetryContinuation, waitStoppedAt: value.waitStoppedAt,
    timingState: value.timingState, decisionSubmittedAt: value.decisionSubmittedAt, caveat: value.caveat });
}

function failure(error: unknown): Response {
  const known = error instanceof HumanCutAcceptanceError || error instanceof CutReviewError || error instanceof RequestFailure;
  const cutAccepted = error instanceof HumanCutAcceptanceError && error.cutAccepted;
  return NextResponse.json({ ok: false, cutAccepted,
    error: error instanceof Error ? error.message.slice(0, 2048) : "Cut decision could not be confirmed; recheck project status" },
  { status: known ? error.status : 409, headers: HEADERS });
}

/** Explicit human transaction only; local-origin checks run before reading a body or project. */
export async function cutAcceptanceResponse(req: NextRequest, services = dependencies): Promise<Response> {
  const rejected = cutReviewRequestRejection(req);
  if (rejected) return rejected;
  try {
    if (req.method === "GET") return NextResponse.json(acceptedStatus(req, services.status), { headers: HEADERS });
    if (req.method !== "POST") return NextResponse.json({ ok: false, error: "Method not allowed" },
      { status: 405, headers: { ...HEADERS, Allow: "GET, POST" } });
    const input = await cutAcceptanceInput(req);
    const action = input.submission.operation === "accept" ? services.accept : services.retry;
    const value = await action(input);
    return NextResponse.json(parseCutAcceptanceResult(value, input.submission.requestHash), { headers: HEADERS });
  } catch (error) { return failure(error); }
}
