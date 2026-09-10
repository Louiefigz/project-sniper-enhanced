import { NextRequest, NextResponse } from "next/server";
import { readPendingHumanCutDecision, HumanCutAcceptanceError } from "@/lib/server/human-cut-acceptance";
import { RequestFailure } from "../auto-edit/request-failure";
import { CutReviewError } from "./state";
import { cutReviewRequestRejection } from "./response";

const IDENTITIES = ["requestHash", "executionKey", "receiptHash"] as const;
const HEADERS = { "Cache-Control": "private, no-store" };

/** Current immutable prior decision only. Reading cannot create an attempt or change any acceptance. */
export async function pendingCutDecisionResponse(req: NextRequest, read = readPendingHumanCutDecision): Promise<Response> {
  const rejected = cutReviewRequestRejection(req);
  if (rejected) return rejected;
  try {
    if (req.method !== "GET") return NextResponse.json({ ok: false, error: "Method not allowed" },
      { status: 405, headers: { ...HEADERS, Allow: "GET" } });
    const query = req.nextUrl.searchParams, keys = ["dir", ...IDENTITIES];
    if ([...query.keys()].length !== keys.length || keys.some((key) => query.getAll(key).length !== 1)
        || IDENTITIES.some((key) => !/^[a-f0-9]{64}$/.test(query.get(key)!))) {
      throw new CutReviewError("Decision recovery requires only dir and exact paused preview identities", 400);
    }
    const value = read(query.get("dir"));
    if (IDENTITIES.some((key) => value.submission[key] !== query.get(key))) {
      throw new CutReviewError("The previous decision does not belong to this exact preview");
    }
    return NextResponse.json({ ok: value.ok, scope: value.scope, requestHash: value.requestHash,
      submission: value.submission }, { headers: HEADERS });
  } catch (error) {
    const known = error instanceof HumanCutAcceptanceError || error instanceof CutReviewError || error instanceof RequestFailure;
    return NextResponse.json({ ok: false, error: error instanceof Error ? error.message.slice(0, 2048)
      : "Prior decision could not be recovered; recheck project status" }, { status: known ? error.status : 409, headers: HEADERS });
  }
}
