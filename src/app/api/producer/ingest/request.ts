/** Shared ingest request validation and explicit transcription-mode arguments. */
import { existsSync } from "node:fs";
import type { NextRequest } from "next/server";
import { validateIntent, type ProjectIntent } from "@/lib/producer/intent-presets";

export interface IngestRequest {
  inputPath: string;
  outDir?: string;
  projectRoot?: string;
  noTranscribe: boolean;
  reuseTranscripts: boolean;
  intent?: ProjectIntent;
}

export function json(value: unknown, status: number): Response {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

export async function parseRequest(req: NextRequest): Promise<IngestRequest | Response> {
  const body = await req.json() as Record<string, unknown>;
  if (!body || typeof body.inputPath !== "string" || !body.inputPath) return json({ error: "No input path provided" }, 400);
  if (!existsSync(body.inputPath)) return json({ error: `Input not found: ${body.inputPath}` }, 404);
  for (const name of ["projectRoot", "outDir"]) {
    if (body[name] !== undefined && (typeof body[name] !== "string" || !(body[name] as string).trim())) {
      return json({ error: `${name} must be a nonempty directory path` }, 400);
    }
  }
  if (body.projectRoot !== undefined && body.outDir !== undefined) return json({ error: "Choose projectRoot or outDir, not both" }, 400);
  if (body.noTranscribe !== undefined && typeof body.noTranscribe !== "boolean"
      || body.reuseTranscripts !== undefined && typeof body.reuseTranscripts !== "boolean"
      || body.reuseTranscripts === true && body.noTranscribe === true) {
    return json({ error: "Transcription modes must be boolean; reuseTranscripts cannot combine with noTranscribe" }, 400);
  }
  if (body.reuseTranscripts === true && typeof body.projectRoot !== "string" && typeof body.outDir !== "string") {
    return json({ error: "Transcript reuse needs an existing projectRoot or outDir" }, 400);
  }
  let intent: ProjectIntent | undefined;
  try {
    if (body.intent != null) intent = validateIntent(body.intent);
  } catch (error) {
    return json({ error: `bad intent: ${(error as Error).message}` }, 400);
  }
  return { inputPath: body.inputPath,
    outDir: typeof body.outDir === "string" ? body.outDir : undefined,
    projectRoot: typeof body.projectRoot === "string" ? body.projectRoot : undefined,
    noTranscribe: body.noTranscribe === true, reuseTranscripts: body.reuseTranscripts === true, intent };
}

/** Build only the selected mode's worker arguments.
 * The reuse worker disables ASR internally while keeping verified source transcripts.
 */
export function ingestArguments(input: { script: string; inputPath: string; manifestPath: string; request: IngestRequest }): string[] {
  const args = [input.script, input.inputPath, "--out", input.manifestPath];
  if (input.request.noTranscribe && input.request.reuseTranscripts) throw new Error("Conflicting transcription modes");
  if (input.request.noTranscribe) args.push("--no-transcribe");
  if (input.request.reuseTranscripts) args.push("--reuse-transcripts");
  return args;
}
