/** The `refs/about` facet: a node's references, each with its own release (docs/STANDARD.md §6).
 *
 * The only refs module that imports nodes. */

import { FacetError, type Invariant } from "@verifiably/nodes";
import { z } from "zod";
import { RefsError } from "./errors.js";
import { parseCurie } from "./ids.js";
import { compareCodePoints } from "./order.js";
import type { Registry } from "./registry.js";
import { type Vocabulary, releases } from "./vocab.js";

export const FACET = "refs/about";

// `release` is a string or absent: a null is refused, as in the Python package.
const EntrySchema = z.object({ id: z.string(), release: z.string().optional() }).strict();
const AboutSchema = z.object({ entries: z.array(EntrySchema) }).strict();

// Type aliases, not interfaces: a facet payload is a `Record<string, unknown>`, which an
// interface (no implicit index signature) is not assignable to.
export type AboutEntry = { id: string; release?: string };
export type About = { entries: AboutEntry[] };

// An absent release sorts first, as "".
function compareKeys(a: AboutEntry, b: AboutEntry): number {
  return compareCodePoints(a.id, b.id) || compareCodePoints(a.release ?? "", b.release ?? "");
}

/** The canonical payload: ids canonicalised, duplicates dropped, sorted by code point.
 * Releases are not checked against vocabularies; the invariant does that. */
export function buildAbout(entries: Iterable<readonly [string, string | null]>, registry: Registry): About {
  const unique = new Map<string, AboutEntry>();
  for (const [id, release] of entries) {
    const canonical = String(parseCurie(id, registry));
    unique.set(JSON.stringify([canonical, release]), release === null ? { id: canonical } : { id: canonical, release });
  }
  return { entries: [...unique.values()].sort(compareKeys) };
}

function firstViolation(
  payload: unknown,
  registry: Registry,
  vocabularies: ReadonlyMap<string, Vocabulary>,
): string | null {
  const shape = AboutSchema.safeParse(payload);
  if (!shape.success) {
    const issues = shape.error.issues.map((i) => `${i.path.join(".") || "payload"}: ${i.message}`).join("; ");
    return `malformed payload: ${issues}`;
  }
  const { entries } = shape.data;
  if (entries.length === 0) return "entries must not be empty";
  let previous: AboutEntry | undefined;
  for (const entry of entries) {
    let canonical: string;
    try {
      canonical = String(parseCurie(entry.id, registry));
    } catch (error) {
      if (error instanceof RefsError) return `${JSON.stringify(entry.id)}: ${error.message}`;
      throw error;
    }
    if (canonical !== entry.id)
      return `${JSON.stringify(entry.id)} is not canonical, write ${JSON.stringify(canonical)}`;
    const prefix = canonical.slice(0, canonical.indexOf(":"));
    const vocabulary = vocabularies.get(prefix);
    const shown = JSON.stringify(entry.id);
    if (vocabulary === undefined) {
      if (entry.release !== undefined) return `${shown}: ${prefix} declares no vocabulary, so it takes no release`;
    } else if (entry.release === undefined) {
      return `${shown}: ${prefix} is a vocabulary, so a release is required`;
    } else if (!releases(vocabulary).has(entry.release)) {
      return `${shown}: release ${JSON.stringify(entry.release)} is not the current release ${JSON.stringify(vocabulary.release)} or one of ${JSON.stringify(vocabulary.accepted)}`;
    }
    if (previous !== undefined) {
      const order = compareKeys(entry, previous);
      if (order <= 0) {
        const kind = order === 0 ? "repeats" : "is out of order after";
        return `${shown} (release ${JSON.stringify(entry.release ?? null)}) ${kind} the entry before it`;
      }
    }
    previous = entry;
  }
  return null;
}

/** A nodes invariant for `refs/about`: a no-op without the facet, otherwise `FacetError`
 * naming the node and the first violation. */
export function aboutFacet(registry: Registry, vocabularies: ReadonlyMap<string, Vocabulary>): Invariant {
  const declared = new Map(vocabularies);
  return (node) => {
    if (!Object.hasOwn(node.facets, FACET)) return;
    const problem = firstViolation(node.facets[FACET], registry, declared);
    if (problem !== null) throw new FacetError(`${node.id}: ${FACET}: ${problem}`);
  };
}
