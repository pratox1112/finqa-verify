# finqa-verify

[![CI](https://github.com/pratox1112/finqa-verify/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/pratox1112/finqa-verify/actions/workflows/ci.yml)

**When Does Verification Help? Disentangling Agentic Retrieval and Grounded Verification in Numerical Financial QA**

Research code for measuring whether agentic retrieval and grounded verification fix the same numerical errors in financial question answering over SEC filings.

## Setup

Requires [uv](https://docs.astral.sh/uv/). uv installs Python 3.11 automatically if needed.

```bash
uv sync
cp .env.example .env   # then fill in your keys
uv run pytest -m "not integration"
```

## Project documents

- [ROADMAP.md](ROADMAP.md): tasks, acceptance criteria, gates
- [PROGRESS.md](PROGRESS.md): current status
- [docs/IMPLEMENTATION_GUIDE.md](docs/IMPLEMENTATION_GUIDE.md): how each part is built
- [docs/DECISIONS.md](docs/DECISIONS.md): design decisions
