import { describe, expect, test } from "vitest";
import { LocalScheme, RefsError, Registry, type Vocabulary, parseVocabularies, releases } from "../src/index.js";
import { loadFixture } from "./fixtures.js";

interface LocalSpec {
  prefix: string;
  name: string;
  pattern: string | null;
  uri_format: string | null;
  why: string;
  issued_by: string | null;
}
interface Doc {
  local_schemes: LocalSpec[];
  accepted: {
    name: string;
    table: Record<string, unknown>;
    expected: Record<string, { issuer: string; release: string; accepted: string[] }>;
  }[];
  refused: { name: string; table: Record<string, unknown> }[];
}

const DOC = loadFixture<Doc>("vocabularies.json");
const REG = Registry.default().withLocal(
  DOC.local_schemes.map(
    (s) =>
      new LocalScheme({
        prefix: s.prefix,
        name: s.name,
        pattern: s.pattern,
        uriFormat: s.uri_format,
        why: s.why,
        issuedBy: s.issued_by,
      }),
  ),
);

describe("vocabularies oracle", () => {
  test.each(DOC.accepted.map((c) => [c.name, c] as const))("accepted: %s", (_name, c) => {
    const parsed = parseVocabularies(c.table, REG);
    const expected = new Map(
      Object.entries(c.expected).map(([prefix, v]) => [prefix, { prefix, ...v }] as [string, Vocabulary]),
    );
    expect(parsed).toEqual(expected);
    expect([...parsed.keys()]).toEqual(Object.keys(c.expected));
  });

  test.each(DOC.refused.map((c) => [c.name, c] as const))("refused: %s", (_name, c) => {
    try {
      parseVocabularies(c.table, REG);
    } catch (e) {
      expect(e).toBeInstanceOf(RefsError);
      expect((e as RefsError).kind).toBe("invalid_vocabulary");
      return;
    }
    throw new Error("expected invalid_vocabulary");
  });
});

describe("Vocabulary", () => {
  test("is frozen", () => {
    const parsed = parseVocabularies({ chebi: { issuer: "external", release: "r" } }, REG).get("chebi") as Vocabulary;
    expect(() => {
      (parsed as { release: string }).release = "x";
    }).toThrow(TypeError);
    expect(() => (parsed.accepted as string[]).push("x")).toThrow(TypeError);
  });

  test("releases are the current and the accepted", () => {
    const v: Vocabulary = { prefix: "a", issuer: "external", release: "c", accepted: ["b", "a"] };
    expect(releases(v)).toEqual(new Set(["a", "b", "c"]));
  });
});
