from __future__ import annotations


class RenderTransportLost(RuntimeError):
    """The renderer exited without a terminal job frame."""


class RenderTimedOut(RuntimeError):
    """The parent deliberately ended a job after its deadline."""


class RenderOversize(RuntimeError):
    """A document or image exceeds the transport budget."""


class RenderUnavailable(RuntimeError):
    """The optional process renderer is not available."""
