import { describe, expect, test } from "vitest";
import { Curie, LocalScheme, RefsError, Registry, Scheme, parseCurie } from "../src/index.js";
import { loadFixture } from "./fixtures.js";

interface ParseCase {
  text: string;
  canonical?: string;
  error?: string;
}

const registry = Registry.default();

function refusal(run: () => unknown): RefsError {
  try {
    run();
  } catch (e) {
    expect(e).toBeInstanceOf(RefsError);
    return e as RefsError;
  }
  throw new Error("expected a RefsError");
}

describe("parse oracle", () => {
  test.each(loadFixture<ParseCase[]>("parse.json").map((c) => [JSON.stringify(c.text), c] as const))(
    "%s",
    (_name, c) => {
      if (c.error !== undefined) {
        expect(refusal(() => parseCurie(c.text, registry)).kind).toBe(c.error);
      } else {
        expect(String(parseCurie(c.text, registry))).toBe(c.canonical);
      }
    },
  );
});

describe("Curie and Scheme", () => {
  test("text form, equality of parts, immutability", () => {
    const curie = new Curie("geo", "GSE1");
    expect(String(curie)).toBe("geo:GSE1");
    expect(curie).toEqual(new Curie("geo", "GSE1"));
    expect(() => {
      (curie as { local: string }).local = "x";
    }).toThrow(TypeError);
  });

  test("the local id is kept as given", () => {
    expect(parseCurie("figshare:0012", registry)).toEqual(new Curie("figshare", "0012"));
  });

  test("local schemes parse after withLocal", () => {
    const reg = registry.withLocal([
      new LocalScheme({
        prefix: "lit.x",
        name: "x",
        pattern: "^[0-9]+$",
        uriFormat: null,
        why: "test",
        issuedBy: "lit",
      }),
    ]);
    expect(parseCurie("LIT.X:12", reg)).toEqual(new Curie("lit.x", "12"));
    expect(refusal(() => parseCurie("lit.x:abc", reg)).kind).toBe("malformed");
  });

  test("a scheme without a pattern accepts any local id", () => {
    const scheme = registry.scheme("aaindex");
    expect(scheme.pattern).toBeNull();
    expect(scheme.matches("whatever: this is")).toBe(true);
  });

  test("a scheme match is a full match of the whole local id", () => {
    const scheme = registry.scheme("hgnc");
    expect(scheme.matches("6390")).toBe(true);
    expect(scheme.matches("6390\n")).toBe(false);
    expect(scheme.matches("١٢٣")).toBe(false);
    expect(scheme.matches("")).toBe(false);
  });

  test("a refused scheme refuses every local id", () => {
    const scheme = registry.scheme("vegbank");
    expect(scheme.refused).not.toBeNull();
    expect(scheme.pattern).toBeNull();
    expect(refusal(() => scheme.matches("anything")).kind).toBe("unsupported_pattern");
  });

  test("a scheme is frozen data", () => {
    const scheme = new Scheme({
      prefix: "p",
      name: "P",
      pattern: null,
      uriFormat: null,
      synonyms: [],
      issuedBy: null,
      refused: null,
    });
    expect(() => {
      (scheme as { name: string }).name = "x";
    }).toThrow(TypeError);
  });
});
