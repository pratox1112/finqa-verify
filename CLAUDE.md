# CLAUDE.md

Instructions for Claude Code in this repository. Read this file fully at the start of every session.

## The project

**When Does Verification Help? Disentangling Agentic Retrieval and Grounded Verification in Numerical Financial QA**

A research project measuring whether agentic retrieval and grounded verification fix the same numerical errors in financial question answering over SEC filings (RQ1), and what happens when sources conflict (RQ2). Model: Qwen3.8-27B via Groq. Benchmark: FinanceBench. Five human teammates share this repo.

## Start of every session

1. Read `PROGRESS.md` to see the current phase, which tasks are claimed, and what is blocked.
2. Read the current phase in `ROADMAP.md`, then the matching section of `docs/IMPLEMENTATION_GUIDE.md`.
3. Confirm with the human which task ID you are working on before writing code. Work on that one task only.
4. Run `git status` and `git branch --show-current` to understand the working tree.

## End of every session (or task hand-off)

1. Run the local checks: `uv run pre-commit run --all-files` and `uv run pytest -m "not integration"`. Fix failures before handing off.
2. Edit the task's row in `PROGRESS.md` (status, notes) and add one Log line.
3. End your message with a **Human steps** block (see below).

## Git and GitHub: humans only

You never act on Git or GitHub. The humans run every such command; you give them the commands.

- **Allowed (read-only):** `git status`, `git diff`, `git log`, `git show`, `git branch --show-current`.
- **Never run:** `git add`, `commit`, `checkout`, `switch`, `branch` (create/delete), `merge`, `rebase`, `reset`, `stash`, `tag`, `pull`, `fetch`, `push`; any `gh` command; any GitHub API call. Never open, comment on, label, approve, or merge pull requests, trigger workflows, or change repository settings.
- These are also blocked in `.claude/settings.json`. Do not try to work around the block.

At every hand-off, end with one copy-pasteable block, listing specific files (never `git add .` or `git add -A`):

```bash
# Human steps: finish section chunking
git add src/finqa/ingestion/chunk.py tests/test_chunk.py PROGRESS.md
git commit -m "Section-aware chunking with unit scale detection"
git push -u origin section-chunking
gh pr create --base main --title "Section-aware chunking with unit scale" --body "Tests: tests/test_chunk.py"
```

When starting a new task, give the branch commands too (`git switch main && git pull && git switch -c section-chunking`). **Branch names, commit messages, and PR titles/descriptions never contain phase names or task IDs** (ROADMAP T7); use short descriptive names. Task IDs appear only in `ROADMAP.md` and `PROGRESS.md`.

## Rules you must follow

**Scope**
- Work only on tasks in the current phase. Do not start a phase until the previous gate is `done` in `PROGRESS.md`.
- Out of scope, do not build even if it seems helpful: DSPy, LlamaFirewall, Graphiti, fine-tuning, extra models, extra benchmarks, any UI beyond the Streamlit demo.
- If a task raises a research-design question (scoring edge cases, inclusion rules, thresholds), stop and ask. Record the human's decision in `docs/DECISIONS.md`.

**Frozen files** (CI blocks changes without the `approved-freeze-change` label)
- `src/finqa/schemas.py`, `data/splits.json`, frozen prompts in `src/finqa/prompts/`, and the model settings in `configs/base.yaml`. Never edit these without explicit human approval.

**Code**
- Every LLM call goes through `src/finqa/llm.py` (caching, retries, rate limiting, logging). Never call a model client directly.
- Every experiment setting lives in `configs/`. Never hardcode a model ID, threshold, split, or arm.
- Import data contracts from `schemas.py`; don't redefine them.
- Dependencies change only via `uv add` / `uv remove`, with `uv.lock` updated in the same change. Mention any dependency change in your hand-off.
- Unit tests never touch the network. Anything calling Groq, EDGAR, Hugging Face, or yfinance is marked `@pytest.mark.integration`. Use fixtures in `tests/fixtures/`.
- Every task's acceptance criteria in `ROADMAP.md` must be covered by tests.

**Research integrity**
- Correctness is always scored against FinanceBench gold answers, for every configuration. Never use a verifier's verdicts or XBRL to decide correctness. XBRL may only choose an error *type*.
- Never run anything on the test split from a feature branch or a dirty tree; the runner enforces this. Develop and debug on the dev split only.
- Never change a prompt in response to test-set results.
- Don't invent numbers anywhere (results, docs, tests' expected values from real data). If a value is unknown, leave a clearly marked placeholder and ask.
- Market data (yfinance / MCP) is demo-only; never add it to experiment configs.

**Files and data**
- Never commit bulky or generated data (`data/raw/`, `data/xbrl/`, the index), `runs/`, caches, or `.env`. Small curated files in `data/` (`splits.json`, `SCOPE.md`, `QA_CHECKS.md`, `metric_map.yaml`, `companies.csv`, `financebench_audit.csv`) are committed, and only when their task calls for them. Never print secrets.
- Keep changes small and focused on the task; don't reformat or refactor unrelated code.

## Useful commands

```bash
uv sync                                   # install from uv.lock
uv run pytest -m "not integration"        # unit tests
uv run pre-commit run --all-files         # lint and format
uv run mypy src/                          # type check
uv run finqa draft  --config configs/grid/r0_v0.yaml --split dev
uv run finqa verify --run <run_id> --config configs/grid/r0_v1.yaml
uv run finqa report                       # regenerate all tables and figures
uv run python scripts/check_progress.py   # validate PROGRESS.md
```

## Key files

| File | What it is |
|---|---|
| `ROADMAP.md` | Every task, its acceptance criteria, and the gates |
| `PROGRESS.md` | Live status; the single source of truth for what's done |
| `docs/IMPLEMENTATION_GUIDE.md` | How to build each part |
| `docs/DECISIONS.md` | Every design decision, with date, who, and why |
| `docs/LABELING_PROTOCOL.md` | Scoring and error-type rules |
| `CONTRIBUTING.md` | Branching, PRs, local checks, shared artifacts |

## When unsure

Ask. A question costs a minute; a silent wrong assumption in scoring or data handling can invalidate the project's results.
