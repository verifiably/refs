from __future__ import annotations

import json
from pathlib import Path

import pytest

from refs import Collision, LocalScheme, RefsError, Registry

FIXTURES = Path(__file__).parents[2] / "fixtures"
ORACLE = json.loads((FIXTURES / "registry.json").read_text(encoding="utf-8"))
DEFAULT = Registry.default()


def _scheme(spec: dict) -> LocalScheme:
    return LocalScheme(spec["prefix"], "x", None, None, "test", spec.get("issued_by"))


def test_version_is_the_upstream_snapshot_version():
    assert DEFAULT.version == ORACLE["version"]


def test_lookup_oracle():
    for text, canonical in ORACLE["lookups"]:
        assert DEFAULT.canonical(text) == canonical, text


def test_fingerprint_is_pinned():
    assert DEFAULT.fingerprint == ORACLE["fingerprint"]


def test_fingerprint_is_stable_across_loads():
    assert Registry.default().fingerprint == DEFAULT.fingerprint


def test_fingerprint_changes_with_local_schemes():
    reg = DEFAULT.with_local([LocalScheme("lit.x", "x", "^[0-9]+$", None, "test", "lit")])
    assert reg.fingerprint != DEFAULT.fingerprint


def test_fingerprint_depends_on_the_scheme_fields():
    a = DEFAULT.with_local([LocalScheme("lit.x", "x", "^[0-9]+$", None, "test", "lit")])
    assert a.fingerprint != DEFAULT.with_local([LocalScheme("lit.x", "x", "^[0-9]*$", None, "test", "lit")]).fingerprint
    assert a.fingerprint != DEFAULT.with_local([LocalScheme("lit.x", "y", "^[0-9]+$", None, "test", "lit")]).fingerprint


def test_why_is_not_part_of_the_fingerprint():
    a = DEFAULT.with_local([LocalScheme("lit.x", "x", None, None, "one", "lit")])
    b = DEFAULT.with_local([LocalScheme("lit.x", "x", None, None, "two", "lit")])
    assert a.fingerprint == b.fingerprint


def test_with_local_does_not_change_the_receiver():
    DEFAULT.with_local([LocalScheme("lit.x", "x", None, None, "test", "lit")])
    assert DEFAULT.canonical("lit.x") is None and not DEFAULT.is_local("lit.x")


@pytest.mark.parametrize(
    "case", ORACLE["collisions"], ids=lambda c: ",".join(s["prefix"] for s in c["schemes"]) or "none"
)
def test_collisions_oracle(case):
    found = DEFAULT.collisions([_scheme(s) for s in case["schemes"]])
    assert [(c.prefix, c.kind) for c in found] == [tuple(e) for e in case["expected"]]
    assert all(isinstance(c, Collision) and c.detail for c in found)
    if found:
        with pytest.raises(RefsError) as e:
            DEFAULT.with_local([_scheme(s) for s in case["schemes"]])
        assert e.value.kind == "local_collision"
    else:
        DEFAULT.with_local([_scheme(s) for s in case["schemes"]])


def test_with_local_raises_on_collision():
    with pytest.raises(RefsError) as e:
        DEFAULT.with_local([LocalScheme("geo", "g", None, None, "x")])
    assert e.value.kind == "local_collision"


def test_with_local_twice_repeats_a_prefix():
    reg = DEFAULT.with_local([LocalScheme("lit.x", "x", None, None, "x", "lit")])
    assert [c.kind for c in reg.collisions([LocalScheme("lit.x", "x", None, None, "x", "lit")])] == ["repeated"]


def test_issued_by_requires_its_prefix():
    with pytest.raises(RefsError) as e:
        LocalScheme("topics.x", "x", None, None, "x", issued_by="lit")
    assert e.value.kind == "local_collision"
    with pytest.raises(RefsError):
        LocalScheme("lit", "x", None, None, "x", issued_by="lit")
    with pytest.raises(RefsError):
        LocalScheme("litter.x", "x", None, None, "x", issued_by="lit")
    with pytest.raises(RefsError):  # compared case-sensitively, before lower-casing
        LocalScheme("LIT.x", "x", None, None, "x", issued_by="lit")


def test_local_pattern_outside_dialect_is_refused():
    with pytest.raises(RefsError) as e:
        DEFAULT.with_local([LocalScheme("lit.x", "x", r"^\d+$", None, "x", "lit")])
    assert e.value.kind == "unsupported_pattern"


