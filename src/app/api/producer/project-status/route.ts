import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { findProjectRoot, readProjectJson } from "../../_lib/workspace";
import { producerRun } from "@/lib/server/producer-run-registry";
import { lookupProducerManifest } from "@/lib/server/producer-manifest";
import { currentPlanRefitReceipt } from "../../_lib/plan-refit-transaction";
import { projectPalmierState } from "@/lib/server/project-palmier-state";
import { projectRunTimings } from "@/lib/server/stage-timing-summary";

import { approvedFinal, projectedIntentStatus } from "@/lib/server/project-status-projection";

export const dynamic = "force-dynamic";

// PIPELINE CHECKMARKS — derive a project's stage strip FROM DISK (the shared
// contract; nothing here is stored):
//   source(origin badge from project.json; absent → null = untagged legacy)
//   → ingested     manifest in <project>/source/ (legacy: <dir>/asset_manifest.json)
//   → transcribed  every manifest sources[].transcriptPath resolves
//   → plan         <producer>/edit_plan.json
//   → base         <producer>/base_final.mp4 + base.fingerprint.json
//   → final        <producer>/final.mp4
// ?dir= is a registry entry: a producer out-dir OR a project root (segmenter/
// clipper projects). The response also carries segments/ + source/ listings so
// the Recent-edits card can offer per-segment "Ingest → edit".

interface ManifestSource {
  transcriptPath?: string | null;
}

function findManifest(sourceDir: string | null, producerDir: string): string | null {
  void sourceDir;
  return lookupProducerManifest(producerDir).path;
}

function transcribed(manifestPath: string): boolean {
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf-8")) as {
    sources: ManifestSource[];
  };
  if (manifest.sources.length === 0) return false;
  return manifest.sources.every((s) => {
    if (typeof s.transcriptPath !== "string" || !s.transcriptPath) return false;
    const p = path.isAbsolute(s.transcriptPath)
      ? s.transcriptPath
      : path.join(path.dirname(manifestPath), s.transcriptPath);
    return fs.existsSync(p);
  });
}

function listSegments(root: string | null): { name: string; path: string }[] {
  if (!root) return [];
  const dir = path.join(root, "segments");
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir)
    .filter((n) => n.toLowerCase().endsWith(".mp4"))
    .sort()
    .map((n) => ({ name: n, path: path.join(dir, n) }));
}

function listClipperFiles(root: string | null): { name: string; path: string }[] {
  if (!root) return [];
  const dir = path.join(root, "clipper");
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir)
    .filter((name) => name.toLowerCase().endsWith(".fcpxml"))
    .sort()
    .map((name) => ({ name, path: path.join(dir, name) }));
}

export async function GET(req: NextRequest) {
  const dir = (req.nextUrl.searchParams.get("dir") || "").replace(/\/$/, "");
  const recoverProcesses = req.nextUrl.searchParams.get("recover") !== "0";
  if (!dir || !path.isAbsolute(dir)) {
    return NextResponse.json({ error: "dir must be an absolute path" }, { status: 400 });
  }
  try {
    const projectRoot = findProjectRoot(dir);
    const producerDir =
      projectRoot && projectRoot === dir ? path.join(projectRoot, "producer") : dir;
    const sourceDir = projectRoot ? path.join(projectRoot, "source") : null;
    const project = projectRoot ? readProjectJson(projectRoot) : null;

    const manifestPath = findManifest(sourceDir, producerDir);
    const intentStatus = projectedIntentStatus(project, manifestPath);
    const finalPath = path.join(producerDir, "final.mp4");
    const finalExists = fs.existsSync(finalPath);
    const finalApproved = approvedFinal(producerDir);
    const run = producerRun(producerDir, { recover: recoverProcesses });
    const stages = {
      ingested: manifestPath !== null,
      transcribed: manifestPath !== null && transcribed(manifestPath),
      plan: fs.existsSync(path.join(producerDir, "edit_plan.json")),
      base:
        fs.existsSync(path.join(producerDir, "base_final.mp4")) &&
        fs.existsSync(path.join(producerDir, "base.fingerprint.json")),
      final: finalApproved,
    };
    return NextResponse.json({
      dir,
      projectRoot,
      producerDir,
      origin: project?.origin ?? null,
      ...intentStatus,
      stages,
      segments: listSegments(projectRoot),
      clipperFiles: listClipperFiles(projectRoot),
      sourceDir: sourceDir && fs.existsSync(sourceDir) ? sourceDir : null,
      manifestPath,
      finalArtifact: {
        state: finalApproved ? "approved" : finalExists ? "unapproved" : "missing",
        path: finalExists ? finalPath : null,
        reason: finalExists && !finalApproved
          ? run?.status === "failed"
            ? run.message
            : "This render does not have current hash-matched QC approval."
          : null,
      },
      palmier: projectPalmierState(producerDir),
      planRefit: currentPlanRefitReceipt(
        producerDir,
        path.join(producerDir, "edit_plan.json"),
      ),
      run,
      timing: projectRunTimings(producerDir),
    });
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 500 });
  }
}
