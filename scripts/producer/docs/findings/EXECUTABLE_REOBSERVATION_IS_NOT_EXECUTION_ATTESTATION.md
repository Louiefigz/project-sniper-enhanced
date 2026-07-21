# Executable Reobservation Is Not Execution Attestation

Hashing `ffmpeg` or `ffprobe` by pathname once is not enough for a trusted video
pipeline. The pathname can be rebound after admission, a symlink can redirect a
component, or a same-byte replacement can preserve the digest while changing the
inode that later code reaches.

The headless runtime seam therefore opens every path component without following
symlinks, retains the directory and executable descriptors, and checks all of the
following before and after one synchronous callback:

- the complete executable bytes still match the exact runtime-manifest SHA-256;
- the held file descriptor still has the admitted device, inode, mode, owner,
  link count, size, mtime, and ctime;
- the leaf entry and the absolute pathname still resolve to that same inode; and
- each held directory entry still resolves to the pinned directory inode.

This catches ordinary path swaps, identical-byte inode replacement, symlink
replacement, in-place mutation, mode changes, and parent-directory replacement.
It also keeps hard-link aliases out of the admitted set by requiring one link.

## What this does not prove

Before/after equality is an endpoint observation. It does not prove that bytes
were never changed and restored between those endpoints. More importantly, it
does not prove that a child process executed the held descriptor, which loader or
dynamic libraries the process used, or that the process produced any particular
media or quality measurement.

For that reason, the report status is
`EXECUTABLE_BYTES_AND_INODES_REOBSERVED_NOT_EXECUTION_ATTESTED`. Its runtime,
execution, dynamic-library, measurement, and publication authority flags remain
false. Do not promote those flags merely because expected and observed hashes are
equal. Process execution attestation and dynamic runtime closure require separate
evidence.

## When not to use this as a gate

Do not accept a serialized report from an untrusted producer as proof that the
callback ran. Canonical bytes make the record closed and tamper-evident relative
to an external seal, but they are not a signature. The trusted controller must
invoke the seam directly, retain its returned result in the same authority
boundary, and still satisfy the remaining runtime and quality gates.
