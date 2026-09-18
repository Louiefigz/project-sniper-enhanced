import { NextResponse } from "next/server";
import { spawn } from "child_process";
import { existsSync } from "fs";
import { dlog } from "@/lib/debug";

export const dynamic = "force-dynamic";

// Reveal a rendered output in Finder — macOS-only, mirrors the local-first
// pattern (the Next server runs on the operator's Mac, so `open -R` surfaces
// the file selected in Finder on their screen). Reads nothing, uploads nothing.
export async function POST(req: Request) {
  if (process.platform !== "darwin") {
    return NextResponse.json({ error: "Reveal in Finder is only supported on macOS." }, { status: 400 });
  }
  const { path: target } = await req.json();
  if (!target || !existsSync(target)) {
    return NextResponse.json({ error: `Path not found: ${target}` }, { status: 404 });
  }
  dlog("producer:reveal", "open -R", { target });
  const child = spawn("open", ["-R", target]);
  return await new Promise<Response>((resolve) => {
    child.on("close", (code) =>
      resolve(
        code === 0
          ? NextResponse.json({ ok: true })
          : NextResponse.json({ error: `open exited with ${code}` }, { status: 500 }),
      ),
    );
    child.on("error", (err) => resolve(NextResponse.json({ error: err.message }, { status: 500 })));
  });
}
