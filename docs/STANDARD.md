# The refs Standard

- **Spec version:** 1.0
- **Status:** Living standard: the authoritative definition of the portable `refs` contract.
- **Implementations:** Python (`python/src/refs/`), TypeScript (`ts/src/`).

The key words MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY are to be interpreted as
described in RFC 2119. Where a dated design document disagrees with this standard, this
standard wins. Where this standard and a fixture disagree, one of them has a bug: fix it
in the same change.

## 1. Scope and conformance

`refs` is the reference layer above `nodes`: a Bioregistry-canonical identifier form (the
CURIE `prefix:local`), the pinned prefix registry that gives each prefix its grammar,
declarations that tie a prefix's identifiers to a released vocabulary, and one facet,
`refs/about`, with which a node says which references it carries. It is offline and
parses, validates and records identifiers; it never resolves one, fetches anything, or
checks membership in a held vocabulary.

Guarantees fall into three conformance tiers:

- **Tier 1: portable contract.** The pattern dialect (§2), CURIE parsing and its errors
  (§3), the registry format, lookup, collisions and fingerprint (§4.1 to §4.6),
  vocabulary declarations (§5), and the `refs/about` facet (§6). Both languages MUST
  agree exactly on every verdict, canonical output and refusal position the fixtures
  pin (§7). Refusal *messages* (`detail`) are not pinned.
- **Tier 2: none yet.** Every pinned behaviour is tier 1.
- **Tier 3: per-language and tooling surface.** No parity obligation: `load_vocabularies`
  (Python reads a TOML file; the TypeScript package takes the parsed table through
  `parseVocabularies`), `build_about` / `buildAbout`, the Python AST (`parse_pattern`,
  `Ast`), `rewrite`, `samples`, and the vendoring tool (§4.7). They are tested by the
  suites' own unit tests, not by shared fixtures.

**Names.** The Python and TypeScript APIs differ only in spelling:

| Concept | Python (`refs`) | TypeScript (`@verifiably/refs`) |
|---------|-----------------|---------------------------------|
| Parse a CURIE | `parse(text, registry)` | `parseCurie(text, registry)` |
| Check, compile a pattern | `check_pattern`, `compile_pattern` | `checkPattern`, `compilePattern` |
| Registry | `Registry.default()`, `.with_local()`, `.collisions()`, `.fingerprint`, `.canonical()`, `.scheme()`, `.is_local()`, `.is_upstream()` | `Registry.default()`, `.withLocal()`, `.collisions()`, `.fingerprint`, `.canonical()`, `.scheme()`, `.isLocal()`, `.isUpstream()` |
| Local scheme | `LocalScheme(..., issued_by=)` | `new LocalScheme({ ..., issuedBy })` |
| Vocabularies | `parse_vocabularies`, `Vocabulary` | `parseVocabularies`, `Vocabulary` |
| The facet | `FACET`, `about_facet(registry, vocabularies)` | `FACET`, `aboutFacet(registry, vocabularies)` |
| Errors | `RefsError(kind, detail, position)` | `RefsError` with the same fields |

**Errors.** A refusal is a `RefsError` carrying `kind` (§3.3), `detail` (human text) and
`position`, a 0-based code-point index into the offending text, or none when the refusal
has no single location. The facet's invariant raises nodes' `FacetError` instead (§6).

**Module boundary.** The identifier, dialect, registry and vocabulary modules import
nothing from `nodes`; only the facet module does. An import test in each language
enforces it (`python/tests/test_ids.py`, `ts/tests/boundary.test.ts`). refs ships a
facet and an invariant, never a kind.

**Change policy.** A tier 1 change updates this document and the affected fixtures in
both languages in the same change. A tier 3 addition does not touch this document.
Refreshing the vendored registry (§4.7) changes data, not the contract, and rewrites the
fixtures it generates (`registry.verdicts.json`) and the pinned fingerprint
(`registry.json`) in the same change.

## 2. The pattern dialect

Python `re` and ECMAScript `RegExp` disagree on ordinary patterns and on syntax. So every
stored identifier pattern is written in a dialect defined by its own grammar, not by what
either engine compiles. Both languages parse a pattern against the grammar **before**
any engine compiles it, and refuse what it does not produce with the same error and the
same position. Fixtures: `dialect.syntax.json`, `dialect.match.json`.

