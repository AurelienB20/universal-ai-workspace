"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { useLanguage } from "@/i18n/language";
import { lineRange, linkCitations } from "@/lib/citations";
import type { Answer, Citation } from "@/lib/types";

const CITATION_ID = /^S\d+$/;

export function AnswerView({ answer }: { answer: Answer }) {
  const { t } = useLanguage();
  const byId = new Map(answer.citations.map((citation) => [citation.id, citation]));

  // The answer derives from untrusted repository content: raw HTML is not rendered
  // (react-markdown escapes it) and links open in a new tab without a referrer.
  const components: Components = {
    a({ href, children }) {
      const label = typeof children === "string" ? children : null;
      const citation = label !== null && CITATION_ID.test(label) ? byId.get(label) : undefined;
      if (citation && citation.url === href) {
        return <CitationChip citation={citation} />;
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="link">
          {children}
        </a>
      );
    },
  };

  return (
    <div className="flex flex-col gap-3">
      {answer.insufficient_context && <p className="notice">{t.insufficientContext}</p>}

      <div className="markdown">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {linkCitations(answer.answer, answer.citations)}
        </ReactMarkdown>
      </div>

      {answer.citations.length > 0 && (
        <div>
          <h4 className="mb-1 text-xs font-semibold tracking-wide text-zinc-500 uppercase">
            {t.sources}
          </h4>
          <ul className="flex flex-col gap-1 text-sm">
            {answer.citations.map((citation) => (
              <li key={citation.id} className="flex items-baseline gap-2">
                <CitationChip citation={citation} />
                <a
                  href={citation.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="link font-mono text-xs break-all"
                >
                  {lineRange(citation)}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {answer.model && (
        <p className="text-xs text-zinc-500">
          {t.answeredBy(answer.model, answer.commit_sha.slice(0, 7))}
        </p>
      )}
    </div>
  );
}

function CitationChip({ citation }: { citation: Citation }) {
  return (
    <a
      href={citation.url}
      target="_blank"
      rel="noopener noreferrer"
      title={lineRange(citation)}
      className="citation"
    >
      {citation.id}
    </a>
  );
}
