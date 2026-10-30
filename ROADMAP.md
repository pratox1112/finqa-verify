# ROADMAP

**Project:** When Does Verification Help? Disentangling Agentic Retrieval and Grounded Verification in Numerical Financial QA

**Detailed design:** `docs/IMPLEMENTATION_GUIDE.md` (read the relevant section before starting any phase)

---

## How to use this roadmap (for Claude Code and humans)

1. **Work on one task at a time**, in order, within the current phase. Each task has an ID (e.g. `P1.3`), the files it touches, and acceptance criteria.
2. **A task is done only when its acceptance criteria pass and its pull request is merged with CI green.** Run `uv run pytest` locally first. Status is recorded in `PROGRESS.md`, never in this file.
3. **Do not start a phase until the previous phase's gate is checked.** Gates exist because later phases depend on frozen outputs of earlier ones.
4. **Tasks marked `[HUMAN]`** need a person (decisions, manual checks, annotation). Claude Code should prepare everything around them, then stop and ask. **All Git and GitHub actions are always human actions** (rule T17), even when a task isn't marked `[HUMAN]`.
5. **Never change `src/finqa/schemas.py`, frozen prompts, or `data/splits.json` without explicit human approval.** Every module depends on them.
6. **Never hardcode experiment settings.** Everything that differs between runs lives in `configs/`.
7. **Never call the LLM directly.** Always go through `src/finqa/llm.py` so caching, retries, rate limiting, and logging apply.
8. **Out of scope** (do not build, even if it seems helpful): DSPy, LlamaFirewall, Graphiti, fine-tuning, extra models, extra benchmarks beyond those listed, UI beyond the Streamlit demo.
9. **If a task reveals a research-design question** (e.g. how to treat an edge case in scoring), stop and ask rather than deciding silently. Record the decision in `docs/DECISIONS.md`.
10. **Independent scoring.** Correctness is always judged against FinanceBench gold answers, for every configuration. Never use a verifier's own verdicts to score results, and never use XBRL to decide correctness (XBRL may only be used to classify error *types*).
11. **Everything reaches `main` through a pull request with CI green.** No direct pushes to `main`. One task per branch where practical (branch name: `section-chunking`; no task IDs in Git names, see T7).
12. **Unit tests never touch the network.** Tests that call Groq, EDGAR, Hugging Face, or yfinance are marked `@pytest.mark.integration` and are skipped in the default CI run. Everything else uses mocks or small fixtures in `tests/fixtures/`.

---

## Team rules

Five people and Claude Code share this repo. These rules apply to everyone, including Claude Code.

### Environment

- **T1. `uv` is checked after every merge.** CI re-runs on `main` after each merge and fails if `uv.lock` is out of date (`uv lock --check`) or the environment doesn't install from it (`uv sync --frozen`). Locally, a post-merge Git hook runs `uv sync` automatically whenever a pull or merge changes `uv.lock` (P0.9).
- **T2. Dependencies change only through `uv add` / `uv remove`,** with the updated `uv.lock` committed in the same PR. Never edit `uv.lock` by hand. Call out any dependency change in the PR description.

### CI

- **T3. CI runs on every branch,** on every push and every pull request, not just `main`. A red branch can't be merged (P0.7).
- **T4. Stop the line.** If `main` is ever red, fixing it takes priority over all other work. Nobody merges anything else until it's green.

### Progress tracking

- **T5. `PROGRESS.md` is the single source of truth for status.** Claim a task there before starting it, and update it in the same PR that does the work. CI validates it (P0.10).
- **T6. Claude Code sessions** start by reading `PROGRESS.md` and `ROADMAP.md`, and end by editing the relevant `PROGRESS.md` rows and adding a Log line in the working tree. The human then commits and pushes those edits (T17).

### Branches and pull requests

- **T7. One task per branch,** with a short descriptive name: `section-chunking`, `baseline-table`. **Branch names, commit messages, and PR titles/descriptions never contain phase names or task IDs**; IDs are only for `ROADMAP.md` and `PROGRESS.md`, whose *Branch / PR* column links each task to its branch. PR title example: `Section-aware chunking with unit scale`.
- **T8. Keep PRs small,** ideally under ~400 changed lines. Split larger work into sub-PRs.
- **T9. Every PR needs one approving review from a teammate who didn't write it.** This includes PRs containing code Claude Code wrote: a human must read and approve it before it merges.
- **T10. Rebase on `main` before merging, then squash-merge,** so `main` has one clean commit per task.
- **T11. Code owners.** A `CODEOWNERS` file requires review from the owning role for its area (e.g. Role E for `src/finqa/verifiers/`, Role B for `src/finqa/eval/`), and from two people for frozen files.

### Experiments and data