### 2.1 Grammar

```
pattern     = alternation
alternation = sequence { "|" sequence }
sequence    = { item }
item        = "^" | "$" | atom [ quantifier ]
atom        = literal | escape | class | group
group       = "(" alternation ")" | "(?:" alternation ")"
quantifier  = ( "?" | "*" | "+" | "{" m "}" | "{" m "," "}" | "{" m "," n "}" ) [ "?" ]
class       = "[" [ "^" ] ( member | range ) { member | range } "]"
range       = member "-" member
```

- `^` is allowed only at index 0 of the pattern and `$` only as its last character
  (`a|^b` and `a$|b` are refused; `^a|b` and `a|b$` are accepted). An anchor takes no
  quantifier.
- The empty pattern, empty branches (`a|`, `(|a)`) and empty groups (`()`) are accepted.
- `{` appears unescaped only as the start of a well-formed quantifier. `m` and `n` are
  decimal bounds written with ASCII digits; `{,n}` is not in the grammar. `m` MUST NOT
  exceed `n`. A quantifier takes an optional trailing `?` (lazy) and nothing more: `a*??`
  and `a{2}{3}` are refused.
- A group is capturing `(...)` or non-capturing `(?:...)`. Any other `(?` is refused.
  Lookaround, named groups, inline flags, backreferences and conditionals are therefore
  all outside the dialect.

### 2.2 Characters and escapes, per context

- **Outside a class**, a literal is any code point except the syntax characters
  `\ ^ $ . | ? * + ( ) [ ] { }`. A syntax character is written escaped (`\.`, `\{`).
  A bare `-`, `/`, space, `#` or newline is a literal. The permitted escapes are the
  escaped syntax characters, `\/`, and the control escapes `\t \n \v \f \r`. `\-` outside
  a class is refused (JavaScript under `u` rejects it); write `-` bare.
- **Inside a class**, a member is any code point other than `\ ] [ ^ -`, one of those five
  escaped (`\\ \] \[ \^ \-`), or a control escape. So `.`, `{`, `*`, `$`, `|` and `(` are
  literal members. `^` unescaped is allowed only as the class's first character, where it
  negates. A class holds at least one member, so `[]` and `[^]` are refused, and `]` in a
  class is always escaped (`[\]]`). A `-` is a range operator only between two members; a
  leading, trailing or doubled unescaped `-` is refused. A range's two ends are members
  (escapes included: `[a\--z]`, `[\t-\r]`), and the first MUST NOT be above the second
  by code point.
- **Doubled reserved characters.** An unescaped `&&`, `~~` or `||` inside a class is
  refused, because Python reserves them for set operations. A single `&`, `~` or `|` is a
  literal member.
- **Every other escape is outside the dialect**: `\x41`, `\u0041`, `\0`, octal, `\b`,
  `\B`, `\A`, `\Z`, `\p{...}`, a backreference `\1`, the shorthand classes `\d \w \s`
  (and their negations), an unknown letter, and any escape inside a class not listed
  above. The shorthands and `.` are accepted only by the vendoring rewrite (§4.7), which
  expands them to explicit ASCII classes before the checker sees the pattern.

### 2.3 Limits

These bounds are part of the contract (they keep both engines and the recursive parser
inside defined behaviour):

- A quantifier bound above 65535 is refused, at the `{`.
- A quantifier bound written with more than five digits is refused, leading zeros
  included, at the `{`: `a{01}` is accepted (it reads as 1); `a{000001}` is refused. The
  digit count is checked before any integer conversion, so a 5000-digit bound is refused
  quickly rather than parsed.
- Groups nest at most 32 deep. The 33rd nested `(` (capturing or not) is refused, at that
  `(`; deeper input is refused there too and never reaches a recursion limit.

### 2.4 Refusal and positions

A pattern outside the grammar is refused with kind `unsupported_pattern` and a
**0-based code-point index** into the pattern (an astral character counts as one, not two
UTF-16 units). The position is that of the first character the grammar cannot accept; the
fixtures pin these refusal points:

