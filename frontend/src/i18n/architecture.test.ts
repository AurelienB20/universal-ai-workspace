import { describe, expect, it } from "vitest";

import { STEP_CODE, STEP_IDS, architecture } from "./architecture";
import { LANGUAGES } from "./messages";

/** Every key path, with array lengths, so that both languages have the same shape. */
function shape(value: unknown, prefix = ""): string[] {
  if (Array.isArray(value)) {
    return [`${prefix}[${value.length}]`, ...value.flatMap((item, i) => shape(item, `${prefix}${i}.`))];
  }
  if (typeof value === "object" && value !== null) {
    return Object.entries(value).flatMap(([key, item]) => shape(item, `${prefix}${key}.`));
  }
  return [prefix];
}

describe("architecture content", () => {
  it("has the same structure in every language", () => {
    const reference = shape(architecture.fr).sort();
    for (const language of LANGUAGES) {
      expect(shape(architecture[language]).sort()).toEqual(reference);
    }
  });

  it("describes every pipeline step, with code to read", () => {
    for (const language of LANGUAGES) {
      expect(Object.keys(architecture[language].pipeline.steps).sort()).toEqual(
        [...STEP_IDS].sort(),
      );
    }
    for (const id of STEP_IDS) {
      expect(STEP_CODE[id].length).toBeGreaterThan(0);
    }
  });
});
