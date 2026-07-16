"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { derror, dlog } from "@/lib/debug";
import { loadProjects } from "@/lib/producer/projects-client";
import type { Listing } from "./project-card";

function useProjectList() {
  const [projects, setProjects] = useState<Listing[]>([]);
  const [error, setError] = useState("");
  const requestRef = useRef<AbortController | null>(null);
  const refresh = useCallback(() => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    loadProjects<Listing>(controller.signal)
      .then((loaded) => { setProjects(loaded); setError(""); })
      .catch((reason) => {
        if (controller.signal.aborted) return;
        derror("producer:projects", "list failed after retry", reason);
        setError(reason instanceof Error ? reason.message : "Could not load saved projects");
      })
      .finally(() => {
        if (requestRef.current === controller) requestRef.current = null;
      });
  }, []);
  useEffect(() => {
    refresh();
    return () => requestRef.current?.abort();
  }, [refresh]);
  return { projects, error, setError, refresh };
}

function useProjectMutations(
  refresh: () => void,
  setError: (message: string) => void,
) {
  const remove = useCallback(async (dir: string) => {
    try {
      const endpoint = `/api/producer/projects?dir=${encodeURIComponent(dir)}`;
      const response = await fetch(endpoint, { method: "DELETE" });
      if (!response.ok) throw new Error(`Could not remove project (${response.status})`);
      dlog("producer:projects", "removed", { dir });
      refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not remove project");
    }
  }, [refresh, setError]);
  const rename = useCallback(async (dir: string, title: string) => {
    const response = await fetch("/api/producer/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dir, title }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || `rename ${response.status}`);
    refresh();
  }, [refresh]);
  return { remove, rename };
}

export function useRecentProjects() {
  const list = useProjectList();
  const [showAll, setShowAll] = useState(false);
  const mutations = useProjectMutations(list.refresh, list.setError);
  return { ...list, ...mutations, showAll, setShowAll };
}