- **T12. Test-set runs happen only from a clean commit on `main`,** never from a feature branch or with uncommitted changes. The runner refuses to start a test-split run otherwise and records the commit hash in `run_meta.json`.
- **T13. Run IDs follow one format:** `{date}_{config-name}_{short-commit}` (e.g. `2026-11-10_r0_v0_a1b2c3d`), so anyone can trace a result to its exact code and config.
- **T14. Never commit bulky data, runs, caches, or secrets.** Downloaded and generated data (`data/raw/`, `data/xbrl/`, the index), `runs/`, response caches, and `.env` stay out of Git. Small curated files in `data/` (`splits.json`, `SCOPE.md`, `QA_CHECKS.md`, `metric_map.yaml`, `companies.csv`, `financebench_audit.csv`) are committed (see `docs/DECISIONS.md`). Shared artifacts (index, XBRL cache, completed runs, response cache) live in one agreed shared location, recorded in `CONTRIBUTING.md`.
- **T15. Every research-design decision goes in `docs/DECISIONS.md`** with the date, who decided, and why, before the code that implements it is merged.

### Claude Code and GitHub

- **T17. Claude Code never acts on Git or GitHub. Humans run every Git and GitHub command; Claude Code gives them the commands.**
  - **Claude Code may** run read-only Git commands to understand the repository state: `git status`, `git diff`, `git log`, `git show`, `git branch --show-current`.
  - **Claude Code must not** run anything that changes Git state or talks to GitHub: no `git add`, `commit`, `checkout`/`switch`, `branch` (create/delete), `merge`, `rebase`, `reset`, `stash`, `tag`, `pull`, `fetch`, or `push`; no `gh` CLI; no GitHub API calls; no opening, commenting on, labeling, approving, or merging pull requests; no triggering workflows; no changes to repository settings.
  - **Instead, at every hand-off point** (starting a task, finishing a task, after review feedback), Claude Code ends its message with a **"Human steps"** block: the exact commands to run, in order, in one copy-pasteable code block, plus anything to do in the GitHub web UI. For example:

    ```bash
    # Human steps: finish section chunking
    git add src/finqa/ingestion/chunk.py tests/test_chunk.py PROGRESS.md
    git commit -m "Section-aware chunking with unit scale detection"
    git push -u origin section-chunking
    gh pr create --base main --title "Section-aware chunking with unit scale" --body "Tests: tests/test_chunk.py"
    ```

  - Claude Code lists the specific files to stage (never `git add .` or `git add -A`), so nothing unintended gets committed.
  - Before suggesting a commit, Claude Code tells the human to run the local checks first (`uv run pre-commit run --all-files` and `uv run pytest -m "not integration"`) if it hasn't just run them itself.
  - This is enforced in Claude Code's permission settings (P0.11), not just by instruction.

### Communication

- **T16. A short weekly sync** where the team reviews `PROGRESS.md`, clears blockers, and confirms the current phase. Update the Snapshot afterwards.

**Current status:** see [PROGRESS.md](PROGRESS.md). This roadmap is the plan and does not track status; there are no checkboxes to tick here.

---

## Locked decisions

| Item | Value |
|---|---|
| Model | Qwen3.8-27B via Groq (exact model ID confirmed in P0.6) |
| Temperature | 0 |
| Thinking mode | One fixed setting for all runs (default: off), recorded in every log |
| Embeddings | `BAAI/bge-base-en-v1.5`, never changed after P1.6 |
| Vector store | Chroma |
| Agent framework | LangGraph |
| Benchmark | FinanceBench public sample; dev/test split frozen in P2.1 |
| Data | SEC EDGAR filings via `edgartools`; XBRL company facts |
| Grid | Retrieval {`rag`, `agentic`} × Verification {`none`, `self_check`, `grounded`} |
| Shared drafts | Each retrieval arm generates drafts once; all verification arms run on the same saved drafts |

---

## Milestones

| Milestone | Requires | Deliverable |
|---|---|---|
| **M1: Midterm report** | Gates 0, 1, 2 + Phase M1 | 4-page report (NeurIPS template): Intro & Motivation (3), Related Work (2), Methods (4), Preliminary Results (5) |
| **M2: Final report** | All gates | Final report, presentation, demo |

**Path to M1:** Phase 0 → Phase 1 → Phase 2 (including P2.5, P2.6) → P3.0, P3.1, P3.2, P3.5, P3.6 → Phase M1. Everything else waits until after the midterm.

---

## Phase 0: Foundations and contracts

**Goal:** a skeleton every teammate can build on in parallel, and proof that the model works.

- **P0.1 Repository skeleton**
  - Create the directory layout from `docs/IMPLEMENTATION_GUIDE.md` §0.1, `pyproject.toml`, `.gitignore` (must include `.env`, `data/`, `runs/`, cache directories), `.env.example`.
  - *Accept:* `uv sync` succeeds on a clean clone; `uv run pytest` runs (zero tests is fine).

> Do P0.7–P0.11 immediately after P0.1, so every later task goes through CI. (They are numbered P0.7+ only to keep existing task IDs stable.)

