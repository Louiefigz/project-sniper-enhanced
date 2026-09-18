"""FRAME.IO REVIEW — scan an MP4 for on-screen text errors with timestamps.

Modular pipeline (one concern per file), per the tool spec:
  - extract.py       ffmpeg → 1 JPG per second, named by timestamp
  - dedup.py         imagehash perceptual-hash dedup (static slide = 1 analysis)
  - claude_client.py Anthropic vision call, forced-JSON structured errors
  - review.py        orchestrator — CLI (results.json + report.html) AND the
                     --server NDJSON mode the Next.js FRAME.IO REVIEW tab consumes

The web UI is the Next.js tab (src/app/(tools)/frameio-review), not Flask —
the tab streams review.py --server and renders results next to a video player.
"""
