"""Studio lane — generate a HyperFrames Studio REVIEW project from a plan.

The generated directory is a VIEW for ``hyperframes preview`` (base footage on
track 0, every graphicsTrack entry as a timed sub-composition clip above it).
It is never ``hyperframes render``ed; the deliverable render path stays
``graphics_render.py`` + ``assemble.py``. Output is deterministic and
manifest-tracked so a later sync-back module can diff Studio's file edits
back into the plan.
"""
from __future__ import annotations


class StudioProjectError(RuntimeError):
    """A studio project cannot be generated or safely overwritten."""