- **P0.7 CI pipeline** — `.github/workflows/ci.yml`
  - Triggers (T3): **every push to any branch** (`push: branches: ['**']`) and **every pull request, whatever its target branch**. Add a `concurrency` group per branch with `cancel-in-progress: true`, so a new push cancels the outdated run instead of queueing.
  - Steps, each a separate job or step so failures are easy to read:
    1. Set up Python 3.11 and `uv` (with dependency caching); run `uv lock --check` (fails if `uv.lock` doesn't match `pyproject.toml`) and `uv sync --frozen` (fails if the environment can't be installed exactly from the lockfile).
    2. **Lint and format:** `ruff check .` and `ruff format --check .`.
    3. **Type check:** `mypy src/` (start lenient; tighten once modules stabilize).
    4. **Unit tests:** `pytest -m "not integration"` with coverage reported. No secrets available, so any test that tries the network fails loudly.
    5. **Config validation:** load every YAML in `configs/` through the config loader and fail on any invalid file.
    6. **Pipeline smoke test:** run the dummy generator and dummy verifier through both runner stages on a 3-question fixture (`tests/fixtures/`), and check the output files and results table are produced.
  - Target: the whole workflow finishes in under ~5 minutes.
  - **Post-merge check on `main` (T1):** the same workflow runs on every push to `main`, which is every merge. A failure here means a merge broke `main` and triggers T4 (stop the line). Show the `main` status badge in the README so a red `main` is visible to everyone.
  - Separate, optional `.github/workflows/integration.yml`: manual trigger only (`workflow_dispatch`), uses repository secrets (`GROQ_API_KEY`, `EDGAR_IDENTITY`), runs `pytest -m integration`. Use it before large experiment runs to confirm external services still behave. Never run it on every PR (it costs tokens and depends on outside services).
  - *Accept:* a push to a feature branch triggers CI; a PR with a deliberately failing test is blocked; a PR that changes `pyproject.toml` without updating `uv.lock` fails; a clean PR passes; the post-merge run on `main` appears after merging.

- **P0.8 Frozen-file guard** — part of `ci.yml`
  - Fails the PR if it modifies any frozen file — `src/finqa/schemas.py`, `data/splits.json`, anything in `src/finqa/prompts/` marked frozen, or `configs/base.yaml` model settings — **unless** the PR carries the label `approved-freeze-change`.
  - This enforces rule 5 automatically instead of relying on memory.
  - *Accept:* a PR touching `schemas.py` without the label fails; with the label it passes.

- **P0.9 Branch protection and local hooks**
  - **[HUMAN]** In GitHub settings for `main`: require a pull request, require CI to pass, require one approving review from a teammate, and block force-pushes.
  - `.pre-commit-config.yaml` running `ruff` and `ruff format` (plus a check that `.env` is never committed), so most CI failures are caught before pushing.
  - **Post-merge hook (T1):** a `post-merge` (and `post-checkout`) hook, installed via pre-commit with `pre-commit install --hook-type post-merge --hook-type post-checkout`, that runs `uv sync` whenever `uv.lock` changed in the pull or merge, so nobody runs code against a stale environment.
  - `.github/CODEOWNERS` mapping each area to its role owner (T11); frozen files require two reviewers.
  - `CONTRIBUTING.md`: branch and PR naming (T7), how to run checks locally (`uv run pre-commit run --all-files`, `uv run pytest -m "not integration"`), the shared artifact location (T14), and how to request an `approved-freeze-change`.
  - *Accept:* direct push to `main` is rejected; pre-commit runs on commit; pulling a change to `uv.lock` triggers `uv sync` automatically.

- **P0.10 Progress check** — part of `ci.yml`
  - A script (`scripts/check_progress.py`) that fails CI if `PROGRESS.md` is malformed: every task and gate ID in `ROADMAP.md` appears exactly once; every status is one of `todo`, `in-progress`, `review`, `blocked`, `done`; every `done` row has a PR link; every `blocked` row has a matching entry under Blockers.
  - Fail any pull request that doesn't modify `PROGRESS.md`, unless it carries the label `no-progress-update` (T5; decided in `docs/DECISIONS.md`, since branch names carry no task IDs).
  - *Accept:* a PR with an invalid status, a missing task ID, or no `PROGRESS.md` change (and no exempt label) fails; a correct PR passes.

- **P0.11 Claude Code guardrails** — `.claude/settings.json` and `CLAUDE.md`
  - **[HUMAN]** creates and commits these files (they govern Claude Code, so Claude Code drafts them and a person reviews them).
  - `.claude/settings.json`: a permissions **deny** list that blocks state-changing Git and all GitHub commands (T17), for example `Bash(git add:*)`, `Bash(git commit:*)`, `Bash(git push:*)`, `Bash(git pull:*)`, `Bash(git merge:*)`, `Bash(git rebase:*)`, `Bash(git checkout:*)`, `Bash(git switch:*)`, `Bash(git reset:*)`, `Bash(gh:*)`, plus an **allow** list for the read-only commands (`Bash(git status)`, `Bash(git diff:*)`, `Bash(git log:*)`). Check the current Claude Code documentation for the exact rule syntax.
  - `CLAUDE.md` at the repo root: read `PROGRESS.md` and `ROADMAP.md` at session start; work only on the current phase; follow all rules in this file; never run Git or GitHub commands; end every hand-off with a "Human steps" block.
  - Commit `.claude/settings.json` so the rules apply to every teammate's Claude Code. Personal overrides go in `.claude/settings.local.json`, which is gitignored and must not loosen the deny list.
  - *Accept:* in a test session, asking Claude Code to commit or push is refused by the permission system, and it responds with a "Human steps" block instead.

