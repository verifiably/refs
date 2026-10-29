from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from refs import RefsError, check_pattern, compile_pattern, parse_pattern
from refs.dialect import Alt, Anchor, Class, Group, Lit, Range, Repeat, Seq

FIXTURES = Path(__file__).parents[2] / "fixtures"


def load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _pattern_id(case: dict) -> str:
    text = repr(case["pattern"])
    return text if len(text) <= 40 else f"{text[:30]}...len{len(case['pattern'])}"


SYNTAX = load("dialect.syntax.json")
MATCH = load("dialect.match.json")
ACCEPTED = [case for case in SYNTAX if case["verdict"] == "ok"]


@pytest.mark.parametrize("case", SYNTAX, ids=_pattern_id)
def test_syntax_oracle(case):
    if case["verdict"] == "ok":
        check_pattern(case["pattern"])
    else:
        with pytest.raises(RefsError) as e:
            check_pattern(case["pattern"])
        assert (e.value.kind, e.value.position) == ("unsupported_pattern", case["position"])


@pytest.mark.parametrize("case", MATCH, ids=lambda c: f"{_pattern_id(c)}~{c['input']!r}")
def test_match_oracle(case):
    assert bool(compile_pattern(case["pattern"]).fullmatch(case["input"])) is case["match"]


@pytest.mark.parametrize("case", ACCEPTED, ids=_pattern_id)
def test_accepted_patterns_compile_and_parse(case):
    assert isinstance(compile_pattern(case["pattern"]), re.Pattern)
    parse_pattern(case["pattern"])


@pytest.mark.parametrize("case", [c for c in SYNTAX if c["verdict"] != "ok"], ids=_pattern_id)
def test_parse_pattern_refuses_what_check_refuses(case):
    with pytest.raises(RefsError) as e:
        parse_pattern(case["pattern"])
    assert (e.value.kind, e.value.position) == ("unsupported_pattern", case["position"])


def test_fixture_files_cover_required_cases():
    refused = {c["pattern"]: c["position"] for c in SYNTAX if c["verdict"] != "ok"}
    for pattern, position in {
        "[]]": 1, "[^]": 2, "[]": 1, "{": 0, "a{": 1, "\\x41": 0, "\\u0041": 0, "\\1": 0,
        "(?i)ab": 1, "^\\-$": 1, "(?=a)": 1, "\\d": 0, ".": 0, "a^b": 1,
    }.items():
        assert refused[pattern] == position
    accepted = {c["pattern"] for c in ACCEPTED}
    assert {"^-$", "^[\\-]$", "^[\\]]$", "^[A-Za-z0-9_]{1,5}$", "^(?:ab|cd)+?$", "^[^\\n]$",
            "^[\\t\\n\\v\\f\\r ]$", "^\\.\\{\\}\\/$"} <= accepted


def test_unsupported_pattern_error_shape():
    with pytest.raises(RefsError) as e:
        check_pattern("a{")
    assert e.value.kind == "unsupported_pattern"
    assert e.value.position == 1
    assert e.value.detail
    assert "unsupported_pattern" in str(e.value)


def test_engine_error_after_a_clean_check_is_invalid_pattern(monkeypatch):
    def refuse(pattern):
        raise re.error("forced")

    monkeypatch.setattr(re, "compile", refuse)
    with pytest.raises(RefsError) as e:
        compile_pattern("a")
    assert (e.value.kind, e.value.position) == ("invalid_pattern", None)


def test_dialect_nodes_are_not_reexported():
    import refs

    assert not hasattr(refs, "Lit")
    assert refs.Ast is Alt


def test_parse_pattern_returns_a_structure():
    ast = parse_pattern("^(?:ab|c)+?[^x-z]$")
    assert ast == Alt((
        Seq((
            Anchor("start"),
            Repeat(
                Group(False, Alt((Seq((Lit("a"), Lit("b"))), Seq((Lit("c"),))))),
                1, None, True,
            ),
            Class(True, (Range("x", "z"),)),
            Anchor("end"),
        )),
    ))


def test_parse_pattern_resolves_escapes_to_code_points():
    ast = parse_pattern(r"\.[\t\-]")
    assert ast == Alt((Seq((Lit("."), Class(False, (Range("\t", "\t"), Range("-", "-"))))),))
