import type { NextRequest } from "next/server";
import { cutAcceptanceResponse } from "../accept-response";

export const dynamic = "force-dynamic";
// Reserve headroom beyond the bounded 120s source verifier for proof reads and worker handoff.
export const maxDuration = 300;

export async function GET(req: NextRequest): Promise<Response> { return cutAcceptanceResponse(req); }
export async function POST(req: NextRequest): Promise<Response> { return cutAcceptanceResponse(req); }
