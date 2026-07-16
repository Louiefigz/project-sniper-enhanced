import { NextResponse } from "next/server";
import { spawn } from "child_process";
import { statSync } from "fs";
import path from "path";
import { dlog } from "@/lib/debug";
import {
  normalizePickedPath,
  pickerAppleScript,
  pickerOptions,
  type NativePickerKind,
  type NativePickerOptions,
} from "@/lib/producer/native-media-picker";

// Native macOS picker for PRODUCER: choose a single media FILE or a project
// FOLDER (raw footage + optional broll/ + music/). Same osascript approach as
// SEGMENTER/FRAME.IO REVIEW's pick-file — nothing is uploaded, only the POSIX
// path of the local selection is returned. `kind` is explicit; the old `dir`
// flag remains accepted for callers that predate the Producer source cards.

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

async function requestOptions(req: Request): Promise<NativePickerOptions> {
  let body: unknown = {};
  try {
    body = await req.json();
  } catch { /* empty body is fine */ }
  return pickerOptions(body);
}

function pickedResponse(filePath: string, expected: NativePickerKind): NextResponse {
  let actual: NativePickerKind;
  try {
    actual = statSync(filePath).isDirectory() ? "folder" : "file";
  } catch (error) {
    return NextResponse.json({ error: `Cannot inspect selection: ${(error as Error).message}` }, { status: 422 });
  }
  if (actual !== expected) {
    return NextResponse.json(
      { error: `Expected a ${expected}, but macOS returned a ${actual}.` },
      { status: 422 },
    );
  }

  const name = path.basename(filePath) || filePath;
  dlog("producer:pick", "picked", { path: filePath, kind: actual });
  return NextResponse.json({ path: filePath, name, kind: actual, dir: actual === "folder" });
}

export async function POST(req: Request) {
  if (process.platform !== "darwin") {
    return NextResponse.json(
      { error: "Native file picker is only supported on macOS." },
      { status: 400 },
    );
  }

  let options;
  try {
    options = await requestOptions(req);
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 400 });
  }

  dlog("producer:pick", "picker request", options);

  const { stdout, stderr, code } = await runOsascript(pickerAppleScript(options));

  if (code !== 0) {
    if (/User canceled|-128/i.test(stderr)) {
      dlog("producer:pick", "picker canceled");
      return NextResponse.json({ canceled: true });
    }
    dlog("producer:pick", "picker error", stderr.trim() || "Picker failed");
    return NextResponse.json({ error: stderr.trim() || "Picker failed" }, { status: 500 });
  }

  const filePath = normalizePickedPath(stdout);
  if (!filePath) {
    dlog("producer:pick", "picker canceled (no path)");
    return NextResponse.json({ canceled: true });
  }

  return pickedResponse(filePath, options.kind);
}
