# Implementation Guide

**When Does Verification Help? Disentangling Agentic Retrieval and Grounded Verification in Numerical Financial QA**

This guide explains **how** to build each part of the project. [`ROADMAP.md`](../ROADMAP.md) lists the tasks and gates, [`PROGRESS.md`](../PROGRESS.md) tracks status, and [`CLAUDE.md`](../CLAUDE.md) tells Claude Code how to work. Section numbers here (for example §0.4) are referenced from the roadmap, so keep them stable.

---

## 0. Locked decisions

| Decision | Choice |
|---|---|
| **RQ1** | Do agentic retrieval and grounded verification fix the same errors or different ones? |
| **RQ2** | What happens when evidence conflicts? (a) natural restatements, (b) controlled perturbations |
| **Supporting result** | Verification coverage using free public data only |
| **Model** | Qwen3.8-27B via Groq (exact model ID confirmed in the pilot, P0.6) |
| **Temperature / thinking** | Temperature 0; one fixed thinking setting for every run (default: off), recorded in every log |
| **Embeddings** | `BAAI/bge-base-en-v1.5`, fixed after the index is built |
| **Vector store** | Chroma |
| **Agent framework** | LangGraph |
| **Benchmark** | FinanceBench public sample (~150 questions), frozen dev/test split |
| **Data** | SEC EDGAR filings via `edgartools`; XBRL company facts |
| **Scoring** | Correctness always judged against FinanceBench gold answers, for every configuration. Never by a verifier's own verdicts, never by XBRL |

### The experimental designs

**Main grid (RQ1):** retrieval × verification, 2 × 3.

| | V0: none | V1: LLM self-check | V2: grounded |
|---|---|---|---|
| **R0: single-shot RAG** | R0-V0 | R0-V1 | R0-V2 |
| **R1: agentic** | R1-V0 | R1-V1 | R1-V2 |

**Retrieval × calculator (separates the two changes between R0 and R1):** 2 × 2, verification V0 only.

| | No calculator | Calculator |
|---|---|---|
| **Single-shot retrieval** | R0 | R0+calc |
| **Agentic retrieval** | R1−calc | R1 |

**Baseline:** S0, closed-book (no retrieval, no tools). It is also the contamination check.

**Shared drafts:** each retrieval arm generates drafts **once**. All three verification conditions run on the **same saved drafts**, so any difference between verification conditions comes only from verification.

---

## 1. Team roles

| Role | Owns | Phases |
|---|---|---|
| **A. Data** | Ingestion, chunking, index, XBRL cache | 1, then 6 |
| **B. Evaluation** | Question set, harness, scoring, error classifier, statistics, results tables | 2, M1 results, 9 |
| **C. Agent** | Generators (S0, R0, R1 and the 2 × 2 arms), prompts, agent state | 3 |
| **D. Tools and infra** | Resolver, search, fetch, calculator, MCP server, CI, demo | 0 (CI), 3 (tools), 10 |
| **E. Verification** | Self-check, grounded verifier, revision loop | 4, then 7 |

Team members: Dheepak Karan Elumalai Santhakumari, Mohammed Ibrahim, Pratosh Karthikeyan, Rahul Vishnuvardhana, Shubh Bharatkumar Panchal. Record the role assignments in `PROGRESS.md`. Everyone annotates in Phase 5. One person also owns **integration**: every configuration runs end to end through the same harness.

---

## 2. Timeline

| Week | Dates | Work | Milestone |
|---|---|---|---|
| 1 | Oct 29 – Nov 4 | Phase 0 (CI and guardrails first), start Phases 1–2 | Contracts agreed; pilot passes |
| 2 | Nov 5 – 11 | Phases 1–2, start Phase 3 | Index built; harness runs; dev/test split frozen |
| 3 | Nov 12 – 18 | S0, R0 on test; Phase M1 | **M1: midterm report** |
| 4 | Nov 19 – 25 | Agent, 2 × 2 arms, verifiers (Thanksgiving: lighter week) | R1 drafts |
| 5 | Nov 26 – Dec 2 | Full grid, Phases 5–7 start | **Feature freeze (Gate 4)** |
| 6 | Dec 3 – 9 | Phases 5–9 | All results and statistics |
| 7 | Dec 10 → | Phases 10–11 | **M2: final report, presentation, demo** |

