import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { dlog } from "@/lib/debug";

export const dynamic = "force-dynamic";

// Read a render's edit_plan.json for the editor view. Read-only, and locked to
// files literally named edit_plan.json (never a generic file-read primitive):
// the write side (POST /save-plan) lands in slice 2.
export async function GET(req: NextRequest) {
  const filePath = req.nextUrl.searchParams.get("path");
  if (!filePath) return new NextResponse("Missing path", { status: 400 });
  if (filePath.split("/").includes("..")) return new NextResponse("Forbidden", { status: 403 });
  if (path.basename(filePath) !== "edit_plan.json") {
    return new NextResponse("Only edit_plan.json is served", { status: 415 });
  }
  try {
    const text = fs.readFileSync(filePath, "utf-8");
    dlog("producer:plan", "read", { file: filePath, bytes: text.length });
    return new NextResponse(text, {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return new NextResponse("Plan not found", { status: 404 });
  }
}
