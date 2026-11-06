"""The pattern dialect: the grammar every stored identifier pattern is in (docs/STANDARD.md §2).

The grammar is the authority, not either regex engine. `parse_pattern` parses a pattern
against it and raises `unsupported_pattern` at the 0-based code-point index of the first
character the grammar cannot accept (the length of the pattern when it ends too soon).
`check_pattern` is that parse with the tree thrown away; `compile_pattern` compiles only
a pattern the grammar accepted.

    pattern     = alternation
    alternation = sequence { "|" sequence }
    sequence    = { item }
    item        = "^" (index 0 only) | "$" (last character only) | atom [ quantifier ]
    atom        = literal | escape | class | group
    group       = "(" alternation ")" | "(?:" alternation ")"
    quantifier  = ( "?" | "*" | "+" | "{" m "}" | "{" m "," "}" | "{" m "," n "}" ) [ "?" ]
    class       = "[" [ "^" ] member-or-range { member-or-range } "]"

The empty pattern, empty branches and empty groups are accepted. Digits in a quantifier
are ASCII digits, at most five of them (leading zeros count), each bound at most 65535, and
m must not exceed n. Groups nest at most 32 deep. Inside a class, the doubled unescaped
characters `&&`, `~~` and `||` are refused: Python reserves them for set operations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from refs.errors import RefsError

_SYNTAX = frozenset("\\^$.|?*+()[]{}")
_CONTROL = {"t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r"}
_OUTSIDE_ESCAPES = _SYNTAX | {"/"}
_CLASS_ESCAPES = frozenset("\\][^-")
_CLASS_PLAIN_EXCLUDED = frozenset("\\][^-")
_CLASS_RESERVED_DOUBLES = frozenset("&~|")
_DIGITS = frozenset("0123456789")
_MAX_COUNT = 65535  # largest quantifier bound; above it the engines differ or Python refuses
_MAX_DIGITS = len(str(_MAX_COUNT))  # a longer digit run is refused before any int conversion
_MAX_DEPTH = 32  # deepest group nesting; keeps the recursive descent far from the recursion limit


@dataclass(frozen=True, slots=True)
class Lit:
    char: str


@dataclass(frozen=True, slots=True)
class Anchor:
    kind: str  # "start" or "end"


@dataclass(frozen=True, slots=True)
class Range:
    lo: str
    hi: str  # equal to lo for a single member


@dataclass(frozen=True, slots=True)
class Class:
    negated: bool
    items: tuple[Range, ...]


@dataclass(frozen=True, slots=True)
class Group:
    capturing: bool
    body: Alt


@dataclass(frozen=True, slots=True)
class Repeat:
    child: Lit | Class | Group
    min: int
    max: int | None  # None is unbounded
    lazy: bool


@dataclass(frozen=True, slots=True)
class Seq:
    items: tuple[Lit | Anchor | Class | Group | Repeat, ...]


@dataclass(frozen=True, slots=True)
class Alt:
    branches: tuple[Seq, ...]


Ast = Alt
"""The parsed pattern: an alternation of sequences.