Adjust once the midterm and final dates are confirmed.

---

## Phase 0: Foundations, contracts, and collaboration

### 0.1 Repository layout

```
<repo-name>/
├── .github/
│   ├── workflows/ci.yml          # every branch, every PR, post-merge on main
│   ├── workflows/integration.yml # manual trigger only
│   └── CODEOWNERS
├── .claude/settings.json         # Claude Code permissions (Git/GitHub denied)
├── CLAUDE.md                     # instructions Claude Code reads every session
├── ROADMAP.md  PROGRESS.md  CONTRIBUTING.md  README.md
├── configs/
│   ├── base.yaml
│   ├── baselines/                # s0_closed_book.yaml
│   ├── grid/                     # r0_v0.yaml ... r1_v2.yaml
│   ├── ablations/                # r0_calc.yaml, r1_nocalc.yaml, verifier ablations
│   └── rq2/                      # restatement and perturbation configs
├── docs/
│   ├── IMPLEMENTATION_GUIDE.md   # this file
│   ├── DECISIONS.md  PILOT.md  RESULTS.md  LABELING_PROTOCOL.md
│   ├── TRACE_REVIEW.md  PLANTED_ERRORS.md
│   └── figures/
├── src/finqa/
│   ├── schemas.py  config.py  llm.py
│   ├── ingestion/                # financebench, download, parse, chunk, index, xbrl
│   ├── tools/                    # resolver, search, fetch, calculate, mcp_market
│   ├── generators/               # closed_book, rag, agent
│   ├── verifiers/                # base, none, self_check, grounded, numbers
│   ├── prompts/                  # versioned prompt files (frozen ones marked)
│   ├── eval/                     # runner, scoring, error_types, retrieval_diag,
│   │                             #   tables, stats, annotation
│   └── rq2/                      # restatements, perturb
├── scripts/                      # pilot.py, check_progress.py
├── data/                         # curated files committed; raw/, xbrl/, index gitignored
├── runs/                         # gitignored
├── annotation/                   # guidelines, label sheets
├── app/                          # Streamlit demo
├── tests/   tests/fixtures/  tests/planted/
├── .pre-commit-config.yaml  .env.example  pyproject.toml  uv.lock
```

### 0.2 Environment

- Python 3.11, dependencies managed with `uv`. `uv.lock` is committed and only changes through `uv add` / `uv remove`.
- Core dependencies: `langgraph`, `langchain`, `langchain-groq`, `langchain-mcp-adapters`, `mcp`, `edgartools`, `yfinance`, `sentence-transformers`, `chromadb`, `pydantic`, `pydantic-settings`, `pyyaml`, `asteval`, `rapidfuzz`, `pandas`, `scipy`, `statsmodels`, `tenacity`, `langfuse`, `streamlit`.
- Dev dependencies: `pytest`, `pytest-cov`, `ruff`, `mypy`, `pre-commit`.
- `.env.example`: `GROQ_API_KEY=`, `EDGAR_IDENTITY="Name email@northeastern.edu"`, `LANGFUSE_*`. `.env` is gitignored. Each person sets their own `EDGAR_IDENTITY`.

### 0.3 Configuration

Every experiment is one YAML file; nothing about an experiment is hardcoded.

```yaml
# configs/base.yaml
model:
  id: "groq:qwen/qwen3.8-27b"   # confirm in P0.6
  temperature: 0
  thinking: "off"               # fixed for every run
  max_tokens: 2048
retrieval:
  arm: "rag"                    # closed_book | rag | agentic
  calculator: true              # false for R1-calc; true for R0+calc
  top_k: 5
  max_agent_steps: 8
verification:
  arm: "none"                   # none | self_check | grounded
  max_revisions: 2
  tolerance: 0.01               # 1% relative tolerance
embedding:
  model: "BAAI/bge-base-en-v1.5"
data:
  question_split: "test"        # dev | test
```

