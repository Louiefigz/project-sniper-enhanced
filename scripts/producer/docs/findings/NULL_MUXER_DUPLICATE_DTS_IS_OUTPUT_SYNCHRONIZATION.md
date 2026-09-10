# A null-muxer duplicate DTS is output synchronization, not necessarily decoder corruption

## Assertion

A full-decode probe must distinguish a decoder failure from a timestamp
collision created while decoded frames are written to FFmpeg's null muxer.
For the null output only, use `-vsync vfr` as an output synchronization
policy compatible with the pinned FFmpeg 4.4.2 runtime. Keep decoding strict.

## The incident (2026-07-31)

The external-media admission probe decoded the real `IMG_7134.MOV`, mapped
its video and audio, and sent the decoded streams to the null muxer. After
about 16.5 minutes of wall time, the probe rejected the source because FFmpeg
wrote a duplicate video DTS at frame/DTS `9019`.

That observation did not prove a corrupt HEVC frame. The decoder had produced
the frame; the complaint arose when the null output tried to assign a
monotonic output timestamp. Treating the message as decoder corruption would
reject decodable variable-timestamp media for the wrong reason.

## Evidence

- A bounded reproduction over source time `295–315s` reached the same
  frame/DTS `9019` collision.
- The original full-source attempt spent about 16.5 minutes before the same
  null-muxer message caused the stderr fail-closed gate to reject it.
- The exact pinned image runs FFmpeg 4.4.2. It rejects the newer
  `-fps_mode:v` spelling before decode, so a host-only success with that
  option was not valid production evidence.
- Applying the FFmpeg 4.4.2-compatible `-vsync vfr` on the output side,
  immediately before `-f null -`, completed the pinned-image reproduction
  over source time `295–315s` with status zero and empty stderr.
- A generated duplicate-timestamp regression exits zero but emits
  `non monotonically increasing dts` without the output policy. With
  `-vsync vfr`, it exits zero with empty stderr.
- A separately truncated MPEG-2 control still exits nonzero with a decoder
  error when the same output policy is present.

The governed full-decode shape is:

```text
ffmpeg -nostdin -v error -xerror -threads 1 -i INPUT \
  -map 0:v? -map 0:a? -vsync vfr -f null -
```

`-vsync vfr` is intentionally placed after input selection and stream
mapping, and before the null muxer. It is not an input error-recovery option.
The contract also forbids `fps_mode` so a newer host FFmpeg cannot silently
reintroduce an option that the governed runtime cannot execute.

## The correction

The external-media probe now:

1. maps every video and audio stream with `-map 0:v? -map 0:a?`;
2. retains `-xerror`, so real decode errors remain fatal;
3. applies `-vsync vfr` only as the null output's video synchronization mode;
4. rejects a nonzero child status; and
5. also rejects status zero when trimmed stderr is nonempty.

It does not add `-err_detect ignore_err`, `-fflags +discardcorrupt`, or any
other decoder-forgiveness flag. The existing resource, isolation, and
full-source bounds remain in force.

## The principle

Decode validity and output synchronization are different contracts. A probe
should make the sink capable of accepting legitimate source timing while
keeping the decoder and evidence gates fail-closed. Fix the layer that emits
the error; do not weaken upstream validation.

## When not to use this

- Do not use `-vsync vfr` to excuse corrupt packets, truncated media,
  decoder errors, or any nonzero FFmpeg exit.
- Do not add it globally to qualification, CFR normalization, render, or
  delivery commands. Those outputs have their own frame-clock contracts.
- Do not suppress or ignore stderr. Empty stderr plus status zero remains part
  of this admission proof.
- Do not map only the first video or audio stream. The admission claim is a
  complete decode of all declared A/V streams.
- Do not treat a successful null-muxer decode as proof of editorial quality,
  A/V synchronization, color correctness, or deliverable conformance. Those
  require separate checks.
