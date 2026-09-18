export interface SerialRequestQueueOptions<T> {
  request: (key: string, signal: AbortSignal) => Promise<T>;
  onSuccess: (key: string, value: T) => void;
  onError: (key: string, error: unknown) => void;
  shouldRun?: (key: string) => boolean;
}

/** Deduplicated, single-concurrency request queue with abortable cleanup. */
export class SerialRequestQueue<T> {
  private readonly pending = new Set<string>();
  private controller: AbortController | null = null;
  private draining = false;
  private disposed = false;

  constructor(private readonly options: SerialRequestQueueOptions<T>) {}

  enqueue(keys: Iterable<string>): void {
    if (this.disposed) return;
    for (const key of keys) this.pending.add(key);
    void this.drain();
  }

  pause(): void {
    this.pending.clear();
    this.controller?.abort();
  }

  dispose(): void {
    this.disposed = true;
    this.pause();
  }

  private takeNext(): string | null {
    for (const key of this.pending) {
      this.pending.delete(key);
      if (!this.options.shouldRun || this.options.shouldRun(key)) return key;
    }
    return null;
  }

  private async run(key: string): Promise<void> {
    const controller = new AbortController();
    this.controller = controller;
    try {
      const value = await this.options.request(key, controller.signal);
      if (!this.disposed && this.options.shouldRun?.(key) !== false) {
        this.options.onSuccess(key, value);
      }
    } catch (error) {
      if (!controller.signal.aborted && !this.disposed) this.options.onError(key, error);
    } finally {
      if (this.controller === controller) this.controller = null;
    }
  }

  private async drain(): Promise<void> {
    if (this.draining || this.disposed) return;
    this.draining = true;
    try {
      for (;;) {
        if (this.disposed) return;
        const key = this.takeNext();
        if (!key) return;
        await this.run(key);
      }
    } finally {
      this.draining = false;
      if (!this.disposed && this.pending.size) void this.drain();
    }
  }
}
