# Type-only imports still belong to a static dependency boundary

A lower-level cut helper used `RenderCtx` only as a type annotation:

```python
if TYPE_CHECKING:
    from render import RenderCtx
```

Python does not execute that import at runtime. Sniper's headless boundary check,
however, walks the import syntax to prove that GUI and Palmier code are not
reachable. The helper made this path visible to the static graph:

```text
headless → audio/sfx_library → cut_speed → cut_reframe → render → Palmier
```

The unchanged baseline passed the tripwire; the new tree failed it. Importing
the module successfully at runtime did not establish that the static boundary
still held. This distinction also matters to code-closure receipts and packagers
that discover dependencies without executing every conditional branch.

The fix was a small structural interface beside the helper:

```python
class ReframeContext(Protocol):
    plan: dict
    manifest: dict
    resume: bool
    out_dir: str
    bootstrap_trace: list[dict]
    fused_reframe: FusedReframe | None
```

The ordinary orchestrator already supplies these facts. The helper can describe
what it consumes without importing the larger component that calls it. The
original boundary test now passes unchanged, including in the final 236-check
regression/media cohort. No scanner exclusion or frozen receipt was repinned.

Use this pattern when a low-level module needs only a few attributes from its
caller. Do not replace a concrete dependency with a protocol merely to hide a
real runtime dependency: if the helper actually needs GUI operations, its owner
or boundary needs redesign. A protocol also does not replace behavioral tests
for those attributes or their values.
