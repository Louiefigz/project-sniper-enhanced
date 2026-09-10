# A file-type check cannot protect an earlier blocking open

## The defect

Producer's external-media result reader and retained ingest-receipt reader both
checked that an opened file was regular, single-linked and bounded. Those are
necessary checks, but their earlier `os.open(path, O_RDONLY | O_NOFOLLOW)` could
already block indefinitely on a FIFO with no writer. The type check, reader
timeout and owned-container cleanup were never reached.

This matters for files on a decoder-writable result mount, and also for local
receipts that can be replaced accidentally or maliciously. A trustworthy name,
`.json` extension, or digest in another document does not establish file type.

## The narrow correction

Open with `O_RDONLY | O_NOFOLLOW | O_NONBLOCK`, then check the descriptor type
and bounds before reading any bytes. Keep the existing single-link, owner where
applicable, size, stable-inode and exact-payload checks. Close descriptors in a
`finally` block, including rejected types.

```python
descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
try:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError("receipt is not a regular file")
    # Existing link/size/identity checks and bounded reads follow.
finally:
    os.close(descriptor)
```

`O_NONBLOCK` is not a substitute for these checks. It prevents a FIFO's open
from waiting for a writer; it does not authenticate a receipt, make ordinary
disk I/O instantaneous, or prove container cleanup succeeded.

## Regression evidence

The new six-test safety suite used actual FIFO paths, a private Unix socket,
real owned `/dev/null` descriptors, and ordinary JSON bytes. Before the fix,
three FIFO cases hit their two-second outer test timeouts, including the path
through the actual probe wait loop. One socket fixture initially failed because
the sandbox prohibited socket creation; this was recorded, not skipped.

After the two-reader correction, the complete 36-test reader/ingest/VFR cohort
passed in 0.70 seconds wall time (0.596 seconds suite), using approved escalation
only for the private Unix socket fixture. The cleanup regression uses actual
FIFO/read/wait behavior and mocked external container operations: it proves
the cleanup call is reached, not that a real Docker daemon removed a container.

Command from `PROJECT_SNIPER`:

```
/usr/bin/time -p env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/producer:scripts/producer/tests .venv/bin/python -m unittest test_media_receipt_read_safety test_external_media_probe_host_result test_external_media_probe test_external_media_probe_vfr test_ingest_admission -q
```

Do not claim this security regression is a video-quality, listening, or
long-form throughput benchmark. It prevents one concrete indefinite wait while
preserving the existing receipt and media authority contracts.