| Construct | Position |
|-----------|----------|
| Unclosed group or class, or a pattern that ends inside one | the length of the pattern (end of input): `(a` is 2, `[a` is 2, `[^a` is 3 |
| `(?` followed by anything but `:`, including end of input | the `?`: `(?i)ab` is 1, `a(?` is 2 |
| Unmatched `)` | the `)` |
| A backslash with nothing after it | the backslash |
| An escape outside the dialect, in or out of a class | the backslash |
| An unescaped syntax character outside a class (`}`, `]`, `.`) | that character |
| A quantifier with nothing to quantify, a second quantifier, a lazy `?` followed by another `?` | the offending quantifier character; for `{...}`, its `{` |
| A brace quantifier that is not well-formed (unterminated, non-numeric, `{,n}`, `m` above `n`, a bound over 65535, a digit run over five) | the `{` that opens it |
| `^` not at index 0, `$` not last | that anchor |
| An empty class (`[]]`, `[]`, `[^]`) | the closing `]` that finds no member: `[]]` is 1, `[^]` is 2 |
| `[` or a non-leading `^` unescaped in a class | that character |
| A misplaced `-` in a class | `[-a]` the leading `-`; `[a-]` the trailing `-`; `[a-z-0]` the dash after a range; `[a--]` the second `-` |
| A reversed range (`[z-a]`, `[\n-\t]`) | the range's first member |
| A doubled reserved character in a class (`[&&]`, `[a&&b]`) | the second character |
| The 33rd nested group | its `(` |

### 2.5 Matching

A local id matches a pattern by **full match over the whole id, code point by code
point, with no flags**. Python compiles the stored pattern as is and calls `fullmatch`;
TypeScript compiles `^(?:pattern)$` with the `u` flag. The match fixtures pin the places
the engines differ without this: non-ASCII digits and letters (`١٢٣`, fullwidth `Ａ`, U+212A the Kelvin
sign) do not match ASCII classes; U+00A0 and U+2003 do not match `[\t\n\v\f\r ]`; a
trailing newline does not match `^...$`; `[^\n]` matches `\r`, U+2028 and an astral
code point as one character.

Compilation runs only on a pattern the grammar accepted. An engine error after that is a
refs bug and is raised as kind `invalid_pattern` (no position), never as a difference
between languages.

### 2.6 Where the dialect applies

Every stored pattern is in it: the vendored registry (§4.1), the shared local schemes
(§4.4), and self-issued schemes at `with_local` (§4.5). Each is run through the checker
before any use.

## 3. CURIEs and errors

### 3.1 The CURIE

`Curie(prefix, local)` has text form `prefix:local`: the prefix is the registry's
canonical prefix, the local id is kept exactly as given (no case folding, no trimming).

### 3.2 Parsing

`parse(text, registry)` splits `text` at the **first** `:` and decides, in this order:

1. no `:` at all: `ambiguous_id`;
2. an empty prefix or an empty local id (`geo:`, `:GSE1`, `:`): `not_a_curie`;
3. a prefix the registry's lookup (§4.5) does not know, including one with leading or
   trailing space (` hgnc:6390`): `unknown_prefix`;
4. a scheme whose upstream pattern had no dialect form (§4.1, `refused`): any local id is
   refused with `unsupported_pattern` (no position);
5. a local id that does not fully match the scheme's pattern (§2.5), including
   `hgnc:6390\n`, `hgnc:123456` and `hgnc:١٢٣`: `malformed`. A scheme with no pattern
   accepts any non-empty local id (`aaindex:anything at all`).

Otherwise the result is a `Curie` with the canonical prefix. Input accepts the canonical
prefix or any synonym in any case (`PMID:21885717`, `PubMed ID:21885717` both give
`pubmed:21885717`); output is canonical. The registry's grammar is the authority:
`hgnc:6390` parses and `hgnc.symbol:KIF14` parses, while `HGNC:KIF14` is `malformed`.
Fixture: `parse.json`.

### 3.3 Error kinds