- **P0.2 Configuration system**
  - `configs/base.yaml`, six grid configs in `configs/grid/` (`r0_v0.yaml` … `r1_v2.yaml`), and a loader in `src/finqa/config.py` using Pydantic Settings that merges base + override.
  - *Accept:* test loads every grid config and asserts the correct `retrieval.arm` and `verification.arm`.

- **P0.3 Shared schemas**
  - `src/finqa/schemas.py` with `Chunk`, `Claim`, `Draft`, `Verdict`, `VerifiedResult`, `ErrorType`, `Annotation` exactly as specified in the guide §0.4.
  - *Accept:* round-trip JSON serialization test for every model.
  - **[HUMAN]** Team reviews and approves the schemas. After approval they are frozen.

- **P0.4 LLM wrapper**
  - `src/finqa/llm.py`: model construction via `init_chat_model` from config; thinking-mode control; `tenacity` retry with exponential backoff on 429/5xx; client-side requests-per-minute and tokens-per-minute limiter; on-disk response cache keyed by hash of (model ID, thinking setting, messages, tools, temperature); token usage logging.
  - *Accept:* tests with a mocked model confirm (a) a repeated call hits the cache, (b) a 429 triggers retry, (c) cache keys differ when any key component differs.

- **P0.5 Tracing**
  - Langfuse integration in the LLM wrapper and tool calls, tagged with `run_id` and `question_id`. Disabled cleanly when keys are absent.
  - *Accept:* a test call appears in Langfuse with both tags (manual check), and tests pass with tracing disabled.

- **P0.6 Model pilot** — the riskiest task in the project
  - **[HUMAN]** Confirm the exact Qwen3.8-27B model ID and the thinking-mode parameter in the Groq console and docs. Record both in `docs/DECISIONS.md`.
  - `scripts/pilot.py`: on 20 hand-picked FinanceBench questions, measure tool-call success with two dummy tools, structured-output validity, and tokens per call.
  - *Accept:* tool-call success ≥ 95% and structured-output validity ≥ 95%. Results written to `docs/PILOT.md` with mean and max tokens per call.
  - If below target: stop and report to the team before continuing.

- **GATE 0:** CI runs on every branch and blocks failing merges; post-merge `uv` check runs on `main`; branch protection and CODEOWNERS on; PROGRESS.md validated by CI; Claude Code guardrails in place; schemas approved and frozen (and guarded by P0.8); pilot passes; every teammate can run the checks locally.

---

## Phase 1: Data

**Goal:** every in-scope filing parsed, chunked, indexed, and checked; XBRL facts cached.

- **P1.1 FinanceBench audit**
  - `src/finqa/ingestion/financebench.py`: download the public sample, produce `data/financebench_audit.csv` (company, document name, document type, period, question type, gold answer).
  - **[HUMAN]** Decide which document types are in scope (10-K and 10-Q only, or also 8-Ks/earnings releases). Write the decision and excluded-question count to `data/SCOPE.md`.
  - *Accept:* audit CSV exists; `SCOPE.md` records the decision.

- **P1.2 Gold value extraction**
  - Parse every numeric gold answer into (value, unit) using the shared number normalizer (create `src/finqa/verifiers/numbers.py` now; it is reused by scoring and verification).
  - *Accept:* tests cover "$1.2B", "1.2 billion", "1,200 million", "(1,234)", "12.5%", "$3.45 per share". Non-numeric answers are flagged, not dropped.

- **P1.3 Company table**
  - `data/companies.csv`: ticker, CIK, name, former names, brand aliases, for every in-scope company, sourced from the SEC company ticker file.
  - *Accept:* every FinanceBench company maps to exactly one CIK.

- **P1.4 Filing download**
  - `src/finqa/ingestion/download.py`: download all 10-K and 10-Q filings per company from two fiscal years before the company's earliest FinanceBench year through one year after its latest (decided 2026-10-30, `docs/DECISIONS.md`). Cache-first (never re-download). Identity read from `EDGAR_IDENTITY`.
  - *Accept:* `data/raw/` contains every expected filing; a manifest lists accession, form, fiscal year, period, filing date.

- **P1.5 Section parsing**
  - `src/finqa/ingestion/parse.py`: structured section extraction via edgartools; regex fallback on "Item N." headings; every fallback logged.
  - *Accept:* fallback rate reported per company; tests on two sample filings.

