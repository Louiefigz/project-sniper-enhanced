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

// Opens the native macOS file picker via AppleScript and returns the POSIX
// path(s) of the chosen file(s). The browser can't expose a real filesystem
// path, but since the Next.js server runs locally on the user's Mac, the
// AppleScript dialog appears on their screen and the path is returned here.
//
// Mirrors SEGMENTER's api/segmenter/pick-file so CLIPPER's browser can pick
// video OR audio, and select many files at once for auto-sorting into slots.
// Kept self-contained in the CLIPPER namespace so the two tools stay independent.
export async function POST(req: Request) {
  if (process.platform !== "darwin") {
    return NextResponse.json(
      { error: "Native file picker is only supported on macOS." },
      { status: 400 },
    );
  }

  let prompt = "Choose a file";
  let kind: "video" | "audio" | "any" = "video";
  let multiple = false;
  try {
    const body = await req.json();
    if (typeof body?.prompt === "string") prompt = body.prompt;
    if (body?.kind === "audio") kind = "audio";
    else if (body?.kind === "any") kind = "any";
    if (body?.multiple === true) multiple = true;
  } catch { /* empty body is fine */ }

  dlog("clipper:pick", "open native dialog", { prompt, kind, multiple });

  const safePrompt = prompt.replace(/["\\]/g, "\\$&");
  // public.audio is the parent UTI; covers wav/mp3/m4a/aac/flac/ogg/opus.
  const VIDEO_UTIS = `"public.movie", "public.mpeg-4", "com.apple.quicktime-movie"`;
  const utis =
    kind === "audio" ? `{"public.audio"}`
    : kind === "any" ? `{${VIDEO_UTIS}, "public.audio"}`
    : `{${VIDEO_UTIS}}`;

  // For multi-select, AppleScript returns a list of file references, so we loop
  // and emit one POSIX path per line. Single-select returns one path directly.
  const script = multiple
    ? `set theFiles to choose file with prompt "${safePrompt}" of type ${utis} with multiple selections allowed
set out to ""
repeat with f in theFiles
  set out to out & POSIX path of f & linefeed
end repeat
return out`
    : `POSIX path of (choose file with prompt "${safePrompt}" of type ${utis})`;

  const { stdout, stderr, code } = await runOsascript(script);

  if (code !== 0) {
    // -128 is "User canceled" in AppleScript.
    if (/User canceled|-128/i.test(stderr)) {
      dlog("clipper:pick", "canceled");
      return NextResponse.json({ canceled: true });
    }
    dlog("clipper:pick", "error", stderr.trim());
    return NextResponse.json(
      { error: stderr.trim() || "Picker failed" },
      { status: 500 },
    );
  }

  if (multiple) {
    const files = stdout
      .split("\n")
      .map((p) => p.trim())
      .filter(Boolean)
      .map((p) => ({ path: p, name: p.split("/").pop() || p }));
    if (files.length === 0) return NextResponse.json({ canceled: true });
    dlog("clipper:pick", "picked (multiple)", { count: files.length, paths: files.map((f) => f.path) });
    return NextResponse.json({ files });
  }

  const filePath = stdout.trim();
  if (!filePath) return NextResponse.json({ canceled: true });
  const name = filePath.split("/").pop() || filePath;
  dlog("clipper:pick", "picked", { path: filePath });
  return NextResponse.json({ path: filePath, name });
}
