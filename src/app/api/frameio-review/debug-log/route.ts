import { NextRequest, NextResponse } from "next/server";

// Receives client-side FRAME.IO REVIEW debug events (from src/lib/debug.ts
// forwarder) and prints them to the dev-server terminal, so the ENTIRE flow —
// browser UI + SSE route + python (whose stderr is mirrored by the review route)
// — is visible in one place. Dev-only; silenced when NEXT_PUBLIC_SNIPER_DEBUG=0.
export async function POST(req: NextRequest) {
  try {
    const { scope, event, data, t } = await req.json();
    const prefix = `[SNIPER ${t ?? ""} client→term ${scope}]`;
    if (data === undefined) {
      console.log(`${prefix} ${event}`);
    } else {
      const body = typeof data === "string" ? data : JSON.stringify(data, null, 2);
      console.log(`${prefix} ${event} ${body}`);
    }
  } catch {
    /* ignore malformed beacons */
  }
  return NextResponse.json({ ok: true });
}
