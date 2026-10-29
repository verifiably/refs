"""The pinned Bioregistry snapshot plus refs' shared local schemes and a profile's self-issued
ones, with a fingerprint over the effective grammar (spec 5.3)."""

from __future__ import annotations

import hashlib
import json
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any, Literal

import rfc8785

from refs.dialect import check_pattern
from refs.errors import RefsError
from refs.ids import Scheme


@dataclass(frozen=True)
class LocalScheme:
    """A scheme Bioregistry lacks. A self-issued one names its issuing project in `issued_by`
    and its prefix begins with that name and a dot."""

    prefix: str
    name: str
    pattern: str | None
    uri_format: str | None
    why: str
    issued_by: str | None = None

    def __post_init__(self) -> None:
        if self.issued_by is not None and not self.prefix.startswith(self.issued_by + "."):
            raise RefsError(
                "local_collision",
                f"{self.prefix!r} is issued by {self.issued_by!r}, so it must begin with {self.issued_by + '.'!r}",
            )


@dataclass(frozen=True)
class Collision:
    prefix: str
    kind: Literal["shadows_registry", "repeated"]
    detail: str


def _data(name: str) -> bytes:
    return (resources.files("refs") / "data" / name).read_bytes()


class Registry:
    """Immutable: `with_local` returns a new registry."""

    def __init__(self, version: str, schemes: dict[str, Scheme], lookup: dict[str, str], local: frozenset[str]) -> None:
        self.version = version
        self._schemes = schemes
        self._lookup = lookup  # lower-cased canonical prefix or synonym -> canonical prefix; upstream only
        self._local = local
        self._fingerprint: str | None = None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> Registry:
        """A registry of the upstream prefixes in `doc` (the shape of registry/bioregistry.json) alone."""
        schemes: dict[str, Scheme] = {}
        lookup: dict[str, str] = {}
        for prefix, body in doc["prefixes"].items():
            schemes[prefix] = Scheme(
                prefix,
                body["name"],
                body["pattern"],
                body["uri_format"],
                tuple(body["synonyms"]),
                None,
                body.get("refused"),
            )
            lookup[prefix.lower()] = prefix
        for prefix, body in doc["prefixes"].items():
            for synonym in body["synonyms"]:
                lookup.setdefault(synonym.lower(), prefix)  # a canonical prefix always wins
        return cls(doc["version"], schemes, lookup, frozenset())

    @classmethod
    def default(cls) -> Registry:
        """The bundled snapshot plus refs' shared local schemes."""
        return _default()

    @property
    def fingerprint(self) -> str:
        """SHA-256 hex of the RFC 8785 canonical JSON of every scheme, local ones included."""
        if self._fingerprint is None:
            effective = {
                "version": self.version,
                "schemes": {
                    prefix: {
                        "name": s.name,
                        "pattern": s.pattern,
                        "uri_format": s.uri_format,
                        "synonyms": list(s.synonyms),
                        "issued_by": s.issued_by,
                        "refused": s.refused,
                    }
                    for prefix, s in self._schemes.items()
                },
            }
            self._fingerprint = hashlib.sha256(rfc8785.dumps(effective)).hexdigest()
        return self._fingerprint

    def canonical(self, prefix: str) -> str | None:
        """The canonical prefix for `prefix` in any case, or a synonym of it; None when unknown."""
        key = prefix.lower()
        return key if key in self._local else self._lookup.get(key)

    def scheme(self, prefix: str) -> Scheme:
        """The scheme under the canonical `prefix`."""
        try:
            return self._schemes[prefix]
        except KeyError:
            raise RefsError("unknown_prefix", f"{prefix!r} is not a canonical prefix") from None

    def is_upstream(self, prefix: str) -> bool:
        return prefix in self._schemes and prefix not in self._local

    def is_local(self, prefix: str) -> bool:
        return prefix.lower() in self._local

    def collisions(self, schemes: Iterable[LocalScheme]) -> list[Collision]:
        """The conflicts `with_local` would refuse, in declaration order, without raising."""
        seen = set(self._local)
        found: list[Collision] = []
        for scheme in schemes:
            key = scheme.prefix.lower()
            if key in seen:
                found.append(Collision(scheme.prefix, "repeated", f"{scheme.prefix!r} is already a local prefix"))
            elif key in self._lookup:
                found.append(
                    Collision(
                        scheme.prefix,
                        "shadows_registry",
                        f"{scheme.prefix!r} is Bioregistry's prefix or synonym {self._lookup[key]!r}",
                    )
                )
            seen.add(key)
        return found

    def with_local(self, schemes: Iterable[LocalScheme]) -> Registry:
        """A registry that adds `schemes`; local prefixes are stored lower-cased, like lookups."""
        declared = list(schemes)
        found = self.collisions(declared)
        if found:
            raise RefsError("local_collision", "; ".join(c.detail for c in found))
        for scheme in declared:
            if scheme.pattern is not None:
                check_pattern(scheme.pattern)
        added = {
            s.prefix.lower(): Scheme(s.prefix.lower(), s.name, s.pattern, s.uri_format, (), s.issued_by, None)
            for s in declared
        }
        return Registry(self.version, {**self._schemes, **added}, self._lookup, self._local | added.keys())


_SHARED_KEYS = ("name", "pattern", "uri_format", "why")


def local_schemes_from_table(table: Mapping[str, Any]) -> list[LocalScheme]:
    """The schemes of `local-schemes.toml`'s `schemes` table. Each entry holds exactly the four
    string keys `name`, `pattern`, `uri_format` and `why`; anything else is a data bug, refused
    here rather than left to change the fingerprint."""
    schemes: list[LocalScheme] = []
    for prefix, body in table.items():
        if not isinstance(body, Mapping):
            raise ValueError(f"local scheme {prefix!r} must be a table")  # noqa: TRY004 - one error type for a bad data file
        for key in body:
            if key not in _SHARED_KEYS:
                raise ValueError(f"local scheme {prefix!r} has an unknown key {key!r}")
        for key in _SHARED_KEYS:
            if key not in body:
                raise ValueError(f"local scheme {prefix!r} is missing {key!r}")
            if not isinstance(body[key], str):
                raise ValueError(f"local scheme {prefix!r}: {key!r} must be a string")  # noqa: TRY004
        schemes.append(LocalScheme(prefix, body["name"], body["pattern"], body["uri_format"], body["why"]))
    return schemes


@cache
def _default() -> Registry:
    upstream = Registry.from_document(json.loads(_data("bioregistry.json")))
    shared = tomllib.loads(_data("local-schemes.toml").decode("utf-8"))["schemes"]
    return upstream.with_local(local_schemes_from_table(shared))
