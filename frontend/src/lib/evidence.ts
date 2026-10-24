import type { RetrievedPassage } from "./types";

/**
 * Width of each passage's score bar, from 0 to 1: the cosine similarity itself, on a
 * fixed scale. Scaling to the best passage would draw near-identical full bars when
 * scores are close (0.49 to 0.50 is common), and suggest a perfect match that is not.
 */
export function scoreWidths(passages: RetrievedPassage[]): number[] {
  return passages.map((passage) => Math.min(1, Math.max(0, passage.score)));
}
