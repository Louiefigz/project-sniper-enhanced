import Nav from "@/components/shared/nav";

export default function ToolsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <>
      <a
        href="#main-content"
        className="sr-only z-[100] rounded bg-background px-4 py-2 text-foreground focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Skip to main content
      </a>
      <Nav />
      <div id="main-content" tabIndex={-1}>{children}</div>
    </>
  );
}
