# @verifiably/refs (TypeScript)

TypeScript implementation of refs, at parity with the Python distribution: both pass the
shared fixtures in `../fixtures`. The portable contract is `../docs/STANDARD.md`; what refs
is, what it does not do, and runnable examples are in the repository README.

## Scope

Tier 1 (parity with Python): the pattern dialect (`checkPattern`, `compilePattern`), CURIE
parsing (`parseCurie`, `Curie`, `Scheme`), the registry (`Registry`, `LocalScheme`, with its
fingerprint and collisions), vocabulary declarations (`parseVocabularies`, `Vocabulary`)
and the `refs/about` facet (`FACET`, `aboutFacet`). Tier 3, Python only: `rewrite`,
`samples`, the vendoring tool, `load_vocabularies` (read a TOML file yourself and pass the
parsed table to `parseVocabularies`) and the dialect AST.

`data/` is a copy of `../registry`, written by `just registry-sync` (gitignored, shipped in
the package). The facet module is the only one that imports `@verifiably/nodes`; a test
enforces it.

## Conventions

- **camelCase API.** The same contract as Python with TypeScript spelling (`parseCurie`,
  `withLocal`, `uriFormat`, `issuedBy`); registry and fixture data stay snake_case.
- Positions in a `RefsError` are 0-based code-point indices, as in Python; patterns compile
  with the `u` flag, and entries sort by code point, never by UTF-16 unit.
- Facet failures surface as nodes' `FacetError`, never a raw Zod error.

## Scripts

The repository front door is `just` (`just test`, `just check`, `just gate`), which runs
these through a timing wrapper; call them directly only when working on this package
alone without the wrapper.

- `npm test`: builds the package, then runs the Vitest suite (the shared fixtures and the
  module-boundary check)
- `npm run typecheck`: `tsc --noEmit`
- `npm run check`: Biome lint and format
