"""Turn source documents into line-addressed chunks, picking a strategy per language."""

from uaw.chunking.boundaries import code_scores, paragraph_scores
from uaw.chunking.lines import ChunkingConfig, split_lines, window_ranges
from uaw.chunking.markdown import Span, markdown_spans
from uaw.domain.chunks import Chunk
from uaw.domain.documents import SourceDocument

CODE_LANGUAGES = frozenset(
    {
        "python",
        "javascript",
        "typescript",
        "java",
        "kotlin",
        "scala",
        "go",
        "rust",
        "ruby",
        "php",
        "csharp",
        "c",
        "cpp",
        "swift",
        "shell",
        "powershell",
        "vue",
        "svelte",
    }
)


def chunk_document(document: SourceDocument, config: ChunkingConfig) -> list[Chunk]:
    lines = split_lines(document.content)
    if document.language == "markdown":
        spans = markdown_spans(lines, config)
    else:
        scores = (
            code_scores(lines) if document.language in CODE_LANGUAGES else paragraph_scores(lines)
        )
        spans = [Span(start, end, None) for start, end in window_ranges(lines, scores, config)]

    return [
        Chunk(
            path=document.path,
            language=document.language,
            start_line=span.start + 1,
            end_line=span.end,
            content="".join(lines[span.start : span.end]),
            section=span.section,
        )
        for span in spans
    ]
