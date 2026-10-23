"""Server-side citation checking: the model cites opaque IDs, the server resolves them.

An ID the model was not given is removed from the answer, so an invented citation can
never reach users. Every remaining ID maps to a file, a line range and a permanent link.
"""

import logging
import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from uaw.generation.prompt import Source

logger = logging.getLogger(__name__)

# "[S1]", and grouped forms such as "[S1, S3]" or "[S1; S3]". The spaces before the
# marker are captured, so that removing a marker does not leave "text ." behind.
_MARKER = re.compile(r"([ \t]*)\[\s*(S\d+(?:\s*[,;]\s*S\d+)*)\s*\]")
_ID = re.compile(r"S\d+")


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    path: str
    start_line: int
    end_line: int
    url: str


class ResolvedAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Answer text with only valid "[Sn]" markers left.
    text: str
    # Cited sources, in order of first citation.
    citations: list[Citation]
    # IDs the model cited although they were not provided.
    unknown_ids: list[str]


def resolve_citations(text: str, sources: Sequence[Source]) -> ResolvedAnswer:
    by_id = {source.id: source for source in sources}
    cited: dict[str, Citation] = {}
    unknown: list[str] = []

    def replace(match: re.Match[str]) -> str:
        valid: list[str] = []
        for source_id in _ID.findall(match.group(2)):
            source = by_id.get(source_id)
            if source is None:
                if source_id not in unknown:
                    unknown.append(source_id)
                continue
            if source_id not in valid:
                valid.append(source_id)
            if source_id not in cited:
                hit = source.hit
                cited[source_id] = Citation(
                    id=source_id,
                    path=hit.path,
                    start_line=hit.start_line,
                    end_line=hit.end_line,
                    url=hit.url,
                )
        if not valid:
            return ""
        # Normalized to one marker per source, the form clients render.
        return match.group(1) + "".join(f"[{source_id}]" for source_id in valid)

    cleaned = _MARKER.sub(replace, text)
    if unknown:
        logger.warning("Removed citations to unknown sources: %s", ", ".join(unknown))
    return ResolvedAnswer(text=cleaned, citations=list(cited.values()), unknown_ids=unknown)
