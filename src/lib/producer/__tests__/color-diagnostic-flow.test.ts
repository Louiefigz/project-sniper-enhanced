import assert from "node:assert/strict";
import test from "node:test";
import { colorLaunchOnce, colorResponseCurrent, initialColorFlow, launchColorJob, loadColorSources, type ColorFlowState } from "../../../components/producer/editor/use-color-diagnostic";
import { unknownColorContext } from "../color-diagnostic";

const descriptor = { ok: true as const, kind: "descriptor" as const, planHash: "a".repeat(64), manifestHash: "b".repeat(64), cutHash: "c".repeat(64),
  sources: [{ id: "raw-1", label: "inert", duration: 90, sha256: "d".repeat(64) }], blockers: [], projectHistory: [] };
test("rapid double launch invokes one task and restores guard on completion/failure", async () => {
  const guard = { current: false }; let calls = 0, finish: () => void = () => {};
  const task = () => { calls++; return new Promise<void>(resolve => { finish = resolve; }); };
  const first = colorLaunchOnce(guard, task), second = colorLaunchOnce(guard, task);
  assert.equal(calls, 1); assert.equal(guard.current, true); finish(); await Promise.all([first, second]);
  assert.equal(guard.current, false);
  await assert.rejects(colorLaunchOnce(guard, async () => { throw new Error("inert failure"); }));
  assert.equal(guard.current, false);
});
test("response fences reject older refreshes and another project", () => {
  assert(colorResponseCurrent({ dir: "a", generation: 2 }, { dir: "a", generation: 2 }));
  assert(!colorResponseCurrent({ dir: "a", generation: 1 }, { dir: "a", generation: 2 }));
  assert(!colorResponseCurrent({ dir: "a", generation: 2 }, { dir: "b", generation: 2 }));
});
test("denied session read/write produces explicit error and never leaves starting or launches", async () => {
  const originalFetch = globalThis.fetch, storage = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage");
  let calls = 0;
  let state: ColorFlowState = { ...initialColorFlow("/inert"), descriptor, contexts: descriptor.sources.map(unknownColorContext), loading: false };
  Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: {
    getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); },
  } });
  globalThis.fetch = async () => { calls++; throw new Error("must not fetch"); };
  try {
    const update = (patch: Partial<typeof state>) => { state = { ...state, ...patch }; };
    await loadColorSources("/inert", update); assert(state.storageBlocked); assert.equal(state.loading, false);
    await launchColorJob(state, update); assert.equal(state.starting, false); assert.equal(calls, 0);
    assert.match(state.error ?? "", /no worker was started/);
  } finally {
    globalThis.fetch = originalFetch;
    if (storage) Object.defineProperty(globalThis, "sessionStorage", storage); else Reflect.deleteProperty(globalThis, "sessionStorage");
  }
});
test("lost POST keeps exact private token and explicit unknown outcome without resetting it", async () => {
  const originalFetch = globalThis.fetch, storage = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage");
  const saved = new Map<string, string>();
  Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: {
    getItem: (key: string) => saved.get(key) ?? null, setItem: (key: string, value: string) => saved.set(key, value),
  } });
  globalThis.fetch = async () => { throw new Error("connection lost"); };
  let state: ColorFlowState = { ...initialColorFlow("/inert"), descriptor, contexts: descriptor.sources.map(unknownColorContext), loading: false };
  try {
    await launchColorJob(state, patch => { state = { ...state, ...patch }; });
    assert.equal(state.starting, false); assert(state.activeId); assert.equal(state.job, null);
    assert.equal(saved.get("sniper-private-color:/inert"), state.activeId);
    assert.match(state.error ?? "", /Outcome may be unknown/);
  } finally {
    globalThis.fetch = originalFetch;
    if (storage) Object.defineProperty(globalThis, "sessionStorage", storage); else Reflect.deleteProperty(globalThis, "sessionStorage");
  }
});
