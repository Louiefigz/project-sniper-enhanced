import { NextResponse } from "next/server";
import { COMPS_CATALOG } from "@/lib/producer/comps-catalog";

export const dynamic = "force-static";

// The ELEMENTS catalog as JSON — the UI imports the TS module directly; this
// route exists so other lanes (Python, curl checks) can read the same catalog.
export async function GET() {
  return NextResponse.json({ comps: COMPS_CATALOG });
}
