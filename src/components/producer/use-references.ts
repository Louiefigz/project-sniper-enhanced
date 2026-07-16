"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { dlog } from "@/lib/debug";
import { readEventStream } from "@/lib/producer/sse";
import type {
  ReferenceDecision,
  ReferenceEntry,
  StudyActivity,
} from "./reference-types";

type JsonRecord = Record<string, unknown>;
type SetReferences = React.Dispatch<React.SetStateAction<ReferenceEntry[]>>;

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as JsonRecord
    : {};
}

function optionalRecord<T>(value: unknown): T | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as T : null;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function normalizeReference(value: unknown, fallbackId = "reference"): ReferenceEntry {
  const row = asRecord(value);
  const dir = typeof row.dir === "string" ? row.dir : "";
  const id = typeof row.id === "string" ? row.id : dir || fallbackId;
  const status = typeof row.status === "string" || (row.status && typeof row.status === "object")
    ? row.status as ReferenceEntry["status"]
    : row.studied ? "studied" : "not-studied";
  return {
    id,
    dir,
    title: typeof row.title === "string" ? row.title : id,
    video: typeof row.video === "string" ? row.video : null,
    studied: row.studied === true,
    status,
    profile: optionalRecord<NonNullable<ReferenceEntry["profile"]>>(row.profile),
    decision: optionalRecord<NonNullable<ReferenceEntry["decision"]>>(row.decision),
    quality: optionalRecord<NonNullable<ReferenceEntry["quality"]>>(row.quality),
    metadata: optionalRecord<NonNullable<ReferenceEntry["metadata"]>>(row.metadata),
    exists: row.exists !== false,
    error: typeof row.error === "string" ? row.error : null,
    updatedAt: typeof row.updatedAt === "string" ? row.updatedAt : undefined,
  };
}

async function jsonResponse(response: Response, label: string): Promise<JsonRecord> {
  const data = asRecord(await response.json().catch(() => ({})));
  if (!response.ok) throw new Error(typeof data.error === "string" ? data.error : `${label} ${response.status}`);
  return data;
}

function mergeReference(setReferences: SetReferences, reference: ReferenceEntry): void {
  setReferences((current) => {
    const found = current.some((item) => item.id === reference.id);
    return found
      ? current.map((item) => item.id === reference.id ? { ...item, ...reference } : item)
      : [reference, ...current];
  });
}

function eventActivity(event: JsonRecord, fallbackStage = "analyzing"): StudyActivity {
  const percent = typeof event.percent === "number" ? event.percent : undefined;
  const stage = typeof event.stage === "string" ? event.stage : fallbackStage;
  const label = event.event === "progress" && percent !== undefined
    ? `${stage} · ${Math.round(percent)}%`
    : stage.replaceAll("-", " ");
  return { running: true, label, ...(percent !== undefined ? { percent } : {}) };
}

function useReferenceCollection() {
  const [references, setReferences] = useState<ReferenceEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef<ReferenceEntry[]>([]);
  useEffect(() => { latest.current = references; }, [references]);
  const refresh = useCallback(async (): Promise<ReferenceEntry[]> => {
    try {
      const response = await fetch("/api/producer/references", { cache: "no-store" });
      const data = await jsonResponse(response, "references");
      const rows = Array.isArray(data.references)
        ? data.references.map((row, index) => normalizeReference(row, `reference-${index}`))
        : [];
      setReferences(rows);
      setError(null);
      return rows;
    } catch (caught) {
      setError(errorMessage(caught, "failed to load references"));
      return latest.current;
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  return { references, setReferences, latest, loading, error, setError, refresh };
}

function useStudyAction(collection: ReturnType<typeof useReferenceCollection>) {
  const [studies, setStudies] = useState<Record<string, StudyActivity>>({});
  const study = useCallback(async (id: string) => {
    setStudies((all) => ({ ...all, [id]: { running: true, label: "starting study" } }));
    collection.setError(null);
    try {
      const response = await fetch("/api/producer/references/study", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }),
      });
      if (!response.ok) await jsonResponse(response, "study");
      await readEventStream(response, (raw) => {
        const event = asRecord(raw);
        if (event.event === "error") throw new Error(String(event.message || "study failed"));
        setStudies((all) => ({ ...all, [id]: eventActivity(event) }));
      });
      dlog("producer:references", "study done", { id });
    } catch (caught) {
      const message = errorMessage(caught, "study failed");
      collection.setError(message);
      setStudies((all) => ({ ...all, [id]: { running: false, label: message } }));
      return;
    }
    await collection.refresh();
    setStudies((all) => {
      const next = { ...all };
      delete next[id];
      return next;
    });
  }, [collection]);
  return { studies, study };
}

