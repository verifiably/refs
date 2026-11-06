"""The `refs/about` facet: a node's references, each with its own release (docs/STANDARD.md §6).

The only refs module that imports nodes."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from nodes.core.errors import FacetError
from nodes.core.node import Node
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from refs.errors import RefsError
from refs.ids import parse
from refs.registry import Registry
from refs.vocab import Vocabulary

FACET = "refs/about"


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str
    release: str | None = None

    @model_validator(mode="after")
    def _release_is_absent_or_a_string(self) -> _Entry:
        if "release" in self.model_fields_set and self.release is None:
            raise ValueError("release is a string; leave it out for none")
        return self


class _About(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    entries: list[_Entry]


def _sort_key(id: str, release: str | None) -> tuple[str, str]:
    # Python compares str by code point; an absent release sorts first as "".
    return (id, release or "")


def build_about(entries: Iterable[tuple[str, str | None]], registry: Registry) -> dict[str, Any]:
    """The canonical payload: ids canonicalised, duplicates dropped, sorted by code point.
    Releases are not checked against vocabularies; the invariant does that."""
    unique = {(str(parse(id, registry)), release) for id, release in entries}
    return {
        "entries": [
            {"id": id} if release is None else {"id": id, "release": release}
            for id, release in sorted(unique, key=lambda pair: _sort_key(*pair))
        ]
    }


def _first_violation(
    payload: Mapping[str, Any], registry: Registry, vocabularies: Mapping[str, Vocabulary]
) -> str | None:
    try:
        about = _About.model_validate(payload)
    except ValidationError as error:
        return f"malformed payload: {error}"
    if not about.entries:
        return "entries must not be empty"
    previous: tuple[str, str] | None = None
    for entry in about.entries:
        try:
            curie = parse(entry.id, registry)
        except RefsError as error:
            return f"{entry.id!r}: {error}"
        if str(curie) != entry.id:
            return f"{entry.id!r} is not canonical, write {str(curie)!r}"
        vocabulary = vocabularies.get(curie.prefix)
        if vocabulary is None:
            if entry.release is not None:
                return f"{entry.id!r}: {curie.prefix} declares no vocabulary, so it takes no release"
        elif entry.release is None:
            return f"{entry.id!r}: {curie.prefix} is a vocabulary, so a release is required"
        elif entry.release not in vocabulary.releases:
            return (
                f"{entry.id!r}: release {entry.release!r} is not the current release "
                f"{vocabulary.release!r} or one of {list(vocabulary.accepted)}"
            )
        key = _sort_key(entry.id, entry.release)
        if previous is not None and key <= previous:
            kind = "repeats" if key == previous else "is out of order after"
            return f"{entry.id!r} (release {entry.release!r}) {kind} the entry before it"
        previous = key
    return None


def about_facet(registry: Registry, vocabularies: Mapping[str, Vocabulary]) -> Callable[[Node], None]:
    """A nodes invariant for `refs/about`: a no-op without the facet, otherwise `FacetError`
    naming the node and the first violation."""
    declared = dict(vocabularies)

    def invariant(node: Node) -> None:
        if FACET not in node.facets:
            return
        problem = _first_violation(node.facets[FACET], registry, declared)
        if problem is not None:
            raise FacetError(f"{node.id}: {FACET}: {problem}")

    return invariant
