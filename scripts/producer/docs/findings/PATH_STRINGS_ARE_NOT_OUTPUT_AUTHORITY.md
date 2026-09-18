# Path strings are not output authority

## What failed

The first dedicated headless-render launcher normalized a worker's returned path
with `realpath`, checked that the resolved target was a regular file inside the
attempt cache, and then returned the original path. A symlink inside the cache
therefore passed when it pointed to a valid cached movie. The symlink could be
retargeted after validation.

## The deeper rule

Path containment answers where a lookup resolved once. It does not identify the
inode that was approved. Authority needs a no-follow open, regular-file and
single-link checks, owner/mode checks, and an inode/device/size/content-digest
binding. A later sealer must re-open by directory handle and compare that binding
before copying or publishing.

The launcher now rejects any noncanonical or symlinked result, opens the movie
relative to the already validated cache directory, hashes the open descriptor,
checks the directory entry still names the same inode, and returns the binding
separately from the informational path.

## When this is unnecessary

A display-only path may remain a string. Do not use the heavier binding when the
path cannot authorize reuse, approval, copying, publication, or cleanup.
