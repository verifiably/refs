import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";
import { LocalScheme, RefsError, Registry } from "../src/index.js";
import { localSchemesFromTable } from "../src/registry.js";
import { loadFixture } from "./fixtures.js";

interface Oracle {
  version: string;
  fingerprint: string;
  lookups: [string, string | null][];
  collisions: { schemes: { prefix: string; issued_by?: string }[]; expected: [string, string][] }[];
}

const ORACLE = loadFixture<Oracle>("registry.json");
const DEFAULT = Registry.default();

function local(
  prefix: string,
  issuedBy: string | null = "lit",
  pattern: string | null = null,
  name = "x",
  why = "test",
) {
  return new LocalScheme({ prefix, name, pattern, uriFormat: null, why, issuedBy });
}

function fromSpec(spec: { prefix: string; issued_by?: string }): LocalScheme {
  return new LocalScheme({
    prefix: spec.prefix,
    name: "x",
    pattern: null,
    uriFormat: null,
    why: "test",
    issuedBy: spec.issued_by ?? null,
  });
}

describe("registry oracle", () => {
  test("version is the upstream snapshot version", () => {
    expect(DEFAULT.version).toBe(ORACLE.version);
  });

  test("lookups", () => {
    for (const [text, canonical] of ORACLE.lookups) {
      expect(DEFAULT.canonical(text), text).toBe(canonical);
    }
  });

  test("the fingerprint equals the value pinned in the fixture", () => {
    expect(DEFAULT.fingerprint).toBe(ORACLE.fingerprint);
  });

  test.each(ORACLE.collisions.map((c) => [c.schemes.map((s) => s.prefix).join(",") || "none", c] as const))(
    "collisions: %s",
    (_name, c) => {
      const schemes = c.schemes.map(fromSpec);
      const found = DEFAULT.collisions(schemes);
      expect(found.map((x) => [x.prefix, x.kind])).toEqual(c.expected);
      for (const x of found) expect(x.detail).not.toBe("");
      if (found.length > 0) {
        try {
          DEFAULT.withLocal(schemes);
          throw new Error("expected local_collision");
        } catch (e) {
          expect(e).toBeInstanceOf(RefsError);
          expect((e as RefsError).kind).toBe("local_collision");
        }
      } else {
        DEFAULT.withLocal(schemes);
      }
    },
  );
});

describe("fingerprint", () => {
  test("is stable across loads and cached", () => {
    expect(Registry.default().fingerprint).toBe(DEFAULT.fingerprint);
  });

  test("changes with local schemes", () => {
    expect(DEFAULT.withLocal([local("lit.x", "lit", "^[0-9]+$")]).fingerprint).not.toBe(DEFAULT.fingerprint);
  });

  test("depends on the scheme fields", () => {
    const a = DEFAULT.withLocal([local("lit.x", "lit", "^[0-9]+$")]).fingerprint;
    expect(a).not.toBe(DEFAULT.withLocal([local("lit.x", "lit", "^[0-9]*$")]).fingerprint);
    expect(a).not.toBe(DEFAULT.withLocal([local("lit.x", "lit", "^[0-9]+$", "y")]).fingerprint);
  });

  test("why is not part of it", () => {
    const a = DEFAULT.withLocal([local("lit.x", "lit", null, "x", "one")]);
    const b = DEFAULT.withLocal([local("lit.x", "lit", null, "x", "two")]);
    expect(a.fingerprint).toBe(b.fingerprint);
  });
});

describe("withLocal", () => {
  test("does not change the receiver", () => {
    DEFAULT.withLocal([local("lit.x")]);
    expect(DEFAULT.canonical("lit.x")).toBeNull();
    expect(DEFAULT.isLocal("lit.x")).toBe(false);
  });

  test("raises on a collision", () => {
    expect(() => DEFAULT.withLocal([local("geo", null)])).toThrow(RefsError);
  });

  test("a second withLocal repeats a prefix", () => {
    const reg = DEFAULT.withLocal([local("lit.x")]);
    expect(reg.collisions([local("lit.x")]).map((c) => c.kind)).toEqual(["repeated"]);
  });

  test("issuedBy requires its prefix and a dot", () => {
    // compared case-sensitively, before lower-casing: LIT.x is not issued by lit
    for (const prefix of ["topics.x", "lit", "litter.x", "LIT.x"]) {
      try {
        local(prefix, "lit");
        throw new Error("expected local_collision");
      } catch (e) {
        expect(e).toBeInstanceOf(RefsError);
        expect((e as RefsError).kind).toBe("local_collision");
      }
    }
  });

  test("a local pattern outside the dialect is refused", () => {
    try {
      DEFAULT.withLocal([local("lit.x", "lit", "^\\d+$")]);
      throw new Error("expected unsupported_pattern");
    } catch (e) {
      expect((e as RefsError).kind).toBe("unsupported_pattern");
    }
  });

  test("a local prefix is lower-cased without replacing an alias", () => {
    const reg = DEFAULT.withLocal([local("Lit.X", "Lit")]);
    expect(reg.isLocal("Lit.X")).toBe(true);
    expect(reg.isLocal("lit.x")).toBe(true);
    expect(reg.scheme("lit.x").prefix).toBe("lit.x");
    expect(reg.canonical("LIT.X")).toBe("lit.x");
    expect(reg.scheme("lit.x").issuedBy).toBe("Lit"); // stored as declared
  });
});

