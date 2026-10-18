"""The made-up contract corpus: Word contracts with their ground truth, for the tests to run on.

    uv run python -m tools.make_corpus [out_dir]

writes 20 contracts and the annexes three of them come with, a ``.truth.json`` beside each Word
file listing every secret in it, and ``manifest.json`` listing the files and their features
(default folder: ``tests/corpus/generated/``, which git ignores). The same files come out every
time. ``tests/corpus/README.md`` describes the corpus; the tests get it from the ``corpus``
fixture.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from tools.corpus.build import build_spec
from tools.corpus.docx_writer import write_docx
from tools.corpus.model import FEATURES, KINDS, ContractSpec, Kind, TruthItem

__all__ = [
    "CATALOGUE",
    "FEATURES",
    "KINDS",
    "ContractSpec",
    "Planned",
    "TruthItem",
    "build_spec",
    "generate",
    "main",
    "write_docx",
    "write_truth",
]

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "tests" / "corpus" / "generated"


@dataclass(frozen=True)
class Planned:
    """One contract of the corpus: its file name, kind, seed, features and parties."""

    name: str
    kind: Kind
    seed: int
    features: frozenset[str]
    parties: tuple[str, str]
    project: str | None = None
    bare_amount: bool = False


def _plan(
    name: str,
    seed: int,
    parties: tuple[str, str],
    *features: str,
    project: str | None = None,
    bare_amount: bool = False,
) -> Planned:
    kind = cast(Kind, name.split("-")[0])  # every name starts with its kind
    return Planned(name, kind, seed, frozenset(features), parties, project, bare_amount)


# The fixed assignments (supply-01 to services-04) are what later tasks test against; the other
# documents mix the features so that each one appears in at least three documents.
CATALOGUE: tuple[Planned, ...] = (
    _plan("supply-01", 101, ("Northwind", "Thamesgate")),
    _plan("supply-02", 102, ("Brightwater", "Ashcombe"), "comments"),
    _plan(
        "supply-03",
        103,
        ("Rheinwerk", "Ambergate"),
        "tracked_changes",
        "secret_only_in_deletion",
    ),
    _plan("supply-04", 104, ("Polderkant", "Calder"), "properties"),
    _plan("supply-05", 105, ("Kronberg", "Larchfield"), "image"),
    _plan("supply-06", 106, ("Hanseatic", "Acme"), "footnotes"),
    _plan("supply-07", 107, ("Isarthal", "Veldkamp"), "annex"),
    _plan("supply-08", 108, ("Pennine", "Lindenhof"), "shared_surname", project="Project Falcon"),
    _plan("supply-09", 109, ("Baltic", "Harbourline"), "existing_placeholders"),
    _plan("supply-10", 110, ("Tulpenburg", "Fairhaven"), "thirty_pages"),
    _plan("services-01", 201, ("Kanaalzicht", "Harbourline"), "hyperlinks"),
    _plan("services-02", 202, ("Zuiderhaven", "Fairhaven"), "hidden_text"),
    _plan("services-03", 203, ("Lindeboom", "Stellwerk"), "textbox"),
    _plan("services-04", 204, ("Burren", "Kastanje"), "nbsp_numbers"),
    _plan(
        "services-05",
        205,
        ("Greystone", "Brinkhof"),
        "thirty_pages",
        "annex",
        "comments",
        bare_amount=True,
    ),
    _plan("nda-01", 301, ("Kestrel", "Oosterdok"), "hyperlinks", "footnotes"),
    _plan(
        "nda-02",
        302,
        ("Marlowe", "Wendelstein"),
        "shared_surname",
        "hidden_text",
        bare_amount=True,
    ),
    _plan("nda-03", 303, ("Corrib", "Altmark"), "existing_placeholders", "image"),
    _plan("nda-04", 304, ("Elbmarsch", "Quayside"), "properties", "textbox", "nbsp_numbers"),
    _plan(
        "nda-05",
        305,
        ("Riverside", "Duinrand"),
        "tracked_changes",
        "secret_only_in_deletion",
        "comments",
    ),
    _plan("dpa-01", 401, ("Westerkade", "Liffey"), "hyperlinks", "image", "properties"),
    _plan("dpa-02", 402, ("Kingsmead", "Merrion"), "annex", "footnotes", "nbsp_numbers"),
    _plan(
        "dpa-03",
        403,
        ("Havenlicht", "Slaney"),
        "tracked_changes",
        "secret_only_in_deletion",
        "hidden_text",
        "textbox",
    ),
    _plan(
        "dpa-04",
        404,
        ("Bergmann", "Penrose"),
        "shared_surname",
        "existing_placeholders",
        bare_amount=True,
    ),
    _plan("dpa-05", 405, ("Eastbridge", "Elbtal"), "thirty_pages", "footnotes", "tracked_changes"),
)


def write_truth(spec: ContractSpec, path: Path) -> None:
    """Write the truth of ``spec`` as a JSON list (plain ASCII, so any platform reads it alike)."""
    items = [item.to_json() for item in spec.truth]
    path.write_text(json.dumps(items, indent=2, ensure_ascii=True) + "\n", encoding="ascii")


def _write(spec: ContractSpec, out_dir: Path, stem: str) -> dict[str, object]:
    write_docx(spec, out_dir / f"{stem}.docx")
    write_truth(spec, out_dir / f"{stem}.truth.json")
    return {
        "file": f"{stem}.docx",
        "format": "docx",
        "features": sorted(spec.features),
        "truth": f"{stem}.truth.json",
    }


def generate(out_dir: Path) -> list[dict[str, object]]:
    """Write the whole corpus into ``out_dir`` and return the manifest it also writes.

    The manifest lists each Word file with its features and truth file; an annex follows its
    contract and names it in ``annex_of``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for planned in CATALOGUE:
        spec = build_spec(
            planned.seed,
            planned.kind,
            planned.features,
            parties=planned.parties,
            project=planned.project,
            bare_amount=planned.bare_amount,
        )
        manifest.append(_write(spec, out_dir, planned.name))
        if spec.annex is not None:
            entry = _write(spec.annex, out_dir, f"{planned.name}-annex")
            entry["annex_of"] = f"{planned.name}.docx"
            manifest.append(entry)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.make_corpus",
        description="Write the made-up contract corpus with its ground truth.",
    )
    parser.add_argument(
        "out_dir",
        nargs="?",
        type=Path,
        default=DEFAULT_OUT,
        help="folder to write into (default: tests/corpus/generated)",
    )
    args = parser.parse_args(argv)
    started = time.perf_counter()
    manifest = generate(args.out_dir)
    seconds = time.perf_counter() - started
    print(
        f"Wrote {len(manifest)} Word files with their truth to {args.out_dir} in {seconds:.1f} s."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
