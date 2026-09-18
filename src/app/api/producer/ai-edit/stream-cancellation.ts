export interface StreamCancellationFence {
  signal: AbortSignal;
  wait: Promise<void>;
  cancel: () => void;
  settle: () => void;
  isCancelled: () => boolean;
}

/** Keep the mutation lease alive until the writer/finalizer actually settles. */
export function createStreamCancellationFence(): StreamCancellationFence {
  const controller = new AbortController();
  let cancelled = false;
  let settled = false;
  let resolveWait: () => void = () => {};
  const wait = new Promise<void>((resolve) => {
    resolveWait = resolve;
  });
  return {
    signal: controller.signal,
    wait,
    cancel: () => {
      cancelled = true;
      controller.abort();
    },
    settle: () => {
      if (settled) return;
      settled = true;
      resolveWait();
    },
    isCancelled: () => cancelled,
  };
}

export function assertStreamActive(signal?: AbortSignal): void {
  if (signal?.aborted) throw new Error("Ask Editor edit was cancelled");
}

/** Settle cancellation even when rollback, cleanup, or lease release fails. */
export function finishStream(
  fence: StreamCancellationFence,
  release: () => void,
  close: () => void,
  rollback?: () => void,
): unknown {
  let failure: unknown;
  try {
    rollback?.();
  } catch (error) {
    failure = error;
  }
  try {
    release();
  } catch (error) {
    failure ??= error;
  } finally {
    fence.settle();
    try { close(); } catch {}
  }
  return failure;
}
