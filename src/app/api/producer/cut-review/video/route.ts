import type { NextRequest } from "next/server";
import { cutReviewResponse } from "../response";

export const dynamic = "force-dynamic";
export const maxDuration = 120;

export async function GET(req: NextRequest): Promise<Response> { return cutReviewResponse(req, true); }
export async function HEAD(req: NextRequest): Promise<Response> { return cutReviewResponse(req, true); }