def test_local_prefix_is_canonicalized_without_replacing_an_alias():
    reg = DEFAULT.with_local([LocalScheme("Lit.X", "x", None, None, "x", "Lit")])
    assert reg.is_local("Lit.X") and reg.is_local("lit.x")
    assert reg.scheme("lit.x").prefix == "lit.x"
    assert reg.canonical("LIT.X") == "lit.x"
    assert reg.scheme("lit.x").issued_by == "Lit"  # stored as declared


def test_upstream_and_local_membership():
    assert DEFAULT.is_upstream("geo") and not DEFAULT.is_local("geo")
    assert DEFAULT.is_local("figshare") and not DEFAULT.is_upstream("figshare")
    assert DEFAULT.is_local("FigShare")
    assert not DEFAULT.is_upstream("nope") and not DEFAULT.is_local("nope")
    reg = DEFAULT.with_local([LocalScheme("lit.x", "x", None, None, "x", "lit")])
    assert reg.is_local("lit.x") and not reg.is_upstream("lit.x")
    assert reg.scheme("lit.x").issued_by == "lit"


def test_scheme_of_an_unknown_prefix_is_refused():
    with pytest.raises(RefsError) as e:
        DEFAULT.scheme("nope")
    assert e.value.kind == "unknown_prefix"


def test_canonical_prefix_wins_over_a_synonym():
    doc = {
        "version": "t",
        "prefixes": {
            "first": {"name": "First", "pattern": None, "uri_format": None, "synonyms": ["SECOND"]},
            "second": {"name": "Second", "pattern": None, "uri_format": None, "synonyms": []},
        },
    }
    reg = Registry.from_document(doc)
    assert reg.canonical("second") == "second" and reg.canonical("SECOND") == "second"
    assert reg.canonical("first") == "first"


GOOD_TABLE = {"name": "N", "pattern": "^[0-9]+$", "uri_format": "https://x/$1", "why": "w"}


def test_shared_local_schemes_table_is_read_into_local_schemes():
    from refs.registry import local_schemes_from_table

    [scheme] = local_schemes_from_table({"x.y": GOOD_TABLE})
    assert scheme == LocalScheme("x.y", "N", "^[0-9]+$", "https://x/$1", "w")


@pytest.mark.parametrize("key", ["name", "pattern", "uri_format", "why"])
def test_shared_local_scheme_refuses_a_missing_key(key):
    from refs.registry import local_schemes_from_table

    body = {k: v for k, v in GOOD_TABLE.items() if k != key}
    with pytest.raises(ValueError, match=f"x.y.*{key}"):
        local_schemes_from_table({"x.y": body})


@pytest.mark.parametrize("key", ["name", "pattern", "uri_format", "why"])
@pytest.mark.parametrize("value", [1, None, ["a"]])
def test_shared_local_scheme_refuses_a_non_string_value(key, value):
    from refs.registry import local_schemes_from_table

    with pytest.raises(ValueError, match=f"x.y.*{key}"):
        local_schemes_from_table({"x.y": {**GOOD_TABLE, key: value}})


def test_shared_local_scheme_refuses_an_unknown_key():
    from refs.registry import local_schemes_from_table

    with pytest.raises(ValueError, match="x.y.*extra"):
        local_schemes_from_table({"x.y": {**GOOD_TABLE, "extra": "1"}})


def test_shared_local_scheme_refuses_a_non_table():
    from refs.registry import local_schemes_from_table

    with pytest.raises(ValueError, match="x.y"):
        local_schemes_from_table({"x.y": "text"})


def test_missing_data_names_the_sync_recipe(monkeypatch, tmp_path):
    # The data copy is gitignored; a fresh checkout that skipped `just registry-sync` lacks it.
    import refs.registry

    monkeypatch.setattr(refs.registry.resources, "files", lambda _package: tmp_path)
    with pytest.raises(FileNotFoundError, match="just registry-sync"):
        refs.registry._data("bioregistry.json")


def test_europepmc_scheme_preserves_provider_identity():
    scheme = DEFAULT.scheme("europepmc")
    assert (scheme.prefix, scheme.name, scheme.pattern, scheme.uri_format) == (
        "europepmc", "Europe PMC record", r"^[A-Z]+/[A-Za-z0-9][A-Za-z0-9._\-]*$",
        "https://europepmc.org/article/$1",
    )
    assert scheme.synonyms == () and scheme.issued_by is None