| Kind | Raised when |
|------|-------------|
| `ambiguous_id` | text has no prefix (§3.2) |
| `not_a_curie` | empty prefix or empty local id |
| `unknown_prefix` | the prefix is not in the lookup; also `Registry.scheme` on a name that is not a canonical prefix |
| `malformed` | the local id does not fully match the prefix's pattern |
| `unsupported_pattern` | a pattern is outside the dialect (§2.4, with a position); a scheme was refused at vendoring (§3.2, no position) |
| `invalid_pattern` | the engine refused a pattern the grammar accepted (§2.5) |
| `local_collision` | a local scheme shadows the registry, repeats a prefix, or breaks the `issued_by` prefix rule (§4.5) |
| `invalid_vocabulary` | a vocabulary declaration is malformed (§5) |

`refs/about` failures are not `RefsError`: the invariant raises nodes' `FacetError` (§6).

## 4. The registry

### 4.1 The snapshot file

`registry/bioregistry.json` is the pinned Bioregistry snapshot, in the dialect:

```
{ "source": "bioregistry", "version": "<upstream version>",
  "prefixes": { "<prefix>": { "name", "pattern", "upstream_pattern", "rules",
                               "synonyms", "uri_format", "refused"? } } }
```

`pattern` is the dialect form or null; `upstream_pattern` is Bioregistry's original or
null; `rules` lists the rewrite rules applied (§4.7); `synonyms` is a list in file order;
`uri_format` is carried as data for resolvers and never dereferenced. Invariants a suite
checks: every non-null `pattern` passes the dialect checker; `refused`, when present,
appears only where `pattern` is null and `upstream_pattern` is not, and holds the reason. A
refused scheme stays in the registry (its prefix is known) but every id under it fails
(§3.2). The 10 refused prefixes of the current snapshot are recorded in
`registry/SOURCES.toml`.

### 4.2 `SOURCES.toml`

`registry/SOURCES.toml` records the snapshot:

| Field | Meaning |
|-------|---------|
| `[bioregistry] version` | the upstream Bioregistry version |
| `vendored` | the date vendoring ran |
| `file` | the written file's name, `bioregistry.json` |
| `sha256` | SHA-256 of the written (rewritten) file; checked by a suite against the file's bytes |
| `upstream_sha256` | SHA-256 of the verified input snapshot, before any rewrite |
| `[refused]` | prefix to reason (with the position of the refusal), equal to the `refused` fields of the file |

### 4.3 Copies

`registry/` is the one copy of the registry data (`bioregistry.json`, `SOURCES.toml`,
`local-schemes.toml`). Each package carries a gitignored copy (`python/src/refs/data/`,
`ts/data/`) written by `just registry-sync` and shipped in the built package. The gate's
`registry-check` compares each copy with `registry/` by SHA-256 and fails on a copy that
is missing, extra or different. Both packages therefore read the same bytes.

### 4.4 Shared local schemes

`registry/local-schemes.toml` holds shared external schemes for prefixes Bioregistry
lacks, each a table `[schemes.<prefix>]` with `name`, `pattern` (in the dialect),
`uri_format` and `why` (why Bioregistry does not cover it). Today `openalex.topic` and
`figshare`. A shared prefix MUST be new: neither a Bioregistry prefix nor a synonym of
one (case-insensitively). The default registry (`Registry.default()`) is the snapshot
plus these schemes, added as local schemes with no `issued_by`.

### 4.5 Lookup, local schemes and collisions

- **Lookup.** `canonical(text)` is case-insensitive: it lower-cases the text and returns
  the canonical prefix, or none when unknown. A canonical prefix wins over a synonym of
  another prefix. There is no trimming (`" geo"` is unknown). The fixtures pin ASCII
  case only. Fixture: `registry.json` `lookups`.
- **Local prefixes are lower-cased.** `with_local` stores a declared prefix lower-cased,
  and `canonical` returns the lower-cased form; the declared spelling is not kept as a
  separate form. (`LIT.X` declared gives canonical `lit.x`, and a vocabulary declaration then
  names `lit.x`.)
- **Self-issued schemes.** A `LocalScheme` may carry `issued_by`, the issuing project's
  prefix; its own prefix MUST begin with `issued_by` and a dot (`lit.topic-c` issued by
  `lit`). A violation (`topics.x` by `lit`, bare `lit`, `litter.x`) is `local_collision`,
  raised at construction.