- **P1.6 Chunking and unit scale**
  - `src/finqa/ingestion/chunk.py`: text chunks of ~500–800 tokens with ~100 overlap on paragraph boundaries; tables as single markdown chunks, split into row groups with the header repeated when over ~1,500 tokens; `unit_scale` detected from captions ("in millions", "in thousands, except per share"); deterministic chunk IDs.
  - *Accept:* tests confirm a split table repeats its header, unit scale is detected on sample tables, and chunk IDs are stable across two runs.

- **P1.7 Embedding and index**
  - `src/finqa/ingestion/index.py`: embed with the locked model; load into Chroma with all metadata filterable.
  - *Accept:* a filtered query (company + year + section) returns only matching chunks.

- **P1.8 XBRL cache and lookup**
  - `src/finqa/ingestion/xbrl.py`: download company facts once per company to `data/xbrl/`; lookup of (CIK, concept, period end, fiscal period) → **all** reported values with accession and filing date.
  - `data/metric_map.yaml`: metric names → XBRL concepts, starting with metrics used in FinanceBench questions.
  - *Accept:* lookup returns multiple values for at least one known restated item (find one manually to test).

- **P1.9 Quality checks**
  - **[HUMAN]** For every company, inspect at least one parsed 10-K (sections, tables intact, unit scale correct). Record results in `data/QA_CHECKS.md`.
  - Claude Code: generate a review sheet per company showing sample chunks and detected unit scales to make this fast.

- **GATE 1:** every in-scope filing indexed; XBRL cache and metric map exist; QA checks recorded.

---

## Phase 2: Evaluation harness

**Goal:** any generator and any verifier can be run, resumed, scored, and tabulated the same way.

- **P2.1 Question types and split**
  - Model-proposed type tags (`single_fact`, `multi_period`, `calculation`, `qualitative`) written to a sheet.
  - **[HUMAN]** Confirm every tag.
  - Create `data/splits.json` with ~20 dev questions (stratified by type) and the rest as test.
  - *Accept:* split committed. **From this point `splits.json` is frozen.**

- **P2.2 Runner**
  - `src/finqa/eval/runner.py` with two stages: `draft` (generator → `runs/{run_id}/drafts.jsonl`) and `verify` (saved drafts + verifier → `runs/{run_id}/verified_{arm}.jsonl`). Fresh thread ID per question. Resumable (skips completed question IDs). Writes `run_meta.json` (config, git commit, model ID, thinking setting, date, package versions).
  - CLI: `uv run finqa draft --config configs/grid/r1_v0.yaml --split dev` and `uv run finqa verify --run <id> --config ...`.
  - Run IDs use the T13 format. For `--split test`, the runner refuses to start unless the working tree is clean and `HEAD` is a commit on `main` (T12).
  - *Accept:* a dummy generator (always answers 42) and dummy verifier run end to end; killing and restarting resumes correctly; a test-split run from a dirty tree or a feature branch is refused.

- **P2.3 Scoring**
  - `src/finqa/eval/scoring.py`: claim-level and answer-level automatic correctness using the shared normalizer and configured tolerance; non-numeric questions scored separately.
  - *Accept:* tests with hand-made claims at, inside, and outside tolerance.

- **P2.4 Results tables**
  - `src/finqa/eval/tables.py`: accuracy by question type with counts, claim-level correctness, latency and token percentiles, estimated cost.
  - **Every percentage is reported with its count (e.g. "8/10, 80%")** and a question-level bootstrap 95% confidence interval (`src/finqa/eval/stats.py`, bootstrap part only; the rest of Phase 9 comes later).
  - *Accept:* produces a markdown table with counts and CIs from the dummy run.

- **P2.5 Rule-based error classifier** — `src/finqa/eval/error_types.py` (needed for M1)
  - For every claim already scored **incorrect against gold**, assign one `ErrorType` by rule, checked in this order:
    1. `wrong_unit_or_scale`: claimed / correct ≈ 10³, 10⁶, or 10⁹ (or the inverse), within tolerance.
    2. `wrong_period`: value matches the same metric, same company, different period in the XBRL lookup.
    3. `wrong_line_item`: value matches a different metric, same company and period.
    4. `wrong_company`: value matches another in-scope company's figure for the same metric and period.
    5. `arithmetic`: claim has an `expression` whose inputs are correct but whose result is not.
    6. `retrieval_miss`: none of the draft's evidence chunks contains the gold evidence (from P2.6).
    7. `other`: no rule fired.
  - Correctness itself comes only from gold answers (rule 10); XBRL is used here only to pick the error type.
  - Write the rules, tolerance, unit normalization, fiscal-period matching, and derived-value handling to `docs/LABELING_PROTOCOL.md` (this text goes into the midterm Methods section).
  - *Accept:* unit tests with one hand-made example per error type; `LABELING_PROTOCOL.md` exists.

- **P2.6 Retrieval diagnostic** — `src/finqa/eval/retrieval_diag.py` (needed for M1)
  - For each question, check whether FinanceBench's gold evidence text appears in the draft's evidence chunks (normalized text overlap above a threshold; record the threshold in `DECISIONS.md`).
  - Output per question: `gold_evidence_retrieved: bool`, plus the best-matching chunk ID.
  - *Accept:* tests on hand-made evidence/chunk pairs; spot-check 10 real questions by hand.

