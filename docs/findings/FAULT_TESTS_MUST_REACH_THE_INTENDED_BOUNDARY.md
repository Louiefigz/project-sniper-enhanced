# A refused fixture mutation is not a tested production fault

The September 10, 2026 JavaScript pass reported 15 failures in the 36-case
source-color staging batch group. These were fixture failures: the temporary
tree was created under the canonical `os.tmpdir()`, while the mutation helper
required a `/private/tmp/source-color-expectations-…` prefix. On this Mac the
creator used the per-user temporary directory instead.

The directory assertion correctly stopped the helper before it replaced files.
The outer test then rejected that assertion because it expected a production
pin/parent identity error. Accepting any exception would have produced a false
pass without exercising the intended fault.

The repair aligns the helper with its actual creator:

```typescript
assert.equal(path.dirname(root), fs.realpathSync(os.tmpdir()));
assert(path.basename(root).startsWith("source-color-expectations-"));
assert.equal(fs.realpathSync(file), file);
```

The original exact first/last paths, regular-file checks, single-link checks,
owner checks, and equality with the fixture's retained path remain in place.
The callback must actually fire, the production refusal must match the intended
boundary, and the assertions still check that nothing was published.

After the repair, all 36 cases passed, including the actual file/parent
replacements, restored-byte mutation, cancellation, reentry, and linear metadata
count checks. The final run also used the corrected 304-file current TS pin
inventory. See `docs/producer/TESTING_REPAIR_2026-09-10.md` for retained failures
and the complete rerun. This is metadata fault coverage, not native-video QA.

Use this approach when the creator deliberately follows the OS temporary
directory. If a fixture deliberately creates its tree under a fixed admitted
directory, retain that exact directory restriction instead. Do not weaken
mutation helpers to accept arbitrary observed code or media paths.
