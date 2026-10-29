/** Vocabulary declarations: a prefix whose ids are drawn from a released vocabulary (spec 5.4). */

import { RefsError } from "./errors.js";
import { compareCodePoints } from "./order.js";
import type { Registry } from "./registry.js";

const KEYS = new Set(["issuer", "release", "accepted"]);

/** `release` is the current release, stamped on new references; `accepted` lists earlier
 * releases that existing references may still carry. Releases are opaque strings. */
export interface Vocabulary {
  readonly prefix: string;
  readonly issuer: "external" | "self";
  readonly release: string;
  readonly accepted: readonly string[];
}

/** The current release and every accepted one. */
export function releases(vocabulary: Vocabulary): Set<string> {
  return new Set([vocabulary.release, ...vocabulary.accepted]);
}

function refuse(prefix: string, detail: string): RefsError {
  return new RefsError("invalid_vocabulary", `${JSON.stringify(prefix)}: ${detail}`);
}

function release(prefix: string, name: string, value: unknown): string {
  if (typeof value !== "string" || value === "") {
    throw refuse(prefix, `${name} must be a non-empty string, got ${JSON.stringify(value)}`);
  }
  return value;
}

function parseOne(prefix: string, declaration: unknown, registry: Registry): Vocabulary {
  if (registry.canonical(prefix) !== prefix) throw refuse(prefix, "not a canonical prefix of the registry");
  if (typeof declaration !== "object" || declaration === null || Array.isArray(declaration)) {
    throw refuse(prefix, "the declaration must be a table");
  }
  const body = declaration as Record<string, unknown>;
  const unknown = Object.keys(body)
    .filter((key) => !KEYS.has(key))
    .sort(compareCodePoints);
  if (unknown.length > 0) throw refuse(prefix, `unknown keys ${JSON.stringify(unknown)}`);
  if (!("issuer" in body) || !("release" in body)) throw refuse(prefix, "issuer and release are required");
  const issuer = body.issuer;
  if (issuer !== "external" && issuer !== "self") {
    throw refuse(prefix, `issuer must be 'external' or 'self', got ${JSON.stringify(issuer)}`);
  }
  const selfIssued = registry.isLocal(prefix) && registry.scheme(prefix).issuedBy !== null;
  if (issuer === "self" && !selfIssued)
    throw refuse(prefix, "a self-issued vocabulary needs a local scheme with issued_by");
  if (issuer === "external" && selfIssued)
    throw refuse(prefix, "the scheme is self-issued, so the issuer must be 'self'");
  const current = release(prefix, "release", body.release);
  const raw = "accepted" in body ? body.accepted : [];
  if (!Array.isArray(raw)) throw refuse(prefix, "accepted must be a list");
  const accepted = (raw as unknown[]).map((item) => release(prefix, "accepted", item));
  if (new Set(accepted).size !== accepted.length) throw refuse(prefix, "accepted repeats a release");
  if (accepted.includes(current)) throw refuse(prefix, "accepted repeats the current release");
  return Object.freeze({ prefix, issuer, release: current, accepted: Object.freeze(accepted) });
}

/** The `[vocabularies]` table of spec 5.4, already parsed. Each key is the canonical prefix. */
export function parseVocabularies(
  table: Readonly<Record<string, unknown>>,
  registry: Registry,
): Map<string, Vocabulary> {
  return new Map(
    Object.entries(table).map(([prefix, declaration]) => [prefix, parseOne(prefix, declaration, registry)]),
  );
}
