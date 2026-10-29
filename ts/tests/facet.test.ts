import { FacetError, type Node, makeNode } from "@verifiably/nodes";
import { describe, expect, test } from "vitest";
import {
  FACET,
  LocalScheme,
  type RefsError,
  Registry,
  aboutFacet,
  buildAbout,
  parseVocabularies,
} from "../src/index.js";
import { loadFixture } from "./fixtures.js";

interface Doc {
  local_schemes: {
    prefix: string;
    name: string;
    pattern: string | null;
    uri_format: string | null;
    why: string;
    issued_by: string | null;
  }[];
  vocabularies: Record<string, unknown>;
  cases: { name: string; payload: unknown; verdict: string }[];
}

const DOC = loadFixture<Doc>("facet.json");
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
const INVARIANT = aboutFacet(REG, parseVocabularies(DOC.vocabularies, REG));

function node(facets: Record<string, Record<string, unknown>>): Node {
  return makeNode({ id: "topic:t", kind: "topic", title: "t", facets });
}

function facetError(run: () => void): FacetError {
  try {
    run();
  } catch (e) {
    expect(e).toBeInstanceOf(FacetError);
    return e as FacetError;
  }
  throw new Error("expected a FacetError");
}

describe("facet oracle", () => {
  test.each(DOC.cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const n = node({ [FACET]: c.payload as Record<string, unknown> });
    if (c.verdict === "ok") {
      INVARIANT(n);
    } else {
      const message = facetError(() => INVARIANT(n)).message;
      expect(message).toContain("topic:t");
      expect(message).toContain(FACET);
    }
  });
});

describe("aboutFacet", () => {
  test("the facet name", () => {
    expect(FACET).toBe("refs/about");
  });

  test("a node without the facet is not checked", () => {
    INVARIANT(node({}));
    INVARIANT(node({ other: { anything: 1 } }));
  });

  test("the error names the first violation", () => {
    const payload = { entries: [{ id: "mesh:D009101", release: "x" }, { id: "KIF14" }] };
    const message = facetError(() => INVARIANT(node({ [FACET]: payload }))).message;
    expect(message).toContain("mesh:D009101");
    expect(message).not.toContain("KIF14");
  });
});

describe("buildAbout", () => {
  test("canonicalises, drops duplicates and orders", () => {
    const payload = buildAbout(
      [
        ["PMID:2", null],
        ["pubmed:1", null],
        ["pmid:2", null],
      ],
      REG,
    );
    expect(payload).toEqual({ entries: [{ id: "pubmed:1" }, { id: "pubmed:2" }] });
  });

  test("orders by code point, not by UTF-16 unit", () => {
    // U+FF21 is one UTF-16 unit (0xFF21); U+1D7D9 is a pair starting 0xD835. A UTF-16
    // sort puts the astral release first; by code point U+FF21 comes first.
    const payload = buildAbout(
      [
        ["chebi:15377", "\u{1d7d9}"],
        ["chebi:15377", "\u{ff21}"],
        ["HGNC.SYMBOL:KIF14", "2026-07-01"],
      ],
      REG,
    );
    expect(payload).toEqual({
      entries: [
        { id: "chebi:15377", release: "\u{ff21}" },
        { id: "chebi:15377", release: "\u{1d7d9}" },
        { id: "hgnc.symbol:KIF14", release: "2026-07-01" },
      ],
    });
    INVARIANT(node({ [FACET]: payload }));
  });

  test("an absent release sorts before a present one", () => {
    const payload = buildAbout(
      [
        ["mesh:D009101", "x"],
        ["mesh:D009101", null],
      ],
      REG,
    );
    expect(payload.entries.map((e) => e.release)).toEqual([undefined, "x"]);
  });

  test("refuses an unparseable id", () => {
    try {
      buildAbout([["KIF14", null]], REG);
    } catch (e) {
      expect((e as RefsError).kind).toBe("ambiguous_id");
      return;
    }
    throw new Error("expected ambiguous_id");
  });

  test("does not check releases", () => {
    expect(buildAbout([["mesh:D009101", "anything"]], REG)).toEqual({
      entries: [{ id: "mesh:D009101", release: "anything" }],
    });
  });
});
