/** Identifiers as CURIEs: `prefix:local` with the registry's canonical prefix (spec 5.2). */

import { compilePattern } from "./dialect.js";
import { RefsError } from "./errors.js";
import type { Registry } from "./registry.js";

export class Curie {
  readonly prefix: string;
  readonly local: string;

  constructor(prefix: string, local: string) {
    this.prefix = prefix;
    this.local = local;
    Object.freeze(this);
  }

  toString(): string {
    return `${this.prefix}:${this.local}`;
  }
}

const compiled = new Map<string, RegExp>();

function compiledPattern(pattern: string): RegExp {
  let re = compiled.get(pattern);
  if (re === undefined) {
    re = compilePattern(pattern);
    compiled.set(pattern, re);
  }
  return re;
}

export interface SchemeFields {
  prefix: string;
  name: string;
  pattern: string | null;
  uriFormat: string | null;
  synonyms: readonly string[];
  issuedBy: string | null;
  refused: string | null;
}

/** One prefix's grammar. `pattern` is in the pattern dialect, null when the registry states
 * none (or when `refused` says the upstream pattern has no dialect form). `uriFormat` is
 * data for resolvers; refs never dereferences it. */
export class Scheme {
  readonly prefix: string;
  readonly name: string;
  readonly pattern: string | null;
  readonly uriFormat: string | null;
  readonly synonyms: readonly string[];
  readonly issuedBy: string | null;
  readonly refused: string | null;

  constructor(fields: SchemeFields) {
    this.prefix = fields.prefix;
    this.name = fields.name;
    this.pattern = fields.pattern;
    this.uriFormat = fields.uriFormat;
    this.synonyms = Object.freeze([...fields.synonyms]);
    this.issuedBy = fields.issuedBy;
    this.refused = fields.refused;
    Object.freeze(this);
  }

  /** Full match of the whole local id; a scheme without a pattern accepts any id, a refused one none. */
  matches(local: string): boolean {
    if (this.refused !== null) throw new RefsError("unsupported_pattern", `${this.prefix}: ${this.refused}`);
    return this.pattern === null || compiledPattern(this.pattern).test(local);
  }
}

/** Parse `prefix:local` into a Curie with the canonical prefix and the local id as given. */
export function parseCurie(text: string, registry: Registry): Curie {
  const colon = text.indexOf(":");
  if (colon < 0) throw new RefsError("ambiguous_id", `${JSON.stringify(text)} needs a prefix: write <prefix>:${text}`);
  const prefix = text.slice(0, colon);
  const local = text.slice(colon + 1);
  if (prefix === "" || local === "") throw new RefsError("not_a_curie", `${JSON.stringify(text)} is not <prefix>:<id>`);
  const canonical = registry.canonical(prefix);
  if (canonical === null) throw new RefsError("unknown_prefix", `${JSON.stringify(prefix)} is not a known prefix`);
  const scheme = registry.scheme(canonical);
  if (!scheme.matches(local)) {
    throw new RefsError(
      "malformed",
      `${JSON.stringify(local)} does not match ${canonical}'s pattern ${scheme.pattern}`,
    );
  }
  return new Curie(canonical, local);
}