`Lit`, `Anchor`, `Range`, `Class`, `Group`, `Repeat`, `Seq` and `Alt` are package-internal:
refs' own modules (rewriting, sample generation) walk them; they are not re-exported from
`refs` and not part of its public API.
"""


def _refuse(detail: str, position: int) -> RefsError:
    return RefsError("unsupported_pattern", detail, position)


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.n = len(text)
        self.i = 0

    def peek(self) -> str | None:
        return self.text[self.i] if self.i < self.n else None

    def parse(self) -> Ast:
        body = self.alternation(depth=0)
        if self.i < self.n:  # only an unmatched ")" stops the top level early
            raise _refuse("unmatched )", self.i)
        return body

    def alternation(self, depth: int) -> Alt:
        branches = [self.sequence(depth)]
        while self.peek() == "|":
            self.i += 1
            branches.append(self.sequence(depth))
        return Alt(tuple(branches))

    def sequence(self, depth: int) -> Seq:
        items: list[Lit | Anchor | Class | Group | Repeat] = []
        while True:
            c = self.peek()
            if c is None or c == "|" or (c == ")" and depth > 0):
                return Seq(tuple(items))
            if c == ")":
                raise _refuse("unmatched )", self.i)
            if c == "^":
                if self.i != 0:
                    raise _refuse("^ is allowed only at the start of the pattern", self.i)
                self.i += 1
                items.append(Anchor("start"))
            elif c == "$":
                if self.i != self.n - 1:
                    raise _refuse("$ is allowed only at the end of the pattern", self.i)
                self.i += 1
                items.append(Anchor("end"))
            else:
                atom = self.atom(depth)
                items.append(self.quantified(atom))

    def atom(self, depth: int) -> Lit | Class | Group:
        c = self.text[self.i]
        if c in "?*+{":
            raise _refuse(f"nothing to quantify before {c!r}", self.i)
        if c == "\\":
            return Lit(self.escape(in_class=False))
        if c == "[":
            return self.char_class()
        if c == "(":
            return self.group(depth)
        if c in _SYNTAX:
            raise _refuse(f"unescaped {c!r} is outside the dialect", self.i)
        self.i += 1
        return Lit(c)

    def escape(self, *, in_class: bool) -> str:
        """Consume a backslash escape; return the code point it denotes."""
        start = self.i
        if start + 1 >= self.n:
            raise _refuse("trailing backslash", start)
        c = self.text[start + 1]
        allowed = _CLASS_ESCAPES if in_class else _OUTSIDE_ESCAPES
        if c in _CONTROL:
            self.i += 2
            return _CONTROL[c]
        if c in allowed:
            self.i += 2
            return c
        raise _refuse(f"escape \\{c} is outside the dialect", start)

    def group(self, depth: int) -> Group:
        if depth >= _MAX_DEPTH:
            raise _refuse(f"groups nest at most {_MAX_DEPTH} deep", self.i)
        self.i += 1  # (
        capturing = True
        if self.peek() == "?":
            if self.text[self.i + 1 : self.i + 2] != ":":
                raise _refuse("only (?: is allowed after (", self.i)
            self.i += 2
            capturing = False
        body = self.alternation(depth + 1)
        if self.peek() != ")":
            raise _refuse("unclosed group", self.i)
        self.i += 1
        return Group(capturing, body)

    def char_class(self) -> Class:
        self.i += 1  # [
        negated = False
        if self.peek() == "^":
            negated = True
            self.i += 1
        items: list[Range] = []
        while True:
            c = self.peek()
            if c is None:
                raise _refuse("unclosed class", self.i)
            if c == "]":
                if not items:
                    raise _refuse("a class holds at least one member", self.i)
                self.i += 1
                return Class(negated, tuple(items))
            first_at = self.i
            lo = self.member()
            hi = lo
            if self.peek() == "-":
                dash_at = self.i
                self.i += 1
                if self.peek() == "]":
                    raise _refuse("- must sit between two members", dash_at)
                hi = self.member()
                if lo > hi:
                    raise _refuse("range is reversed", first_at)
            items.append(Range(lo, hi))

    def member(self) -> str:
        c = self.peek()
        if c is None:
            raise _refuse("unclosed class", self.i)
        if c == "\\":
            return self.escape(in_class=True)
        if c in _CLASS_PLAIN_EXCLUDED:
            raise _refuse(f"unescaped {c!r} is not a class member here", self.i)
        if c in _CLASS_RESERVED_DOUBLES and self.i > 0 and self.text[self.i - 1] == c:
            raise _refuse(f"doubled {c!r} in a class is reserved for set operations", self.i)
        self.i += 1
        return c

    def quantified(self, atom: Lit | Class | Group) -> Lit | Class | Group | Repeat:
        c = self.peek()
        if c is None or c not in "?*+{":
            return atom
        if c == "{":
            lo, hi = self.braces()
        else:
            self.i += 1
            lo, hi = {"?": (0, 1), "*": (0, None), "+": (1, None)}[c]
        lazy = self.peek() == "?"
        if lazy:
            self.i += 1
        return Repeat(atom, lo, hi, lazy)

    def braces(self) -> tuple[int, int | None]:
        start = self.i
        self.i += 1  # {
        lo = self.digits(start)
        hi: int | None = lo
        if self.peek() == ",":
            self.i += 1
            hi = self.digits(start) if self.peek() in _DIGITS else None
        if self.peek() != "}":
            raise _refuse("malformed quantifier", start)
        self.i += 1
        if hi is not None and lo > hi:
            raise _refuse("quantifier lower bound exceeds upper bound", start)
        return lo, hi

    def digits(self, start: int) -> int:
        j = self.i
        while self.i < self.n and self.text[self.i] in _DIGITS:
            self.i += 1
        if j == self.i:
            raise _refuse("malformed quantifier", start)
        if self.i - j > _MAX_DIGITS:
            raise _refuse(f"quantifier bound has more than {_MAX_DIGITS} digits", start)
        value = int(self.text[j : self.i])
        if value > _MAX_COUNT:
            raise _refuse(f"quantifier bound exceeds {_MAX_COUNT}", start)
        return value


def parse_pattern(pattern: str) -> Ast:
    """Parse `pattern` against the dialect grammar; raise `unsupported_pattern` if it is outside it."""
    return _Parser(pattern).parse()


def check_pattern(pattern: str) -> None:
    """Refuse a pattern outside the dialect with `unsupported_pattern` and a code-point position."""
    parse_pattern(pattern)


def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Check `pattern`, then compile it with no flags. An engine error after a clean check is `invalid_pattern`."""
    check_pattern(pattern)
    try:
        return re.compile(pattern)
    except (re.error, OverflowError) as e:
        raise RefsError("invalid_pattern", f"engine refused a pattern the grammar accepted: {e}") from e
