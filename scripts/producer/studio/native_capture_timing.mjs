/** Phase timing for native capture children: telemetry only, never a gate or a changed call. */
import path from 'node:path';
import {performance} from 'node:perf_hooks';
import {pathToFileURL} from 'node:url';

/** The pinned SDK entry points a capture child spends its time in, by reported phase. */
const PHASES = Object.freeze({runCompileStage: 'compile', extractAllVideoFrames: 'sourceExtraction',
  extractMediaMetadata: 'sourceMetadata', createFileServer2: 'fileServer', createCaptureSession: 'browserLaunch',
  initializeSession: 'sessionInitialize', captureFrame: 'captureFrame', closeCaptureSession: 'sessionClose',
  drainBrowserPool: 'browserDrain'});
const PERF_KEYS = ['frames', 'seekMs', 'beforeCaptureMs', 'screenshotMs', 'totalMs'];

/** One child's timing ledger; `started` anchors every mark on this process's monotonic clock. */
export function nativeTimingLedger() {
  return {started: performance.now(), phases: {}, sessions: [], marks: {}};
}

function add(ledger, phase, milliseconds) {
  const row = ledger.phases[phase] ??= {calls: 0, ms: 0};
  row.calls += 1; row.ms += milliseconds;
}

/** Time one awaited step under a named mark (for work outside the SDK: hashing, encoding, receipts). */
export async function timedStep(ledger, name, action) {
  const started = performance.now();
  try { return await action(); } finally { add(ledger, name, performance.now() - started); }
}

/** Keep the SDK's own per-session split of seek, frame injection and screenshot time. */
function sessionPerf(session) {
  const perf = session?.capturePerf;
  if (!perf) return null;
  return Object.fromEntries(PERF_KEYS.filter(key => Number.isFinite(perf[key])).map(key => [key, perf[key]]));
}

/**
 * Wrap the pinned SDK's own async functions: arguments, results and errors pass through
 * unchanged; only elapsed time is recorded. Synchronous helpers are not wrapped.
 */
export function timedNativeSdk(sdk, ledger) {
  const timed = {...sdk};
  for (const [name, phase] of Object.entries(PHASES)) {
    if (typeof sdk[name] !== 'function') continue;
    timed[name] = async (...args) => {
      if (name === 'closeCaptureSession') ledger.sessions.push(sessionPerf(args[0]));
      const started = performance.now();
      try { return await sdk[name](...args); } finally { add(ledger, phase, performance.now() - started); }
    };
  }
  return timed;
}

/** Import the same library file the capture context pins, so it can be timed before use. */
export async function importNativeCaptureLibrary(request) {
  return import(pathToFileURL(path.join(request.runtime, 'dist/native-capture-library.mjs')).href);
}

/** A bounded, rounded summary suitable for a receipt. */
export function nativeTimingSummary(ledger) {
  const round = value => Math.round(value * 1000) / 1000;
  return {schemaVersion: 1, clock: 'process-monotonic-ms', scope: 'telemetry only; not a quality or admission gate',
    elapsedMs: round(performance.now() - ledger.started),
    phases: Object.fromEntries(Object.entries(ledger.phases).map(([key, row]) => [key, {calls: row.calls, ms: round(row.ms)}])),
    sessions: ledger.sessions.map(row => row && Object.fromEntries(Object.entries(row).map(([key, value]) => [key, round(value)]))),
    marks: ledger.marks};
}
