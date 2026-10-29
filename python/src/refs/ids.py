"""Identifiers as CURIEs: `prefix:local` with the registry's canonical prefix (spec 5.2)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING

from refs.dialect import compile_pattern
from refs.errors import RefsError

if TYPE_CHECKING:
    from refs.registry import Registry


@dataclass(frozen=True)
class Curie:
    prefix: str
    local: str

    def __str__(self) -> str:
        return f"{self.prefix}:{self.local}"


@cache
def _compiled(pattern: str) -> re.Pattern[str]:
    return compile_pattern(pattern)


@dataclass(frozen=True)
class Scheme:
    """One prefix's grammar. `pattern` is in the pattern dialect, None when the registry states none
    (or when `refused` says the upstream pattern has no dialect form). `uri_format` is data for
    resolvers; refs never dereferences it."""

    prefix: str
    name: str
    pattern: str | None
    uri_format: str | None
    synonyms: tuple[str, ...]
    issued_by: str | None
    refused: str | None

    def matches(self, local: str) -> bool:
        """Full match of the whole local id; a scheme without a pattern accepts any id, a refused one none."""
        if self.refused is not None:
            raise RefsError("unsupported_pattern", f"{self.prefix}: {self.refused}")
        return self.pattern is None or _compiled(self.pattern).fullmatch(local) is not None


def parse(text: str, registry: Registry) -> Curie:
    """Parse `prefix:local` into a Curie with the canonical prefix and the local id as given."""
    prefix, separator, local = text.partition(":")
    if not separator:
        raise RefsError("ambiguous_id", f"{text!r} needs a prefix: write <prefix>:{text}")
    if not prefix or not local:
        raise RefsError("not_a_curie", f"{text!r} is not <prefix>:<id>")
    canonical = registry.canonical(prefix)
    if canonical is None:
        raise RefsError("unknown_prefix", f"{prefix!r} is not a known prefix")
    scheme = registry.scheme(canonical)
    if not scheme.matches(local):
        raise RefsError("malformed", f"{local!r} does not match {canonical}'s pattern {scheme.pattern}")
    return Curie(canonical, local)
