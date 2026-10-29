from __future__ import annotations

import pytest

from refs import LocalScheme, RefsError, Registry
from refs.vocab import Vocabulary, load_vocabularies, parse_vocabularies

REG = Registry.default().with_local([LocalScheme("lit.topic-c", "topic", "^[A-Z]+$", None, "test", "lit")])


def test_parse_vocabularies_reads_the_spec_example():
    table = {
        "hgnc.symbol": {"issuer": "external", "release": "2026-07-01", "accepted": ["2026-04-01"]},
        "openalex.topic": {"issuer": "external", "release": "2026-06-26"},
        "lit.topic-c": {"issuer": "self", "release": "run:1"},
    }
    assert parse_vocabularies(table, REG) == {
        "hgnc.symbol": Vocabulary("hgnc.symbol", "external", "2026-07-01", ("2026-04-01",)),
        "openalex.topic": Vocabulary("openalex.topic", "external", "2026-06-26", ()),
        "lit.topic-c": Vocabulary("lit.topic-c", "self", "run:1", ()),
    }


def test_vocabulary_is_frozen():
    with pytest.raises(AttributeError):
        Vocabulary("a", "external", "r", ()).release = "x"  # type: ignore[misc]


@pytest.mark.parametrize(
    "table",
    [
        {"hgnc.symbol": {"issuer": "external", "release": ""}},
        {"hgnc.symbol": {"issuer": "external", "release": 1}},
        {"hgnc.symbol": {"issuer": "external"}},
        {"hgnc.symbol": {"release": "a"}},
        {"hgnc.symbol": {"issuer": "other", "release": "a"}},
        {"hgnc.symbol": {"issuer": "external", "release": "a", "accepted": ["b", "b"]}},
        {"hgnc.symbol": {"issuer": "external", "release": "a", "accepted": ["a"]}},
        {"hgnc.symbol": {"issuer": "external", "release": "a", "accepted": [""]}},
        {"hgnc.symbol": {"issuer": "external", "release": "a", "accepted": "b"}},
        {"hgnc.symbol": {"issuer": "self", "release": "a"}},  # self needs a self-issued local scheme
        {"openalex.topic": {"issuer": "self", "release": "a"}},  # local, but not self-issued
        {"lit.topic-c": {"issuer": "external", "release": "a"}},  # self-issued, declared external
        {"nope": {"issuer": "external", "release": "a"}},  # unknown prefix
        {"HGNC.SYMBOL": {"issuer": "external", "release": "a"}},  # not the canonical spelling
        {"hgnc.symbol": {"issuer": "external", "release": "a", "extra": 1}},
        {"hgnc.symbol": "external"},
    ],
)
def test_vocabulary_refusals(table):
    with pytest.raises(RefsError) as e:
        parse_vocabularies(table, REG)
    assert e.value.kind == "invalid_vocabulary"


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