Grid and ablation files override only the fields that define them.

### 0.4 Shared schemas (`schemas.py`)

Agreed by the whole team before module code is written, then frozen (guarded by CI). The code in `src/finqa/schemas.py` is authoritative; this sketch reflects the 2026-10-30 schema review (`docs/DECISIONS.md`).

```python
Unit = Literal["USD", "USD/share", "%", "shares", "ratio", "days"]
Period = str  # validated: "FY2022" | "Q3 FY2022" | "6M FY2022" / "9M FY2022" (company fiscal year)

class Chunk(BaseModel):
    chunk_id: str; cik: str; ticker: str; form: str
    fiscal_year: int; period: Period | None; section: str
    is_table: bool; unit_scale: float | None  # 1e3, 1e6, 1e9 or None
    text: str; source_accession: str

class Claim(BaseModel):
    claim_id: str; metric: str          # e.g. "total revenue"
    value: float; unit: Unit            # full units; 12.5% stored as 12.5
    period: Period                      # e.g. "FY2022"
    chunk_ids: list[str]                # evidence cited
    derived_from: list[str] = []        # claim_ids used to compute this one
    expression: str | None = None       # e.g. "(a - b) / b" for derived values

class Draft(BaseModel):
    question_id: str; retrieval_arm: str
    answer_text: str; claims: list[Claim]
    answer_claim_id: str | None = None  # the claim that answers the question; None if qualitative
    evidence: dict[str, Chunk]          # every chunk the generator saw
    trace_id: str; latency_s: float; tokens_in: int; tokens_out: int
    error: str | None = None            # generation failed: scored incorrect, never dropped

class Verdict(BaseModel):
    claim_id: str; ok: bool | None      # None = check could not run
    check: str                          # "cited_text" | "xbrl" | "recompute" | "self_check"
    reason: str

class VerifiedResult(BaseModel):
    question_id: str; retrieval_arm: str; verification_arm: str
    claims_before: list[Claim]; claims_after: list[Claim]
    verdicts: list[Verdict]; revisions_used: int
    flagged_claim_ids: list[str]; latency_s: float; tokens_in: int; tokens_out: int
    error: str | None = None            # verification failed: claims_after = claims_before

class ErrorType(str, Enum):
    WRONG_PERIOD = "wrong_period"; WRONG_UNIT = "wrong_unit_or_scale"
    WRONG_LINE_ITEM = "wrong_line_item"; ARITHMETIC = "arithmetic"
    RETRIEVAL_MISS = "retrieval_miss"; WRONG_COMPANY = "wrong_company"
    OTHER = "other"

class Annotation(BaseModel):
    question_id: str; claim_id: str; run_id: str; annotator: str
    correct: bool; error_type: ErrorType | None; note: str = ""
```

### 0.5 Model wrapper (`llm.py`)

Every LLM call in the project goes through one function. It handles:

1. **Construction:** `init_chat_model(cfg.model.id, temperature=0, max_tokens=...)`.
2. **Thinking control:** set Groq's reasoning parameter for Qwen3.8 so thinking is off (or at a fixed budget). Confirm the parameter name in Groq's docs during the pilot. Log the setting with every call.
3. **Rate limits and retries:** `tenacity` exponential backoff on HTTP 429 and 5xx; a client-side limiter for requests and tokens per minute. Groq applies limits per organization, so extra API keys don't add capacity.
4. **Response cache:** every response cached on disk, keyed by a hash of (model ID, thinking setting, messages, tools, temperature). Reruns are free, crashes lose nothing, and runs are exactly reproducible.

### 0.6 Model pilot

A 20-question smoke test on hand-picked FinanceBench questions measuring tool-call success (two dummy tools), structured-output validity, and tokens per call. Targets: at least 95% on both. If tool calling falls short, try clearer tool descriptions, fewer tools at once, or an updated chat template, and report to the team before continuing. Record the model ID, thinking parameter, and results in `docs/PILOT.md`.

