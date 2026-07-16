"use client";

import { useState } from "react";

export default function OpenPalmierButton({
  dir,
  disabled,
  mode,
  onOpened,
  label = "Open in Palmier",
}: {
  dir: string;
  disabled?: boolean;
  mode?: "short" | "longform";
  onOpened?: () => void;
  label?: string;
}) {
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState("");

  const open = async () => {
    setOpening(true);
    setError("");
    try {
      const viewed = await post("/api/producer/palmier/view", { dir });
      const result = viewed.response.status === 409 && mode
        ? await post("/api/producer/palmier/workspace", { dir, mode }) : viewed;
      if (!result.response.ok) {
        throw new Error(result.body.error || `open ${result.response.status}`);
      }
      onOpened?.();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not open Palmier");
    } finally {
      setOpening(false);
    }
  };

  return (
    <span className="flex items-center gap-1">
      <button
        type="button"
        disabled={disabled || opening}
        onClick={() => void open()}
        title="Open the current working timeline. Opening changes nothing; manual edits become the next working revision."
        className="rounded border border-neutral-800 px-2 py-0.5 text-neutral-400 hover:border-neutral-600 hover:text-neutral-200 disabled:opacity-40"
      >
        {opening ? "Opening…" : label}
      </button>
      {error && <span role="alert" className="max-w-52 truncate text-red-400" title={error}>{error}</span>}
    </span>
  );
}

async function post(url: string, body: Record<string, unknown>) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const result = await response.json().catch(() => ({})) as { error?: string };
  return { response, body: result };
}
