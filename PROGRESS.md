# PROGRESS

Live status of the project. **[ROADMAP.md](ROADMAP.md) says what to build; this file says where we are.** This file is the single source of truth for status: task checkboxes are not used in the roadmap.

---

## Snapshot

| | |
|---|---|
| **Current phase** | Phase 0 |
| **Next milestone** | M1: Midterm report — due *[date]* |
| **Gates passed** | none |
| **Open blockers** | 0 |
| **Last updated** | *[YYYY-MM-DD] by [name]* |

---

## How to update this file

1. **Claim before you start.** Set the task to `in-progress`, put your name in *Owner* and your branch in *Branch / PR*, and push that change before writing code, so two people never build the same task. (A human pushes it, per ROADMAP T17.)
2. **Update in the same PR that does the work.** Set `review` when the PR opens and `done` when it merges, with the PR link. CI checks this (see ROADMAP P0.10).
3. **Statuses:** `todo` · `in-progress` · `review` · `blocked` · `done`. Use exactly these words.
4. **Blocked?** Set `blocked`, then add a row to *Blockers* saying what you're waiting on and who can unblock it.
5. **Edit only your own rows**, plus one line in the *Log*, to keep merge conflicts rare. If you do hit a conflict here, keep both sides' changes.
6. **Whoever merges a gate** updates the *Snapshot* (current phase, gates passed) in the same PR.
7. **Claude Code:** read this file and ROADMAP.md at the start of every session; edit your task rows and add a Log line before ending a session. Claude Code never commits or pushes; it gives the human the commands (ROADMAP T17).

---

## Team

| Name | Role (see docs/IMPLEMENTATION_GUIDE.md §1) |
|---|---|
| Dheepak Karan Elumalai Santhakumari | B. Evaluation + C. Generators (S0, R0) for M1 |
| Mohammed Ibrahim | *TBD* |
| Pratosh Karthikeyan | *TBD* |
| Rahul Vishnuvardhana | *TBD* |
| Shubh Bharatkumar Panchal | *TBD* |

---

## Blockers

| Task | Waiting on | Who can unblock | Since |
|---|---|---|---|
| | | | |

---


