from __future__ import annotations

import json
from pathlib import Path

import pytest

from refs import LocalScheme, RefsError, Registry
from refs.vocab import Vocabulary, load_vocabularies, parse_vocabularies

FIXTURES = Path(__file__).parents[2] / "fixtures"
DOC = json.loads((FIXTURES / "vocabularies.json").read_text(encoding="utf-8"))
REG = Registry.default().with_local(
    [LocalScheme(s["prefix"], s["name"], s["pattern"], s["uri_format"], s["why"], s["issued_by"]) for s in DOC["local_schemes"]]
)


def test_vocabularies_oracle_accepted():
    for case in DOC["accepted"]:
        expected = {
            prefix: Vocabulary(prefix, v["issuer"], v["release"], tuple(v["accepted"]))
            for prefix, v in case["expected"].items()
        }
        assert parse_vocabularies(case["table"], REG) == expected, case["name"]


@pytest.mark.parametrize("case", DOC["refused"], ids=lambda c: c["name"])
def test_vocabularies_oracle_refused(case):
    with pytest.raises(RefsError) as e:
        parse_vocabularies(case["table"], REG)
    assert e.value.kind == "invalid_vocabulary"


def test_vocabulary_is_frozen():
    with pytest.raises(AttributeError):
        Vocabulary("a", "external", "r", ()).release = "x"  # type: ignore[misc]


def test_releases_are_the_current_and_the_accepted():
    assert Vocabulary("a", "external", "c", ("b", "a")).releases == {"a", "b", "c"}


def test_load_vocabularies_reads_toml(tmp_path):
    path = tmp_path / "vocab.toml"
    path.write_text('[vocabularies."hgnc.symbol"]\nissuer = "external"\nrelease = "2026-07-01"\n', encoding="utf-8")
    assert load_vocabularies(path, REG) == {"hgnc.symbol": Vocabulary("hgnc.symbol", "external", "2026-07-01", ())}


@pytest.mark.parametrize("text", ["", "[other]\nx = 1\n", "[vocabularies]\n[x\n", "[vocabularies]\n[extra]\n"])
def test_load_vocabularies_refuses_a_file_that_is_not_a_vocabularies_table(tmp_path, text):
    path = tmp_path / "vocab.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(RefsError) as e:
        load_vocabularies(path, REG)
    assert e.value.kind == "invalid_vocabulary"

