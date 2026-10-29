import { describe, expect, test } from "vitest";
import { RefsError, checkPattern, compilePattern } from "../src/index.js";
import { label, loadFixture } from "./fixtures.js";

interface SyntaxCase {
  pattern: string;
  verdict: string;
  position?: number;
}
interface MatchCase {
  pattern: string;
  input: string;
  match: boolean;
}

const SYNTAX = loadFixture<SyntaxCase[]>("dialect.syntax.json");
const MATCH = loadFixture<MatchCase[]>("dialect.match.json");

describe("dialect syntax oracle", () => {
  test.each(SYNTAX.map((c) => [label(c.pattern), c] as const))("%s", (_name, c) => {
    if (c.verdict === "ok") {
      expect(() => checkPattern(c.pattern)).not.toThrow();
      expect(compilePattern(c.pattern)).toBeInstanceOf(RegExp);
      return;
    }
    let error: unknown;
    try {
      checkPattern(c.pattern);
    } catch (e) {
      error = e;
    }
    expect(error).toBeInstanceOf(RefsError);
    const refs = error as RefsError;
    expect([refs.kind, refs.position]).toEqual(["unsupported_pattern", c.position]);
    expect(() => compilePattern(c.pattern)).toThrow(RefsError);
  });
});

describe("dialect match oracle", () => {
  test.each(MATCH.map((c) => [`${label(c.pattern)} ~ ${JSON.stringify(c.input)}`, c] as const))("%s", (_name, c) => {
    expect(compilePattern(c.pattern).test(c.input)).toBe(c.match);
  });
});

describe("dialect errors", () => {
  test("shape of an unsupported_pattern error", () => {
    let error: unknown;
    try {
      checkPattern("a{");
    } catch (e) {
      error = e;
    }
    const refs = error as RefsError;
    expect(refs).toBeInstanceOf(Error);
    expect(refs.kind).toBe("unsupported_pattern");
    expect(refs.position).toBe(1);
    expect(refs.detail).not.toBe("");
    expect(refs.message).toContain("unsupported_pattern");
  });

  test("positions are code-point indices, not UTF-16 units", () => {
    // U+1D7D9 is two UTF-16 units and one code point: the bad "{" sits at code point 2.
    let error: unknown;
    try {
      checkPattern("\u{1d7d9}a{");
    } catch (e) {
      error = e;
    }
    expect((error as RefsError).position).toBe(2);
  });

  test("a reversed range compares by code point, not UTF-16 unit", () => {
    // U+FF21 (one unit, 0xFF21) precedes U+1D7D9 (units 0xD835 0xDFD9) by code point.
    expect(() => checkPattern("[\u{ff21}-\u{1d7d9}]")).not.toThrow();
    expect(() => checkPattern("[\u{1d7d9}-\u{ff21}]")).toThrow(RefsError);
  });

  test("a pattern is anchored whole: compilePattern is a full match", () => {
    const re = compilePattern("a|b");
    expect(re.test("a")).toBe(true);
    expect(re.test("ab")).toBe(false);
  });
});
