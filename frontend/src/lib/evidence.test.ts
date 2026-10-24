import { describe, expect, it } from "vitest";

import { scoreWidths } from "./evidence";
import type { RetrievedPassage } from "./types";

function passage(score: number): RetrievedPassage {
  return {
    id: "S1",
    path: "a.py",
    start_line: 1,
    end_line: 1,
    section: null,
    content: "",
    score,
    url: "",
    cited: false,
  };
}

describe("scoreWidths", () => {
  it("draws the similarity itself, so close scores give close bars", () => {
    expect(scoreWidths([passage(0.503), passage(0.497), passage(0.2)])).toEqual([
      0.503, 0.497, 0.2,
    ]);
  });

  it("keeps every bar between empty and full", () => {
    expect(scoreWidths([passage(-0.1), passage(1.2)])).toEqual([0, 1]);
    expect(scoreWidths([])).toEqual([]);
  });
});
