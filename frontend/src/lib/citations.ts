import type { Citation } from "./types";

const MARKER = /\[(S\d+)\]/g;
// Fenced code blocks and inline code: citation markers there are code, not links.
const CODE = /(```[\s\S]*?(?:```|$)|`[^`\n]*`)/g;

/**
 * Turn each ``[S1]`` marker of a Markdown answer into a link to the cited lines on
 * GitHub. The server has already removed markers that match no citation; any other
 * marker is left as plain text.
 */
export function linkCitations(markdown: string, citations: readonly Citation[]): string {
  const urls = new Map(citations.map((citation) => [citation.id, citation.url]));
  return markdown
    .split(CODE)
    .map((part, index) =>
      // split() with a capturing group puts the code parts at odd indexes.
      index % 2 === 1
        ? part
        : part.replace(MARKER, (marker, id: string) => {
            const url = urls.get(id);
            return url ? `[${id}](${url})` : marker;
          }),
    )
    .join("");
}

/** "src/app.py:10-14", or "src/app.py:10" for a single line. */
export function lineRange(citation: Citation): string {
  const { path, start_line: start, end_line: end } = citation;
  return start === end ? `${path}:${start}` : `${path}:${start}-${end}`;
}
