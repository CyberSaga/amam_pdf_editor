from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class CompletionEvidence:
    """Observed output for one immutable document revision and paint cycle."""

    session: str
    revision: int
    page: int
    scale: float
    visible: frozenset[int]
    high: frozenset[int]
    painted: frozenset[int]
    thumbnails: frozenset[int]
    indexed: frozenset[int]
    idle: bool
    metadata_ready: bool


@dataclass(frozen=True)
class CompletionContract:
    """Freeze equivalent work before timing; queue emptiness is insufficient."""

    session: str
    revision: int
    page: int
    scale: float
    page_count: int
    required_indexed: frozenset[int] | None = None

    def visible_complete(self, evidence: CompletionEvidence) -> bool:
        pages = frozenset(range(self.page_count))
        return bool(
            evidence.session == self.session
            and evidence.revision == self.revision
            and evidence.page == self.page
            and math.isfinite(evidence.scale)
            and abs(evidence.scale - self.scale) < 1e-6
            and self.page in evidence.visible
            and evidence.visible <= pages
            and evidence.visible <= evidence.high
            and evidence.visible <= evidence.painted
        )

    def background_complete(self, evidence: CompletionEvidence) -> bool:
        pages = frozenset(range(self.page_count))
        return bool(
            self.visible_complete(evidence)
            and evidence.idle
            and evidence.thumbnails == pages
            and evidence.metadata_ready
            and (pages if self.required_indexed is None else self.required_indexed) <= evidence.indexed
        )
