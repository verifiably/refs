import { readFileSync } from "node:fs";

/** A shared fixture from `fixtures/`, read as UTF-8 JSON. */
export function loadFixture<T>(name: string): T {
  return JSON.parse(readFileSync(new URL(`../../fixtures/${name}`, import.meta.url), "utf-8")) as T;
}

/** The Python-style short label of a pattern for a test title. */
export function label(text: string): string {
  const shown = JSON.stringify(text);
  return shown.length <= 40 ? shown : `${shown.slice(0, 30)}...len${Array.from(text).length}`;
}
