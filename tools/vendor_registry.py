"""Vendor a Bioregistry snapshot into registry/ in the pattern dialect (docs/STANDARD.md §2 and §4).

    vendor_registry.py --from-snapshot <bioregistry.json> --sha256 <hex>

The snapshot is the reduced form `{source, version, prefixes: {name, pattern, synonyms,
uri_format}}`. Its bytes must hash to --sha256. Every pattern is rewritten into the dialect
(`refs.rewrite`); one with no dialect form is refused, stored with a null pattern and its
reason, and listed in SOURCES.toml. Writes registry/bioregistry.json, registry/SOURCES.toml
and fixtures/registry.verdicts.json, and prints a summary on stderr. Run through
`just registry-vendor`, which runs it in the Python package's environment and then copies
registry/ into the packages. This project's own tool, not one vendored from ops.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

from refs import RefsError, compile_pattern
from refs.rewrite import rewrite, samples

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry"
FIXTURES = ROOT / "fixtures"

# Inputs every pattern's verdicts are taken over, beside samples drawn from the pattern:
# the empty id, non-ASCII digits and letters, a fullwidth form, a space, a carriage return,
# a trailing newline, an astral digit and a lone hyphen (docs/STANDARD.md §2 and §4.7).
ADVERSARIAL = ["", "١٢٣", "Ａ", " ", "a\rb", "123\n", "\U0001d7d9", "-"]


def _toml_string(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)  # a JSON string is a TOML basic string


def vendor(snapshot: dict) -> tuple[dict, dict[str, str]]:
    if snapshot.get("source") != "bioregistry":
        raise SystemExit(f"vendor_registry: snapshot source is {snapshot.get('source')!r}, not 'bioregistry'")
    prefixes: dict[str, dict] = {}
    refused: dict[str, str] = {}
    for prefix, entry in sorted(snapshot["prefixes"].items()):
        upstream = entry["pattern"]
        scheme = {
            "name": entry["name"],
            "pattern": None,
            "upstream_pattern": upstream,
            "rules": [],
            "synonyms": entry["synonyms"],
            "uri_format": entry["uri_format"],
        }
        if upstream is not None:
            try:
                out = rewrite(upstream)
                scheme["pattern"], scheme["rules"] = out.pattern, list(out.rules)
            except RefsError as e:
                where = "" if e.position is None else f" (at {e.position})"
                scheme["refused"] = refused[prefix] = f"{e.detail}{where}"
        prefixes[prefix] = scheme
    return {"source": "bioregistry", "version": snapshot["version"], "prefixes": prefixes}, refused


def verdicts(registry: dict) -> dict[str, list[list]]:
    out: dict[str, list[list]] = {}
    for prefix, scheme in registry["prefixes"].items():
        if scheme["pattern"] is None:
            continue
        compiled = compile_pattern(scheme["pattern"])
        inputs = list(dict.fromkeys(ADVERSARIAL + samples(scheme["pattern"], 4, seed=0)))
        out[prefix] = [[text, compiled.fullmatch(text) is not None] for text in inputs]
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Vendor a Bioregistry snapshot into registry/.")
    parser.add_argument("--from-snapshot", required=True, type=Path, help="the reduced bioregistry.json to vendor")
    parser.add_argument("--sha256", required=True, help="the snapshot's expected SHA-256")
    args = parser.parse_args(argv)

    data = args.from_snapshot.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != args.sha256:
        raise SystemExit(f"vendor_registry: {args.from_snapshot} has sha256 {digest}, expected {args.sha256}")
    registry, refused = vendor(json.loads(data))

    REGISTRY.mkdir(exist_ok=True)
    target = REGISTRY / "bioregistry.json"
    target.write_text(json.dumps(registry, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    lines = [
        "[bioregistry]",
        f"version = {_toml_string(registry['version'])}",
        f'vendored = "{datetime.date.today().isoformat()}"',
        'file = "bioregistry.json"',
        f'sha256 = "{hashlib.sha256(target.read_bytes()).hexdigest()}"',
        f'upstream_sha256 = "{digest}"',
        "",
        "# Prefixes whose upstream pattern has no dialect form: ids under them are refused.",
        "[refused]",
        *(f"{_toml_string(prefix)} = {_toml_string(reason)}" for prefix, reason in sorted(refused.items())),
    ]
    (REGISTRY / "SOURCES.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    table = verdicts(registry)
    body = ",\n".join(f" {json.dumps(prefix)}: {json.dumps(cases)}" for prefix, cases in sorted(table.items()))
    (FIXTURES / "registry.verdicts.json").write_text("{\n" + body + "\n}\n", encoding="utf-8")

    schemes = registry["prefixes"].values()
    patterns = sum(1 for s in schemes if s["upstream_pattern"] is not None)
    rewritten = sum(1 for s in schemes if s["rules"])
    print(
        f"bioregistry {registry['version']}: {len(registry['prefixes'])} prefixes, {patterns} patterns,"
        f" {rewritten} rewritten, {patterns - rewritten - len(refused)} unchanged, {len(refused)} refused",
        file=sys.stderr,
    )
    for prefix, reason in sorted(refused.items()):
        print(f"  refused {prefix}: {reason}", file=sys.stderr)


if __name__ == "__main__":
    main()
