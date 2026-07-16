import { NextRequest, NextResponse } from "next/server";
import { spawn } from "child_process";
import { existsSync, mkdtempSync, writeFileSync, rmSync } from "fs";
import os from "os";
import path from "path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import { dlog } from "@/lib/debug";

export const dynamic = "force-dynamic";

const SCRIPT_PATH = path.join(SCRIPTS_DIR, "producer", "plan_lint.py");

// plan_lint.py prints its verdict JSON on stdout for BOTH outcomes — exit 0
// (renderable) and exit 1 (rejected). spawnPython() rejects on non-zero exit,
// which would throw away a valid "rejected" verdict, so we spawn directly and
// read stdout regardless of the exit code. We own the temp plan file's cleanup.
function runLint(planPath: string, manifestPath: string): Promise<{ stdout: string; code: number }> {
  return new Promise((resolve) => {
    const proc = spawn(pythonInterpreter(), [SCRIPT_PATH, planPath, manifestPath], {
      env: { ...process.env },
    });
    let stdout = "";
    proc.stdout.on("data", (d: Buffer) => (stdout += d.toString()));
    proc.stderr.on("data", (d: Buffer) => process.stderr.write(d));
    proc.on("close", (code) => resolve({ stdout, code: code ?? 1 }));
    proc.on("error", () => resolve({ stdout, code: 1 }));
  });
}

export async function POST(req: NextRequest) {
  const { planJson, manifestPath } = await req.json();

  if (planJson == null || (typeof planJson === "string" && !planJson.trim())) {
    return NextResponse.json({ error: "No plan JSON provided" }, { status: 400 });
  }
  if (!manifestPath || !existsSync(manifestPath)) {
    return NextResponse.json({ error: `Manifest not found: ${manifestPath}` }, { status: 404 });
  }

  // Write the operator's plan verbatim so plan_lint surfaces JSON syntax errors
  // (it does its own json.load and reports them as a load-failed verdict).
  const planText = typeof planJson === "string" ? planJson : JSON.stringify(planJson, null, 2);
  const tmpDir = mkdtempSync(path.join(os.tmpdir(), "producer-lint-"));
  const planPath = path.join(tmpDir, "edit_plan.json");

  try {
    writeFileSync(planPath, planText);
    dlog("producer:lint", "run plan_lint.py", { planPath, manifestPath });
    const { stdout, code } = await runLint(planPath, manifestPath);
    try {
      const verdict = JSON.parse(stdout.trim());
      dlog("producer:lint", "verdict", { ok: verdict.ok, errors: verdict.errors?.length, code });
      return NextResponse.json(verdict);
    } catch {
      return NextResponse.json(
        { ok: false, errors: [`lint produced no verdict (exit ${code})`, stdout.slice(-300)], warnings: [] },
        { status: 500 },
      );
    }
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
}
