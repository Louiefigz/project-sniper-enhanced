# Canonical archives require byte reconstruction

## What failed

Tar parsers normalize many different byte streams into similar member objects.
A verifier can check names, payload hashes, and apparent modes while still
accepting alternate type flags, PAX metadata, ownership fields, header
encodings, ordering, padding, or trailing bytes.

That is adequate for ordinary extraction. It is not adequate when the archive
digest is the render-input identity.

## The correction

Define one serializer and reconstruct the complete expected archive from the
verified member payloads. Accept only when the retained bytes equal that exact
canonical USTAR byte stream. The serializer fixes:

- sorted unique paths;
- exact regular-file type and private mode;
- fixed owner, group, timestamp, and header encoding;
- no PAX or implementation-specific extensions;
- deterministic padding and end markers; and
- no trailing bytes.

Semantic JSON members need their own decode, closed-schema validation, and
canonical re-encoding before archive reconstruction. A canonical container
cannot make a noncanonical payload authoritative.
