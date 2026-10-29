# verifiably-refs

Vocabulary identifiers pinned to releases: the reference layer above nodes.

`verifiably-refs` is the Python implementation of refs. A TypeScript implementation
(`@verifiably/refs`) passes the same shared fixtures. What refs is, what it does not do,
and runnable examples are in the repository README; the normative contract is
`../docs/STANDARD.md`.

## Install

Not published yet; take a path dependency on this directory. It depends on
`verifiably-nodes` (the sibling `nodes` checkout's `python/`). `just setup` at the
repository root installs it.

## Use

```python
from refs import Registry, parse

registry = Registry.default()
print(parse("PMID:21885717", registry))  # pubmed:21885717
```

The package exports the identifier, registry and vocabulary API from `refs`
(`parse`, `Curie`, `Scheme`, `Registry`, `LocalScheme`, `check_pattern`, `compile_pattern`,
`parse_vocabularies`, `load_vocabularies`, `RefsError`). The `refs/about` facet is
`refs.facet` (`FACET`, `about_facet`, `build_about`), the only module that imports `nodes`.
`refs.rewrite` (`rewrite`, `samples`) is vendoring tooling, outside the parity contract.

`Registry.default()` is the bundled Bioregistry snapshot plus refs' shared local schemes.
The registry data is `registry/` at the repository root, copied into `src/refs/data/` by
`just registry-sync` (gitignored, shipped in the wheel).

## Scripts

The repository front door is `just` (`just test`, `just check`, `just gate`), which runs
pytest, ruff and pyright through a timing wrapper; call them directly only when working on
this package alone without the wrapper. `just test-one tests/test_dialect.py` runs one
test file.

## License

MIT
