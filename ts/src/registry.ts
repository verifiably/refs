/** The pinned Bioregistry snapshot plus refs' shared local schemes and a profile's self-issued
 * ones, with a fingerprint over the effective grammar (spec 5.3). */

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import canonicalize from "canonicalize";
import { parse as parseToml } from "smol-toml";
import { checkPattern } from "./dialect.js";
import { RefsError } from "./errors.js";
import { Scheme } from "./ids.js";

export interface LocalSchemeFields {
  prefix: string;
  name: string;
  pattern: string | null;
  uriFormat: string | null;
  why: string;
  issuedBy?: string | null;
}

/** A scheme Bioregistry lacks. A self-issued one names its issuing project in `issuedBy`
 * and its prefix begins with that name and a dot. */
export class LocalScheme {
  readonly prefix: string;
  readonly name: string;
  readonly pattern: string | null;
  readonly uriFormat: string | null;
  readonly why: string;
  readonly issuedBy: string | null;

  constructor(fields: LocalSchemeFields) {
    const issuedBy = fields.issuedBy ?? null;
    if (issuedBy !== null && !fields.prefix.startsWith(`${issuedBy}.`)) {
      throw new RefsError(
        "local_collision",
        `${JSON.stringify(fields.prefix)} is issued by ${JSON.stringify(issuedBy)}, so it must begin with ${JSON.stringify(`${issuedBy}.`)}`,
      );
    }
    this.prefix = fields.prefix;
    this.name = fields.name;
    this.pattern = fields.pattern;
    this.uriFormat = fields.uriFormat;
    this.why = fields.why;
    this.issuedBy = issuedBy;
    Object.freeze(this);
  }
}

export interface Collision {
  readonly prefix: string;
  readonly kind: "shadows_registry" | "repeated";
  readonly detail: string;
}

/** The shape of `registry/bioregistry.json`. */
export interface RegistryDocument {
  version: string;
  prefixes: Record<
    string,
    {
      name: string;
      pattern: string | null;
      uri_format: string | null;
      synonyms: string[];
      refused?: string;
    }
  >;
}

// The data directory sits beside src/ and dist/ in the package, so this resolves from both.
function readData(name: string): string {
  return readFileSync(new URL(`../data/${name}`, import.meta.url), "utf-8");
}

const SHARED_KEYS = ["name", "pattern", "uri_format", "why"] as const;

/** The schemes of `local-schemes.toml`'s `schemes` table. Each entry holds exactly the four
 * string keys `name`, `pattern`, `uri_format` and `why`; anything else is a data bug, refused
 * here rather than left to change the fingerprint. */
export function localSchemesFromTable(table: Record<string, unknown>): LocalScheme[] {
  return Object.entries(table).map(([prefix, body]) => {
    const name = JSON.stringify(prefix);
    if (typeof body !== "object" || body === null || Array.isArray(body)) {
      throw new Error(`local scheme ${name} must be a table`);
    }
    const fields = body as Record<string, unknown>;
    for (const key of Object.keys(fields)) {
      if (!(SHARED_KEYS as readonly string[]).includes(key)) {
        throw new Error(`local scheme ${name} has an unknown key ${JSON.stringify(key)}`);
      }
    }
    for (const key of SHARED_KEYS) {
      if (!(key in fields)) throw new Error(`local scheme ${name} is missing ${JSON.stringify(key)}`);
      if (typeof fields[key] !== "string") {
        throw new Error(`local scheme ${name}: ${JSON.stringify(key)} must be a string`);
      }
    }
    return new LocalScheme({
      prefix,
      name: fields.name as string,
      pattern: fields.pattern as string,
      uriFormat: fields.uri_format as string,
      why: fields.why as string,
    });
  });
}

let defaultRegistry: Registry | undefined;

/** Immutable: `withLocal` returns a new registry. */
export class Registry {
  readonly version: string;
  private readonly schemes: ReadonlyMap<string, Scheme>;
  private readonly lookup: ReadonlyMap<string, string>; // lower-cased canonical prefix or synonym -> canonical prefix; upstream only
  private readonly local: ReadonlySet<string>;
  private fingerprintCache: string | undefined;

  private constructor(
    version: string,
    schemes: ReadonlyMap<string, Scheme>,
    lookup: ReadonlyMap<string, string>,
    local: ReadonlySet<string>,
  ) {
    this.version = version;
    this.schemes = schemes;
    this.lookup = lookup;
    this.local = local;
  }

