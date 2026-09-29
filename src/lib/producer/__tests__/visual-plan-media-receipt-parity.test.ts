import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { validateAdmissionReceiptDocument, type AdmissionIdentity } from
  "../../../app/api/producer/auto-edit/visual-plan-media-receipt";

const H = "a".repeat(64), PROFILE = "b".repeat(64), SNAPSHOT = "/missing/admitted.media";
const LIMITS = { max_bytes: 16 * 1024 ** 3, max_width: 8192, max_height: 8192,
  max_frames: 2_000_000, max_duration_seconds: 6 * 60 * 60,
  max_streams: 32, max_decode_seconds: 20 * 60 };
const PYTHON = String.raw`
import json, sys
from headless.admission_receipt import validate_admission_receipt
try:
    validate_admission_receipt(json.load(sys.stdin))
except Exception:
    raise SystemExit(1)
`;

type Document = Record<string, unknown>;

function objectAt(value: Document, ...keys: Array<string | number>): Document {
  let current: unknown = value;
  for (const key of keys) {
    assert.ok(current !== null && typeof current === "object");
    current = (current as Document)[key];
  }
  assert.ok(current !== null && typeof current === "object");
  return current as Document;
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

function decoded(kind = "timed-media", size = 100): Document {
  const timed = kind === "timed-media";
  const font = kind === "font";
  const svg = kind === "svg";
  return { schemaVersion: 1, ok: true, decoded: true, facts: {
    mediaKind: kind, durationSeconds: timed ? 1 : 0, sizeBytes: size,
    width: font ? 0 : 32, height: font ? 0 : 18,
    videoStreams: font ? 0 : 1, audioStreams: timed ? 1 : 0,
    streamCount: font || svg ? 1 : timed ? 2 : 1,
    declaredFrames: font ? 0 : svg ? 1 : timed ? 24 : 1,
  } };
}

function tool(name: string) {
  return { path: `/approved/${name}`, sha256: H, version: "fixture" };
}

function run(decoder: string, kind: "mac" | "windows"): Document {
  const value: Document = { sandboxed: true,
    mode: decoder === "/dev/null" ? "inspect" : "exec", decoder,
    input: SNAPSHOT, profileSha256: PROFILE, memoryMiB: 768 };
  if (kind === "windows") {
    return { ...value, kind: "windows-appcontainer", networkCapabilities: 0,
      ephemeralProfile: true, writeDeniedOutsideProfile: true,
      job: { activeProcessLimit: 1 } };
  }
  return { ...value,
    rlimits: { RLIMIT_FSIZE: [0, 0], RLIMIT_CORE: [0, 0] } };
}

function approvedPair(): Document {
  const file = path.join(process.cwd(),
    "scripts/producer/headless/native_media_runtime_approval.json");
  return JSON.parse(readFileSync(file, "utf8")).approved[0];
}

function nativeReceipt(platform: "mac" | "windows" = "mac",
  kind = "timed-media"): Document {
  const tools = { ffprobe: tool("ffprobe"), ffmpeg: tool("ffmpeg") };
  const mac = platform === "mac", approval = approvedPair();
  const runtime: Document = mac ? {
    kind: "macos-seatbelt", policy: "sniper-native-media-jail-v2",
    profileTemplateSha256: approval.profileTemplateSha256,
    profileSha256: PROFILE, launcherSha256: approval.launcherSha256,
    closureSha256: H, closureCount: 2, openedPathCount: 3, tools,
  } : {
    kind: "windows-appcontainer", policy: "sniper-windows-appcontainer-v1",
    profileSha256: PROFILE, appContainerSid: "S-1-15-2-fixture",
    sourceSha256: { "windows_media_jail.cs": H, "windows_media_inspect.cs": H },
    launcher: { sha256: H }, inspector: { sha256: H }, tools,
  };
  const isolation: Document = mac ? {
    kind: "macos-seatbelt", policy: "sniper-native-media-jail-v2",
    network: "denied", processCreation: "denied", writes: "/dev/null only",
    otherProcesses: "denied", watchdog: "footprint+cpu", memoryMiB: 768,
    profileSha256: PROFILE,
  } : {
    kind: "windows-appcontainer", policy: "sniper-windows-appcontainer-v1",
    network: "denied", processCreation: "job-limited",
    writes: "ephemeral profile only", otherProcesses: "denied",
    watchdog: "job-object", memoryMiB: 768, profileSha256: PROFILE,
  };
  const steps = kind === "font" || kind === "svg"
    ? ["/dev/null"] : ["/dev/null", tools.ffprobe.path, tools.ffmpeg.path];
  isolation.jailRuns = steps.map(decoder => run(decoder, platform));
  return { schemaVersion: 1, policy: "sniper-external-media-probe-v4-native",
    snapshot: { path: SNAPSHOT, sha256: H, sizeBytes: 100 },
    limits: clone(LIMITS), runtime, isolation, decoded: decoded(kind) };
}

function containerReceipt(): Document {
  return { schemaVersion: 1, policy: "sniper-external-media-probe-v3",
    snapshot: { path: SNAPSHOT, sha256: H, sizeBytes: 100 },
    limits: clone(LIMITS), image: { historical: true },
    isolation: { retained: "opaque historical evidence" }, network: {},
    decoded: decoded() };
}

function identity(document: Document): AdmissionIdentity {
  const snapshot = objectAt(document, "snapshot");
  const facts = objectAt(document, "decoded", "facts");
  assert.equal(typeof snapshot.path, "string");
  assert.equal(typeof snapshot.sha256, "string");
  assert.equal(typeof snapshot.sizeBytes, "number");
  assert.equal(typeof facts.mediaKind, "string");
  return { snapshotPath: snapshot.path as string, sha256: snapshot.sha256 as string,
    sizeBytes: snapshot.sizeBytes as number, mediaKind: facts.mediaKind as string };
}

function pythonAccepts(document: Document): boolean {
  const result = spawnSync(path.join(process.cwd(), ".venv/bin/python"), ["-c", PYTHON], {
    input: JSON.stringify(document), encoding: "utf8",
    env: { ...process.env, PYTHONPATH: path.join(process.cwd(), "scripts/producer") },
  });
  return result.status === 0;
}

function typescriptAccepts(document: Document): boolean {
  try {
    validateAdmissionReceiptDocument(document, identity(document));
    return true;
  } catch { return false; }
}

function mutation(base: () => Document, change: (value: Document) => void): Document {
  const value = base();
  change(value);
  return value;
}

function main(): void {
  const cases: Array<[string, Document, boolean]> = [
    ["valid approved macOS receipt", nativeReceipt(), true],
    ["valid approved Windows receipt", nativeReceipt("windows"), true],
    ["valid one-step font receipt", nativeReceipt("mac", "font"), true],
    ["historical container receipt keeps Python semantics", containerReceipt(), true],
    ["unsupported media kind", mutation(nativeReceipt, value => {
      objectAt(value, "decoded", "facts").mediaKind = "archive";
    }), false],
    ["kind facts are inconsistent", mutation(nativeReceipt, value => {
      objectAt(value, "decoded", "facts").videoStreams = 0; objectAt(value, "decoded", "facts").audioStreams = 0;
      objectAt(value, "decoded", "facts").width = 0; objectAt(value, "decoded", "facts").height = 0;
      objectAt(value, "decoded", "facts").declaredFrames = 0;
    }), false],
    ["facts must be numeric", mutation(nativeReceipt, value => {
      objectAt(value, "decoded", "facts").durationSeconds = "1";
    }), false],
    ["duration bound", mutation(nativeReceipt, value => {
      objectAt(value, "decoded", "facts").durationSeconds = LIMITS.max_duration_seconds + 1;
    }), false],
    ["dimension bound", mutation(nativeReceipt, value => {
      objectAt(value, "decoded", "facts").width = LIMITS.max_width + 1;
    }), false],
    ["frame bound", mutation(nativeReceipt, value => {
      objectAt(value, "decoded", "facts").declaredFrames = LIMITS.max_frames + 1;
    }), false],
    ["stream bound", mutation(nativeReceipt, value => {
      objectAt(value, "decoded", "facts").streamCount = LIMITS.max_streams + 1;
    }), false],
    ["integer count", mutation(nativeReceipt, value => {
      objectAt(value, "decoded", "facts").declaredFrames = 1.5;
    }), false],
    ["size bound", mutation(nativeReceipt, value => {
      objectAt(value, "decoded", "facts").sizeBytes = LIMITS.max_bytes + 1;
      objectAt(value, "snapshot").sizeBytes = LIMITS.max_bytes + 1;
    }), false],
    ["approved runtime identity", mutation(nativeReceipt, value => {
      objectAt(value, "runtime").profileTemplateSha256 = "f".repeat(64);
    }), false],
    ["runtime closure counts", mutation(nativeReceipt, value => {
      objectAt(value, "runtime").closureCount = 0;
    }), false],
    ["run mode", mutation(nativeReceipt, value => {
      objectAt(value, "isolation", "jailRuns", 1).mode = "inspect";
    }), false],
    ["macOS rlimit", mutation(nativeReceipt, value => {
      objectAt(value, "isolation", "jailRuns", 2, "rlimits").RLIMIT_FSIZE = [1, 1];
    }), false],
    ["macOS isolation", mutation(nativeReceipt, value => {
      objectAt(value, "isolation").processCreation = "allowed";
    }), false],
    ["AppContainer runtime source identity", mutation(
      () => nativeReceipt("windows"), value => {
        delete objectAt(value, "runtime", "sourceSha256")["windows_media_inspect.cs"];
      }), false],
    ["AppContainer run confinement", mutation(
      () => nativeReceipt("windows"), value => {
        objectAt(value, "isolation", "jailRuns", 1).networkCapabilities = 1;
      }), false],
    ["AppContainer isolation", mutation(
      () => nativeReceipt("windows"), value => {
        objectAt(value, "isolation").writes = "host";
      }), false],
  ];
  for (const [label, document, expected] of cases) {
    const python = pythonAccepts(document), typescript = typescriptAccepts(document);
    assert.equal(python, expected, `${label}: unexpected Python result`);
    assert.equal(typescript, python, `${label}: TypeScript/Python admission drift`);
  }
  console.log(`visual-plan media receipt parity tests passed (${cases.length} cases)`);
}

main();
