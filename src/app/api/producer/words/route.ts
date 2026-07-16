import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { dlog } from "@/lib/debug";

export const dynamic = "force-dynamic";

// SOURCE-time word list for the editor's Script mode (word-level strike-to-cut).
// The word times come from each source's ingest transcript, so they are SOURCE
// seconds — the client maps them through the cutTrack to decide kept/cut and to
// seek. Path guard: everything is DERIVED from <dir>/base.fingerprint.json
// (fixed basename) → manifestPath → sources[].transcriptPath; the query string
// never names an arbitrary file, so this is not a generic file-read primitive.

interface SourceWord {
  sourceId: string;
  word: string;
  start: number;
  end: number;
}

interface Utterance {
  words?: { word: string; start: number; end: number }[];
}

function readJson(file: string): unknown {
  return JSON.parse(fs.readFileSync(file, "utf-8"));
}

function flattenTranscript(sourceId: string, transcriptFile: string): SourceWord[] {
  const doc = readJson(transcriptFile) as { transcript?: Utterance[] };
  const utterances = doc.transcript;
  if (!Array.isArray(utterances)) {
    throw new Error(`${transcriptFile}: no "transcript" utterance list`);
  }
  const words: SourceWord[] = [];
  for (const utt of utterances) {
    for (const w of utt.words ?? []) {
      words.push({ sourceId, word: w.word, start: w.start, end: w.end });
    }
  }
  return words;
}

export async function GET(req: NextRequest) {
  const dir = (req.nextUrl.searchParams.get("dir") || "").replace(/\/$/, "");
  if (!dir) return NextResponse.json({ error: "Missing dir" }, { status: 400 });
  if (dir.split("/").includes("..")) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  const fingerprintPath = path.join(dir, "base.fingerprint.json");
  if (!fs.existsSync(fingerprintPath)) {
    return NextResponse.json(
      { error: `No base.fingerprint.json in ${dir} — words are only served for a rendered base` },
      { status: 409 },
    );
  }

  try {
    const fp = readJson(fingerprintPath) as { manifestPath?: string };
    if (!fp.manifestPath) throw new Error("base.fingerprint.json has no manifestPath");
    const manifest = readJson(fp.manifestPath) as {
      sources?: { id: string; transcriptPath?: string | null }[];
    };
    if (!Array.isArray(manifest.sources)) {
      throw new Error(`${fp.manifestPath}: no sources[]`);
    }
    const manifestDir = path.dirname(fp.manifestPath);
    const words: SourceWord[] = [];
    for (const src of manifest.sources) {
      if (!src.transcriptPath) continue;
      words.push(...flattenTranscript(src.id, path.resolve(manifestDir, src.transcriptPath)));
    }
    dlog("producer:words", "served", { dir, words: words.length });
    return NextResponse.json({ words });
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 500 });
  }
}
