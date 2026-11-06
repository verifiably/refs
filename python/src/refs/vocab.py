"""Vocabulary declarations: a prefix whose ids are drawn from a released vocabulary (docs/STANDARD.md §5)."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from refs.errors import RefsError
from refs.registry import Registry

_KEYS = frozenset({"issuer", "release", "accepted"})


@dataclass(frozen=True)
class Vocabulary:
    """`release` is the current release, stamped on new references; `accepted` lists earlier
    releases that existing references may still carry. Releases are opaque strings."""

    prefix: str
    issuer: Literal["external", "self"]
    release: str
    accepted: tuple[str, ...]

    @property
    def releases(self) -> frozenset[str]:
        return frozenset((self.release, *self.accepted))


def _refuse(prefix: str, detail: str) -> RefsError:
    return RefsError("invalid_vocabulary", f"{prefix!r}: {detail}")


def _release(prefix: str, name: str, value: Any) -> str:
    if not isinstance(value, str) or value == "":
        raise _refuse(prefix, f"{name} must be a non-empty string, got {value!r}")
    return value


def _parse_one(prefix: str, declaration: Any, registry: Registry) -> Vocabulary:
    if registry.canonical(prefix) != prefix:
        raise _refuse(prefix, "not a canonical prefix of the registry")
    if not isinstance(declaration, Mapping):
        raise _refuse(prefix, "the declaration must be a table")
    body = cast("Mapping[str, Any]", declaration)
    unknown = sorted(set(body) - _KEYS)
    if unknown:
        raise _refuse(prefix, f"unknown keys {unknown}")
    if "issuer" not in body or "release" not in body:
        raise _refuse(prefix, "issuer and release are required")
    issuer = body["issuer"]
    if issuer not in ("external", "self"):
        raise _refuse(prefix, f"issuer must be 'external' or 'self', got {issuer!r}")
    self_issued = registry.is_local(prefix) and registry.scheme(prefix).issued_by is not None
    if issuer == "self" and not self_issued:
        raise _refuse(prefix, "a self-issued vocabulary needs a local scheme with issued_by")
    if issuer == "external" and self_issued:
        raise _refuse(prefix, "the scheme is self-issued, so the issuer must be 'self'")
    release = _release(prefix, "release", body["release"])
    raw = body.get("accepted", [])
    if not isinstance(raw, (list, tuple)):
        raise _refuse(prefix, "accepted must be a list")
    accepted = tuple(_release(prefix, "accepted", item) for item in cast("list[Any]", raw))
    if len(set(accepted)) != len(accepted):
        raise _refuse(prefix, "accepted repeats a release")
    if release in accepted:
        raise _refuse(prefix, "accepted repeats the current release")
    return Vocabulary(prefix, issuer, release, accepted)


def parse_vocabularies(table: Mapping[str, Any], registry: Registry) -> dict[str, Vocabulary]:
    """The `[vocabularies]` table of docs/STANDARD.md §5, already parsed. Each key is the canonical prefix."""
    return {prefix: _parse_one(prefix, declaration, registry) for prefix, declaration in table.items()}


def load_vocabularies(path: Path, registry: Registry) -> dict[str, Vocabulary]:
    """Read a TOML file holding a `[vocabularies]` table and nothing else."""
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise RefsError("invalid_vocabulary", f"{path.name}: not valid TOML: {error}") from error
    if set(document) != {"vocabularies"}:
        raise RefsError("invalid_vocabulary", f"{path.name}: expected a [vocabularies] table and nothing else")
    return parse_vocabularies(document["vocabularies"], registry)
