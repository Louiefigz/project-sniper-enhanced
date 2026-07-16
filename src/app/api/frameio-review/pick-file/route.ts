import { NextResponse } from "next/server";
import { spawn } from "child_process";
import { dlog } from "@/lib/debug";

function runOsascript(script: string): Promise<{ stdout: string; stderr: string; code: number }> {
  return new Promise((resolve) => {
    const child = spawn("osascript", ["-e", script]);
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => (stdout += d.toString()));
    child.stderr.on("data", (d) => (stderr += d.toString()));
    child.on("close", (code) => resolve({ stdout, stderr, code: code ?? 1 }));
  });
}

// Native macOS file picker for FRAME.IO REVIEW. Mirrors the SEGMENTER/CLIPPER
// pickers: the Next server runs locally, so the AppleScript dialog appears on
// the user's Mac and we return an absolute POSIX path — nothing is uploaded.
export async function POST(req: Request) {
  if (process.platform !== "darwin") {
    return NextResponse.json(
      { error: "Native file picker is only supported on macOS." },
      { status: 400 },
    );
  }

  let prompt = "Choose an MP4 to review";
  try {
    const body = await req.json();
    if (typeof body?.prompt === "string") prompt = body.prompt;
  } catch { /* empty body is fine */ }

  const safePrompt = prompt.replace(/["\\]/g, "\\$&");
  const utis = `{"public.movie", "public.mpeg-4", "com.apple.quicktime-movie"}`;
  const script = `POSIX path of (choose file with prompt "${safePrompt}" of type ${utis})`;

  dlog("frameio:pick", "open native dialog", { prompt });
  const { stdout, stderr, code } = await runOsascript(script);

  if (code !== 0) {
    if (/User canceled|-128/i.test(stderr)) return NextResponse.json({ canceled: true });
    return NextResponse.json({ error: stderr.trim() || "Picker failed" }, { status: 500 });
  }

  const filePath = stdout.trim();
  if (!filePath) return NextResponse.json({ canceled: true });
  const name = filePath.split("/").pop() || filePath;
  dlog("frameio:pick", "picked", { path: filePath });
  return NextResponse.json({ path: filePath, name });
}
