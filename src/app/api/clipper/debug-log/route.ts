import { NextRequest, NextResponse } from "next/server";

// Receives client-side CLIPPER debug events (from src/lib/debug.ts forwarder) and
// prints them to the dev-server terminal, so the ENTIRE clipper flow — browser
// UI + server routes + python — is visible in one place. Dev-only convenience;
// silenced when NEXT_PUBLIC_SNIPER_DEBUG=0 (the client simply stops sending).
export async function POST(req: NextRequest) {
  try {
    const { scope, event, data, t } = await req.json();
    const prefix = `[SNIPER ${t ?? ""} client→term ${scope}]`;
    if (data === undefined) {
      console.log(`${prefix} ${event}`);
    } else {
      // Pretty-print objects so nested payloads stay readable in the terminal.
      const body = typeof data === "string" ? data : JSON.stringify(data, null, 2);
      console.log(`${prefix} ${event} ${body}`);
    }
  } catch {
    /* ignore malformed beacons */
  }
  return NextResponse.json({ ok: true });
}
