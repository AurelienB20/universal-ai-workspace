"""Full-text search over chunks, tuned for code (PostgreSQL ``tsvector``).

Design choices, checked against PostgreSQL's parser:

- The ``simple`` configuration: no stemming and no stop words, so code words such as
  ``after``, ``this`` or ``self`` are kept (the ``english`` one drops them).
- PostgreSQL splits ``after_this_request`` into ``after``, ``this`` and ``request``. Joined
  forms are indexed too (``afterthisrequest``), so that an exact name matches exactly.
- The file path (weight A) and the Markdown section (weight B) count more than the
  content (weight C).
- Questions are natural language: their words are combined with OR, not AND (a question
  about ``PROPAGATE_EXCEPTIONS`` "change" must not require the word "change").
"""

import re
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Identifiers with an underscore, e.g. after_this_request or PROPAGATE_EXCEPTIONS. No
# "(?:...)" group: SQLAlchemy would read ":_" in the SQL text as a bind parameter. The
# first group of the match (m[1] below) is the whole identifier.
_SNAKE_IDENTIFIER = r"[A-Za-z0-9]+(_[A-Za-z0-9]+)+"

# The tsvector of one chunk ``c`` of document ``d``. Migration 0006 repeats this
# expression to fill existing rows: change both together.
CHUNK_SEARCH_VECTOR_SQL = f"""
    setweight(to_tsvector('simple', regexp_replace(d.path, '[/._-]+', ' ', 'g')), 'A')
    || setweight(to_tsvector('simple', coalesce(c.section, '')), 'B')
    || setweight(to_tsvector('simple', c.content), 'C')
    || setweight(to_tsvector('simple', array_to_string(ARRAY(
        SELECT replace(m[1], '_', '')
        FROM regexp_matches(c.content, '({_SNAKE_IDENTIFIER})', 'g') AS m
    ), ' ')), 'C')
"""

# Words that say nothing about the code: question words and the most common English and
# French words. Code words (self, return, class...) are deliberately not listed.
_STOP_WORDS = frozenset(
    # A word list reads better as one string than as a hundred lines.
    """
    a about an and are as at be by can could do does doing done for from has have how i if
    in into is it its me my of on or should so than that the their them then there these
    they this those to use used using was we were what when where which who whom why will
    with would you your
    au aux avec ce ces comment dans de des du elle en est et il je la le les leur mais ne
    on ou où par pas pour qu que quel quelle quels qui sa se son sont sur un une vous
    """.split()  # noqa: SIM905
)
_WORD = re.compile(r"[A-Za-z0-9_]+")


def text_query_terms(question: str) -> list[str]:
    """The search terms of a question: lowercase words, joined forms of snake_case names,
    no stop words. Only letters and digits, so nothing can inject tsquery syntax."""
    terms: list[str] = []
    for word in _WORD.findall(question):
        lowered = word.lower()
        parts = [part for part in lowered.split("_") if part]
        if len(parts) > 1:
            terms.append("".join(parts))
        terms.extend(part for part in parts if part not in _STOP_WORDS and len(part) > 1)
    return list(dict.fromkeys(terms))


# A code name in a question: snake_case (after_this_request), camelCase or PascalCase
# with an inner capital (ScriptInfo, URLSafeTimedSerializer), or an upper-case setting
# of 5+ letters (DEBUG, TESTING). Short acronyms (HTTP, JSON) are ordinary words here.
_NAME = re.compile(
    r"^(?:"
    r"[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+"  # snake_case, UPPER_SNAKE
    r"|[a-z][a-z0-9]*[A-Z][A-Za-z0-9]*"  # camelCase
    r"|[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*"  # PascalCase
    r"|[A-Z]{2,}[a-z][A-Za-z0-9]*"  # acronym then words: URLSafeTimedSerializer
    r"|[A-Z][A-Z0-9]{4,}"  # DEBUG, TESTING
    r")$"
)


def name_terms(question: str) -> list[str]:
    """The code names of a question, as indexed: lowercase, underscores removed.

    Measured on the evaluation: matching every word of a question adds noise (common words
    such as "request" or "error" match file names and long passages, and ts_rank has no
    notion of word rarity), while an exact name is a precise signal."""
    terms = [word.replace("_", "").lower() for word in _WORD.findall(question) if _NAME.match(word)]
    return list(dict.fromkeys(terms))


def text_query(question: str, *, names_only: bool = False) -> str | None:
    """A ``to_tsquery('simple', ...)`` expression matching any term, or None if none."""
    terms = name_terms(question) if names_only else text_query_terms(question)
    return " | ".join(terms) if terms else None


async def index_snapshot_text(session: AsyncSession, snapshot_id: uuid.UUID) -> None:
    """Compute the full-text vector of every chunk of a snapshot."""
    await session.execute(
        text(
            f"UPDATE chunks AS c SET search_vector = {CHUNK_SEARCH_VECTOR_SQL} "
            "FROM documents AS d "
            "WHERE d.id = c.document_id AND c.snapshot_id = :snapshot_id"
        ),
        {"snapshot_id": snapshot_id},
    )


async def text_matches(
    session: AsyncSession,
    snapshot_id: uuid.UUID,
    question: str,
    *,
    limit: int,
    names_only: bool = False,
) -> list[uuid.UUID]:
    """Ids of the chunks of the snapshot that best match the question's words (or only its
    code names), best first."""
    query = text_query(question, names_only=names_only)
    if query is None:
        return []
    # Normalization 1: the rank is divided by 1 + log(length), so that a long chunk does
    # not win only by repeating words.
    stmt = text(
        """
        SELECT c.id
        FROM chunks AS c, to_tsquery('simple', :query) AS q
        WHERE c.snapshot_id = :snapshot_id AND c.search_vector @@ q
        ORDER BY ts_rank(c.search_vector, q, 1) DESC, c.id
        LIMIT :limit
        """
    )
    result = await session.execute(
        stmt, {"query": query, "snapshot_id": snapshot_id, "limit": limit}
    )
    return list(result.scalars().all())
