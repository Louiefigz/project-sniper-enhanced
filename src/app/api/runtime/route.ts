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
  // scripts/asr_policy.py transcribes locally in every mode; Deepgram needs explicit
  // per-run command-line authorization that no app route passes.
  const transcription = process.env.SNIPER_TRANSCRIBE_PROVIDER || "local-whisper";
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
