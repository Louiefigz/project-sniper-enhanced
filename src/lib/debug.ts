// Lightweight end-to-end debug logging, shared by both tools.
//
// ON by default so a run is fully traced with zero setup; silence everything by
// setting NEXT_PUBLIC_SNIPER_DEBUG=0 in .env.local. Works in BOTH client
// components (browser console) and server route handlers (the `npm run dev`
// terminal). The matching Python flag is SNIPER_DEBUG (stderr), see scripts/.
//
// TERMINAL VISIBILITY: client logs normally only reach the browser console. For
// CLIPPER scopes ("clipper:*") and FRAME.IO REVIEW scopes ("frameio:*") we ALSO
// POST each event to the matching /api/*/debug-log route so the dev-server
// terminal shows the WHOLE flow (client + server + python) in one place.
//
// Lines look like:  [SNIPER 12:01:03.412 client clipper:browse] picked Host camera { ... }

const ENABLED = process.env.NEXT_PUBLIC_SNIPER_DEBUG !== "0";

function stamp(): string {
  try {
    return new Date().toISOString().slice(11, 23);
  } catch {
    return "--:--:--";
  }
}

function truncate(s: string, max: number): string {
  return s.length > max ? `${s.slice(0, max)}… (+${s.length - max} more chars)` : s;
}

/**
 * Make a big value safe/cheap to log: long strings are truncated, arrays are
 * reduced to {length, sample of first 3}, nested objects pass through. Use this
 * for transcripts/word lists/XML so the console stays readable.
 */
export function summarize(value: unknown, maxStr = 1200): unknown {
  if (value == null) return value;
  if (typeof value === "string") return truncate(value, maxStr);
  if (Array.isArray(value)) {
    return {
      _array: true,
      length: value.length,
      sample: value.slice(0, 3).map((v) => summarize(v, 300)),
    };
  }
  return value;
}

/** Length helper for arrays/strings, null-safe. */
export function len(value: unknown): number {
  if (value == null) return 0;
  if (typeof value === "string" || Array.isArray(value)) return value.length;
  return 0;
}

// Turn an Error (or anything) into a JSON-safe, detailed object for logging.
function errToObj(err: unknown): unknown {
  if (err instanceof Error) {
    return { name: err.name, message: err.message, stack: err.stack };
  }
  return err;
}

// Client → dev-terminal forwarder. Best-effort, never throws. Limited to the two
// tools that opt into full end-to-end terminal tracing (CLIPPER + FRAME.IO REVIEW).
function forwardToTerminal(scope: string, event: string, data?: unknown): void {
  if (typeof window === "undefined") return;        // server already prints to terminal
  const endpoint = scope.startsWith("clipper")
    ? "/api/clipper/debug-log"
    : scope.startsWith("frameio")
      ? "/api/frameio-review/debug-log"
      : null;
  if (!endpoint) return;
  try {
    let safeData: unknown = data;
    try {
      JSON.stringify(data);                          // probe for circular refs / BigInt
    } catch {
      safeData = String(data);
    }
    const body = JSON.stringify({ scope, event, data: safeData, t: stamp() });
    if (navigator.sendBeacon) {
      navigator.sendBeacon(endpoint, new Blob([body], { type: "application/json" }));
    } else {
      void fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        keepalive: true,
      }).catch(() => {});
    }
  } catch {
    /* never let logging break the app */
  }
}

/**
 * Log one step. `scope` is "tool:step" (e.g. "clipper:transcribe"); `event` is a
 * short human phrase; `data` (optional) is any payload — pass summarize(...) for
 * large structures. CLIPPER-scoped client logs are also mirrored to the terminal.
 */
export function dlog(scope: string, event: string, data?: unknown): void {
  if (!ENABLED) return;
  const where = typeof window === "undefined" ? "server" : "client";
  const prefix = `[SNIPER ${stamp()} ${where} ${scope}]`;
  if (data === undefined) {
    console.log(`${prefix} ${event}`);
  } else {
    console.log(`${prefix} ${event}`, data);
  }
  forwardToTerminal(scope, event, data);
}

/**
 * Log a client/server-only line WITHOUT forwarding to the terminal. Use for
 * high-volume echoes (e.g. python stderr already mirrored to the terminal)
 * that would otherwise be logged twice in the terminal.
 */
export function dlogLocal(scope: string, event: string, data?: unknown): void {
  if (!ENABLED) return;
  const where = typeof window === "undefined" ? "server" : "client";
  const prefix = `[SNIPER ${stamp()} ${where} ${scope}]`;
  if (data === undefined) console.log(`${prefix} ${event}`);
  else console.log(`${prefix} ${event}`, data);
}

/** Log an error with its full message + stack, mirrored to the terminal for clipper scopes. */
export function derror(scope: string, event: string, err: unknown): void {
  if (!ENABLED) return;
  const where = typeof window === "undefined" ? "server" : "client";
  const detail = errToObj(err);
  console.error(`[SNIPER ${stamp()} ${where} ${scope}] ERROR ${event}`, detail);
  forwardToTerminal(scope, `ERROR ${event}`, detail);
}

let errorCaptureInstalled = false;
/**
 * Install global browser handlers that forward uncaught errors and unhandled
 * promise rejections to the terminal. Call once from the CLIPPER page so we
 * catch crashes that never reach a try/catch. No-op on the server / when off.
 */
export function installClientErrorCapture(): void {
  if (errorCaptureInstalled || typeof window === "undefined" || !ENABLED) return;
  errorCaptureInstalled = true;
  window.addEventListener("error", (e) => {
    forwardToTerminal("clipper:window", "uncaught error", {
      message: e.message,
      source: `${e.filename}:${e.lineno}:${e.colno}`,
      stack: (e.error as Error | undefined)?.stack,
    });
  });
  window.addEventListener("unhandledrejection", (e) => {
    const r = e.reason;
    forwardToTerminal("clipper:window", "unhandled promise rejection",
      r instanceof Error ? { message: r.message, stack: r.stack } : { reason: String(r) });
  });
  dlog("clipper:window", "error capture installed");
}

export const DEBUG_ENABLED = ENABLED;