- **Collisions.** `collisions(schemes)` returns, in declaration order and without raising,
  one entry per conflict: kind `shadows_registry` when the prefix (case-insensitively)
  equals a Bioregistry prefix or synonym, kind `repeated` when it equals an already local
  prefix, a shared one included, or one declared earlier in the same call.
  `with_local(schemes)` raises `local_collision` (the details joined) if any exist,
  runs the dialect checker over each declared pattern (`unsupported_pattern` if
  refused), and returns a **new** registry; the receiver is unchanged. Fixture:
  `registry.json` `collisions`. The `issued_by` prefix rule and the pattern check are
  pinned by each suite's unit tests.
- `is_local` / `is_upstream` answer membership (a local scheme is not upstream).

### 4.6 The fingerprint

`registry.version` is the upstream snapshot version. `registry.fingerprint` is the
lower-case hex SHA-256 of the UTF-8 RFC 8785 canonical JSON of the effective registry:

```
{ "version": <registry.version>,
  "schemes": { "<canonical prefix>": { "name", "pattern", "uri_format",
                                       "synonyms", "issued_by", "refused" } } }
```

over **every** scheme: Bioregistry's (refused ones included) after the dialect rewrite,
the shared local schemes, and any added by `with_local`. Absent values are JSON `null`
(`pattern`, `uri_format`, `issued_by`, `refused`); `synonyms` is an array in file order
(empty for a local scheme). `why`, `upstream_pattern` and `rules` are not in the payload,
so a rationale edit does not change the fingerprint but a grammar change does. Object key
order does not matter (RFC 8785 sorts it). The default registry's value is pinned by
`registry.json` `fingerprint`, so both languages must compute the same one.

### 4.7 Vendoring (tier 3)

The tooling that writes the registry is outside the parity contract, but its rules are
recorded here because the dialect's meaning depends on them.
`just registry-vendor <snapshot> <sha256>` runs `tools/vendor_registry.py`: it checks the
snapshot's bytes against the given SHA-256, rewrites every pattern with `refs.rewrite`,
writes `registry/bioregistry.json`, `registry/SOURCES.toml` and
`fixtures/registry.verdicts.json`, then syncs the copies (§4.3). The input is the reduced
form `{source: "bioregistry", version, prefixes: {name, pattern, synonyms, uri_format}}`.
A pattern already in the dialect passes unchanged with no rules. A refresh route from a
Bioregistry package release (`--from-package`) is not implemented yet; it is deferred to
the refresh task that moves to refs.

`rewrite(pattern)` reads Python's regex syntax permissively, limited to what Bioregistry
uses, and emits the dialect. Each rule keeps Python's meaning under full match, except
the recorded ASCII narrowing of `\d`, `\w`, `\s` (a non-ASCII digit no longer matches;
`hgnc:١٢٣` is `malformed`). The rules, by the name recorded in `rules`:

