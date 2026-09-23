/** Compatibility URL; every new export enters mandatory saved-plan review and final QC. */
import { NextRequest } from "next/server";
import { reviewedRenderEntry } from "../auto-edit/reviewed-render-entry";

export const maxDuration = 2400;
export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<Response> {
  return reviewedRenderEntry(request, "assemble");
}
