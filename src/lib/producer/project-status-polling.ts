export const ACTIVE_PROJECT_POLL_MS = 2_500;
export const IDLE_PROJECT_POLL_MS = 60_000;

interface RunStatusEntry {
  status: {
    run: { status?: string } | null;
    palmier?: { candidateQc?: { active?: boolean } };
  } | null;
}

export function activeProjectDirs(
  dirs: readonly string[],
  entries: Readonly<Record<string, RunStatusEntry | undefined>>,
): string[] {
  return dirs.filter((dir) => {
    const status = entries[dir]?.status;
    return status?.run?.status === "running"
      || status?.palmier?.candidateQc?.active === true;
  });
}

/** Keep the slow lane disjoint from active polling so timer ticks never duplicate work. */
export function idleProjectDirs(
  dirs: readonly string[],
  activeDirs: readonly string[],
): string[] {
  if (!activeDirs.length) return [...dirs];
  const active = new Set(activeDirs);
  return dirs.filter((dir) => !active.has(dir));
}

export function projectStatusUrl(dir: string, recoverProcesses: boolean): string {
  return `/api/producer/project-status?dir=${encodeURIComponent(dir)}&recover=${recoverProcesses ? "1" : "0"}`;
}