### 0.7 Continuous integration

`.github/workflows/ci.yml` runs on **every push to every branch and every pull request**, with a per-branch concurrency group that cancels outdated runs. Steps:

1. Python 3.11 and `uv` with caching; `uv lock --check` and `uv sync --frozen`.
2. `ruff check .` and `ruff format --check .`.
3. `mypy src/` (lenient at first).
4. `pytest -m "not integration"` with coverage.
5. Validate every YAML in `configs/` through the loader.
6. Pipeline smoke test: dummy generator and verifier through both runner stages on a 3-question fixture.
7. **Frozen-file guard:** fail if the PR changes `schemas.py`, `data/splits.json`, frozen prompts, or model settings in `base.yaml` without the label `approved-freeze-change`.
8. **Progress check:** `scripts/check_progress.py` validates `PROGRESS.md` (every task ID present once, valid statuses, PR links on done rows, blockers listed), and on task branches requires `PROGRESS.md` to change.

The same workflow runs on every push to `main`, which is every merge: that's the post-merge `uv` and test check. A red `main` stops all other merges until fixed.

`.github/workflows/integration.yml` is manual-only (`workflow_dispatch`), uses repository secrets, and runs `pytest -m integration`. Use it before large experiment runs.

**Testing convention:** unit tests never touch the network. Anything calling Groq, EDGAR, Hugging Face, or yfinance is marked `@pytest.mark.integration`.

### 0.8 Collaboration setup

- **Branch protection on `main`** (set by a human in GitHub settings): PR required, CI required, one approving review from a teammate who didn't write the code, no force-pushes.
- **`CODEOWNERS`** maps each area to its role; frozen files need two reviewers.
- **Pre-commit hooks:** `ruff`, `ruff format`, a guard against committing `.env`, and a **post-merge / post-checkout hook that runs `uv sync` whenever `uv.lock` changed**.
- **`CONTRIBUTING.md`:** branch naming (`section-chunking`), PR titles (`Section-aware chunking ...`; no task IDs in Git names), local checks, the shared artifact location, and the freeze-change process.
- **Branch and PR practice:** one task per branch, PRs under ~400 changed lines where possible, rebase on `main`, squash-merge.

### 0.9 Claude Code guardrails

Claude Code never runs Git or GitHub commands that change state; it writes code and gives humans the commands. Enforced by:

- **`.claude/settings.json`** (committed, so it applies to everyone): a permissions deny list blocking state-changing Git commands and the `gh` CLI, and an allow list for read-only Git commands (`status`, `diff`, `log`). Check the current Claude Code docs for the exact rule syntax. Personal overrides go in the gitignored `.claude/settings.local.json` and must not loosen the deny list.
- **`CLAUDE.md`** at the repo root, which Claude Code reads at the start of every session.

A human creates and reviews both files, since they govern Claude Code itself.

---

## Phase 1: Data (Role A)

### 1.1 FinanceBench audit

1. Download the public sample from Hugging Face.
2. One row per question: company, document name, document type, fiscal period, question type, gold answer.
3. **Decide scope explicitly:** some questions reference 8-Ks or earnings releases. Ingest those document types too, or exclude the questions. Record the decision and excluded count in `data/SCOPE.md`.
4. Extract a numeric gold value (value + unit) for every numeric question, using the shared normalizer in `verifiers/numbers.py`. Non-numeric answers are flagged and scored separately.

### 1.2 Company table

`data/companies.csv`: ticker, CIK, name, former names, brand aliases, from the SEC company ticker file. Feeds the resolver.

### 1.3 Filing download

All 10-K and 10-Q filings per company, from at least two years before the earliest FinanceBench year through the latest available (multiple years are required for restatement detection). Cache-first; never re-download. Save raw markdown plus accession, form, fiscal year, period of report, and filing date.

### 1.4 Section parsing

edgartools' structured 10-K / 10-Q objects for sections (Items 1, 1A, 7, 7A, 8 and 10-Q equivalents). Regex fallback on "Item N." headings. Log every fallback; a high rate for one company means a manual look.

