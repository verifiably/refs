from __future__ import annotations

import json
import random
import re
import zlib
from pathlib import Path

import pytest

from refs import RefsError, check_pattern, compile_pattern
from refs.rewrite import Rewritten, rewrite, samples

REGISTRY = Path(__file__).parents[2] / "registry"


@pytest.mark.parametrize("upstream, dialect", [
    (r"^\d{1,5}$", "^[0-9]{1,5}$"),
    (r"^\w+$", "^[A-Za-z0-9_]+$"),
    (r"^\s$", r"^[\t\n\v\f\r ]$"),
    (r"^a.b$", r"^a[^\n]b$"),
    (r"^a\-b$", "^a-b$"),
    (r"^a\_b\:c\@d$", "^a_b:c@d$"),
    (r"^[\.\_]$", "^[._]$"),
    (r"^[A-Za-z-0-9_]+(\@)?$", r"^[A-Za-z\-0-9_]+(@)?$"),   # hgnc.symbol
    (r"^[-A-Z]$", r"^[\-A-Z]$"),
    (r"^[]a]$", r"^[\]a]$"),
    ("^a{$", r"^a\{$"),
    (r"^[0-9]{5}(-[a-z]{0,7})?$|^[0-9]{10}$", "^(?:[0-9]{5}(-[a-z]{0,7})?|[0-9]{10})$"),  # addgene
    (r"^[\w.]+$", r"^[A-Za-z0-9_.]+$"),
    (r"^[\w^_]$", r"^[A-Za-z0-9_\^_]$"),                     # envipath: ^ not first is a literal
    (r"^[a\$]\/$", r"^[a$]\/$"),                             # \/ is in the dialect outside a class
    (r"^((S\d+$)|(Y[A-Z]))$", "^((S[0-9]+)|(Y[A-Z]))$"),     # sgd: a $ at the pattern's end edge
    (r"^a}$", r"^a\}$"),
])
def test_rewrite(upstream, dialect):
    out = rewrite(upstream)
    assert out.pattern == dialect
    check_pattern(out.pattern)


def test_rewrite_records_its_rules():
    assert rewrite(r"^\d.\-$") == Rewritten("^[0-9][^\\n]-$", ("digit-class", "dot", "identity-escape"))
    assert rewrite(r"^a$|^b$").rules == ("anchored-alternation",)


def test_a_pattern_already_in_the_dialect_is_unchanged():
    assert rewrite(r"^[0-9]+\/x$") == Rewritten(r"^[0-9]+\/x$", ())


@pytest.mark.parametrize("upstream", [
    r"^(?i:ab)$", r"^\S+$", r"^\D{4}$", r"^\W$", r"^[\S]$", r"^(?=a)a$",
    r"^(a$)+$", r"^a$|b", r"^(?P<x>a)$", r"^a\b$", r"^\1$", r"^a{,3}$", r"^a++$", r"^[&&]$",
    r"^[^\w]$", r"^[^\d]$", r"^[^\s]$",   # a shorthand in a negated class would widen, like \W \D \S
])
def test_unrewritable(upstream):
    with pytest.raises(RefsError) as e:
        rewrite(upstream)
    assert e.value.kind == "unsupported_pattern"


@pytest.mark.parametrize("p", ["^[0-9]{1,5}$", "^(?:ab|c)+[x-z]?$", "^a?$", "^[a-z]{4}$", "^[0-9]{2,3}$", "^b*c{0,1}$",
                               r"^[^\n]+$", "^[^A-Z]{2}$"])
def test_samples_match_their_pattern(p):
    assert all(compile_pattern(p).fullmatch(s) for s in samples(p, 50, seed=1))


def test_fixed_count_samples_have_that_length():
    assert {len(s) for s in samples("^[a-z]{4}$", 50, seed=2)} == {4}


def test_samples_are_seeded():
    assert samples("^[a-z]+$", 10, seed=3) == samples("^[a-z]+$", 10, seed=3)


def _printable(rng: random.Random) -> str:
    return "".join(chr(rng.randint(0x20, 0x7E)) for _ in range(rng.randint(0, 12)))


def test_rewrite_keeps_python_meaning_on_ascii():
    # For every rewritten registry pattern, the upstream pattern and its rewrite agree on
    # printable-ASCII samples drawn from both: the only narrowing is non-ASCII (spec §5.2).
    prefixes = json.loads((REGISTRY / "bioregistry.json").read_text(encoding="utf-8"))["prefixes"]
    rewritten = {p: s for p, s in prefixes.items() if s["rules"]}
    assert rewritten
    for prefix, scheme in sorted(rewritten.items()):
        seed = zlib.crc32(prefix.encode())
        rng = random.Random(seed)
        inputs = samples(scheme["pattern"], 8, seed) + [_printable(rng) for _ in range(8)]
        upstream, dialect = re.compile(scheme["upstream_pattern"]), compile_pattern(scheme["pattern"])
        for s in inputs:
            assert bool(upstream.fullmatch(s)) is bool(dialect.fullmatch(s)), (prefix, s)