- **GATE 2:** dummy system runs through both stages and produces tables with counts and CIs; error classifier and retrieval diagnostic tested; split frozen.

---

## Phase 3: Retrieval arms

**Goal:** both generators produce complete, structured drafts on the test set.

- **P3.0 Closed-book generator (S0)** — `src/finqa/generators/closed_book.py` (needed for M1)
  - The question goes straight to the model with no retrieval and no tools; output is a `Draft` with claims and an empty evidence set. Config: `configs/baselines/s0_closed_book.yaml`.
  - Doubles as the contamination check (also reused in P7.5).
  - *Accept:* produces valid `Draft` objects on all dev questions.

- **P3.1 Company resolver** — `src/finqa/tools/resolver.py`
  - `rapidfuzz` over names, tickers, former names, aliases; returns one match above threshold or a candidate list.
  - *Accept:* tests for Alphabet's share classes, Meta under its former name, a brand name, and an ambiguous name.

- **P3.2 Filing search tool** — `src/finqa/tools/search.py`
  - `search_filings(cik, fiscal_year, section, query)` returning chunks with IDs.
  - *Accept:* filters are respected; returned chunks carry IDs.

- **P3.3 On-demand fetch tool** — `src/finqa/tools/fetch.py`
  - `fetch_filing(cik, form, fiscal_year)` reusing Phase 1 code; no-op if already indexed.
  - *Accept:* fetching an unindexed filing makes it searchable.

- **P3.4 Calculator tool** — `src/finqa/tools/calculate.py`
  - `calculate(expression, variables)` via `asteval`; returns result and expression; rejects anything that isn't arithmetic.
  - *Accept:* tests for growth rate, margin, ratio; rejection of non-arithmetic input.

- **P3.5 Single-shot RAG generator** — `src/finqa/generators/rag.py`
  - Resolve company → filtered top-k retrieval → one structured call producing a `Draft` with claims and chunk citations.
  - *Accept:* produces valid `Draft` objects on all dev questions.
  - **[HUMAN] Early freeze for M1:** approve and freeze the S0 and R0 prompts before any test-set run (record the commit hash in `docs/DECISIONS.md`). After this, do not change them based on test results. If the team isn't ready to freeze, M1 reports dev-set numbers only, labeled preliminary.

- **P3.6 Agent generator** — `src/finqa/generators/agent.py`
  - LangGraph state (`messages` append reducer, `company`, `evidence` merge reducer, `claims`, `steps_used`); `agent` → `tools` | `finalize`; system prompt rules from the guide §3.3; step limit from config; tool-result caching; `MemorySaver` with fresh thread per question.
  - *Accept:* produces valid `Draft` objects on all dev questions; evidence contains every chunk retrieved.
  - **[HUMAN]** Read 20 agent traces and note failure patterns in `docs/TRACE_REVIEW.md`.

- **P3.7 Freeze prompts**
  - Move all generator prompts into `src/finqa/prompts/` as versioned files (S0 and R0 are already frozen from P3.5).
  - **[HUMAN]** Approve and freeze the agent prompt. Record the commit hash in `docs/DECISIONS.md`.

- **P3.8 Test-set drafts**
  - Run both arms on the test split.
  - *Accept:* `runs/` contains complete draft sets for R0 and R1; every test question present.

