# Directory metadata is not pathname identity

Comparing a directory descriptor with its pathname by the entire `stat` tuple
looks strict, but it rejects legitimate concurrency. Creating a child changes
the directory's size, link count, modification time, and change time without
replacing the directory inode.

The generation sealer exposed this race when two identical seal requests opened
the same authority root. One request created `authority.json` or `generations/`
between the other's `fstat(fd)` and `stat(path)`. The second request rejected
with `directory pathname identity changed`, even though both observations named
the same device and inode.

The same principle later exposed a nondeterministic toolchain failure on APFS.
Executable pins retained every ancestor from `/` through the shared temporary
directory and compared each directory's link count. An unrelated test creating
or removing a sibling `TemporaryDirectory` changed that ancestor link count, so
an unchanged pinned `docker` executable was reported as tampered. The failure
appeared only under concurrent test churn, which made it easy to mislabel as a
test flake.

For the initial open-to-name check, compare the pathname's `{device, inode}` to
the already opened descriptor and separately validate owner, type, and mode.
After acquiring the relevant kernel lock, recheck safety and the current named
inode again. Preserve full snapshots for immutable files and sealed directory
closures where metadata change is itself evidence of mutation.

For executable path ancestors, the retained invariant is now
`{device, inode, mode, uid, gid}`. This still rejects pathname replacement and
permission/ownership changes, while allowing unrelated descendant creation.
The executable leaf keeps the stronger link-count, size, timestamp, inode, and
content-digest checks.

The sealer fix survived 20 repeated concurrent same-commit installations. The
toolchain fix survived ten repetitions of 29 focused tests plus 15 subtests,
including deterministic unrelated-child, directory-replacement, mode-mutation,
and exact executable-byte cases.

Do not weaken file checks this way. A regular file's size, link count, mode,
timestamps, and content digest are part of the authority proof. The relaxation
is specific to opening a mutable coordination directory before its lock is
held; descendant creation is expected there.
