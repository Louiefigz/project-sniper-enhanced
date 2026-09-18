# `black@0` is not transparent unless the source pixel format carries alpha

## The incident

The first long-form CaptionTrackV1 page compositor created its transparent
base with:

```text
color=c=black@0.0:s=1080x1920:r=30
```

FFmpeg's `color` source selected a non-alpha pixel format. Converting that
already-opaque source to RGBA later produced alpha `255`, so a caption page
placed above picture would have become a full black frame.

## Evidence

A one-pixel decode gave:

| Source graph | Decoded RGBA |
|---|---|
| `color=c=black@0.0:s=2x2:r=1` | `00 00 00 ff` |
| `color=c=black@0.0:s=2x2:r=1,format=rgba` | `00 00 00 00` |

The corrected production source is:

```text
color=c=black@0.0:s={width}x{height}:r={fps},format=rgba
```

The real-media regression composes two three-frame alpha assets into one
six-frame page. It proves:

- an untouched background pixel is exactly `00 00 00 00`;
- the red cue is opaque on frame `0`;
- the next cue becomes opaque on frame `3`;
- the page fully decodes exactly six frames.

## The principle

An alpha value in a color literal is only intent. Transparency exists only
after the source negotiates an alpha-capable pixel format. Prove the decoded
alpha channel and a known transparent pixel; do not infer either from the
filter string or output codec.

## When not to use it

Do not force RGBA on an intentionally opaque delivery base. Opaque H.264
picture should stay in its normal YUV delivery format. This rule applies to
transparent intermediates—caption pages, title cards, motion-graphic shards,
and other overlay media.