## Phase 0: Foundations and contracts

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P0.1 | Repository skeleton | done | Pratosh Karthikeyan | [#1](https://github.com/pratox1112/finqa-verify/pull/1) | 2026-10-30 | Layout, pyproject (dev deps only), .gitignore, .env.example, 2 tests. Runtime deps added per task. |
| P0.7 | CI pipeline | done | Pratosh Karthikeyan | [#2](https://github.com/pratox1112/finqa-verify/pull/2) | 2026-10-30 | ci.yml (uv lock/sync, ruff, mypy, pytest+cov) + manual integration.yml. Config-validation step added in P0.2, smoke test in P2.2. "Failing PR is blocked" needs branch protection (P0.9). |
| P0.8 | Frozen-file guard | done | Pratosh Karthikeyan | [#3](https://github.com/pratox1112/finqa-verify/pull/3) | 2026-10-30 | scripts/check_frozen.py + `frozen-files` CI job; prompt manifest src/finqa/prompts/FROZEN.txt. 9 unit tests. Live schemas.py check possible only after P0.3 merges. |
| P0.9 | Branch protection and local hooks | in-progress | Pratosh Karthikeyan | [#4](https://github.com/pratox1112/finqa-verify/pull/4) | 2026-11-01 | Hooks, CONTRIBUTING.md, CODEOWNERS draft merged; ruleset on main active. Shared artifact location set 2026-11-01 (OneDrive, link in CONTRIBUTING.md). Pending: teammate usernames for CODEOWNERS, then approvals=1 + code-owner review. |
| P0.10 | Progress check | done | Pratosh Karthikeyan | [#5](https://github.com/pratox1112/finqa-verify/pull/5) | 2026-10-30 | scripts/check_progress.py in `checks`; new PR-only `progress-updated` job (label no-progress-update exempts). 8 tests. |
| P0.11 | Claude Code guardrails | done | Pratosh Karthikeyan | [#6](https://github.com/pratox1112/finqa-verify/pull/6) | 2026-10-30 | .claude/settings.json: Bash + PowerShell deny rules for state-changing git and gh, read-only allow list, GitHub API WebFetch denied. Known gaps: `git branch <name>` creation, calling git by full path. Manual acceptance test after merge. Since 2026-11-01 kept locally and gitignored, not in the repo (DECISIONS.md). |
| P0.2 | Configuration system | done | Pratosh Karthikeyan | [#7](https://github.com/pratox1112/finqa-verify/pull/7) | 2026-10-30 | base.yaml + 6 grid configs, src/finqa/config.py (merge + validation, Secrets from .env), CI config-validation step. Model ID is a placeholder until P0.6. |
| P0.3 | Shared schemas | review | Pratosh Karthikeyan | [#9](https://github.com/pratox1112/finqa-verify/pull/9), [#10](https://github.com/pratox1112/finqa-verify/pull/10) | 2026-10-30 | Frozen on main with the 5 review decisions (#10 via approved-freeze-change). Merged by Pratosh without a second review: team review still needed before Gate 0. |
| P0.4 | LLM wrapper | done | Pratosh Karthikeyan | [#8](https://github.com/pratox1112/finqa-verify/pull/8) | 2026-10-30 | src/finqa/llm.py: cache, 429/5xx retry, RPM/TPM limiter, thinking control, token logging, structured output. RPM/TPM and the thinking parameter to confirm in P0.6. |
| P0.5 | Tracing | done | Pratosh Karthikeyan | [#11](https://github.com/pratox1112/finqa-verify/pull/11) | 2026-10-30 | src/finqa/tracing.py: one Langfuse trace per (run, question), tagged with both IDs; LLM calls and tool spans join it; off without keys. Manual check: tests/test_tracing_integration.py with Langfuse keys. |
| P0.6 | Model pilot | done | Pratosh Karthikeyan | [#12](https://github.com/pratox1112/finqa-verify/pull/12) | 2026-10-30 | PASS: tool calls 55/55 (100%), structured output 20/20 (100%); tokens/call mean 1,344, max 2,783 (docs/PILOT.md). 20 pilot questions reserved for dev. |
| G0 | **GATE 0** | todo | | | | |


## Phase 1: Data

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P1.1 | FinanceBench audit | done | Pratosh Karthikeyan | [#13](https://github.com/pratox1112/finqa-verify/pull/13) | 2026-10-30 | data/financebench_audit.csv (150 rows) + data/SCOPE.md: 127 of 150 questions in scope (10-K/10-Q), 31 companies; Foot Locker excluded. |
| P1.2 | Gold value extraction | done | Pratosh Karthikeyan | [#13](https://github.com/pratox1112/finqa-verify/pull/13) | 2026-10-30 | src/finqa/verifiers/numbers.py (shared reader) + gold_value/gold_unit/answer_numbers in the audit: 52 single-number gold answers, 49 text-with-numbers (P2.3 decides how to score), 26 text. |
| P1.3 | Company table | done | Pratosh Karthikeyan | [#13](https://github.com/pratox1112/finqa-verify/pull/13) | 2026-10-30 | data/companies.csv: 31 in-scope companies, each exactly one CIK (ticker, else SEC name search for delisted Activision). Brand aliases need a human look. |
| P1.4 | Filing download | done | Pratosh Karthikeyan | [#13](https://github.com/pratox1112/finqa-verify/pull/13) | 2026-10-30 | 819 filings (206 10-K, 613 10-Q), 427 MB in data/raw; all 72 FinanceBench documents found. Fiscal labels by filing order: 803 agree with XBRL, 15 corrected, 1 had none. Manifest committed: data/filings_manifest.csv. |
| P1.5 | Section parsing | done | Pratosh Karthikeyan | [#13](https://github.com/pratox1112/finqa-verify/pull/13) | 2026-10-30 | src/finqa/ingestion/parse.py: sections cut from Markdown (tables intact) using edgartools boundaries. 4,003/4,095 via edgartools, 8 heading fallback, 0 failed, 84 absent. Fallback rate per company in data/parse_stats.csv. Known gaps in DECISIONS.md. |
| P1.6 | Chunking and unit scale | done | Pratosh Karthikeyan | [#13](https://github.com/pratox1112/finqa-verify/pull/13) | 2026-10-30 | src/finqa/ingestion/chunk.py: 84,753 text chunks (≤450 tokens, 60 overlap) + 97,445 table chunks (≤800 tokens, header repeated; 4,289 tables split), after the 2026-11-01 Item 8 and Corning fixes. Unit scale stated on 42.5% of all tables (39,269 of 92,308, including multi-row headers since 2026-11-01), else None. Sizes in configs/base.yaml (smaller than roadmap, DECISIONS.md). Counts in data/chunk_stats.csv. Open: PepsiCo-style section-wide scale. |
| P1.7 | Embedding and index | done | Pratosh Karthikeyan | [#13](https://github.com/pratox1112/finqa-verify/pull/13) | 2026-11-01 | src/finqa/ingestion/index.py + tests (filtered query returns only matching chunks). Full build on a Kaggle T4 (docs/BUILD_INDEX.md), then `--sync` re-embedded the 36 filings changed by the Item 8 fix; `--check` 2026-11-01: 181,970 chunks, all hits from 3M FY2018 Item 8. Later syncs: scales updated in place (298 filings), Corning FY2019–21 re-embedded; now 182,198 chunks. Index in data/chroma/ (gitignored). Note: the capex test query ranks text above the cash-flow row; retrieval quality is for Phase 2. |
| P1.8 | XBRL cache and lookup | done | Pratosh Karthikeyan | [#13](https://github.com/pratox1112/finqa-verify/pull/13) | 2026-11-01 | src/finqa/ingestion/xbrl.py (all reported values per concept and period, matched by dates) + data/metric_map.yaml (25 metrics). Restated item: 3M 2017 operating income $7,820M → $7,692M, confirmed in both 10-Ks by Pratosh 2026-11-01 (test on a real-facts fixture). Coverage in data/xbrl_coverage.csv. |
| P1.9 | Quality checks | done | Pratosh Karthikeyan | [#13](https://github.com/pratox1112/finqa-verify/pull/13) | 2026-11-01 | Manual review replaced by automated checks on all 206 10-Ks (src/finqa/ingestion/qa_check.py; decision 2026-11-01, teammates to confirm): line items vs XBRL, section titles, garbled text. Result 151 pass, 29 warn, 26 flag in data/QA_CHECKS.md; flags are known limitations (DECISIONS.md). Fixed on the way: Item 8 statements (35 10-Ks), Corning sections, multi-row-header scales. 31 review sheets kept in data/qa_sheets/. |
| G1 | **GATE 1** | review | Pratosh Karthikeyan | [#13](https://github.com/pratox1112/finqa-verify/pull/13) | 2026-11-01 | Criteria met: all 819 in-scope filings indexed (182,198 chunks); XBRL cache and metric map; QA checks recorded (data/QA_CHECKS.md). Waiting: teammates confirm the automated QA decision (DECISIONS.md 2026-11-01), and Gate 0 is still open (P0.3, P0.9). |


## Phase 2: Evaluation harness

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P2.1 | Question types and split | in-progress | Dheepak Karan Elumalai Santhakumari | dheepak/question-split | 2026-11-02 | Keyword-rule proposals confirmed (6 changed) → data/splits.json: dev 20 (pilot) / test 107. Decisions in DECISIONS.md 2026-11-02. |
| P2.2 | Runner | in-progress | Dheepak Karan Elumalai Santhakumari | dheepak/runner | 2026-11-02 | src/finqa/eval/runner.py + `finqa draft/verify` CLI: drafts.jsonl / verified_{arm}.jsonl, resume (half-written line cut), run_meta.json, T13 run IDs, T12 test-split guard, failures kept with `error`. Dummy generator/verifier in eval/dummies.py; pipeline smoke test in tests/test_runner.py (results-table part comes with P2.4). 16 tests. |
| P2.3 | Scoring | in-progress | Dheepak Karan Elumalai Santhakumari | scoring-fixes | 2026-11-06 | src/finqa/eval/scoring.py: failed → incorrect; refused (no claims + declining text, incl. R0's "the excerpts do not contain ..." wording); single-number gold → answer claim within 1% of gold; text gold → LLM judge (prompts/judge_v1.txt) to be checked against human labels; selective accuracy. Decision in DECISIONS.md 2026-11-02. 18 tests. |
| P2.4 | Results tables | in-progress | Dheepak Karan Elumalai Santhakumari | dheepak/results-tables | 2026-11-03 | src/finqa/eval/tables.py (score a run; accuracy by type with refusals, selective accuracy, failures; latency/token p50/p95; estimated cost; McNemar comparison) + eval/stats.py (bootstrap CI, exact McNemar). Dummy run → tables in tests/test_tables.py (also the P0.7 pipeline smoke test). 8 tests. |
| P2.5 | Rule-based error classifier | in-progress | Dheepak Karan Elumalai Santhakumari | dheepak/error-classifier | 2026-11-03 | src/finqa/eval/error_types.py: 7 rules in order (scale incl. 10^±2 for fraction/percent, period ±1/±2/−3 years, line item, company via XBRL for mapped metrics and 10-K questions only, arithmetic via a safe expression evaluator, retrieval miss, other). docs/LABELING_PROTOCOL.md written (scoring, conventions, error types, human labels with gold-ambiguous / technical-failure notes, κ). 11 tests incl. the real 3M restatement. |
| P2.6 | Retrieval diagnostic | in-progress | Dheepak Karan Elumalai Santhakumari | dheepak/retrieval-diagnostic | 2026-11-03 | src/finqa/eval/retrieval_diag.py: word-4-gram overlap per gold evidence item, retrieved at ≥ 0.6 (new `diagnostics` config section); items found / items; hit@k + curve. Calibrated on all 127 questions against the index; spot check 10/10 correct. 12 questions have gold evidence outside the index (cover page, Item 3, …). Shared chunks.zip is older than the index for 34 filings (DECISIONS.md). 6 tests. |
| G2 | **GATE 2** | todo | | | | |


## Phase 3: Retrieval arms

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P3.0 | Closed-book generator (S0) | todo | | | | |
| P3.1 | Company resolver | todo | | | | |
| P3.2 | Filing search tool | todo | | | | |
| P3.3 | On-demand fetch tool | todo | | | | |
| P3.4 | Calculator tool | todo | | | | |
| P3.5 | Single-shot RAG generator | todo | | | | |
| P3.6 | Agent generator | todo | | | | |
| P3.7 | Freeze prompts | todo | | | | |
| P3.8 | Test-set drafts | todo | | | | |
| P3.9 | Retrieval × calculator design | todo | | | | |
| G3 | **GATE 3** | todo | | | | |


## Phase M1: Midterm results and report

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| M1.1 | S0 on test | todo | | | | |
| M1.2 | R0 on test | todo | | | | |
| M1.3 | Main baseline table | todo | | | | |
| M1.4 | Retrieval diagnostic | todo | | | | |
| M1.5 | R0 error breakdown | todo | | | | |
| M1.6 | Contamination check | todo | | | | |
| M1.7 | Pipeline and model reliability table | todo | | | | |
| M1.8 | (Optional) Agent on dev | todo | | | | |
| M1.9 | One command | todo | | | | |
| M1.10 | Methods documents | todo | | | | |
| M1.11 | Related work and contribution statement | todo | | | | |
| M1.12 | Architecture figure | todo | | | | |
| M1.13 | Draft the report | todo | | | | |
| M1.14 | Final check | todo | | | | |
| GM1 | **GATE M1** | todo | | | | |


## Phase 4: Verification arms

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P4.1 | Verifier interface and V0 | todo | | | | |
| P4.2 | V1: LLM self-check | todo | | | | |
| P4.3 | V2 check 1: cited text | todo | | | | |
| P4.4 | V2 check 2: XBRL | todo | | | | |
| P4.5 | V2 check 3: recomputation | todo | | | | |
| P4.6 | Revision loop | todo | | | | |
| P4.7 | Planted-error suite | todo | | | | |
| P4.8 | Run the grid | todo | | | | |
| G4 | **GATE 4 (feature freeze)** | todo | | | | |


## Phase 5: Annotation

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P5.1 | Guidelines | todo | | | | |
| P5.2 | Export tooling | todo | | | | |
| P5.3 | Pilot | todo | | | | |
| P5.4 | Main round | todo | | | | |
| P5.5 | Agreement | todo | | | | |
| P5.6 | Adjudication | todo | | | | |
| G5 | **GATE 5** | todo | | | | |


## Phase 6: RQ2a — Restatements

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P6.1 | Detection | todo | | | | |
| P6.2 | Question set | todo | | | | |
| P6.3 | Runs | todo | | | | |
| P6.4 | Analysis | todo | | | | |
| G6 | **GATE 6** | todo | | | | |


## Phase 7: RQ2b — Controlled perturbation

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P7.1 | Selection | todo | | | | |
| P7.2 | Perturbation | todo | | | | |
| P7.3 | Injection runs | todo | | | | |
| P7.4 | Company tiers | todo | | | | |
| P7.5 | Closed-book baseline | todo | | | | |
| P7.6 | Analysis | todo | | | | |
| G7 | **GATE 7** | todo | | | | |


## Phase 8: Verification coverage

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P8.1 | Coverage analysis | todo | | | | |
| G8 | **GATE 8** | todo | | | | |


## Phase 9: Variance and statistics

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P9.1 | Variance | todo | | | | |
| P9.2 | Error-type figure | todo | | | | |
| P9.3 | Paired tests | todo | | | | |
| P9.4 | Confidence intervals | todo | | | | |
| P9.5 | Flip matrices | todo | | | | |
| P9.6 | Cost and latency | todo | | | | |
| P9.7 | Examples | todo | | | | |
| G9 | **GATE 9** | todo | | | | |


## Phase 10: Demo

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P10.1 | MCP market-data server | todo | | | | |
| P10.2 | Streamlit app | todo | | | | |
| G10 | **GATE 10** | todo | | | | |


## Phase 11: Report and reproducibility

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P11.1 | README | todo | | | | |
| P11.2 | Reproducibility package | todo | | | | |
| P11.3 | Final report | todo | | | | |
| P11.4 | Presentation | todo | | | | |
| G11 | **GATE 11** | todo | | | | |


---

## Log

One line per merged PR or completed session, newest at the bottom: `YYYY-MM-DD · name · task ID · what changed · PR link`.

- *[YYYY-MM-DD] · [name] · — · PROGRESS.md created*
- 2026-10-30 · Pratosh Karthikeyan (with Claude Code) · P0.1 · Repository skeleton; decisions on data/ and Git naming recorded in docs/DECISIONS.md · https://github.com/pratox1112/finqa-verify/pull/1
- 2026-10-30 · Pratosh Karthikeyan (with Claude Code) · P0.7 · CI workflow on every push/PR, manual integration workflow, README badge · https://github.com/pratox1112/finqa-verify/pull/2
- 2026-10-30 · Pratosh Karthikeyan (with Claude Code) · P0.8 · Frozen-file guard in CI with approved-freeze-change label override · https://github.com/pratox1112/finqa-verify/pull/3
- 2026-10-30 · Pratosh Karthikeyan (with Claude Code) · P0.9 · Pre-commit hooks, CONTRIBUTING.md, CODEOWNERS draft · https://github.com/pratox1112/finqa-verify/pull/4
- 2026-10-30 · Pratosh Karthikeyan (with Claude Code) · P0.10 · PROGRESS.md validation and every-PR update rule in CI · https://github.com/pratox1112/finqa-verify/pull/5
- 2026-10-30 · Pratosh Karthikeyan (with Claude Code) · P0.11 · Claude Code permission rules enforcing T17 · https://github.com/pratox1112/finqa-verify/pull/6 (acceptance test passed)
- 2026-10-30 · Pratosh Karthikeyan (with Claude Code) · P0.2 · Configuration system and grid configs · https://github.com/pratox1112/finqa-verify/pull/7
- 2026-10-30 · Pratosh Karthikeyan (with Claude Code) · P0.4 · LLM wrapper · https://github.com/pratox1112/finqa-verify/pull/8
- 2026-10-30 · Pratosh Karthikeyan (with Claude Code) · P0.3, P0.6 · Shared schemas; Groq model ID, thinking parameter and limits confirmed · https://github.com/pratox1112/finqa-verify/pull/9
- 2026-10-30 · Pratosh Karthikeyan (with Claude Code) · P0.3 · Schema review decisions merged with approved-freeze-change (missed #9) · https://github.com/pratox1112/finqa-verify/pull/10
- 2026-10-30 · Pratosh Karthikeyan (with Claude Code) · P0.5 · Langfuse tracing with run_id and question_id tags · https://github.com/pratox1112/finqa-verify/pull/11 (manual Langfuse check passed 2026-10-30)
- 2026-10-30 · Pratosh Karthikeyan (with Claude Code) · P0.6 · Pilot script, FinanceBench loader, pilot question selection · https://github.com/pratox1112/finqa-verify/pull/12
- 2026-10-30 · Pratosh Karthikeyan (with Claude Code) · P1.1–P1.9 · Phase 1 started on one branch; data decisions recorded in docs/DECISIONS.md · https://github.com/pratox1112/finqa-verify/pull/13
- 2026-11-01 · Pratosh Karthikeyan (with Claude Code) · P1.1–P1.9, G1 · Filing pipeline merged; automated QA on all 206 10-Ks (151 pass, 29 warn, 26 flag); Gate 1 waits on teammates' confirmation and Gate 0 · https://github.com/pratox1112/finqa-verify/pull/13
- 2026-11-01 · Pratosh Karthikeyan · P0.9 · Shared data folder (OneDrive) and teammate setup steps in CONTRIBUTING.md; shareable link
- 2026-11-02 · Dheepak Karan Elumalai Santhakumari · P2.1 · Question types (keyword rules, confirmed) and dev/test split (dev = 20 pilot questions); Phase 2 started before Gate 0/1 sign-off (DECISIONS.md) · branch dheepak/question-split
- 2026-11-02 · Dheepak Karan Elumalai Santhakumari · P2.2 · Runner with draft and verify stages, resume, run metadata, test-split guard and the finqa command · branch dheepak/runner
- 2026-11-02 · Dheepak Karan Elumalai Santhakumari · P2.3 · Scoring against gold only: numeric tolerance, refusals, failures, LLM judge for text answers · branch dheepak/scoring
- 2026-11-03 · Dheepak Karan Elumalai Santhakumari · P2.4 · Results tables with counts, bootstrap CIs, refusals, selective accuracy, cost and a paired McNemar test · branch dheepak/results-tables
- 2026-11-03 · Dheepak Karan Elumalai Santhakumari · P2.5 · Rule-based error classifier and the labeling protocol · branch dheepak/error-classifier
- 2026-11-03 · Dheepak Karan Elumalai Santhakumari · P2.6 · Retrieval diagnostic with a calibrated overlap threshold and hit@k · branch dheepak/retrieval-diagnostic
- 2026-11-03 · Dheepak Karan Elumalai Santhakumari · — · Numeric citation check (diagnostic for the mid-term, reused by the grounded verifier later; DECISIONS.md) · branch dheepak/citation-check
- 2026-11-06 · Dheepak Karan Elumalai Santhakumari · P2.3 · Refusal detection covers R0's "excerpts do not contain" wording; runner test for an unbuilt arm no longer depends on which generators exist (it failed once rag.py from #17 is merged) · branch scoring-fixes
- 2026-11-06 · Dheepak Karan Elumalai Santhakumari · P2.2 · Transient API errors (429/5xx after retries, lost connection) stop the run so it can resume, instead of being scored as wrong answers (raised on #17; DECISIONS.md) · branch scoring-fixes
