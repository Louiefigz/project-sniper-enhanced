import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { test } from "node:test";
import { PLANNING_GATE_IDS } from "@/app/api/producer/auto-edit/planning-gate-contract";
import { readinessContainerName, readinessRenderer, reconcileReadinessContainers, sealedRendererConfigured,
  type DockerExec } from "../readiness-render-containers";

const ID = "0f4b6a1c-3d2e-4f5a-8b7c-9d0e1f2a3b4c", CONFIG = { dockerPath: "/TEST/docker", socket: "/TEST/docker.sock" };

test("only a fully configured sealed renderer yields owned per-gate container names", () => {
  assert.equal(sealedRendererConfigured({}), null);
  assert.equal(sealedRendererConfigured({ SNIPER_RENDER_IMAGE_ID: "sha256:x", SNIPER_DOCKER_PATH: "/d" }), null);
  assert.deepEqual(sealedRendererConfigured({ SNIPER_RENDER_IMAGE_ID: "sha256:x", SNIPER_DOCKER_PATH: "/d", SNIPER_DOCKER_SOCKET: "/s" }),
    { dockerPath: "/d", socket: "/s" });
  // The sealed renderer only accepts `sniper-render-<32 hex>` (container_renderer.py _CONTAINER_NAME); the hex is our own derivation.
  const compSize = readinessContainerName(ID, "comp_size");
  assert.match(compSize, /^sniper-render-[0-9a-f]{32}$/);
  assert.equal(compSize, `sniper-render-${createHash("sha256").update(`readiness|${ID}|comp_size`).digest("hex").slice(0, 32)}`);
  assert.throws(() => readinessContainerName("not-an-id", "comp_size"), /exact execution id/);
  const names = new Set(PLANNING_GATE_IDS.map((gate) => readinessContainerName(ID, gate)));
  assert.equal(names.size, PLANNING_GATE_IDS.length);
  let reads = 0;
  const tools = { executionId: ID, proofTools: () => { reads += 1; return { ffmpeg: "/TEST/ffmpeg", ffprobe: "/TEST/ffprobe" }; } };
  assert.equal(readinessRenderer(tools, {}), null); assert.equal(reads, 0);   // host renderer never touches the toolchain
  const sealed = { SNIPER_RENDER_IMAGE_ID: "sha256:x", SNIPER_DOCKER_PATH: "/d", SNIPER_DOCKER_SOCKET: "/s" };
  const renderer = readinessRenderer(tools, sealed, () => ({ code: 0, stdout: "", stderr: "" }));
  assert.deepEqual(renderer!.env("geometry_feasibility"), { SNIPER_RENDER_CONTAINER_NAME: readinessContainerName(ID, "geometry_feasibility"),
    SNIPER_PROOF_FFMPEG_PATH: "/TEST/ffmpeg", SNIPER_PROOF_FFPROBE_PATH: "/TEST/ffprobe" });
  assert.equal(reads, 1);
  assert.throws(() => readinessRenderer({ ...tools, proofTools: () => ({ ffmpeg: "ffmpeg", ffprobe: "/TEST/ffprobe" }) }, sealed), /absolute pinned/);
});

test("reconciliation removes only this execution's exact names and fails closed when absence cannot be verified", () => {
  const calls: string[][] = [];
  const own = (gate: "comp_size" | "plan_lint") => readinessContainerName(ID, gate);
  let listing = [own("comp_size"), "someone-elses-container", own("plan_lint")];
  const exec: DockerExec = (config, args) => {
    calls.push(args); assert.equal(config, CONFIG);
    if (args[0] === "ps") return { code: 0, stdout: `${listing.join("\n")}\n`, stderr: "" };
    if (args[0] === "rm") { listing = listing.filter((name) => name !== args[2]); return { code: 0, stdout: "", stderr: "" }; }
    throw new Error(`unexpected docker ${args.join(" ")}`);
  };
  const result = reconcileReadinessContainers(CONFIG, ID, exec);
  assert.deepEqual(result.present, [own("comp_size"), own("plan_lint")]);
  assert.deepEqual(result.removed, result.present); assert.equal(result.verifiedAbsent, true);
  assert.ok(calls.every((args) => args[0] === "ps" || (args[0] === "rm" && args[1] === "-f" && /^sniper-render-[0-9a-f]{32}$/.test(args[2]))));
  assert.ok(listing.includes("someone-elses-container"));
  const stuck: DockerExec = (_config, args) => args[0] === "ps"
    ? { code: 0, stdout: `${own("comp_size")}\n`, stderr: "" } : { code: 1, stdout: "", stderr: "TEST rm refused" };
  const unresolved = reconcileReadinessContainers(CONFIG, ID, stuck);
  assert.equal(unresolved.verifiedAbsent, false); assert.deepEqual(unresolved.removed, []); assert.match(unresolved.detail, /still present/);
  const down: DockerExec = () => ({ code: null, stdout: "", stderr: "TEST daemon unreachable" });
  assert.equal(reconcileReadinessContainers(CONFIG, ID, down).verifiedAbsent, false);
});
