# The MASK

The MASK lets you use an AI tool on a confidential contract without the AI ever reading the
confidential parts. Before you upload a Word or PDF contract, it replaces personal data and
business secrets with placeholders such as `[PERSON_1]` or `[AMOUNT_2]` and keeps the real values
in an encrypted key on your own computer. When the AI gives you back a Word file, it puts the real
values back in. Everything runs on your machine and nothing is ever sent anywhere.

The design is in `docs/superpowers/specs/2026-10-17-the-mask-design.md`. The step-by-step build
plan for the Mac version is in `docs/superpowers/plans/2026-10-17-the-mask-mac-v1.md`.

## Requirements

- macOS (the first version; Windows follows in a later phase)
- [uv](https://docs.astral.sh/uv/). It installs the right Python (3.12) and every pinned
  dependency, including the English language model, for you.

## Run from source

```bash
uv sync
uv run python -m themask
```

`uv sync` needs the network once, to download the dependencies. The finished app never does.

The window opens at once and says "Loading…" for a few seconds while it loads the language model.
Drop a Word or PDF contract on it (or use "Choose files…") to analyse it and review what it found.
The export and the restore screens are added in later steps of the build plan.

## Develop

```bash
uv run pytest -q              # tests, including the licence gate
uv run ruff check src tests   # lint
uv run mypy src               # types (strict)
```

The licence gate (`tests/test_licences.py`) fails if any GPL or AGPL package is installed in the
environment. LGPL libraries (such as Qt for Python) and dual licences with a permissive or LGPL
option are accepted.
