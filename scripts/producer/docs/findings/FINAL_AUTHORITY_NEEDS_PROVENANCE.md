# A clean final is not necessarily the current final

## Finding

A canonical plan hash and passing media QC do **not** prove that a rendered
`final.mp4` came from that plan. At an NLE handoff, bind three identities:

1. the saved plan's canonical content hash;
2. the exact in-house authority file's SHA-256;
3. the NLE delivery metadata written after that file was used.

Without all three, a stale but technically clean audio master can be relabeled
as current.

## The C0679 incident

The current plan hash was:

```text
6206df53dccca54e67df473c7fc77cf25ab7541ff0054b9fe364e084f70dba0a
```

It required `audioEnhance.preset = "voice"` and `music.enabled = false`, but
the producer `final.mp4` predated those edits. The first provenance-era Palmier
attempt remuxed that stale authority and correctly failed the tonal-hum gate:

```text
111.0 Hz; prominence 23.8 dB; level -37.9 dBFS; stable 92% / 13.5s
```

That failure was lucky. If the stale master had passed loudness, peak, timing,
balance, hum, and ending checks, the old implementation would have written the
**current plan hash** into Palmier metadata anyway. QC proves fitness; it does
not prove origin.

The isolated current-plan render passed Audit B, then received this proof:

```json
{
  "videoFingerprint": "6b18301946c7ae84",
  "graphicsFingerprint": "bb73c67e602b04f3",
  "planHash": "6206df53dccca54e67df473c7fc77cf25ab7541ff0054b9fe364e084f70dba0a",
  "authorityHash": "1b1878b6865e5a83521881a6edb11e19f861d6155ad0b0118097c2acc6c7c21d"
}
```

Palmier then rebuilt even though the plan hash had not changed, because the
authority hash had. The verified delivery measured 81.375s, -14.1 LUFS,
-1.9 dBTP, 0.000s endpoint skew, and no sustained-tone failure.

## Contract

`fingerprints.py` owns the shared identities:

```python
plan_hash = plan_content_hash(plan)  # excludes version/private/graphic ids
authority_hash = file_sha256(final_path)
```

After a successful full render or assemble, write
`final.mp4.assembled.json` atomically with both hashes. Before any operation
mutates `final.mp4`, invalidate the old sidecar. A failed render must leave no
stale proof behind.

Before Palmier touches MCP:

```python
proof = read_json("final.mp4.assembled.json")
assert proof["planHash"] == plan_content_hash(disk_plan)
assert proof["authorityHash"] == file_sha256("final.mp4")
```

After verified Palmier picture export and authoritative-audio finish, copy both
hashes into `final.palmier.meta.json`. `up_to_date` requires the plan hash,
authority hash, verified picture, verified audio, lane fingerprints, and the
schema-v2 sync checkpoint.

## Why weaker signals fail

- **`planVersion`** is a UI counter, not content identity.
- **mtime/size** detect many replacements but do not identify bytes or origin.
- **LUFS/peak/timing** can pass for an old mix.
- **The sidecar plan hash alone** becomes a lie if the MP4 changes afterward.
- **The file hash alone** proves bytes, not which plan produced them.

The sidecar must therefore contain both, and the consumer must recompute the
file hash rather than trusting the sidecar blindly.

## Important music exception

In this pipeline, `render.py` does not apply an enabled music bed; music is an
assemble-time stage. A monolithic music-enabled render must **not** stamp final
authority. It emits `final_provenance_skipped` and requires `assemble.py` to
produce and prove the post-music file.

## When not to use this exact pattern

Do not declare the in-house final authoritative when an operator intentionally
mixes audio in the NLE. In that workflow, the NLE's mastered stem/output is the
authority and needs its own plan/job identity plus file hash. Also do not stamp
provenance onto a manually repaired file merely because it sounds right;
regenerate it through the declared authority workflow or use an explicit,
audited recovery process.
