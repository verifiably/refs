from __future__ import annotations


class RefsError(Exception):
    """A refs refusal: `kind` names the error class, `detail` says why, `position` locates it.

    `position` is a 0-based code-point index into the offending text, or None when the
    refusal has no single location.
    """

    def __init__(self, kind: str, detail: str, position: int | None = None) -> None:
        self.kind = kind
        self.detail = detail
        self.position = position
        where = "" if position is None else f" (at {position})"
        super().__init__(f"{kind}: {detail}{where}")