### 1.5 Chunking

1. **Text:** ~500–800-token chunks, ~100-token overlap, on paragraph boundaries, within sections.
2. **Tables:** one markdown chunk per table; over ~1,500 tokens, split into row groups with the **header repeated in each piece**.
3. **Unit scale:** detect "in millions", "in thousands, except per share data", and similar phrases in the caption or lines above each table; store in `unit_scale`.
4. **Deterministic chunk IDs:** `{cik}-{accession}-{section}-{index}`.

### 1.6 Embedding and index

Embed with the locked model (with its query instruction prefix) and load into Chroma with all metadata filterable. The embedding model never changes after this.

### 1.7 XBRL cache and metric map

1. Download company facts JSON once per company to `data/xbrl/`.
2. Lookup: (CIK, concept, period start, period end) → **all** reported values with accession and filing date. Identify periods by their actual start and end dates, not the filing's fiscal-year label (a 10-K's prior-year comparatives carry the later filing's fiscal year). Ignore dimensional (segment) facts.
3. `data/metric_map.yaml`: metric names → XBRL concepts, starting with metrics in FinanceBench questions. Revenue alone has several concepts in use (`Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet`, ...).

### 1.8 Quality checks

A person inspects at least one parsed 10-K per company (sections, intact tables, correct unit scale). Claude Code generates a review sheet per company to speed this up. Results go in `data/QA_CHECKS.md`.

---

## Phase 2: Evaluation harness (Role B)

### 2.1 Question set and split

1. Type tags: `single_fact`, `multi_period`, `calculation`, `qualitative`. Model-proposed, human-confirmed.
2. **Dev (~20, stratified by type) and test (the rest).** Prompt development uses dev only; test runs use frozen prompts only.
3. Freeze `data/splits.json` (guarded by CI).

### 2.2 Runner

1. **Draft stage:** generator → `runs/{run_id}/drafts.jsonl`, fresh thread ID per question.
2. **Verification stage:** saved drafts + verifier → `runs/{run_id}/verified_{arm}.jsonl`.
3. `run_meta.json`: config, git commit, model ID, thinking setting, date, package versions.
4. **Run IDs:** `{date}_{config-name}_{short-commit}`.
5. **Test-split guard:** the runner refuses a test-split run unless the working tree is clean and `HEAD` is a commit on `main`.
6. Both stages resumable.

CLI: `uv run finqa draft --config configs/grid/r1_v0.yaml --split dev`, `uv run finqa verify --run <id> --config ...`.

### 2.3 Scoring

1. **Number normalization** (`verifiers/numbers.py`, shared with the verifier): "$1.2B", "1.2 billion", "1,200 million", "(1,234)" as negative, percentages versus fractions, per-share values.
2. **Claim correctness:** value within the configured relative tolerance of the gold value. **Gold answers are the only source of correctness** for every configuration.
3. **Answer-level score:** the final answer's key figure matches gold.
4. **Claims without a gold value** (intermediate figures in a calculation): validated on a sample by humans reading the filing text, never by XBRL.
5. Non-numeric questions scored separately (human-validated judge or human only).

### 2.4 Results tables

Accuracy by question type, claim-level correctness, latency and token percentiles, cost. **Every percentage shown with its count** ("8/10, 80%") and a **question-level bootstrap 95% confidence interval**.

### 2.5 Rule-based error classifier

For each claim already scored **incorrect against gold**, assign one error type, checking rules in order:

1. `wrong_unit_or_scale`: claimed / correct ≈ 10³, 10⁶, 10⁹ (or the inverse), within tolerance.
2. `wrong_period`: matches the same metric, same company, different period in XBRL.
3. `wrong_line_item`: matches a different metric, same company and period.
4. `wrong_company`: matches another in-scope company's figure for the metric and period.
5. `arithmetic`: has an `expression` whose inputs are correct but whose result isn't.
6. `retrieval_miss`: no evidence chunk contains the gold evidence (from 2.6).
7. `other`: no rule fired.

