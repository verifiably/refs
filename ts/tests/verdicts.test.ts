import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";
import { Registry, compilePattern } from "../src/index.js";
import { loadFixture } from "./fixtures.js";

/** prefix -> [input, matched][] recorded from the stored registry patterns. */
const VERDICTS = loadFixture<Record<string, [string, boolean][]>>("registry.verdicts.json");
const registry = Registry.default();
const UPSTREAM = (
  JSON.parse(readFileSync(new URL("../../registry/bioregistry.json", import.meta.url), "utf-8")) as {
    prefixes: Record<string, { pattern: string | null }>;
  }
).prefixes;

describe("registry pattern verdicts", () => {
  test("the fixture covers exactly the prefixes with a pattern", () => {
    const withPattern = Object.keys(UPSTREAM).filter((p) => UPSTREAM[p].pattern !== null);
    expect(Object.keys(VERDICTS).sort()).toEqual(withPattern.sort());
  });

  test.each(Object.entries(VERDICTS))("%s", (prefix, cases) => {
    const pattern = registry.scheme(prefix).pattern;
    expect(pattern).toBe(UPSTREAM[prefix].pattern);
    const re = compilePattern(pattern as string);
    const wrong = cases.filter(([input, matched]) => re.test(input) !== matched).map(([input]) => input);
    expect(wrong).toEqual([]);
  });
});