| Rule | Rewrite |
|------|---------|
| `digit-class` | `\d` to `[0-9]` |
| `word-class` | `\w` to `[A-Za-z0-9_]` |
| `space-class` | `\s` to `[\t\n\v\f\r ]`. This drops Python's `\x1c` to `\x1f`; no vendored pattern uses `\s`. Inside a class the shorthand expands to its members (`[\w.]` to `[A-Za-z0-9_.]`) |
| `dot` | `.` to `[^\n]` (Python's meaning) |
| `identity-escape` | an escaped non-syntax character outside a class becomes the bare character (`\-` to `-`, `\_` to `_`) |
| `class-escape` | inside a class, an escaped member other than `\ ] [ ^ -` becomes bare (`[\.\_]` to `[._]`) |
| `class-dash` | a `-` that is not a range operator becomes `\-` (`[-A-Z]` to `[\-A-Z]`) |
| `class-literal` | an unescaped `]`, `[` or non-leading `^` that Python reads as a member is escaped (`[]a]` to `[\]a]`) |
| `syntax-literal` | an unescaped `{` that starts no quantifier, a `}`, or a `]` outside a class is escaped |
| `anchored-alternation` | a top-level `^a$\|^b$` becomes `^(?:a\|b)$` |
| `edge-anchor` | an anchor inside an unquantified group at the pattern's start or end edge is dropped, since under full match it always holds there (sgd: `^((S\d+$)\|(Y...))$` loses the inner `$`) |

**Refused at vendoring** (`unsupported_pattern`; the prefix is stored with a null
`pattern` and a `refused` reason): a negated shorthand `\D \S \W` (its ASCII complement
would accept characters Python refuses); a shorthand inside a negated class (`[^\w]`,
same reason); a shorthand as a range bound; lookaround, named groups, inline flags,
comments, conditionals and atomic groups; backreferences and octal escapes; letter
escapes outside the dialect; a quantified anchor, a possessive quantifier, a repeated
quantifier, `{,n}`; and any rewrite the strict checker still refuses. The current
snapshot refuses 10 prefixes: `biolink`, `ccf`, `d1id`, `gtdb`, `mavedb`, `sphn`, `swh`,
`vectorbase` and `wikipedia.en` (negated shorthand) and `vegbank` (inline flag). No prefix
quarry owns is refused (a suite checks `geo`, `pubmed`, `zenodo.record`, `biostudies`,
`arrayexpress`, `bioproject`, `insdc.sra` and `hgnc`).

`samples(pattern, count, seed)` draws strings a dialect pattern matches, reproducibly
from a seed (a fixed `{m}` repeats exactly m times, an unbounded repeat draws `m` to
`m + 3`, a negated class draws printable ASCII). The vendoring tool uses it, with an
adversarial alphabet (the empty id, `١٢٣`, `Ａ`, a space, `a\rb`, `123\n`, an astral
digit, `-`), to record per-prefix verdicts in `registry.verdicts.json` (§7).

## 5. Vocabularies

A **vocabulary declaration** says a prefix's ids are drawn from a released vocabulary.
Declarations are data a profile holds; refs ships none. The table is
`[vocabularies.<prefix>]` with keys:

| Key | Contract |
|-----|----------|
| `issuer` | `external` or `self`. Required. |
| `release` | the current release: a non-empty string, stamped on newly added references. Required. |
| `accepted` | earlier releases existing references may still carry: a list of non-empty strings, in the order given, default empty. It MUST NOT repeat a release or contain the current release. |

A release is an opaque string compared for equality only (a non-ASCII release is fine).
`parse_vocabularies(table, registry)` returns one `Vocabulary(prefix, issuer, release,
accepted)` per key, in table order; the releases it admits are the current one and the
accepted ones.

Every shape error is kind `invalid_vocabulary`, and parsing stops at the first bad
declaration in table order (a good declaration before a bad one yields no result):

- the prefix MUST be a **canonical** prefix of the supplied registry: an unknown prefix, a
  synonym (`PMID`) and a different case (`HGNC.SYMBOL`) are refused;
- the declaration MUST be a table (a string or a list is refused) with no key outside
  `issuer`, `release`, `accepted`;
- `issuer` and `release` are required; a non-string or empty release, a numeric issuer,
  an issuer other than `external` or `self`, and a non-list or non-string `accepted`
  entry are refused;
- `self` requires an **issued** local scheme (one with `issued_by`): `self` on an
  upstream scheme or on a shared local scheme (`openalex.topic`) is refused, and so is
  `external` on a self-issued scheme.

The Python `load_vocabularies(path, registry)` (tier 3) reads a TOML file that holds a
`[vocabularies]` table and nothing else; invalid TOML or any other top-level key is
`invalid_vocabulary`. Fixture: `vocabularies.json`.

## 6. The `refs/about` facet

The facet name is `refs/about`. A kind composes it by listing it among its facets and
adding the invariant returned by `about_facet(registry, vocabularies)` /
`aboutFacet(registry, vocabularies)`, built from the registry the profile supplies and
its parsed declarations (§5).

**Payload.** `{ "entries": [ {"id": <string>, "release": <string>?}, ... ] }`.

- Unknown keys are refused, at the top level and in each entry. Types are strict: `id` and
  `release` are strings; `release` is never `null` (leave it out for none); `entries` is a
  list; an entry without `id` is refused.
- `entries` MUST be non-empty.
- Each `id` MUST parse (§3.2) against the registry and MUST equal its canonical text:
  `HGNC.SYMBOL:KIF14` parses but is refused, write `hgnc.symbol:KIF14`.
- **Release.** If the id's prefix has a declaration, `release` is required and MUST be the
  declaration's `release` or one of its `accepted`; if it has none, `release` is refused.
  A release belongs to the reference, not the prefix: one prefix may appear at different
  releases in one payload, and the same id may appear at two releases.
- **Order.** Entries are unique by `(id, release)` and strictly sorted by `id`, then
  `release` (absent first), both compared by **Unicode code point**, never UTF-16 code
  unit or locale. A duplicate and a misordered pair are both refused. The fixture pins
  the difference: U+FF21 sorts before U+1D7D9, though a UTF-16 sort puts the astral
  character first.

**Invariant behaviour.** The invariant is a no-op for a node without the facet. Otherwise
it checks the payload shape first, then the entries in order (id, canonical text, release,
then order against the previous entry), and raises nodes' `FacetError` naming the node
and the facet and the **first** violation: `"<node id>: refs/about: <problem>"`. Any
refs refusal while checking an entry (an unparseable id) surfaces as that `FacetError`,
not as a `RefsError`. Only the verdict and the node id plus facet name in the message are
pinned. Fixture: `facet.json`.

**`build_about(entries, registry)` / `buildAbout` (tier 3).** A convenience that returns a
payload from `(id, release-or-none)` pairs: ids canonicalised (an unparseable id raises
its `RefsError`), duplicates dropped, entries sorted as above. It does not check releases
against declarations; the invariant does.

## 7. Conformance fixtures

The shared oracles under `fixtures/` are the conformance suite. Both languages MUST
assert against them, and a tier 1 change lands with its fixtures first.

| Fixture | Pins | Read by |
|---------|------|---------|
| `parse.json` | CURIE parsing over the default registry: cases of `{text, canonical}` or `{text, error}`: case and synonym canonicalisation, `ambiguous_id`, `not_a_curie`, `unknown_prefix`, `malformed` (`HGNC:KIF14`, `hgnc:١٢٣`, a trailing newline), a refused scheme (`vegbank`, `unsupported_pattern`), a scheme with no pattern | `python/tests/test_ids.py`, `ts/tests/parse.test.ts` |
| `dialect.syntax.json` | the dialect grammar: cases of `{pattern, verdict, position?, note}`, each refusal with its code-point position (§2.4), including the quantifier and nesting limits, the reserved class doubles, astral-character positions, and the accepted forms beside them | `python/tests/test_dialect.py`, `ts/tests/dialect.test.ts` |
| `dialect.match.json` | dialect matching: cases of `{pattern, input, match}` over the adversarial alphabet (non-ASCII digits and letters, fullwidth and Kelvin forms, Unicode whitespace, `\r`, trailing `\n`, astral characters, the empty id) | `test_dialect.py`, `dialect.test.ts` |
| `registry.json` | the default registry's `version`, its pinned `fingerprint` (§4.6), `lookups` of `[text, canonical-or-null]`, and `collisions` cases `{schemes, expected}` (§4.5) | `python/tests/test_registry.py`, `ts/tests/registry.test.ts` |
| `registry.verdicts.json` | for every vendored prefix with a pattern, `[input, matched]` pairs over the adversarial alphabet plus samples drawn from the pattern; verdicts recorded from Python and asserted in both, so the two engines agree on every stored pattern. Generated by the vendoring tool, never edited by hand | `python/tests/test_vendored.py`, `ts/tests/verdicts.test.ts` |
| `vocabularies.json` | declaration parsing (§5): `local_schemes` used by the cases, `accepted` tables with their expected result, and `refused` tables (each `invalid_vocabulary`) | `python/tests/test_vocab.py`, `ts/tests/vocab.test.ts` |
| `facet.json` | the facet (§6): the `local_schemes` and `vocabularies` the cases run under, and payloads with verdict `ok` or `refused`: mixed releases under one prefix, the same id at two releases, accepted and unknown releases, a missing or forbidden release, a non-canonical id, ordering and duplicates, malformed shapes, unknown keys, and the code-point ordering pair of releases | `python/tests/test_facet.py`, `ts/tests/facet.test.ts` |

Beyond the fixtures, the suites pin tier 1 rules with unit tests where a fixture row
would not fit (the `issued_by` rule, `with_local` immutability and pattern check, the
`SOURCES.toml` digests, the module boundary, a canonical prefix winning over a synonym).
