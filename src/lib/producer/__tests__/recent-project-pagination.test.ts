import assert from "node:assert/strict";
import test from "node:test";
import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ProjectListSection } from "@/components/producer/recent-projects";

type Props = ComponentProps<typeof ProjectListSection>;
const projects: Props["projects"] = Array.from({ length: 19 }, (_, index) => ({
  dir: `/private/tmp/test-only-project-${index + 1}/producer`, title: `TEST project ${index + 1}`,
  exists: true, mtime: null, updatedAt: "2026-09-06T00:00:00.000Z",
}));

function markup(count: number, total = 19): string {
  return renderToStaticMarkup(createElement(ProjectListSection, {
    projects: projects.slice(0, total), visibleProjects: projects.slice(0, Math.min(count, total)),
    statuses: { entries: {}, refresh: () => undefined },
    onMore: () => {}, onFewer: () => {}, onOpen: () => {}, onRemove: () => {}, onRename: async () => {},
  }));
}

test("progressive pages do not strand projects after the eighth entry", () => {
  for (const count of [3, 8, 13, 18, 19]) {
    const html = markup(count);
    assert.match(html, new RegExp(`TEST project ${count}<`));
    if (count < 19) assert.doesNotMatch(html, new RegExp(`TEST project ${count + 1}<`));
    if (count < 18) assert.match(html, /Show 5 more projects/);
    if (count === 18) assert.match(html, /Show 1 more project</);
    if (count === 19) assert.doesNotMatch(html, /more projects?/);
    if (count > 3) assert.match(html, /Show fewer projects/);
    else assert.doesNotMatch(html, /Show fewer projects/);
  }
});

test("a shortened registry cannot show negative remaining counts", () => {
  const html = markup(19, 2);
  assert.match(html, /TEST project 2</);
  assert.doesNotMatch(html, /Show .*more project|Show fewer projects/);
});
