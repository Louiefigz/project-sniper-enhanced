import { NextResponse } from "next/server";
import {
  brainModel,
  brainProvider,
  codexSettings,
  executionMode,
} from "../_lib/ai-provider";
import { codexPreflight } from "../_lib/codex-preflight";
import { localWhisperPreflight } from "../_lib/local-whisper-preflight";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const mode = executionMode();
  const provider = brainProvider();
  const codex = provider === "codex" ? codexSettings() : null;
  const preflight = codex ? await codexPreflight(request.signal) : null;
  const transcription = process.env.SNIPER_TRANSCRIBE_PROVIDER ||
    (mode === "local" ? "local-whisper" : "deepgram");
  const whisper = transcription === "local-whisper" ? localWhisperPreflight() : null;
  return NextResponse.json(
    {
      mode,
      brain: {
        provider,
        model: brainModel(provider),
        reasoning: codex?.reasoning ?? null,
      },
      transcription,
      renderer: "local",
      codex: preflight,
      whisper,
    },
    { headers: { "Cache-Control": "private, no-store" } },
  );
}
