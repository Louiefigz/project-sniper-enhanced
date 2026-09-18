const PROJECTS_ENDPOINT = "/api/producer/projects";
const RETRYABLE_STATUSES = new Set([502, 503, 504]);

type ProjectFetcher = typeof fetch;
type RetryDelay = (milliseconds: number, signal: AbortSignal) => Promise<void>;

export interface ProjectsClientDeps {
  fetcher?: ProjectFetcher;
  delay?: RetryDelay;
  retryDelayMs?: number;
}

export class ProjectsClientError extends Error {
  constructor(
    message: string,
    readonly retryable: boolean,
    readonly detail?: string,
  ) {
    super(message);
    this.name = "ProjectsClientError";
  }
}

function isJsonResponse(response: Response): boolean {
  const contentType = response.headers.get("content-type")?.split(";", 1)[0].trim();
  return contentType === "application/json" || Boolean(contentType?.endsWith("+json"));
}

function payloadError(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const error = (payload as { error?: unknown }).error;
  return typeof error === "string" && error.trim() ? error : null;
}

function isOpaqueEngineError(message: string | null): boolean {
  return Boolean(message && /string did not match the expected pattern/i.test(message));
}

function transientResponseError(response: Response, detail: string): ProjectsClientError {
  return new ProjectsClientError(
    `The local project index returned an unreadable response (HTTP ${response.status}).`,
    response.ok || response.status >= 500,
    detail,
  );
}

async function parseProjects<T>(response: Response): Promise<T[]> {
  const text = await response.text();
  if (!isJsonResponse(response)) throw transientResponseError(response, text.slice(0, 240));
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch (error) {
    throw transientResponseError(response, error instanceof Error ? error.message : String(error));
  }
  const serverError = payloadError(payload);
  if (!response.ok && isOpaqueEngineError(serverError)) {
    throw transientResponseError(response, serverError ?? "opaque parser error");
  }
  if (!response.ok) {
    throw new ProjectsClientError(
      serverError ?? `Could not load saved projects (HTTP ${response.status}).`,
      RETRYABLE_STATUSES.has(response.status),
    );
  }
  const projects = (payload as { projects?: unknown } | null)?.projects;
  if (!Array.isArray(projects)) throw transientResponseError(response, "projects was not an array");
  return projects as T[];
}

async function requestProjects<T>(fetcher: ProjectFetcher, signal: AbortSignal): Promise<T[]> {
  try {
    const response = await fetcher(PROJECTS_ENDPOINT, { cache: "no-store", signal });
    return await parseProjects<T>(response);
  } catch (error) {
    if (signal.aborted || error instanceof ProjectsClientError) throw error;
    throw new ProjectsClientError(
      "The local project index could not be reached.",
      true,
      error instanceof Error ? error.message : String(error),
    );
  }
}

function defaultDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const finish = () => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    };
    const timer = globalThis.setTimeout(finish, milliseconds);
    const onAbort = () => {
      signal.removeEventListener("abort", onAbort);
      globalThis.clearTimeout(timer);
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
    if (signal.aborted) onAbort();
  });
}

/** Load saved projects, retrying one transient local-server response. */
export async function loadProjects<T>(
  signal: AbortSignal,
  deps: ProjectsClientDeps = {},
): Promise<T[]> {
  const fetcher = deps.fetcher ?? fetch;
  try {
    return await requestProjects<T>(fetcher, signal);
  } catch (error) {
    if (signal.aborted || !(error instanceof ProjectsClientError) || !error.retryable) throw error;
    await (deps.delay ?? defaultDelay)(deps.retryDelayMs ?? 250, signal);
    return await requestProjects<T>(fetcher, signal);
  }
}