function useLocalAdd(collection: ReturnType<typeof useReferenceCollection>, study: (id: string) => Promise<void>) {
  const [adding, setAdding] = useState(false);
  const addLocal = useCallback(async () => {
    setAdding(true);
    collection.setError(null);
    try {
      const picked = await jsonResponse(await fetch("/api/producer/pick-file", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "file", prompt: "Choose a polished reference video" }),
      }), "picker");
      if (picked.canceled) return;
      const data = await jsonResponse(await fetch("/api/producer/references", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: picked.path }),
      }), "references");
      const created = normalizeReference(data.reference ?? data, String(data.id ?? "reference"));
      mergeReference(collection.setReferences, created);
      void study(created.id);
    } catch (caught) {
      collection.setError(errorMessage(caught, "failed to add reference"));
    } finally {
      setAdding(false);
    }
  }, [collection, study]);
  return { adding, addLocal };
}

function useUrlFetch(collection: ReturnType<typeof useReferenceCollection>, study: (id: string) => Promise<void>) {
  const [fetching, setFetching] = useState(false);
  const [fetchStatus, setFetchStatus] = useState<string | null>(null);
  const fetchUrl = useCallback(async (url: string, allowCookies: boolean): Promise<boolean> => {
    const knownIds = new Set(collection.latest.current.map((row) => row.id));
    setFetching(true);
    setFetchStatus("starting download");
    collection.setError(null);
    let completed: ReferenceEntry | null = null;
    try {
      const response = await fetch("/api/producer/references/fetch", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, allowCookies }),
      });
      if (!response.ok) await jsonResponse(response, "fetch");
      await readEventStream(response, (raw) => {
        const event = asRecord(raw);
        if (event.event === "error") throw new Error(String(event.message || "download failed"));
        setFetchStatus(eventActivity(event, "downloading").label);
        if (event.event === "done" && event.reference) completed = normalizeReference(event.reference);
      });
      const rows = await collection.refresh();
      const created = completed ?? rows.find((row) => !knownIds.has(row.id)) ?? null;
      if (!created) throw new Error("download completed but no reference was registered");
      void study(created.id);
      return true;
    } catch (caught) {
      collection.setError(errorMessage(caught, "failed to fetch reference"));
      return false;
    } finally {
      setFetching(false);
      setFetchStatus(null);
    }
  }, [collection, study]);
  return { fetching, fetchStatus, fetchUrl };
}

function useReferenceMutations(collection: ReturnType<typeof useReferenceCollection>) {
  const [savingId, setSavingId] = useState<string | null>(null);
  const saveDecision = useCallback(async (id: string, decision: ReferenceDecision) => {
    setSavingId(id);
    collection.setError(null);
    try {
      const data = await jsonResponse(await fetch("/api/producer/references/decision", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, ...decision }),
      }), "decision");
      const existing = collection.latest.current.find((row) => row.id === id);
      const updated = data.reference ? normalizeReference(data.reference) : existing ? { ...existing, decision } : null;
      if (updated) mergeReference(collection.setReferences, updated);
      return updated;
    } catch (caught) {
      collection.setError(errorMessage(caught, "failed to save decision"));
      return null;
    } finally {
      setSavingId(null);
    }
  }, [collection]);
  const remove = useCallback(async (reference: ReferenceEntry) => {
    collection.setError(null);
    try {
      const query = new URLSearchParams({ id: reference.id, dir: reference.dir });
      await jsonResponse(await fetch(`/api/producer/references?${query}`, { method: "DELETE" }), "remove");
      collection.setReferences((rows) => rows.filter((row) => row.id !== reference.id));
      return true;
    } catch (caught) {
      collection.setError(errorMessage(caught, "failed to remove reference"));
      return false;
    }
  }, [collection]);
  return { savingId, saveDecision, remove };
}

export function useReferences() {
  const collection = useReferenceCollection();
  const studyAction = useStudyAction(collection);
  const local = useLocalAdd(collection, studyAction.study);
  const remote = useUrlFetch(collection, studyAction.study);
  const mutations = useReferenceMutations(collection);
  return {
    references: collection.references,
    loading: collection.loading,
    error: collection.error,
    refresh: collection.refresh,
    ...studyAction,
    ...local,
    ...remote,
    ...mutations,
  };
}
