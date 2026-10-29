from __future__ import annotations

import json
from pathlib import Path

import pytest
from nodes.core.errors import FacetError
from nodes.core.node import Node

from refs import LocalScheme, RefsError, Registry
from refs.facet import FACET, about_facet, build_about
from refs.vocab import parse_vocabularies

FIXTURES = Path(__file__).parents[2] / "fixtures"
DOC = json.loads((FIXTURES / "facet.json").read_text(encoding="utf-8"))
REG = Registry.default().with_local([LocalScheme(**s) for s in DOC["local_schemes"]])
VOCABULARIES = parse_vocabularies(DOC["vocabularies"], REG)
INVARIANT = about_facet(REG, VOCABULARIES)


def node(facets: dict) -> Node:
    return Node(id="topic:t", kind="topic", title="t", facets=facets)


@pytest.mark.parametrize("case", DOC["cases"], ids=lambda c: c["name"])
def test_facet_oracle(case):
    n = node({FACET: case["payload"]})
    if case["verdict"] == "ok":
        INVARIANT(n)
    else:
        with pytest.raises(FacetError) as e:
            INVARIANT(n)
        assert "topic:t" in str(e.value) and FACET in str(e.value)


def test_facet_name():
    assert FACET == "refs/about"


def test_a_node_without_the_facet_is_not_checked():
    INVARIANT(node({}))
    INVARIANT(node({"other": {"anything": 1}}))


def test_error_names_the_first_violation():
    payload = {"entries": [{"id": "mesh:D009101", "release": "x"}, {"id": "KIF14"}]}
    with pytest.raises(FacetError) as e:
        INVARIANT(node({FACET: payload}))
    assert "mesh:D009101" in str(e.value) and "KIF14" not in str(e.value)


def test_build_about_canonicalises_and_orders():
    payload = build_about([("PMID:2", None), ("pubmed:1", None), ("pmid:2", None)], REG)
    assert payload == {"entries": [{"id": "pubmed:1"}, {"id": "pubmed:2"}]}


def test_build_about_keeps_releases_and_orders_by_code_point():
    payload = build_about(
        [("chebi:15377", "\U0001d7d9"), ("chebi:15377", "Ａ"), ("HGNC.SYMBOL:KIF14", "2026-07-01")], REG
    )
    assert payload == {
        "entries": [
            {"id": "chebi:15377", "release": "Ａ"},
            {"id": "chebi:15377", "release": "\U0001d7d9"},
            {"id": "hgnc.symbol:KIF14", "release": "2026-07-01"},
        ]
    }
    INVARIANT(node({FACET: payload}))


def test_build_about_refuses_an_unparseable_id():
    with pytest.raises(RefsError) as e:
        build_about([("KIF14", None)], REG)
    assert e.value.kind == "ambiguous_id"


def test_build_about_does_not_check_releases():
    assert build_about([("mesh:D009101", "anything")], REG) == {
        "entries": [{"id": "mesh:D009101", "release": "anything"}]
    }
