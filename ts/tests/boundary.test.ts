import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";

const IDENTIFIER_MODULES = ["dialect.ts", "ids.ts", "registry.ts", "vocab.ts", "errors.ts", "order.ts"];
/** Each other, node builtins and their libraries; never `./facet.js`, which imports nodes. */
const ALLOWED = /^(\.\/(?:dialect|ids|registry|vocab|errors|order)\.js|node:[a-z]+|canonicalize|smol-toml)$/;

/** The module specifiers a source file imports or re-exports from, by line. */
function importedModules(file: string): string[] {
  const text = readFileSync(new URL(`../src/${file}`, import.meta.url), "utf-8");
  const found: string[] = [];
  for (const m of text.matchAll(/^\s*(?:import|export)\b[^;]*?\bfrom\s+["']([^"']+)["']/gms)) found.push(m[1]);
  for (const m of text.matchAll(/^\s*import\s+["']([^"']+)["']/gm)) found.push(m[1]);
  for (const m of text.matchAll(/\b(?:import|require)\(\s*["']([^"']+)["']\s*\)/g)) found.push(m[1]);
  return found;
}

describe("the identifier modules do not import nodes", () => {
  test.each(IDENTIFIER_MODULES)("%s", (file) => {
    const modules = importedModules(file);
    expect(modules.filter((m) => m.startsWith("@verifiably/nodes"))).toEqual([]);
  });

  test("the scan sees imports: facet.ts imports nodes", () => {
    expect(importedModules("facet.ts")).toContain("@verifiably/nodes");
  });

  test("the identifier modules import only each other, node builtins and their libraries", () => {
    for (const file of IDENTIFIER_MODULES) {
      for (const m of importedModules(file)) expect(m, `${file} imports ${m}`).toMatch(ALLOWED);
    }
  });

  test("the allow-list refuses the facet module, which would bring nodes in", () => {
    expect("./facet.js").not.toMatch(ALLOWED);
  });
});
