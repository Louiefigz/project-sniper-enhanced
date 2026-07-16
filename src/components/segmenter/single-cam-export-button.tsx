"use client";

import { useState } from "react";

interface ExportSegment {
  title: string;
  start: number;
  end: number;
}

export default function SingleCamExportButton({
  filePath,
  segments,
  disabled,
}: {
  filePath: string;
  segments: ExportSegment[];
  disabled: boolean;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const download = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/segmenter/export-mp4", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filePath, segments }),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.error || `export ${response.status}`);
      }
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "segments.zip";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Export failed");
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="mb-3">
      <button
        type="button"
        onClick={download}
        disabled={disabled || loading}
        className="flex w-full items-center justify-between rounded-xl border border-neutral-700 bg-neutral-900/40 px-5 py-4 text-left transition hover:border-neutral-500 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <span>
          <span className="block text-sm font-semibold text-neutral-100">{loading ? "Creating download…" : "Download selected MP4 clips"}</span>
          <span className="mt-0.5 block text-xs text-neutral-500">One MP4 per selected clip, bundled in a zip file.</span>
        </span>
        <span>{loading ? "⏳" : "⬇"}</span>
      </button>
      {error && <p role="alert" className="mt-1 text-xs text-red-400">{error}</p>}
    </div>
  );
}
