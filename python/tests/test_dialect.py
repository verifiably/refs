from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from refs import RefsError, check_pattern, compile_pattern, parse_pattern
from refs.dialect import _Alt, _Anchor, _Class, _Group, _Lit, _Range, _Repeat, _Seq

FIXTURES = Path(__file__).parents[2] / "fixtures"


def load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


SYNTAX = load("dialect.syntax.json")
MATCH = load("dialect.match.json")
ACCEPTED = [case for case in SYNTAX if case["verdict"] == "ok"]


@pytest.mark.parametrize("case", SYNTAX, ids=lambda c: repr(c["pattern"]))
def test_syntax_oracle(case):
    if case["verdict"] == "ok":
        check_pattern(case["pattern"])
    else:
        with pytest.raises(RefsError) as e:
            check_pattern(case["pattern"])
        assert (e.value.kind, e.value.position) == ("unsupported_pattern", case["position"])


@pytest.mark.parametrize("case", MATCH, ids=lambda c: f"{c['pattern']!r}~{c['input']!r}")
def test_match_oracle(case):
    assert bool(compile_pattern(case["pattern"]).fullmatch(case["input"])) is case["match"]


@pytest.mark.parametrize("case", ACCEPTED, ids=lambda c: repr(c["pattern"]))
def test_accepted_patterns_compile_and_parse(case):
    assert isinstance(compile_pattern(case["pattern"]), re.Pattern)
    parse_pattern(case["pattern"])


@pytest.mark.parametrize("case", [c for c in SYNTAX if c["verdict"] != "ok"], ids=lambda c: repr(c["pattern"]))
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


def test_compile_error_after_a_clean_check_is_invalid_pattern():
    # The grammar accepts a repetition count larger than Python's limit; the engine refuses it.
    check_pattern("a{4294967296}")
    with pytest.raises(RefsError) as e:
        compile_pattern("a{4294967296}")
    assert e.value.kind == "invalid_pattern"


def test_parse_pattern_returns_a_structure():
    ast = parse_pattern("^(?:ab|c)+?[^x-z]$")
    assert ast == _Alt((
        _Seq((
            _Anchor("start"),
            _Repeat(
                _Group(False, _Alt((_Seq((_Lit("a"), _Lit("b"))), _Seq((_Lit("c"),))))),
                1, None, True,
            ),
            _Class(True, (_Range("x", "z"),)),
            _Anchor("end"),
        )),
    ))


def test_parse_pattern_resolves_escapes_to_code_points():
    ast = parse_pattern(r"\.[\t\-]")
    assert ast == _Alt((_Seq((_Lit("."), _Class(False, (_Range("\t", "\t"), _Range("-", "-"))))),))
