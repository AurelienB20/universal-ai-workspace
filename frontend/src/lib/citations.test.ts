import { describe, expect, it } from "vitest";

import { lineRange, linkCitations } from "./citations";
import type { Citation } from "./types";

const S1: Citation = {
  id: "S1",
  path: "src/signer.py",
  start_line: 10,
  end_line: 14,
  url: "https://github.com/o/r/blob/abc/src/signer.py#L10-L14",
};
const S2: Citation = { ...S1, id: "S2", start_line: 3, end_line: 3, url: "https://x/S2" };

describe("linkCitations", () => {
  it("turns markers into links to the cited lines", () => {
    expect(linkCitations("Signed [S1][S2].", [S1, S2])).toBe(
      `Signed [S1](${S1.url})[S2](https://x/S2).`,
    );
  });

  it("leaves markers without a citation as text", () => {
    expect(linkCitations("See [S9].", [S1])).toBe("See [S9].");
  });

  it("does not touch code", () => {
    const markdown = "Use `a[S1]` and [S1]:\n```python\nx = y[S1]\n```\n";

    expect(linkCitations(markdown, [S1])).toBe(
      `Use \`a[S1]\` and [S1](${S1.url}):\n\`\`\`python\nx = y[S1]\n\`\`\`\n`,
    );
  });

  it("treats an unclosed code fence as code until the end", () => {
    expect(linkCitations("[S1]\n```\n[S1]", [S1])).toBe(`[S1](${S1.url})\n\`\`\`\n[S1]`);
  });
});

describe("lineRange", () => {
  it("formats a range or a single line", () => {
    expect(lineRange(S1)).toBe("src/signer.py:10-14");
    expect(lineRange(S2)).toBe("src/signer.py:3");
  });
});