- **P3.9 Retrieval × calculator design** (answers the TA's proposal question; after M1)
  - Add two arms so retrieval and the calculator can be separated in a 2 × 2 design:
    - `R0+calc`: single-shot retrieval, then the model writes its arithmetic as an expression evaluated by `calculate`.
    - `R1−calc`: the agent with the calculator tool removed.
  - Configs in `configs/ablations/`. Run on the test split with V0 only.
  - *Accept:* the 2 × 2 table (R0, R0+calc, R1−calc, R1) produced with counts and CIs.

- **GATE 3:** R0 and R1 test drafts complete; agent prompt frozen before its test run; 2 × 2 arms complete.

---

## Phase M1: Midterm results and report

**Goal:** every result the 4-page midterm report needs, produced by commands, not by hand. Starts once Gates 0–2 are checked and P3.0, P3.1, P3.2, P3.5 (with early freeze) are done. P3.6 only needs to run on dev for M1.

Report sections and points: Intro & Motivation (3), Related Work (2), Methods (4), **Preliminary Results (5)**. Results carry the most points; if space runs out, cut Methods prose before cutting results.

### Results to produce (for the Preliminary Results section)

- **M1.1 S0 on test** — run the closed-book generator on the full test split.
- **M1.2 R0 on test** — run single-shot RAG on the full test split with the frozen R0 prompt; apply V0 so results flow through the standard pipeline.
- **M1.3 Main baseline table** — S0 vs R0 accuracy by question type, with counts and bootstrap 95% CIs, plus latency and tokens per question. → `docs/RESULTS.md` Table M1-A.
- **M1.4 Retrieval diagnostic** — run P2.6 on R0 drafts. Report: share of questions where gold evidence was retrieved; R0 accuracy when it was vs when it wasn't. → Table M1-B.
- **M1.5 R0 error breakdown** — run P2.5 on R0's incorrect claims. Bar chart of error types with counts. → Figure M1-1 (`docs/figures/m1_error_types.pdf`).
  - **[HUMAN]** Spot-check 20 classified errors against the filings and note the agreement; report it in one sentence.
- **M1.6 Contamination check** — S0 accuracy overall and by question type, with a short interpretation in `docs/RESULTS.md`. Flag it prominently if closed-book accuracy is high.
- **M1.7 Pipeline and model reliability table** — companies, filings, chunks, tables, parsing fallback rate, unit-scale detection rate, scope exclusions (from `SCOPE.md`), and model pilot results (from `PILOT.md`). → Table M1-C.
- **M1.8 (Optional) Agent on dev** — R1 vs R0 on the same ~20 dev questions. **Must be labeled dev-only and too small for conclusions.** Never put agent test-set numbers in M1 (its prompt isn't frozen yet).
- **M1.9 One command** — `uv run finqa report --milestone m1` regenerates every M1 table and figure from saved runs.

### Written material (for the Methods and Related Work sections)

- **M1.10 Methods documents** — make sure these exist and are current: `docs/LABELING_PROTOCOL.md` (from P2.5), the independent scoring rule (rule 10 above), the 2 × 3 grid and the 2 × 2 retrieval × calculator design (P3.9, described even though not yet run), and the RQ2 designs (Phases 6 and 7).
- **M1.11 Related work and contribution statement** — **[HUMAN]** update per the proposal feedback: add numerical-claim verification work (FinGround, VeriFin, CoVe, CRITIC, Huang et al.), and replace the commercial comparison with an accurate one (commercial systems do verify, but their methods aren't published or testable; this project's contribution is the explicit three-part per-number check with open ablations).
- **M1.12 Architecture figure** — update the TikZ figure from the proposal to reflect the grid and the 2 × 2 design.

### Report

- **M1.13 Draft the report** — **[HUMAN]** 4 pages including references, NeurIPS template, using the results and documents above. Section budget: Intro ~0.6 page, Related Work ~0.5, Methods ~1.1, Preliminary Results ~1.3, Next Steps + references ~0.5.
- **M1.14 Final check** — every percentage has a count; every rate has a CI; dev-only numbers are labeled; page limit met.

- **GATE M1:** midterm report submitted.

---

## Phase 4: Verification arms

**Goal:** all six grid cells have verified results on the test set.

- **P4.1 Verifier interface and V0** — `src/finqa/verifiers/base.py`, `none.py`
  - `verify(draft, cfg) -> VerifiedResult`. V0 returns the draft unchanged.
  - *Accept:* V0 output equals input claims.

- **P4.2 V1: LLM self-check** — `src/finqa/verifiers/self_check.py`
  - Chain-of-Verification-style prompt over the draft and its cited evidence; revised claims become the new draft; repeat up to `max_revisions` while claims change.
  - **[HUMAN]** Approve and freeze the self-check prompt (it is reported verbatim in the paper).
  - *Accept:* runs on dev drafts; `claims_before` and `claims_after` both saved.

- **P4.3 V2 check 1: cited text** — `src/finqa/verifiers/grounded.py`
  - Extract and normalize numbers from cited chunks using `unit_scale`; match within tolerance.
  - *Accept:* tests including a millions-scaled table versus a billions-stated claim.

- **P4.4 V2 check 2: XBRL**
  - Map metric → concepts via `metric_map.yaml`; compare to the period's value. No mapping → `ok=None`, never `False`.
  - *Accept:* tests for match, mismatch, and unmapped metric.

- **P4.5 V2 check 3: recomputation**
  - Re-evaluate `expression` from `derived_from` claim values.
  - *Accept:* tests for correct and incorrect derived values.

- **P4.6 Revision loop**
  - Specific feedback message per failed claim → same generator revises → re-verify, up to `max_revisions`; remaining failures flagged.
  - *Accept:* integration test where a planted error gets corrected in one round.

- **P4.7 Planted-error suite** — `tests/planted/`
  - ~20 hand-made drafts covering every error type. V2 must catch all checkable ones; record V1's catch rate in `docs/PLANTED_ERRORS.md`.

- **P4.8 Run the grid**
  - Apply V0, V1, V2 to both saved draft sets.
  - *Accept:* six `verified_*.jsonl` files covering every test question.

- **GATE 4 (feature freeze):** all six cells complete. **No new features after this gate.** Only bug fixes, analysis, and writing.

---

## Phase 5: Annotation

**Goal:** every claim has an agreed human label.

- **P5.1 Guidelines** — **[HUMAN]** write `annotation/guidelines.md` (claim definition, correctness and tolerance, each error type with examples, pre-decided edge cases).
- **P5.2 Export tooling** — `src/finqa/eval/annotation.py`: export claims from all six cells into label sheets with question, gold answer, cited text, and automatic pre-label, **with the grid cell hidden** and rows shuffled; assign two annotators per claim with rotating pairs.
- **P5.3 Pilot** — **[HUMAN]** all five label the same 30 claims; discuss; revise guidelines.
- **P5.4 Main round** — **[HUMAN]** two labels per claim.
- **P5.5 Agreement** — compute Cohen's kappa for correctness and error type; produce a disagreement sheet.
- **P5.6 Adjudication** — **[HUMAN]** resolve disagreements; third person decides any remaining.
- **GATE 5:** every claim has one final label; kappa recorded in `docs/RESULTS.md`.

---

## Phase 6: RQ2a — Restatements

- **P6.1 Detection** — `src/finqa/rq2/restatements.py`: find (company, concept, period) groups with differing values across filings beyond rounding.
- **P6.2 Question set** — templated questions for 30–50 cases with original value, restated value, and source filings recorded in `data/rq2_restatements.jsonl`.
- **P6.3 Runs** — agentic arm with V0 and V2 (`configs/rq2/restatement_*.yaml`).
- **P6.4 Analysis** — share of answers reporting original, restated, or neither; V2 false-rejection rate on original-filing-correct claims.
- **GATE 6:** results table in `docs/RESULTS.md`.

---

## Phase 7: RQ2b — Controlled perturbation

- **P7.1 Selection** — test questions where the R1 draft retrieved the gold evidence chunk.
- **P7.2 Perturbation** — `src/finqa/rq2/perturb.py`: change the key number by a fixed factor; keep tables internally consistent (avoid summed figures or adjust totals). Tests verify consistency.
- **P7.3 Injection runs** — inject the perturbed chunk directly into evidence (bypass retrieval); run V0 and V2.
- **P7.4 Company tiers** — fetch market caps once with `yfinance`, freeze to `data/company_tiers.csv`.
- **P7.5 Closed-book baseline** — reuse the P3.0 generator on the same questions (contamination check).
- **P7.6 Analysis** — context-faithfulness vs memory rate by tier; V2 detection rate; closed-book accuracy.
- **GATE 7:** results table in `docs/RESULTS.md`.

---

## Phase 8: Verification coverage

- **P8.1** From V2 verdicts: share of claims each check could run on; share with no check; accuracy for checkable vs uncheckable claims; top reasons a check couldn't run.
- **GATE 8:** coverage table in `docs/RESULTS.md`.

---

## Phase 9: Variance and statistics

- **P9.1 Variance** — rerun R1-V0 and R1-V2 three times on a 40-question subset with the cache disabled; report spread.
- **P9.2 Error-type figure** — stacked bars of error types per grid cell (the main RQ1 figure).
- **P9.3 Paired tests** — `src/finqa/eval/stats.py`: McNemar's test between planned cell pairs with Holm correction.
- **P9.4 Confidence intervals** — extend the P2.4 bootstrap to every reported rate in the final results.
- **P9.5 Flip matrices** — for V1 and V2, before vs after revision.
- **P9.6 Cost and latency** per cell.
- **P9.7 Examples** — **[HUMAN]** pick 2–3 representative examples per error type with traces.
- **GATE 9:** all figures and tables generated by a single command: `uv run finqa report`.

---

## Phase 10: Demo

- **P10.1 MCP market-data server** — `src/finqa/tools/mcp_market.py` (`get_price`, `get_financials` via `yfinance`, timestamped logging). Demo only; not used in experiment configs.
- **P10.2 Streamlit app** — `app/`: question box, resolved company, answer with per-number badges (verified / revised / unverifiable), clickable citations, live-data toggle, preset restatement and perturbation examples.
- **GATE 10:** demo runs from a clean clone with one command.

---

## Phase 11: Report and reproducibility

- **P11.1 README** — setup, environment variables, and exact commands to reproduce every table.
- **P11.2 Reproducibility package** — configs, frozen prompts, `splits.json`, `SCOPE.md`, `DECISIONS.md`, and the response cache if size allows.
- **P11.3 Final report** — **[HUMAN]** motivation, related work (FinGround and VeriFin positioning), methods, RQ1, RQ2a, RQ2b, coverage, limitations, future work.
- **P11.4 Presentation** — **[HUMAN]**
- **GATE 11:** submitted.

---

## Living documents

| File | Purpose |
|---|---|
| `PROGRESS.md` | **Live status of every task and gate (single source of truth)** |
| `docs/IMPLEMENTATION_GUIDE.md` | Detailed design for every phase |
| `docs/DECISIONS.md` | Every design decision with date and reason |
| `docs/PILOT.md` | Model pilot results |
| `docs/RESULTS.md` | All results tables as they are produced |
| `data/SCOPE.md` | What is in and out of scope, with counts |
| `CONTRIBUTING.md` | Branching, local checks, PR and freeze-change process |
| `CLAUDE.md` | Instructions Claude Code reads every session (including T17) |
| `.claude/settings.json` | Claude Code permissions enforcing T17 |
