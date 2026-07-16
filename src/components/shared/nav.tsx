"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import RuntimeBadge from "./runtime-badge";

const DESTINATIONS = [
  { href: "/producer", label: "CREATE / EDIT", product: "Producer" },
  { href: "/segmenter", label: "SPLIT FOOTAGE", product: "Segmenter" },
  { href: "/clipper", label: "PRECISION CUT", product: "Clipper" },
  { href: "/frameio-review", label: "TEXT CHECK", product: "Text Review" },
] as const;

export default function Nav() {
  const pathname = usePathname();

  return (
    <div className="sticky top-0 z-50 border-b border-border bg-background/90 backdrop-blur-md">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-5 gap-y-2 px-6 py-3 sm:px-10">
        <Link href="/" className="group flex shrink-0 items-center gap-2.5" aria-label="Project Sniper home">
          <span className="tally inline-block size-1.5 rounded-full" />
          <span className="label text-foreground/80 transition-colors group-hover:text-foreground">
            PROJECT&nbsp;SNIPER
          </span>
        </Link>

        <nav
          aria-label="Video tools"
          className="order-3 flex w-full items-center gap-1 overflow-x-auto pb-0.5 sm:order-none sm:w-auto sm:flex-1 sm:pb-0"
        >
          {DESTINATIONS.map((item) => {
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                title={item.product}
                aria-current={active ? "page" : undefined}
                className={`relative shrink-0 rounded px-2.5 py-1.5 transition-colors ${
                  active
                    ? "bg-signal/10 text-foreground"
                    : "text-muted-foreground hover:bg-card hover:text-foreground"
                }`}
              >
                <span className="label text-[10px]">{item.label}</span>
                {active && <span className="absolute inset-x-2 -bottom-3 h-px bg-signal sm:-bottom-3" />}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto shrink-0">
          <RuntimeBadge />
        </div>
      </div>
    </div>
  );
}
