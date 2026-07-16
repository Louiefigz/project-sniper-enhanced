"use client";

import { useState } from "react";
import { Download, FilePlus2, Loader2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Props {
  adding: boolean;
  fetching: boolean;
  fetchStatus: string | null;
  onAddLocal: () => void;
  onFetch: (url: string, allowCookies: boolean) => Promise<boolean>;
}

function IntakeHeader({ adding, fetching, onAddLocal }: Pick<Props, "adding" | "fetching" | "onAddLocal">) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p className="text-xs font-medium text-foreground">Add a polished video</p>
        <p className="mt-0.5 text-[11px] text-muted-foreground">
          Intake starts the deterministic study automatically. You confirm its format and style direction afterward.
        </p>
      </div>
      <Button variant="outline" size="sm" disabled={adding || fetching} onClick={onAddLocal}>
        {adding ? <Loader2 className="size-3.5 animate-spin" /> : <FilePlus2 className="size-3.5" />}
        {adding ? "Copying…" : "Local video"}
      </Button>
    </div>
  );
}

function CookieOption({ checked, disabled, onChange }: {
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-2 text-[11px] text-muted-foreground">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 accent-signal"
      />
      <span>
        <span className="inline-flex items-center gap-1 text-foreground/80">
          <ShieldCheck className="size-3" /> Allow Chrome cookies for this fetch
        </span>
        <span className="block text-muted-foreground/60">
          Optional. Reads your local Chrome session only for a URL that requires sign-in; leave off for public videos.
        </span>
      </span>
    </label>
  );
}

function UrlFetcher({ adding, fetching, fetchStatus, onFetch }: Omit<Props, "onAddLocal">) {
  const [url, setUrl] = useState("");
  const [allowCookies, setAllowCookies] = useState(false);
  const fetchUrl = async () => {
    const value = url.trim();
    if (!value || fetching) return;
    if (await onFetch(value, allowCookies)) setUrl("");
  };
  return (
    <>
      <div className="flex items-center gap-2">
        <Input
          type="url"
          inputMode="url"
          placeholder="YouTube, Instagram, or TikTok URL"
          value={url}
          disabled={fetching || adding}
          onChange={(event) => setUrl(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void fetchUrl();
          }}
          className="h-8 font-mono text-xs"
        />
        <Button
          variant="outline"
          size="sm"
          disabled={fetching || adding || !url.trim()}
          onClick={() => void fetchUrl()}
        >
          {fetching ? <Loader2 className="size-3.5 animate-spin" /> : <Download className="size-3.5" />}
          Fetch
        </Button>
      </div>
      <p className="text-[10px] text-muted-foreground/60">
        HTTPS only · capped at 1080p, 2 GiB, and 60 minutes · 5 GiB free disk required.
      </p>
      <CookieOption checked={allowCookies} disabled={fetching} onChange={setAllowCookies} />
      {fetching && fetchStatus && (
        <p className="font-mono text-[11px] text-signal">{fetchStatus}</p>
      )}
    </>
  );
}

export default function ReferenceIntake(props: Props) {
  return (
    <div className="space-y-3 rounded-md border border-border/70 bg-background/30 p-3">
      <IntakeHeader adding={props.adding} fetching={props.fetching} onAddLocal={props.onAddLocal} />
      <UrlFetcher
        adding={props.adding}
        fetching={props.fetching}
        fetchStatus={props.fetchStatus}
        onFetch={props.onFetch}
      />
    </div>
  );
}