XBRL is used **only to choose the error type**, never to decide correctness. All rules, the tolerance, unit normalization, fiscal-period matching, and derived-value handling are written in `docs/LABELING_PROTOCOL.md`, which becomes part of the report's Methods.

### 2.6 Retrieval diagnostic

For each question, does FinanceBench's gold evidence text appear in the draft's evidence (normalized text overlap above a threshold recorded in `DECISIONS.md`)? Output `gold_evidence_retrieved` and the best-matching chunk ID. Spot-check 10 by hand.

### 2.7 Tracing

Every LLM and tool call sent to Langfuse, tagged with run ID and question ID.

---

## Phase 3: Generators (Roles C and D)

### 3.0 Closed-book baseline (S0)

Question straight to the model, no retrieval or tools, output as a `Draft` with empty evidence.

### 3.1 Tools (each unit-tested)

1. **`resolve_company(name)`:** `rapidfuzz` over names, tickers, former names, aliases; one match above threshold or a candidate list. Tests: Alphabet's share classes, Meta's former name, a brand name, an ambiguous name.
2. **`search_filings(cik, fiscal_year, section, query)`:** filtered Chroma search; returned chunks also written into the agent's `evidence`.
3. **`fetch_filing(cik, form, fiscal_year)`:** reuse Phase 1 to download, parse, chunk, index on demand.
4. **`calculate(expression, variables)`:** `asteval` on named variables; returns the result and expression (which becomes the claim's `expression`); rejects non-arithmetic input.
5. **Market data MCP server:** `get_price`, `get_financials` via `yfinance`, timestamped logging. **Demo only**, never in experiment configs.

### 3.2 Single-shot RAG (R0)

Resolve company → filtered top-k retrieval → one structured call producing a `Draft` with claims and chunk citations. R0 must output structured claims exactly like the agent, or the arms can't be compared claim by claim.

**Early freeze:** the S0 and R0 prompts are frozen before any test-set run (needed for the midterm). After that, they never change in response to test results.

### 3.3 Agent (R1)

1. **State:** `messages` (append reducer), `company`, `evidence` (merge reducer), `claims`, `steps_used`. Serializable values only.
2. **Graph:** `agent` → conditional edge → `tools` or `finalize`; `tools` → `agent`; `finalize` produces the structured `Draft`.
3. **System prompt rules:** resolve the company first; search with filters; every number comes from a cited chunk; all arithmetic through `calculate`; no number without a chunk ID.
4. **Limits:** recursion limit from config; tool results cached by arguments.
5. **Checkpointer:** `MemorySaver`, fresh thread ID per question.
6. Develop on dev, read 20 traces by hand, then freeze the prompt before the test run.

### 3.4 Retrieval × calculator arms

- **R0+calc:** single-shot retrieval, then the model writes its arithmetic as an expression evaluated by `calculate`.
- **R1−calc:** the agent with the calculator tool removed.

Both run on test with V0. Together with R0 and R1, they give the 2 × 2 table separating the retrieval effect from the calculator effect.

---

## Phase M1: Midterm report

Four pages including references. Points: Introduction & Motivation (3), Related Work (2), Methods (4), **Preliminary Results (5)**.

**Prerequisites:** Phases 0–2 complete; S0 and R0 built with prompts frozen; the agent running on dev.

| Section | ~Pages | Content | Source |
|---|---|---|---|
| Introduction & Motivation | 0.6 | Problem, research framing, RQ1 and RQ2, contributions | — |
| Related Work | 0.5 | FinanceBench and financial QA datasets; agents and tools; **numerical claim verification (FinGround, VeriFin, CoVe, CRITIC, Huang et al.)**; accurate commercial comparison | — |
| Methods | 1.1 | Architecture figure, 2 × 3 grid and 2 × 2 design, labeling protocol, independent scoring rule, model setup, RQ2 designs | Phases 0–3, `LABELING_PROTOCOL.md` |
| Preliminary Results | 1.3 | See below | Phases 0–3, M1 tasks |
| Next steps + references | 0.5 | Remaining phases and timeline | — |

**Preliminary results, in order of importance:**

1. **Main baseline table:** S0 vs R0 accuracy by question type, with counts and CIs, plus latency and tokens.
2. **Retrieval diagnostic:** share of R0 questions where gold evidence was retrieved, and R0 accuracy in each case. Separates "never saw the evidence" from "saw it and still got it wrong".
3. **R0 error-type breakdown:** bar chart from the rule-based classifier, with a 20-error human spot-check.
4. **Contamination check:** interpretation of S0 accuracy.
5. **Pipeline and model reliability:** filings, chunks, parsing fallback rate, unit-scale detection rate, scope exclusions, pilot results.
6. *(Optional)* Agent vs R0 on dev, **labeled dev-only**. No agent test-set numbers before its prompt is frozen.

**Related-work correction from proposal feedback:** commercial systems do verify across sources, so don't claim automated verification is unique. The contribution is an explicit check of every number against the cited passage, XBRL, and recomputation, with open, reproducible ablations.

If space runs short, cut Methods prose before cutting results.

---

## Phase 4: Verification arms (Role E)

All implement `verify(draft: Draft, cfg) -> VerifiedResult`.

### 4.1 V0: none

Returns the draft unchanged. Control condition.

### 4.2 V1: LLM self-check

Chain-of-Verification style: the model sees the question, its draft, and the cited evidence, and for each claim states whether the evidence supports it, giving a corrected value if not. Repeat up to `max_revisions` while claims change. Freeze the prompt early and report it verbatim; it must be a fair attempt, not a strawman.

### 4.3 V2: grounded

Per claim, up to three checks, each recording a verdict (`ok=None` when it can't run):

1. **Cited text:** normalize numbers in the cited chunks using `unit_scale`; match within tolerance.
2. **XBRL:** metric → concepts via `metric_map.yaml`; compare to the period's value. No mapping → `ok=None`, not a failure.
3. **Recomputation:** re-evaluate `expression` from `derived_from` values.

A claim fails if any check that ran returns `ok=False`. The LLM is only used to extract claims, never to judge them.

### 4.4 Revision loop (V1, V2)

Specific feedback per failed claim → the same generator revises → re-verify, up to `max_revisions` → remaining failures flagged. **Save `claims_before` and `claims_after`.**

### 4.5 Planted errors

~20 hand-made drafts with every error type. V2 must catch every checkable one; record V1's catch rate in `docs/PLANTED_ERRORS.md`.

### 4.6 Scoring independence

Verified results are scored exactly like everything else: against gold answers by the Phase 2 scorer. A verifier's verdicts never count as correctness.

---

## Phase 5: Annotation (everyone)

1. **Guidelines** (`annotation/guidelines.md`): claim definition, correctness and tolerance, each error type with examples, pre-decided edge cases (correct value with wrong citation, right value for wrong period, rounding, irrelevant claims).
2. **Export:** claims from all cells, **deduplicated** across cells (shared drafts mean many are identical), shown with question, gold answer, cited text, and automatic pre-label; **grid cell hidden**; rows shuffled; two annotators per claim with rotating pairs.
3. **Pilot:** all five label the same 30 claims; revise guidelines.
4. **Main round:** two labels per claim. Don't show model-suggested error types (anchoring bias).
5. **Agreement:** Cohen's kappa for correctness and error type.
6. **Adjudication:** discuss; a third person resolves what remains.

---

## Phase 6: RQ2a — Restatements (Role A)

1. **Detect:** (company, concept, exact period start and end) groups with different values across filings beyond rounding.
2. **Spot-check:** a person confirms 10–15 cases against both filings; decide whether reclassifications count, and record it in `DECISIONS.md`.
3. **Questions:** templated, for 30–50 cases, recording original value, restated value, and source filings.
4. **Run:** agentic arm with V0 and V2.
5. **Measure:** share reporting original vs restated vs neither; V2 false-rejection rate on claims that match the original filing. Report false rejections as a finding, not a bug to hide.

---

## Phase 7: RQ2b — Controlled perturbation (Role E)

1. **Select** test questions where the R1 draft retrieved the gold evidence chunk.
2. **Perturb** the key number by a fixed factor (e.g. +20%), keeping tables internally consistent.
3. **Inject** the perturbed chunk directly into evidence (bypassing retrieval).
4. **Measure** context-faithfulness vs memory rate.
5. **Company tiers** by market cap (fetched once via `yfinance`, frozen); test whether better-known companies show a higher memory rate.
6. **V2 detection rate** via the XBRL check.
7. **Closed-book accuracy** (S0) on the same questions, to frame contamination.

---

## Phase 8: Verification coverage (Role E)

From V2 verdicts: share of claims each check could run on; share with no check; accuracy for checkable vs uncheckable claims; top reasons checks couldn't run.

---

## Phase 9: Variance and statistics (Role B)

1. **Variance:** rerun R1-V0 and R1-V2 three times on 40 questions with the cache off; report spread; average runs if needed.
2. **RQ1 figure:** error types by grid cell, stacked bars.
3. **2 × 2 table:** retrieval effect and calculator effect separately.
4. **Paired tests:** McNemar's test between planned cell pairs, Holm-corrected.
5. **CIs:** bootstrap 95% on every reported rate.
6. **Flip matrices** for V1 and V2 (correct→wrong, wrong→correct, and so on).
7. **Cost and latency** per cell.
8. **Examples:** 2–3 per error type, with traces.

All figures and tables regenerate with `uv run finqa report`.

---

## Phase 10: Demo (Role D)

Streamlit: question box, resolved company, answer with a badge per number (verified / revised / unverifiable), clickable citations, a live-data toggle using the MCP market-data tool, and preset restatement and perturbation examples.

---

## Phase 11: Final report and reproducibility

1. **README:** setup, environment variables, exact commands to reproduce every table, CI badge.
2. **Reproducibility package:** configs, frozen prompts, `splits.json`, `SCOPE.md`, `DECISIONS.md`, response cache if size allows.
3. **Report:** motivation; related work (FinGround and VeriFin positioning, accurate commercial comparison); methods (designs, verifiers, labeling protocol, independent scoring); results (RQ1 grid and 2 × 2, RQ2a, RQ2b, coverage); limitations (single model family, FinanceBench size, possible contamination, unofficial yfinance); future work.

---

## Budget and rate limits

Measure tokens per question in the pilot, then estimate:

```
total ≈ questions × [ S0 + R0 + R1 + R0+calc + R1−calc drafts
                      + 2 × (V1 + V2 with revisions) ]
        + RQ2 runs + variance reruns + ~30% development overhead
```

- Groq's free plan covers Phase 0 and dev work; full test runs will almost certainly need the paid Developer tier. Check the current Qwen3.8-27B price in the Groq console before Week 4 and set a spending limit.
- The response cache means each unique call is paid for once.
- Self-hosting with vLLM is a fallback, but a quantized model is a different model: never mix serving setups within the reported results.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Qwen3.8 tool calling unreliable | Pilot in Week 1; simpler tool descriptions; fixed chat template |
| Rate limits stall runs | Response cache; resumable runs; paid tier for test runs |
| Modules don't connect | Frozen schemas; integration owner; CI smoke test |
| Parsing errors corrupt results | Quality checks; unit-scale extraction; fallback logging |
| Prompt tuning on test set | Frozen split; prompts frozen before test runs; runner test-split guard |
| Verifier grades itself | Gold-only scoring rule, enforced in scoring code and review |
| Too few errors to analyze | Claim-level analysis; mid-size model; counts with every rate |
| Annotation bias | Blinded cells; two labels per claim; kappa |
| Broken `main` / stale environments | CI on every branch; post-merge checks; `uv sync` hook; stop-the-line rule |
| Accidental Git/GitHub actions by Claude Code | Permission deny list in `.claude/settings.json`; human-only Git rule |
| Scope creep | Feature freeze at Gate 4; out-of-scope list in `ROADMAP.md` |
