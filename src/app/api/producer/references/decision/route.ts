import { NextRequest } from "next/server";
import {
  findReferenceById,
  persistReferenceDecision,
  persistStyleProfile,
} from "../../../_lib/reference-library";
import { parseReferenceDecision } from "../../../_lib/reference-decision";

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as Record<string, unknown> | null;
  try {
    if (!body) throw new Error("request body is required");
    const decision = parseReferenceDecision(body);
    const id = decision.referenceId;
    const reference = findReferenceById(id);
    if (!reference.profile || !reference.status.deepStudyPath) {
      throw new Error(`reference ${id} must be studied before a decision`);
    }
    if (!reference.profile.representativeFrames.length) {
      throw new Error(`reference ${id} has no safe representative frames; rerun the full study`);
    }
    persistStyleProfile(reference);
    persistReferenceDecision(reference, decision);
    return Response.json({ ok: true, id, decision, reference: findReferenceById(id) });
  } catch (error) {
    return Response.json({ error: (error as Error).message }, { status: 400 });
  }
}
