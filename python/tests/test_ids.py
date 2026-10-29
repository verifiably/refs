from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from refs import Curie, LocalScheme, RefsError, Registry, Scheme, parse

FIXTURES = Path(__file__).parents[2] / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.default()


@pytest.mark.parametrize("case", load("parse.json"), ids=lambda c: repr(c["text"]))
def test_parse_oracle(case, registry):
    if "error" in case:
        with pytest.raises(RefsError) as e:
            parse(case["text"], registry)
        assert e.value.kind == case["error"]
    else:
        assert str(parse(case["text"], registry)) == case["canonical"]


def test_curie_text_form_and_equality():
    assert str(Curie("geo", "GSE1")) == "geo:GSE1"
    assert Curie("geo", "GSE1") == Curie("geo", "GSE1")
    with pytest.raises(AttributeError):
        Curie("geo", "GSE1").local = "x"  # type: ignore[misc]


def test_the_local_id_is_kept_as_given(registry):
    assert parse("figshare:0012", registry) == Curie("figshare", "0012")


def test_local_schemes_parse_after_with_local():
    reg = Registry.default().with_local([LocalScheme("lit.x", "x", "^[0-9]+$", None, "test", "lit")])
    assert parse("LIT.X:12", reg) == Curie("lit.x", "12")
    with pytest.raises(RefsError) as e:
        parse("lit.x:abc", reg)
    assert e.value.kind == "malformed"


def test_scheme_without_a_pattern_accepts_any_local_id(registry):
    scheme = registry.scheme("aaindex")
    assert scheme.pattern is None and scheme.matches("whatever: this is")


def test_scheme_matches_is_a_full_match(registry):
    scheme = registry.scheme("hgnc")
    assert scheme.matches("6390")
    assert not scheme.matches("6390\n")
    assert not scheme.matches("١٢٣")
    assert not scheme.matches("")


def test_refused_scheme_refuses_every_local_id(registry):
    scheme = registry.scheme("vegbank")
    assert scheme.refused is not None and scheme.pattern is None
    with pytest.raises(RefsError) as e:
        scheme.matches("anything")
    assert e.value.kind == "unsupported_pattern"


def test_scheme_is_frozen_data():
    scheme = Scheme("p", "P", None, None, (), None, None)
    with pytest.raises(AttributeError):
        scheme.name = "x"  # type: ignore[misc]


def test_identifier_modules_do_not_import_nodes(tmp_path):
    code = (
        "import refs.ids, refs.registry, refs.dialect, refs.vocab, sys; "
        "assert not any(m == 'nodes' or m.startswith('nodes.') for m in sys.modules), 'nodes imported'"
    )
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path)}
    done = subprocess.run(
        [sys.executable, "-I", "-c", code], check=False, env=env, capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr


def test_every_shared_local_scheme_is_in_the_default_registry(registry):
    shared = tomllib.loads((FIXTURES.parent / "registry" / "local-schemes.toml").read_text(encoding="utf-8"))["schemes"]
    assert set(shared) == {"openalex.topic", "figshare"}
    for prefix, body in shared.items():
        scheme = registry.scheme(prefix)
        assert (scheme.name, scheme.pattern, scheme.uri_format) == (body["name"], body["pattern"], body["uri_format"])
        assert scheme.issued_by is None and scheme.synonyms == () and scheme.refused is None
        assert registry.is_local(prefix) and not registry.is_upstream(prefix)