describe("membership and lookup", () => {
  test("upstream and local", () => {
    expect(DEFAULT.isUpstream("geo") && !DEFAULT.isLocal("geo")).toBe(true);
    expect(DEFAULT.isLocal("figshare") && !DEFAULT.isUpstream("figshare")).toBe(true);
    expect(DEFAULT.isLocal("FigShare")).toBe(true);
    expect(DEFAULT.isUpstream("nope") || DEFAULT.isLocal("nope")).toBe(false);
    const reg = DEFAULT.withLocal([local("lit.x")]);
    expect(reg.isLocal("lit.x") && !reg.isUpstream("lit.x")).toBe(true);
    expect(reg.scheme("lit.x").issuedBy).toBe("lit");
  });

  test("the scheme of an unknown prefix is refused", () => {
    try {
      DEFAULT.scheme("nope");
      throw new Error("expected unknown_prefix");
    } catch (e) {
      expect((e as RefsError).kind).toBe("unknown_prefix");
    }
  });

  test("a canonical prefix wins over a synonym", () => {
    const reg = Registry.fromDocument({
      version: "t",
      prefixes: {
        first: { name: "First", pattern: null, uri_format: null, synonyms: ["SECOND"] },
        second: { name: "Second", pattern: null, uri_format: null, synonyms: [] },
      },
    });
    expect(reg.canonical("second")).toBe("second");
    expect(reg.canonical("SECOND")).toBe("second");
    expect(reg.canonical("first")).toBe("first");
  });

  test("every shared local scheme is in the default registry", () => {
    const text = readFileSync(new URL("../../registry/local-schemes.toml", import.meta.url), "utf-8");
    const prefixes = [...text.matchAll(/^\[schemes\.("?)([^\]"]+)\1\]$/gm)].map((m) => m[2]);
    expect(prefixes.sort()).toEqual(["europepmc", "figshare", "openalex.topic"]);
    for (const prefix of prefixes) {
      const scheme = DEFAULT.scheme(prefix);
      expect(DEFAULT.isLocal(prefix) && !DEFAULT.isUpstream(prefix)).toBe(true);
      expect([scheme.issuedBy, scheme.synonyms.length, scheme.refused]).toEqual([null, 0, null]);
    }
  });
});

describe("the shared local schemes table", () => {
  const good = { name: "N", pattern: "^[0-9]+$", uri_format: "https://x/$1", why: "w" };

  test("is read into local schemes", () => {
    const [scheme] = localSchemesFromTable({ "x.y": good });
    expect([scheme?.prefix, scheme?.name, scheme?.pattern, scheme?.uriFormat, scheme?.why, scheme?.issuedBy]).toEqual([
      "x.y",
      "N",
      "^[0-9]+$",
      "https://x/$1",
      "w",
      null,
    ]);
  });

  test.each(["name", "pattern", "uri_format", "why"])("refuses a missing %s", (key) => {
    const { [key as keyof typeof good]: _omitted, ...body } = good;
    expect(() => localSchemesFromTable({ "x.y": body })).toThrow(new RegExp(`x\\.y.*${key}`));
  });

  test.each(["name", "pattern", "uri_format", "why"])("refuses a non-string %s", (key) => {
    for (const value of [1, null, ["a"]]) {
      expect(() => localSchemesFromTable({ "x.y": { ...good, [key]: value } })).toThrow(new RegExp(`x\\.y.*${key}`));
    }
  });

  test("refuses an unknown key", () => {
    expect(() => localSchemesFromTable({ "x.y": { ...good, extra: "1" } })).toThrow(/x\.y.*extra/);
  });

  test("refuses a non-table entry", () => {
    expect(() => localSchemesFromTable({ "x.y": "text" })).toThrow(/x\.y/);
  });
});

test("Europe PMC preserves provider source/id identity", () => {
  const scheme = DEFAULT.scheme("europepmc");
  expect([scheme.prefix, scheme.name, scheme.pattern, scheme.uriFormat, scheme.synonyms, scheme.issuedBy]).toEqual([
    "europepmc",
    "Europe PMC record",
    "^[A-Z]+/[A-Za-z0-9][A-Za-z0-9._\\-]*$",
    "https://europepmc.org/article/$1",
    [],
    null,
  ]);
});