  /** A registry of the upstream prefixes in `doc` (the shape of registry/bioregistry.json) alone. */
  static fromDocument(doc: RegistryDocument): Registry {
    const schemes = new Map<string, Scheme>();
    const lookup = new Map<string, string>();
    for (const [prefix, body] of Object.entries(doc.prefixes)) {
      schemes.set(
        prefix,
        new Scheme({
          prefix,
          name: body.name,
          pattern: body.pattern,
          uriFormat: body.uri_format,
          synonyms: body.synonyms,
          issuedBy: null,
          refused: body.refused ?? null,
        }),
      );
      lookup.set(prefix.toLowerCase(), prefix);
    }
    for (const [prefix, body] of Object.entries(doc.prefixes)) {
      for (const synonym of body.synonyms) {
        const key = synonym.toLowerCase();
        if (!lookup.has(key)) lookup.set(key, prefix); // a canonical prefix always wins
      }
    }
    return new Registry(doc.version, schemes, lookup, new Set());
  }

  /** The bundled snapshot plus refs' shared local schemes. */
  static default(): Registry {
    if (defaultRegistry === undefined) {
      const upstream = Registry.fromDocument(JSON.parse(readData("bioregistry.json")) as RegistryDocument);
      const shared = (parseToml(readData("local-schemes.toml")) as { schemes: Record<string, unknown> }).schemes;
      defaultRegistry = upstream.withLocal(localSchemesFromTable(shared));
    }
    return defaultRegistry;
  }

  /** SHA-256 hex of the RFC 8785 canonical JSON of every scheme, local ones included. */
  get fingerprint(): string {
    if (this.fingerprintCache === undefined) {
      const effective = {
        version: this.version,
        schemes: Object.fromEntries(
          [...this.schemes].map(([prefix, s]) => [
            prefix,
            {
              name: s.name,
              pattern: s.pattern,
              uri_format: s.uriFormat,
              synonyms: [...s.synonyms],
              issued_by: s.issuedBy,
              refused: s.refused,
            },
          ]),
        ),
      };
      const text = canonicalize(effective);
      if (text === undefined) throw new Error("canonicalizer returned undefined");
      this.fingerprintCache = createHash("sha256").update(text, "utf-8").digest("hex");
    }
    return this.fingerprintCache;
  }

  /** The canonical prefix for `prefix` in any case, or a synonym of it; null when unknown. */
  canonical(prefix: string): string | null {
    const key = prefix.toLowerCase();
    return this.local.has(key) ? key : (this.lookup.get(key) ?? null);
  }

  /** The scheme under the canonical `prefix`. */
  scheme(prefix: string): Scheme {
    const found = this.schemes.get(prefix);
    if (found === undefined)
      throw new RefsError("unknown_prefix", `${JSON.stringify(prefix)} is not a canonical prefix`);
    return found;
  }

  isUpstream(prefix: string): boolean {
    return this.schemes.has(prefix) && !this.local.has(prefix);
  }

  isLocal(prefix: string): boolean {
    return this.local.has(prefix.toLowerCase());
  }

  /** The conflicts `withLocal` would refuse, in declaration order, without throwing. A pattern
   * outside the dialect, which `withLocal` also refuses, is not a collision and is not listed. */
  collisions(schemes: Iterable<LocalScheme>): Collision[] {
    const seen = new Set(this.local);
    const found: Collision[] = [];
    for (const scheme of schemes) {
      const key = scheme.prefix.toLowerCase();
      const shadowed = this.lookup.get(key);
      if (seen.has(key)) {
        found.push({
          prefix: scheme.prefix,
          kind: "repeated",
          detail: `${JSON.stringify(scheme.prefix)} is already a local prefix`,
        });
      } else if (shadowed !== undefined) {
        found.push({
          prefix: scheme.prefix,
          kind: "shadows_registry",
          detail: `${JSON.stringify(scheme.prefix)} is Bioregistry's prefix or synonym ${JSON.stringify(shadowed)}`,
        });
      }
      seen.add(key);
    }
    return found;
  }

  /** A registry that adds `schemes`; local prefixes are stored lower-cased, like lookups. */
  withLocal(schemes: Iterable<LocalScheme>): Registry {
    const declared = [...schemes];
    const found = this.collisions(declared);
    if (found.length > 0) throw new RefsError("local_collision", found.map((c) => c.detail).join("; "));
    for (const scheme of declared) {
      if (scheme.pattern !== null) checkPattern(scheme.pattern);
    }
    const all = new Map(this.schemes);
    const local = new Set(this.local);
    for (const s of declared) {
      const prefix = s.prefix.toLowerCase();
      all.set(
        prefix,
        new Scheme({
          prefix,
          name: s.name,
          pattern: s.pattern,
          uriFormat: s.uriFormat,
          synonyms: [],
          issuedBy: s.issuedBy,
          refused: null,
        }),
      );
      local.add(prefix);
    }
    return new Registry(this.version, all, this.lookup, local);
  }
}
