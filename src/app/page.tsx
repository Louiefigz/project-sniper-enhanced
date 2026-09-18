import Link from "next/link";

const SPECIALIZED_TOOLS = [
  {
    href: "/segmenter",
    name: "Split a long recording",
    product: "Segmenter",
    description:
      "Find separate topics in a long recording, adjust the suggested boundaries, and export one MP4 per clip.",
    input: "Long recording",
    output: "Clip files",
    action: "Split footage",
  },
  {
    href: "/clipper",
    name: "Make precise dialogue cuts",
    product: "Clipper",
    description:
      "Remove filler words and pauses at the word level, then export a timeline for Final Cut Pro.",
    input: "One scene or interview",
    output: "Final Cut Pro timeline",
    action: "Fine-tune a clip",
  },
  {
    href: "/frameio-review",
    name: "Check text on screen",
    product: "Text Review",
    description:
      "Scan a local MP4 for likely spelling, grammar, and formatting problems. Optional paid add-on: it sends still frames to Anthropic on your own API key, billed by Anthropic. It creates a report and does not change the video.",
    input: "Finished MP4",
    output: "Issue report",
    action: "Check a video",
  },
] as const;

export default function Home() {
  return (
    <main className="reticle-field grain relative min-h-screen overflow-hidden bg-background text-foreground">
      <div className="relative mx-auto flex min-h-screen max-w-5xl flex-col px-6 sm:px-10">
        <header className="flex items-center justify-between py-6">
          <div className="flex items-center gap-2.5">
            <span className="tally inline-block size-1.5 rounded-full" />
            <span className="label text-foreground/80">PROJECT&nbsp;SNIPER</span>
          </div>
          <span className="label text-muted-foreground">LOCAL VIDEO EDITOR</span>
        </header>

        <section className="rise-in pt-14 pb-10 sm:pt-20">
          <p className="label mb-5 flex items-center gap-3 text-signal">
            <span className="inline-block h-px w-8 bg-signal/60" />
            START HERE
          </p>
          <h1 className="max-w-4xl font-display text-[clamp(2.6rem,8vw,6rem)] font-extrabold leading-[0.94] tracking-[-0.03em]">
            Create and revise
            <br />
            <span className="text-signal">a finished video.</span>
          </h1>
          <p className="mt-6 max-w-2xl text-base leading-relaxed text-muted-foreground">
            Choose raw footage, describe the result you want, and Producer makes a finished MP4.
            Watch it, type another change, render the revision, and open the editable project in Studio.
          </p>
        </section>

        <Link
          href="/producer"
          className="rise-in group rounded-xl border border-signal/40 bg-signal/5 p-6 transition-all hover:-translate-y-0.5 hover:border-signal hover:bg-signal/10 sm:p-8"
        >
          <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="label text-signal">RECOMMENDED · PRODUCER</div>
              <h2 className="mt-2 font-display text-3xl font-bold tracking-tight">
                Create or edit a video
              </h2>
              <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
                New video: choose media and write a plain-language brief. Existing project: open it,
                watch the current version, and use the revision field directly below the preview.
              </p>
              <div className="mt-4 flex flex-wrap gap-2 text-xs text-foreground/80">
                {[
                  "1 · Choose media",
                  "2 · Describe the edit",
                  "3 · Generate and review",
                  "4 · Revise or open in Studio",
                ].map((step) => (
                  <span key={step} className="rounded-full border border-border bg-background/50 px-3 py-1">
                    {step}
                  </span>
                ))}
              </div>
            </div>
            <span className="shrink-0 rounded-md bg-signal px-5 py-3 text-sm font-semibold text-background transition-transform group-hover:translate-x-1">
              Open Producer →
            </span>
          </div>
        </Link>

        <section className="py-12" aria-labelledby="specialized-tools-title">
          <div className="mb-5">
            <h2 id="specialized-tools-title" className="font-display text-2xl font-bold">
              Specialized tools
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Use these only when their stated output is what you need. They are not required steps before Producer.
            </p>
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            {SPECIALIZED_TOOLS.map((tool) => (
              <Link
                key={tool.href}
                href={tool.href}
                className="group flex flex-col rounded-lg border border-border bg-card/50 p-5 transition-colors hover:border-signal/50 hover:bg-card/80"
              >
                <span className="label text-signal/80">{tool.product}</span>
                <h3 className="mt-2 text-lg font-semibold">{tool.name}</h3>
                <p className="mt-2 flex-1 text-sm leading-relaxed text-muted-foreground">
                  {tool.description}
                </p>
                <dl className="mt-5 grid grid-cols-2 gap-3 border-t border-border pt-4 text-xs">
                  <div>
                    <dt className="label text-muted-foreground/60">YOU PROVIDE</dt>
                    <dd className="mt-1 text-foreground/80">{tool.input}</dd>
                  </div>
                  <div>
                    <dt className="label text-muted-foreground/60">YOU GET</dt>
                    <dd className="mt-1 text-foreground/80">{tool.output}</dd>
                  </div>
                </dl>
                <span className="mt-5 text-sm font-medium text-foreground/80 group-hover:text-signal">
                  {tool.action} →
                </span>
              </Link>
            ))}
          </div>
        </section>

        <details className="mb-10 rounded-lg border border-border bg-card/30 px-5 py-4 text-sm text-muted-foreground">
          <summary className="cursor-pointer font-medium text-foreground">Where does my footage go?</summary>
          <div className="mt-3 max-w-3xl space-y-2 leading-relaxed">
            <p>
              No feature of the app uploads a video or audio file. Speech-to-text and rendering run
              on this Mac. Your Codex or Claude subscription receives the transcript, the edit plan and
              your instructions as text, and still frames of each rendered edit for its review —
              trim-only edits included.
            </p>
            <p>
              The agent that writes and revises the plan works with file tools in your project folders;
              its instructions keep video and audio on this Mac, but for that agent this is not
              enforced by the app. Reference links are downloaded with yt-dlp, and Chrome cookies are
              used only when you tick the box for that fetch. Text Review is an optional paid add-on
              that sends still frames to Anthropic on your own API key. The full list is in the
              manual&apos;s privacy page.
            </p>
          </div>
        </details>

        <footer className="mt-auto flex flex-wrap items-center justify-between gap-3 border-t border-border py-5">
          <span className="label text-muted-foreground/60">CREATE · REVIEW · REVISE</span>
          <span className="label text-muted-foreground/60">MACOS · LOCAL RENDERING</span>
        </footer>
      </div>
    </main>
  );
}
