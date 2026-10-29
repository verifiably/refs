from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

from refs import check_pattern, compile_pattern

ROOT = Path(__file__).parents[2]
REGISTRY = ROOT / "registry"

# Prefixes quarry's catalog owns or names as facet namespaces; spec §5.2 forbids refusing them.
QUARRY_PREFIXES = {"geo", "pubmed", "zenodo.record", "biostudies", "arrayexpress", "bioproject", "insdc.sra", "hgnc"}


def _prefixes() -> dict[str, dict]:
    return json.loads((REGISTRY / "bioregistry.json").read_text(encoding="utf-8"))["prefixes"]


def _sources() -> dict:
    return tomllib.loads((REGISTRY / "SOURCES.toml").read_text(encoding="utf-8"))


def test_verdict_oracle():
    prefixes = _prefixes()
    verdicts = json.loads((ROOT / "fixtures" / "registry.verdicts.json").read_text(encoding="utf-8"))
    assert set(verdicts) == {p for p, s in prefixes.items() if s["pattern"] is not None}
    for prefix, cases in verdicts.items():
        compiled = compile_pattern(prefixes[prefix]["pattern"])
        assert cases
        for text, matched in cases:
            assert bool(compiled.fullmatch(text)) is matched, (prefix, text)


def test_sources_record_the_written_file_and_its_refusals():
    sources = _sources()
    record = sources["bioregistry"]
    assert record["sha256"] == hashlib.sha256((REGISTRY / record["file"]).read_bytes()).hexdigest()
    assert record["upstream_sha256"] == "5e37b760a1ca7f65ab02b5f3f7402a4961b7a162687678a718453d5c6de9fe01"
    refused = {p: s["refused"] for p, s in _prefixes().items() if "refused" in s}
    assert sources["refused"] == refused


def test_every_stored_pattern_is_in_the_dialect():
    for scheme in _prefixes().values():
        if scheme["pattern"] is not None:
            check_pattern(scheme["pattern"])
        if "refused" in scheme:
            assert scheme["pattern"] is None and scheme["upstream_pattern"] is not None


def test_no_quarry_prefix_is_refused():
    prefixes = _prefixes()
    for prefix in QUARRY_PREFIXES:
        assert prefixes[prefix]["pattern"] is not None, prefix


def test_local_schemes_are_in_the_dialect_and_new():
    schemes = tomllib.loads((REGISTRY / "local-schemes.toml").read_text(encoding="utf-8"))["schemes"]
    assert set(schemes) == {"openalex.topic", "figshare"}
    taken = {name.lower() for p, s in _prefixes().items() for name in (p, *s["synonyms"])}
    for prefix, scheme in schemes.items():
        assert prefix.lower() not in taken
        check_pattern(scheme["pattern"])
        assert scheme["name"] and scheme["uri_format"] and scheme["why"]
