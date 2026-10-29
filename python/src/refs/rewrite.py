"""Vendoring-time rewriting of upstream patterns into the dialect, and sample generation.

`rewrite` reads a pattern with a permissive reader of Python's regex syntax, limited to the
constructs Bioregistry uses, and emits it in the dialect (spec section 5.2). It is a
different grammar from `refs.dialect`'s strict one: it accepts what Python accepts and
decides, construct by construct, whether the dialect can say the same thing. Every rule it
applies keeps Python's meaning under full match, except the recorded ASCII narrowing of
`\\d`, `\\w` and `\\s` in a positive context. Negated forms (`\\D`, `\\S`, `\\W`, and a
shorthand inside `[^...]`) would widen instead, so they are refused. A construct with no
dialect form raises `unsupported_pattern`, and so does a rewrite the strict checker still
refuses.

Rules, by the name recorded in `Rewritten.rules`:

    digit-class           \\d to [0-9]
    word-class            \\w to [A-Za-z0-9_]
    space-class           \\s to [\\t\\n\\v\\f\\r ]
    dot                   . to [^\\n]
    identity-escape       an escaped non-syntax character outside a class to the bare character
    class-escape          an escaped class member other than \\ ] [ ^ - to the bare character
    class-dash            a - that is not a range operator to \\- inside a class
    class-literal         an unescaped ] [ or ^ that Python reads as a class member, escaped
    syntax-literal        an unescaped { } or ] that Python reads as a literal, escaped
    anchored-alternation  ^a$|^b$ at the top level to ^(?:a|b)$
    edge-anchor           an anchor inside an unquantified group at the pattern's edge, dropped
                          (under full match it always holds there)

`samples` walks the strict dialect AST and draws strings the pattern matches.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from refs.dialect import Alt, Anchor, Class, Group, Lit, Repeat, Seq, check_pattern, parse_pattern
from refs.errors import RefsError

_OUTSIDE_KEPT = frozenset("\\^$.|?*+()[]{}/")  # escapes outside a class that the dialect has
_CLASS_KEPT = frozenset("\\][^-")  # escapes inside a class that the dialect has
_CONTROL = {"t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r"}
_SHORTHAND = {"d": ("0-9", "digit-class"), "w": ("A-Za-z0-9_", "word-class"), "s": ("\\t\\n\\v\\f\\r ", "space-class")}
_NEGATED_SHORTHAND = frozenset("DSW")
_ASCII_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_DIGITS = frozenset("0123456789")
_PRINTABLE = [chr(c) for c in range(0x20, 0x7F)]
_WIDENS = "has no dialect form: its ASCII complement would accept non-ASCII characters Python refuses"


@dataclass(frozen=True, slots=True)
class Rewritten:
    pattern: str
    rules: tuple[str, ...]


# The reader's tree. An atom carries its dialect spelling; groups and anchors keep structure
# so the anchor rules can see where they sit.


@dataclass(slots=True)
class _Atom:
    text: str
    quantifier: str = ""


@dataclass(slots=True)
class _Anchor:
    kind: str  # "^" or "$"


@dataclass(slots=True)
class _Group:
    opener: str  # "(" or "(?:"
    branches: list[list[_Item]]
    quantifier: str = ""


_Item = _Atom | _Anchor | _Group


def _refuse(detail: str, position: int | None) -> RefsError:
    return RefsError("unsupported_pattern", detail, position)


class _Reader:
    def __init__(self, text: str) -> None:
        self.text = text
        self.n = len(text)
        self.i = 0
        self.rules: set[str] = set()

    def peek(self, offset: int = 0) -> str | None:
        j = self.i + offset
        return self.text[j] if j < self.n else None

    def read(self) -> list[list[_Item]]:
        branches = self.alternation(depth=0)
        if self.i < self.n:
            raise _refuse("unbalanced )", self.i)
        return branches

    def alternation(self, depth: int) -> list[list[_Item]]:
        branches = [self.sequence(depth)]
        while self.peek() == "|":
            self.i += 1
            branches.append(self.sequence(depth))
        return branches

    def sequence(self, depth: int) -> list[_Item]:
        items: list[_Item] = []
        while True:
            c = self.peek()
            if c is None or c == "|" or (c == ")" and depth > 0):
                return items
            if c == ")":
                raise _refuse("unbalanced )", self.i)
            if c in "^$":
                self.i += 1
                after = self.peek()
                if after in ("?", "*", "+") or (after == "{" and self.braces_at(self.i) is not None):
                    raise _refuse(f"quantified anchor {c}", self.i)
                items.append(_Anchor(c))
                continue
            item = self.atom(depth)
            item.quantifier = self.quantifier()  # a literal { may itself be quantified, as in Python
            items.append(item)

    def atom(self, depth: int) -> _Atom | _Group:
        c = self.text[self.i]
        if c in "?*+":
            raise _refuse(f"nothing to repeat before {c!r}", self.i)
        if c == "{":
            if self.braces_at(self.i) is not None:
                raise _refuse("nothing to repeat before '{'", self.i)
            self.i += 1
            self.rules.add("syntax-literal")
            return _Atom("\\{")
        if c in "}]":
            self.i += 1
            self.rules.add("syntax-literal")
            return _Atom("\\" + c)
        if c == ".":
            self.i += 1
            self.rules.add("dot")
            return _Atom("[^\\n]")
        if c == "\\":
            return _Atom(self.escape())
        if c == "[":
            return _Atom(self.char_class())
        if c == "(":
            return self.group(depth)
        self.i += 1
        return _Atom(c)

    def escape(self) -> str:
        start = self.i
        c = self.peek(1)
        if c is None:
            raise _refuse("trailing backslash", start)
        self.i += 2
        if c in _OUTSIDE_KEPT or c in _CONTROL:
            return "\\" + c
        if c in _SHORTHAND:
            members, rule = _SHORTHAND[c]
            self.rules.add(rule)
            return f"[{members}]"
        self.refuse_escape(c, start)
        self.rules.add("identity-escape")
        return c

    def refuse_escape(self, c: str, start: int) -> None:
        if c in _NEGATED_SHORTHAND:
            raise _refuse(f"negated shorthand \\{c} {_WIDENS}", start)
        if c in _DIGITS:
            raise _refuse(f"backreference or octal escape \\{c} is outside the dialect", start)
        if c in _ASCII_LETTERS:
            raise _refuse(f"escape \\{c} is outside the dialect", start)

    def group(self, depth: int) -> _Group:
        start = self.i
        self.i += 1
        opener = "("
        if self.peek() == "?":
            if self.peek(1) != ":":
                kind = {"=": "lookahead", "!": "lookahead", "<": "lookbehind or named group", "P": "named group",
                        "#": "comment", "(": "conditional", ">": "atomic group"}.get(self.peek(1) or "", "inline flag")
                raise _refuse(f"{kind} (?{self.peek(1) or ''} is outside the dialect", start)
            self.i += 2
            opener = "(?:"
        branches = self.alternation(depth + 1)
        if self.peek() != ")":
            raise _refuse("unclosed group", start)
        self.i += 1
        return _Group(opener, branches)

    def char_class(self) -> str:
        start = self.i
        self.i += 1
        out = "["
        negated = self.peek() == "^"
        if negated:
            self.i += 1
            out += "^"
        first = True
        while True:
            c = self.peek()
            if c is None:
                raise _refuse("unclosed class", start)
            if c == "]" and not first:
                self.i += 1
                return out + "]"
            lo_text, lo_char = self.member(negated)
            first = False
            if self.peek() == "-" and self.peek(1) is not None and self.peek(1) != "]":
                dash = self.i
                self.i += 1
                hi_text, hi_char = self.member(negated)
                if lo_char is None or hi_char is None:
                    raise _refuse("a shorthand class cannot bound a range", dash)
                if lo_char > hi_char:
                    raise _refuse("range is reversed", dash)
                out += f"{lo_text}-{hi_text}"
            else:
                out += lo_text

    def member(self, negated: bool) -> tuple[str, str | None]:
        """Read one class member; return its dialect spelling and its code point (None for a shorthand).

        A shorthand in a negated class is refused: its ASCII expansion there widens what the
        class accepts (`[^\\w]` would take `é`), the same reason `\\W`, `\\D` and `\\S` are refused.
        """
        start = self.i
        c = self.text[start]
        if c != "\\":
            self.i += 1
            if c in "][^-":
                self.rules.add("class-dash" if c == "-" else "class-literal")
                return "\\" + c, c
            return c, c
        e = self.peek(1)
        if e is None:
            raise _refuse("trailing backslash", start)
        self.i += 2
        if e in _CLASS_KEPT:
            return "\\" + e, e
        if e in _CONTROL:
            return "\\" + e, _CONTROL[e]
        if e in _SHORTHAND:
            if negated:
                raise _refuse(f"shorthand \\{e} in a negated class {_WIDENS}", start)
            members, rule = _SHORTHAND[e]
            self.rules.add(rule)
            return members, None
        self.refuse_escape(e, start)
        self.rules.add("class-escape")
        return e, e

    def braces_at(self, j: int) -> tuple[str, int] | None:
        """If a well-formed Python quantifier `{…}` starts at j, return (lo, end) where end is past the `}`."""
        k = j + 1
        while k < self.n and self.text[k] in _DIGITS:
            k += 1
        lo = self.text[j + 1 : k]
        if k < self.n and self.text[k] == ",":
            k += 1
            while k < self.n and self.text[k] in _DIGITS:
                k += 1
        if k < self.n and self.text[k] == "}" and k > j + 1:
            return lo, k + 1
        return None

    def quantifier(self) -> str:
        c = self.peek()
        if c is None:
            return ""
        if c in "?*+":
            self.i += 1
            text = c
        elif c == "{":
            found = self.braces_at(self.i)
            if found is None:
                return ""  # a literal {, read as the next atom
            lo, end = found
            if not lo:
                raise _refuse("quantifier without a lower bound is outside the dialect", self.i)
            text = self.text[self.i : end]
            self.i = end
        else:
            return ""
        if self.peek() == "?":
            self.i += 1
            text += "?"
        after = self.peek()
        if after == "+":
            raise _refuse("possessive quantifier is outside the dialect", self.i)
        if after in ("*", "?") or (after == "{" and self.braces_at(self.i) is not None):
            raise _refuse("multiple repeat", self.i)
        return text


def _drop_edge_anchors(seq: list[_Item], start_edge: bool, end_edge: bool, nested: bool, rules: set[str]) -> list[_Item]:
    """Drop the anchors inside groups that sit at the pattern's start or end edge.

    An item is at the start edge when only anchors precede it in its sequence and that
    sequence is at the start edge (an unquantified group passes its edges to its branches);
    the end edge likewise. Under full match `^` always holds at the start edge and `$` at
    the end edge, so dropping them there keeps the meaning. Top-level anchors stay.
    """
    out: list[_Item] = []
    for k, item in enumerate(seq):
        at_start = start_edge and all(isinstance(x, _Anchor) for x in seq[:k])
        at_end = end_edge and all(isinstance(x, _Anchor) for x in seq[k + 1 :])
        if isinstance(item, _Anchor) and nested and (at_start if item.kind == "^" else at_end):
            rules.add("edge-anchor")
            continue
        if isinstance(item, _Group) and not item.quantifier:
            item.branches = [_drop_edge_anchors(b, at_start, at_end, True, rules) for b in item.branches]
        out.append(item)
    return out


def _emit(branches: list[list[_Item]]) -> str:
    return "|".join("".join(_emit_item(x) for x in seq) for seq in branches)


def _emit_item(item: _Item) -> str:
    if isinstance(item, _Anchor):
        return item.kind
    if isinstance(item, _Atom):
        return item.text + item.quantifier
    return f"{item.opener}{_emit(item.branches)}){item.quantifier}"


def _anchored(seq: list[_Item]) -> bool:
    return (
        len(seq) >= 2
        and isinstance(seq[0], _Anchor) and seq[0].kind == "^"
        and isinstance(seq[-1], _Anchor) and seq[-1].kind == "$"
    )


def rewrite(pattern: str) -> Rewritten:
    """Rewrite a Python pattern into the dialect, or raise `unsupported_pattern`."""
    try:
        check_pattern(pattern)
        return Rewritten(pattern, ())
    except RefsError:
        pass
    reader = _Reader(pattern)
    branches = reader.read()
    rules = reader.rules
    if len(branches) > 1 and all(_anchored(seq) for seq in branches):
        rules.add("anchored-alternation")
        inner: list[list[_Item]] = [seq[1:-1] for seq in branches]
        branches = [[_Anchor("^"), _Group("(?:", inner), _Anchor("$")]]
    branches = [_drop_edge_anchors(seq, True, True, False, rules) for seq in branches]
    out = _emit(branches)
    try:
        check_pattern(out)
    except RefsError as e:
        raise _refuse(f"the rewrite {out!r} is still outside the dialect: {e.detail}", None) from e
    return Rewritten(out, tuple(sorted(rules)))


# Samples.


def _draw_class(node: Class, rng: random.Random) -> str:
    if not node.negated:
        r = rng.choice(node.items)
        return chr(rng.randint(ord(r.lo), ord(r.hi)))
    outside = [c for c in _PRINTABLE if not any(r.lo <= c <= r.hi for r in node.items)]
    if not outside:
        raise ValueError("no printable ASCII character lies outside this negated class")
    return rng.choice(outside)


def _draw(node: Alt | Seq | Lit | Anchor | Class | Group | Repeat, rng: random.Random) -> str:
    if isinstance(node, Alt):
        return _draw(rng.choice(node.branches), rng)
    if isinstance(node, Seq):
        return "".join(_draw(x, rng) for x in node.items)
    if isinstance(node, Lit):
        return node.char
    if isinstance(node, Anchor):
        return ""
    if isinstance(node, Class):
        return _draw_class(node, rng)
    if isinstance(node, Group):
        return _draw(node.body, rng)
    hi = node.min + 3 if node.max is None else node.max
    return "".join(_draw(node.child, rng) for _ in range(rng.randint(node.min, hi)))


def samples(pattern: str, count: int, seed: int) -> list[str]:
    """Draw `count` strings that `pattern` (a dialect pattern) fully matches, reproducibly from `seed`.

    A fixed `{m}` repeats exactly m times, a bounded `{m,n}` or `?` draws from [m, n], and an
    unbounded `*`, `+` or `{m,}` draws from [m, m + 3]. A negated class draws printable ASCII.
    """
    ast = parse_pattern(pattern)
    rng = random.Random(seed)
    return [_draw(ast, rng) for _ in range(count)]


__all__ = ["Rewritten", "rewrite", "samples"]
