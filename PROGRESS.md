# PROGRESS

Live status of the project. **[ROADMAP.md](ROADMAP.md) says what to build; this file says where we are.** This file is the single source of truth for status: task checkboxes are not used in the roadmap.

---

## Snapshot

| | |
|---|---|
| **Current phase** | Phase 5 (Phase 4 complete) |
| **Next milestone** | M1: Midterm report — due *[date]* |
| **Gates passed** | Gate 3, Gate 4 (Gates 0–2: see their rows) |
| **Open blockers** | 0 |
| **Last updated** | 2026-11-26 by — |

---

## How to update this file

1. **Claim before you start.** Set the task to `in-progress`, put your name in *Owner* and your branch in *Branch / PR*, and push that change before writing code, so two people never build the same task. (A human pushes it, per ROADMAP T17.)
2. **Update in the same PR that does the work.** Set `review` when the PR opens and `done` when it merges, with the PR link. CI checks this (see ROADMAP P0.10).
3. **Statuses:** `todo` · `in-progress` · `review` · `blocked` · `done`. Use exactly these words.
4. **Blocked?** Set `blocked`, then add a row to *Blockers* saying what you're waiting on and who can unblock it.
5. **Edit only your own rows**, plus one line in the *Log*, to keep merge conflicts rare. If you do hit a conflict here, keep both sides' changes.
6. **Whoever merges a gate** updates the *Snapshot* (current phase, gates passed) in the same PR.
7. **AI assistant:** read this file and ROADMAP.md at the start of every session; edit your task rows and add a Log line before ending a session. The AI assistant never commits or pushes; it gives the human the commands (ROADMAP T17).

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

## Model runners

Each runner downloads their own copy of the model and runs their own vLLM server (ROADMAP *Model serving*). Everyone else works without the model. Assign runners per phase; one grid cell is run by one person, start to finish.

| Phase / runs | Runner | Model copy ready |
|---|---|---|
| Phase 3: R1, R0+calc, R1−calc drafts and scoring | *TBD* | |
| Phase 4: V1, V2 revision loop, grid runs and scoring | *TBD* | |
| Phase 6: restatement runs and scoring | *TBD* | |
| Phase 7: injection and closed-book runs, scoring | *TBD* | |
| Phase 9: variance re-runs | *TBD* | |

---


## Phase 0: Foundations and contracts

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P0.1 | Repository skeleton | done | Pratosh Karthikeyan | [#1](https://github.com/pratox1112/finqa-verify/pull/1) | 2026-10-30 | Layout, pyproject (dev deps only), .gitignore, .env.example, 2 tests. Runtime deps added per task. |
| P0.7 | CI pipeline | done | Pratosh Karthikeyan | [#2](https://github.com/pratox1112/finqa-verify/pull/2) | 2026-10-30 | ci.yml (uv lock/sync, ruff, mypy, pytest+cov) + manual integration.yml. Config-validation step added in P0.2, smoke test in P2.2. "Failing PR is blocked" needs branch protection (P0.9). |
| P0.8 | Frozen-file guard | done | Pratosh Karthikeyan | [#3](https://github.com/pratox1112/finqa-verify/pull/3) | 2026-10-30 | scripts/check_frozen.py + `frozen-files` CI job; prompt manifest src/finqa/prompts/FROZEN.txt. 9 unit tests. Live schemas.py check possible only after P0.3 merges. |
| P0.9 | Branch protection and local hooks | in-progress | Pratosh Karthikeyan | [#4](https://github.com/pratox1112/finqa-verify/pull/4) | 2026-11-01 | Hooks, CONTRIBUTING.md, CODEOWNERS draft merged; ruleset on main active. Shared artifact location set 2026-11-01 (OneDrive, link in CONTRIBUTING.md). Pending: teammate usernames for CODEOWNERS, then approvals=1 + code-owner review. |
| P0.10 | Progress check | done | Pratosh Karthikeyan | [#5](https://github.com/pratox1112/finqa-verify/pull/5) | 2026-10-30 | scripts/check_progress.py in `checks`; new PR-only `progress-updated` job (label no-progress-update exempts). 8 tests. |
| P0.11 | AI assistant guardrails | done | Pratosh Karthikeyan | [#6](https://github.com/pratox1112/finqa-verify/pull/6) | 2026-10-30 | .claude/settings.json: Bash + PowerShell deny rules for state-changing git and gh, read-only allow list, GitHub API WebFetch denied. Known gaps: `git branch <name>` creation, calling git by full path. Manual acceptance test after merge. Since 2026-11-01 kept locally and gitignored, not in the repo (DECISIONS.md). |
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
| P2.1 | Question types and split | done | Dheepak Karan Elumalai Santhakumari | [#18](https://github.com/pratox1112/finqa-verify/pull/18) | 2026-11-06 | Keyword-rule proposals confirmed (6 changed) → data/splits.json: dev 20 (pilot) / test 107. Decisions in DECISIONS.md 2026-11-02. |
| P2.2 | Runner | done | Dheepak Karan Elumalai Santhakumari | [#18](https://github.com/pratox1112/finqa-verify/pull/18) + scoring-fixes | 2026-11-06 | src/finqa/eval/runner.py + `finqa draft/verify` CLI: drafts.jsonl / verified_{arm}.jsonl, resume (half-written line cut), run_meta.json, T13 run IDs, T12 test-split guard, failures kept with `error`. Dummy generator/verifier in eval/dummies.py; pipeline smoke test in tests/test_runner.py (results-table part comes with P2.4). 16 tests. |
| P2.3 | Scoring | done | Dheepak Karan Elumalai Santhakumari | [#18](https://github.com/pratox1112/finqa-verify/pull/18) + scoring-fixes | 2026-11-06 | src/finqa/eval/scoring.py: failed → incorrect; refused (no claims + declining text, incl. R0's "the excerpts do not contain ..." wording); single-number gold → answer claim within 1% of gold, after % ↔ ratio conversion, or rounding to the gold when the question asks for N decimals; text gold → LLM judge (prompts/judge_v1.txt) to be checked against human labels; selective accuracy. Decision in DECISIONS.md 2026-11-02. 18 tests. |
| P2.4 | Results tables | done | Dheepak Karan Elumalai Santhakumari | [#18](https://github.com/pratox1112/finqa-verify/pull/18) | 2026-11-06 | src/finqa/eval/tables.py (score a run; accuracy by type with refusals, selective accuracy, failures; latency/token p50/p95; estimated cost; McNemar comparison) + eval/stats.py (bootstrap CI, exact McNemar). Dummy run → tables in tests/test_tables.py (also the P0.7 pipeline smoke test). 8 tests. |
| P2.5 | Rule-based error classifier | done | Dheepak Karan Elumalai Santhakumari | [#18](https://github.com/pratox1112/finqa-verify/pull/18) | 2026-11-06 | src/finqa/eval/error_types.py: 7 rules in order (scale incl. 10^±2 for fraction/percent, period ±1/±2/−3 years, line item, company via XBRL for mapped metrics and 10-K questions only, arithmetic via a safe expression evaluator, retrieval miss, other). docs/LABELING_PROTOCOL.md written (scoring, conventions, error types, human labels with gold-ambiguous / technical-failure notes, κ). 11 tests incl. the real 3M restatement. |
| P2.6 | Retrieval diagnostic | done | Dheepak Karan Elumalai Santhakumari | [#18](https://github.com/pratox1112/finqa-verify/pull/18) | 2026-11-06 | src/finqa/eval/retrieval_diag.py: word-4-gram overlap per gold evidence item, retrieved at ≥ 0.6 (new `diagnostics` config section); items found / items; hit@k + curve. Calibrated on all 127 questions against the index; spot check 10/10 correct. 12 questions have gold evidence outside the index (cover page, Item 3, …). Shared chunks.zip is older than the index for 34 filings (DECISIONS.md). 6 tests. |
| G2 | **GATE 2** | review | Dheepak Karan Elumalai Santhakumari | [#18](https://github.com/pratox1112/finqa-verify/pull/18) | 2026-11-06 | Criteria met: the dummy system runs through draft and verify and produces tables with counts and 95% CIs (tests/test_tables.py::test_dummy_run_produces_tables_with_counts_and_cis, in CI); error classifier (tests/test_error_types.py) and retrieval diagnostic (tests/test_retrieval_diag.py) tested; data/splits.json frozen on main (scripts/check_frozen.py). Also checked on real drafts: S0/R0 dev runs scored with the runner and scoring (#17). Waiting: team sign-off. |


## Phase 3: Retrieval arms

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P3.0 | Closed-book generator (S0) | done | Rahul Vishnuvardhana | [#17](https://github.com/pratox1112/finqa-verify/pull/17) | 2026-11-07 | `generators/closed_book.py` (runner interface `generate(question, cfg, ctx)`), config `baselines/s0_closed_book.yaml`. Dev, scored with the Phase 2 runner: 3/20 (15%); 2 failed drafts are model repetition loops (scored incorrect). |
| P3.1 | Company resolver | done | Rahul Vishnuvardhana | [#17](https://github.com/pratox1112/finqa-verify/pull/17) | 2026-11-07 | `tools/resolver.py` (rapidfuzz; threshold 90, margin 5 in base.yaml); tests for Alphabet share classes, Meta/Facebook, brands, ambiguous "American". |
| P3.2 | Filing search tool | done | Rahul Vishnuvardhana | [#17](https://github.com/pratox1112/finqa-verify/pull/17) | 2026-11-07 | `tools/search.py`: `search_filings(cik, fiscal_year, section, query)` plus optional form/period (10-Qs) and is_table filters. |
| P3.3 | On-demand fetch tool | done | Rahul Vishnuvardhana | [#17](https://github.com/pratox1112/finqa-verify/pull/17) | 2026-11-07 | `tools/fetch.py`: `fetch_filing(cik, form, fiscal_year, quarter=None)` reuses the Phase 1 steps (labels, download, parse, chunk, index); no-op if indexed; statuses fetched / already_indexed / not_found / empty. Live EDGAR integration test passed (3M FY2013 10-K, temporary index). |
| P3.4 | Calculator tool | done | Rahul Vishnuvardhana | [#17](https://github.com/pratox1112/finqa-verify/pull/17) | 2026-11-07 | `tools/calculate.py`: `calculate(expression, variables)` via asteval after an arithmetic-only allow-list; returns result + expression; tests for growth rate, margin, ratio, CAGR and 15 rejected inputs. |
| P3.5 | Single-shot RAG generator | done | Rahul Vishnuvardhana | [#17](https://github.com/pratox1112/finqa-verify/pull/17) | 2026-11-07 | `generators/rag.py` (runner interface; base.py copied byte-for-byte from main): top-5 tables + 1 text chunk; answer-claim normalization and recovery of Groq-refused answers (DECISIONS.md 2026-11-04/05, proposed). Dev, scored: 8/20 (40%), 0 failed, 6 refusals. S0/R0 prompts frozen (FROZEN.txt, DECISIONS 2026-11-07; team approval via approved-freeze-change). |
| P3.6 | Agent generator | done | | [#27](https://github.com/pratox1112/finqa-verify/pull/27) | 2026-11-23 | `generators/agent.py`: LangGraph loop (agent → tools → agent … → finalize) over resolve_company, search_filings, fetch_filing, calculate and the shared Answer form; step limit `max_agent_steps`; forced Answer when the model stops or runs out of rounds; tool results cached by arguments; MemorySaver, one thread per question; every retrieved chunk is evidence; conversation saved to `runs/<run>/agent_traces/`. Prompts `r1_system.txt`, `r1_nocalc_system.txt`, `r1_user.txt`, `r1_finalize.txt` (not frozen). 25 unit tests. Dev (Explorer, scored with `scripts/compare_runs.py`): R1 14/20, R0 9/20 (6 refusals), S0 4/20; R1 vs R0 6 vs 1 discordant (McNemar p = 0.125). Trace review done (`docs/TRACE_REVIEW.md`: 20 traces, 10 patterns). Prompt fixes made and prompts frozen (P3.7). |
| P3.7 | Freeze prompts | done | | [#27](https://github.com/pratox1112/finqa-verify/pull/27) | 2026-11-23 | `r1_system.txt`, `r1_nocalc_system.txt`, `r1_user.txt`, `r1_finalize.txt`, `r0_calc_system.txt` added to `FROZEN.txt` (blob hashes in DECISIONS 2026-11-22). Team approval confirmed; merged with the `approved-freeze-change` label (freeze commit 7309952). |
| P3.8 | Test-set drafts | done | | [#31](https://github.com/pratox1112/finqa-verify/pull/31) | 2026-11-23 | Test drafts for R0 (`2026-11-22_r0_v0_7309952`) and R1 (`2026-11-22_r1_v0_7309952`): all 107 test questions each, from clean main at 7309952 (job 12070741); 1 and 3 failed generations, scored incorrect. Runs are on Explorer under /scratch (not committed). |
| P3.9 | Retrieval × calculator design | done | | [#31](https://github.com/pratox1112/finqa-verify/pull/31) | 2026-11-23 | R0+calc and R1−calc built (DECISIONS 2026-11-22). All four arms on the 107 test questions at 7309952 (job 12070741), scored by `finqa report --milestone p3` (job 12074387): `docs/RESULTS_P3.md` Tables P3-A to P3-E (2 × 2 with bootstrap CIs, five paired effects with McNemar, accuracy by question type, efficiency, errata sensitivity). |
| G3 | **GATE 3** | done | | [#31](https://github.com/pratox1112/finqa-verify/pull/31) | 2026-11-23 | R0 and R1 test drafts complete (P3.8); agent prompts frozen before their test run (P3.7, 7309952); 2 × 2 arms complete and scored (P3.9, `docs/RESULTS_P3.md`). |


## Phase M1: Midterm results and report

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| M1.1 | S0 on test | review | Rahul Vishnuvardhana | [#20](https://github.com/pratox1112/finqa-verify/pull/20), baseline-results-report | 2026-11-08 | Full split on vLLM: `2026-11-08_s0_closed_book_835b8b8` (clean main), 107/107 drafts, 1 failed (00941, output limit), 18/107 correct. Groq subset run `2026-11-07_s0_closed_book_876a8ae` (5/40) kept in docs/RESULTS_midterm_subset.md. |
| M1.2 | R0 on test | review | Rahul Vishnuvardhana | [#20](https://github.com/pratox1112/finqa-verify/pull/20), baseline-results-report | 2026-11-08 | Full split on vLLM: `2026-11-08_r0_v0_835b8b8` (clean main), 107/107 drafts, 1 failed (00460, unit outside schema), 33/107 correct, 22 refused; McNemar vs S0 p = 0.0135. Groq subset run (14/40) in docs/RESULTS_midterm_subset.md. |
| M1.3 | Main baseline table | review | Rahul Vishnuvardhana | baseline-results-report | 2026-11-08 | Table M1-A in `docs/RESULTS.md` (accuracy, refusals, selective accuracy, efficiency, McNemar). |
| M1.4 | Retrieval diagnostic | review | Rahul Vishnuvardhana | baseline-results-report | 2026-11-08 | Table M1-B: gold evidence retrieved 7/40. |
| M1.5 | R0 error breakdown | review | Rahul Vishnuvardhana | baseline-results-report | 2026-11-08 | Figure M1-1 (`docs/figures/m1_error_types.tex`). Human spot-check of all 16: agrees with 10/16; 3 answers look correct but score incorrect (gold sign convention, rounded gold outside 1% tolerance, judge miss) and 5 had gold pages in context the overlap test missed. Scores unchanged; scoring questions raised with the team. |
| M1.6 | Contamination check | review | Rahul Vishnuvardhana | baseline-results-report | 2026-11-08 | In `docs/RESULTS.md`; S0 5/40. |
| M1.7 | Pipeline and model reliability table | review | Rahul Vishnuvardhana | baseline-results-report | 2026-11-08 | Table M1-C. |
| M1.8 | (Optional) Agent on dev | todo | | | | |
| M1.9 | One command | review | Rahul Vishnuvardhana | baseline-results-report | 2026-11-08 | `uv run finqa report --milestone m1 [--scope full|subset]` (`src/finqa/eval/report.py`, `tests/test_report.py`); full writes docs/RESULTS.md, subset writes docs/RESULTS_midterm_subset.md. |
| M1.10 | Methods documents | todo | | | | |
| M1.11 | Related work and contribution statement | todo | | | | |
| M1.12 | Architecture figure | review | Rahul Vishnuvardhana | baseline-results-report | 2026-11-08 | Figure 1 in `report/m1/main.tex`. |
| M1.13 | Draft the report | review | Rahul Vishnuvardhana | baseline-results-report | 2026-11-08 | `report/m1/` builds to 4 pages with the full 107-question numbers (strict), retitled "Agentic Claim-Level Verification for Numerically Reliable Financial Question Answering". Follow-ups (not blocking): errata adjudication of 6 flagged golds, judge-vs-human agreement on 112 text-gold answers, hand check of the 52 full-run R0 errors. |
| M1.14 | Final check | todo | | | | |
| GM1 | **GATE M1** | todo | | | | |


## Phase 4: Verification arms

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P4.1 | Verifier interface and V0 | done | | [#33](https://github.com/pratox1112/finqa-verify/pull/33) | 2026-11-22 | `verifiers/base.py` (`Verifier` protocol, `result()` builder: claims_before always the draft's), `verifiers/none.py` (V0: claims unchanged, no checks or model calls); V0 through the runner scores exactly like the drafts; 5 tests. Started before Gate 3 as an exception (DECISIONS 2026-11-22). |
| P4.2 | V1: LLM self-check | done | | [#33](https://github.com/pratox1112/finqa-verify/pull/33) | 2026-11-22 | `verifiers/self_check.py`: Chain-of-Verification-style check over the draft's claims and cited excerpts (computed claims recomputed from their inputs); corrects value, unit, period; re-checks up to `max_revisions`, last check only flags; claims_before/after saved. Prompts `v1_system.txt`, `v1_user.txt` (draft, awaiting team approval and freeze). 18 tests. Dev run pending (after the Phase 3 test job frees the cluster checkout). Dev run done (jobs 12075270, 12082410); prompts frozen 2026-11-23. |
| P4.3 | V2 check 1: cited text | done | | [#33](https://github.com/pratox1112/finqa-verify/pull/33) | 2026-11-22 | `verifiers/grounded.py` `check_cited_text`: numbers from cited chunks in full units via `unit_scale`, match within tolerance ignoring sign; USD claims must match the scaled value (DECISIONS 2026-11-22), other units also raw; uncited or unretrieved citations fail, computed claims `ok=None`. 13 tests incl. millions table vs billions claim. |
| P4.4 | V2 check 2: XBRL | done | | [#33](https://github.com/pratox1112/finqa-verify/pull/33) | 2026-11-22 | `verifiers/grounded.py` `check_xbrl`: claim metric -> `metric_map.yaml` key via new `aliases:` lists (`xbrl.normalize_metric`, `metric_for`); passes if any reported value for the period is within tolerance (sign ignored); unmapped name, unit mismatch, unknown company or no value -> `ok=None`. Aliases drafted from dev names; need a teammate's review before P4.8 (DECISIONS 2026-11-22). 27 new tests. |
| P4.5 | V2 check 3: recomputation | done | | [#33](https://github.com/pratox1112/finqa-verify/pull/33) | 2026-11-22 | `verifiers/grounded.py` `check_recompute`: expression re-evaluated on the inputs' current values (shared `error_types.recompute`), within tolerance with sign; no inputs, unknown input or unevaluable expression fails; quoted claims `ok=None` (DECISIONS 2026-11-22). 6 tests. |
| P4.6 | Revision loop | done | | [#33](https://github.com/pratox1112/finqa-verify/pull/33) | 2026-11-23 | `verifiers/grounded.py` `GroundedVerifier`: three checks per claim; failed claims + per-check feedback -> same model fills a `Revision` form (value, unit, period; same as V1) -> re-check, up to `max_revisions`; remaining failures flagged; company from the question (resolver). Prompts `v2_system.txt`, `v2_user.txt` (draft, to freeze with V1's). 15 tests with a fake model incl. a planted scale error fixed in one round; the same case as an integration test against the served model (runs on the cluster). DECISIONS 2026-11-23. |
| P4.7 | Planted-error suite | done | | [#33](https://github.com/pratox1112/finqa-verify/pull/33) | 2026-11-23 | `tests/planted/cases.py`: 23 synthetic cases (fictional companies), 18 planted errors covering every error type + 5 controls; each states the V2 checks that should fail. `tests/test_planted.py`: V2's checks catch all 15 checkable errors with exactly the expected checks and flag no control; 3 errors V2 cannot see by design are listed (sign of a quoted value, wrong period of an unmapped metric, a fraction labelled %). `scripts/planted_errors.py` runs V1 and V2 with the model -> `docs/PLANTED_ERRORS.md`; to run on the cluster with the V1 dev run. Run with the model (job 12082410): V1 caught 14/18 planted errors (11/15 checkable), V2 15/18 (15/15), no false alarms on 5 controls; `docs/PLANTED_ERRORS.md`. |
| P4.8 | Run the grid | done | | [#36](https://github.com/pratox1112/finqa-verify/pull/36) | 2026-11-23 | Job 12083578 (43:42) on main at 90cc1e1, clean tree: V0, V1, V2 applied to the R0 and R1 test drafts (runs `2026-11-22_r0_v0_7309952`, `2026-11-22_r1_v0_7309952`). Six `verified_*.jsonl` files, each covering all 107 test questions, 0 failed verifications. Questions revised / flagged: R0 V1 4 / 19, R0 V2 24 / 29, R1 V1 0 / 4, R1 V2 7 / 21 (V0 0 / 0). Not yet scored against gold (analysis). |
| G4 | **GATE 4 (feature freeze)** | done | | [#36](https://github.com/pratox1112/finqa-verify/pull/36) | 2026-11-26 | All six cells complete (P4.8). Feature freeze from here: only bug fixes, analysis and writing. Test claims may now be exported for annotation (DECISIONS 2026-11-23). |


## Phase 5: Annotation

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P5.1 | Guidelines | in-progress | | branch annotation | 2026-11-26 | `annotation/guidelines.md` drafted (by an AI assistant, for the team to edit and approve): what a claim row shows, number conventions, correctness, error types with synthetic examples, edge cases, note tags, process. Started before Gate 4 as an exception (DECISIONS 2026-11-23). The six open questions decided (DECISIONS 2026-11-26): non-answer claims against the filing; tags `unsupported`, `from-input`, `label-error`, `irrelevant`. Waiting: team approval. |
| P5.2 | Export tooling | review | | branch annotation | 2026-11-26 | `src/finqa/eval/annotation.py`, `scripts/labels.py claim-sheets` / `claim-labels`: claims of all cells, de-duplicated within each draft run, blind shuffled CSV sheets (question, gold, answer, claim, inputs, cited text with headers, pre-label; no cell, verdicts or error types), two annotators per claim in rotating pairs or everyone for the pilot (`--everyone --sample N`); filled sheets checked and written as `Annotation`s, cell in `run_id` (DECISIONS 2026-11-26). 12 tests. Test cells: 803 distinct claims (1,606 labels at two per claim). |
| P5.3 | Pilot | review | | branch annotation | 2026-11-26 | Skipped for time (DECISIONS 2026-11-26): no pilot round; guidelines approved by the team before the main round instead. Pilot sheets made (`runs/labels/pilot15/`) are not used. |
| P5.4 | Main round | review | | branch annotation | 2026-11-27 | AI-labelled, disclosed (DECISIONS 2026-11-26): 200 of 200 sampled test claims labelled by annotator `ai` (`runs/labels/ai/labels.jsonl`, 0 invalid; all 23 pre-labelled answer claims agree with the gold pre-label). 33 rows the AI flagged as uncertain listed for a human check. Waiting: the team's confirmation and the human check. |
| P5.5 | Agreement | in-progress | | branch annotation | 2026-11-26 | Tooling built: `scripts/labels.py claim-agreement` -> `agreement.md` (Cohen's kappa for correct and for error type (a) combined label, (b) among both-incorrect; pooled and per pair), `disagreements.csv`, and `final_labels.jsonl` from a filled `adjudication.csv` (DECISIONS 2026-11-26, proposed). `stats.cohen_kappa` now takes any categories. 13 tests. Waiting: the main-round labels (P5.4). |
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
- 2026-10-30 · Pratosh Karthikeyan · P0.1 · Repository skeleton; decisions on data/ and Git naming recorded in docs/DECISIONS.md · https://github.com/pratox1112/finqa-verify/pull/1
- 2026-10-30 · Pratosh Karthikeyan · P0.7 · CI workflow on every push/PR, manual integration workflow, README badge · https://github.com/pratox1112/finqa-verify/pull/2
- 2026-10-30 · Pratosh Karthikeyan · P0.8 · Frozen-file guard in CI with approved-freeze-change label override · https://github.com/pratox1112/finqa-verify/pull/3
- 2026-10-30 · Pratosh Karthikeyan · P0.9 · Pre-commit hooks, CONTRIBUTING.md, CODEOWNERS draft · https://github.com/pratox1112/finqa-verify/pull/4
- 2026-10-30 · Pratosh Karthikeyan · P0.10 · PROGRESS.md validation and every-PR update rule in CI · https://github.com/pratox1112/finqa-verify/pull/5
- 2026-10-30 · Pratosh Karthikeyan · P0.11 · AI assistant permission rules enforcing T17 · https://github.com/pratox1112/finqa-verify/pull/6 (acceptance test passed)
- 2026-10-30 · Pratosh Karthikeyan · P0.2 · Configuration system and grid configs · https://github.com/pratox1112/finqa-verify/pull/7
- 2026-10-30 · Pratosh Karthikeyan · P0.4 · LLM wrapper · https://github.com/pratox1112/finqa-verify/pull/8
- 2026-10-30 · Pratosh Karthikeyan · P0.3, P0.6 · Shared schemas; Groq model ID, thinking parameter and limits confirmed · https://github.com/pratox1112/finqa-verify/pull/9
- 2026-10-30 · Pratosh Karthikeyan · P0.3 · Schema review decisions merged with approved-freeze-change (missed #9) · https://github.com/pratox1112/finqa-verify/pull/10
- 2026-10-30 · Pratosh Karthikeyan · P0.5 · Langfuse tracing with run_id and question_id tags · https://github.com/pratox1112/finqa-verify/pull/11 (manual Langfuse check passed 2026-10-30)
- 2026-10-30 · Pratosh Karthikeyan · P0.6 · Pilot script, FinanceBench loader, pilot question selection · https://github.com/pratox1112/finqa-verify/pull/12
- 2026-10-30 · Pratosh Karthikeyan · P1.1–P1.9 · Phase 1 started on one branch; data decisions recorded in docs/DECISIONS.md · https://github.com/pratox1112/finqa-verify/pull/13
- 2026-11-01 · Pratosh Karthikeyan · P1.1–P1.9, G1 · Filing pipeline merged; automated QA on all 206 10-Ks (151 pass, 29 warn, 26 flag); Gate 1 waits on teammates' confirmation and Gate 0 · https://github.com/pratox1112/finqa-verify/pull/13
- 2026-11-01 · Pratosh Karthikeyan · P0.9 · Shared data folder (OneDrive) and teammate setup steps in CONTRIBUTING.md; shareable link
- 2026-11-02 · Dheepak Karan Elumalai Santhakumari · P2.1 · Question types (keyword rules, confirmed) and dev/test split (dev = 20 pilot questions); Phase 2 started before Gate 0/1 sign-off (DECISIONS.md) · branch dheepak/question-split
- 2026-11-02 · Dheepak Karan Elumalai Santhakumari · P2.2 · Runner with draft and verify stages, resume, run metadata, test-split guard and the finqa command · branch dheepak/runner
- 2026-11-02 · Dheepak Karan Elumalai Santhakumari · P2.3 · Scoring against gold only: numeric tolerance, refusals, failures, LLM judge for text answers · branch dheepak/scoring
- 2026-11-03 · Dheepak Karan Elumalai Santhakumari · P2.4 · Results tables with counts, bootstrap CIs, refusals, selective accuracy, cost and a paired McNemar test · branch dheepak/results-tables
- 2026-11-03 · Dheepak Karan Elumalai Santhakumari · P2.5 · Rule-based error classifier and the labeling protocol · branch dheepak/error-classifier
- 2026-11-03 · Dheepak Karan Elumalai Santhakumari · P2.6 · Retrieval diagnostic with a calibrated overlap threshold and hit@k · branch dheepak/retrieval-diagnostic
- 2026-11-03 · Dheepak Karan Elumalai Santhakumari · — · Numeric citation check (diagnostic for the mid-term, reused by the grounded verifier later; DECISIONS.md) · branch dheepak/citation-check
- 2026-11-04 · Rahul Vishnuvardhana · P3.0, P3.1, P3.2, P3.5 · Company resolver, filing search, closed-book (S0) and single-shot RAG (R0) generators; dev check on the pilot questions; S0/R0 prompt freeze pending · https://github.com/pratox1112/finqa-verify/pull/17
- 2026-11-05 · Rahul Vishnuvardhana · P3.3, P3.4, P3.5 · On-demand fetch tool and calculator tool; R0 retrieves top-5 tables plus 1 text chunk (dev gold-evidence recall 0.13 to 0.36) · https://github.com/pratox1112/finqa-verify/pull/17
- 2026-11-05 · Rahul Vishnuvardhana · P3.0, P3.5 · S0/R0 on the runner interface; answer-claim normalization and Groq refusal recovery; scored dev S0 3/20, R0 8/20 · https://github.com/pratox1112/finqa-verify/pull/17
- 2026-11-06 · Dheepak Karan Elumalai Santhakumari · P2.3 · Refusal detection covers R0's "excerpts do not contain" wording; runner test for an unbuilt arm no longer depends on which generators exist (it failed once rag.py from #17 is merged) · branch scoring-fixes
- 2026-11-06 · Dheepak Karan Elumalai Santhakumari · P2.2 · Transient API errors (429/5xx after retries, lost connection) stop the run so it can resume, instead of being scored as wrong answers (raised on #17; DECISIONS.md) · branch scoring-fixes
- 2026-11-06 · Dheepak Karan Elumalai Santhakumari · P2.3 · Numeric scoring converts % ↔ ratio and honours the question's "round to N decimal places" (Coca-Cola ROA 1.35% vs gold 0.01 was scored wrong; raised on #17; DECISIONS.md) · branch scoring-fixes
- 2026-11-06 · Dheepak Karan Elumalai Santhakumari · P2.1–P2.6, G2 · Phase 2 rows marked done (merged in #18); Gate 2 criteria met, waiting for team sign-off · branch scoring-fixes
- 2026-11-06 · Dheepak Karan Elumalai Santhakumari · P2.3, P2.2 · Review of #19: refusal detection only counts sentences about the excerpts/filing ("the company does not disclose X" is an answer); verify stage flushes traces before a stop · branch scoring-fixes
- 2026-11-07 · Rahul Vishnuvardhana · P3.0–P3.5 · Merged in #17 (approved by Dheepak); S0/R0 prompts frozen
- 2026-11-07 · Rahul Vishnuvardhana · M1.1, M1.2, P2.3 · Judge prompt frozen; `finqa draft --subset` and the frozen 40-question midterm test subset (Groq paid tier unavailable; DECISIONS.md) · https://github.com/pratox1112/finqa-verify/pull/20
- 2026-11-08 · Rahul Vishnuvardhana · M1.1–M1.7, M1.9, M1.12, M1.13 · `finqa report --milestone m1` generates docs/RESULTS.md and Figure M1-1 from the Groq subset runs (S0 5/40, R0 14/40, McNemar p = 0.023); 4-page midterm draft in report/m1/ · branch baseline-results-report
- 2026-11-08 · Rahul Vishnuvardhana · — · Model serving switched to self-hosted vLLM (Qwen3.8-27B, bf16, A100 80 GB, thinking off per request; approved by Dheepak; DECISIONS 2026-11-08). Dev agreement with Groq: S0 19/20, R0 17/20 same outcome, McNemar p = 1.0. Runner refuses test runs with non-frozen model settings · branch self-hosted-serving
- 2026-11-08 · Rahul Vishnuvardhana · M1.1, M1.2, M1.9, M1.13 · Full 107-question S0/R0 runs on vLLM from clean main 835b8b8, scored strict (S0 18/107, R0 33/107, McNemar p = 0.0135); rounding rule dropped and 6 golds flagged for blind errata before scoring (DECISIONS); `finqa report --scope`; paper updated · branch baseline-results-report
- 2026-11-08 · Rahul Vishnuvardhana · M1.13 · Report retitled; refusal claim corrected (wrong answers 52 outnumber refusals 22); M1.13 to review · branch baseline-results-report
- 2026-11-17 · — · P3.6, P3.9 · Architecture decisions written into ROADMAP.md (Locked decisions and a new Architecture section): five generators, agent tools, 2 × 3 verification grid, 2 × 2 calculator arms with V0 only; model row updated to self-hosted vLLM
- 2026-11-20 · — · — · Model serving plan in ROADMAP.md (*Model serving*): no team server, each runner keeps an identical copy (pinned revision, same vLLM and flags), which phases need the model, runs and LLM cache shared via the shared artifact location; *Model runners* table added here, runners TBD
- 2026-11-20 · — · — · Slurm job scripts in `scripts/slurm/` (env setup with version check, pinned model download, server-and-run job on one A100 80 GB); setup and download jobs submitted on Explorer
- 2026-11-21 · — · — · Env setup job limit raised to 6 hours (installing vLLM on scratch took about one); on Explorer the vLLM env passed the version check (vllm 0.32.0, torch 2.13.0+cu129, CUDA 12.9), the model snapshot is downloaded (52 GB, pinned revision) and the project env is built
- 2026-11-21 · — · — · Slurm fixes: install the CUDA 12.9 vLLM wheel from the release page (PyPI's 0.32.0 is the CUDA 13 build) and check the exact `0.32.0+cu129`; server gets the env's `ninja` on PATH (FlashInfer compiles at startup). Smoke test on Explorer (A100 80 GB): server ready in about 6 minutes, S0 on dev 20 drafts, 0 failed (unscored)
- 2026-11-21 · — · P3.6 · Agent generator and R1-calc config; R1 on dev on Explorer: 20 drafts, 0 failed (unscored). Filtered searches on /scratch took 50-190 s each (GPU idle; RC warning), so jobs now copy the index to the node's local disk (`FINQA_INDEX_DIR`; 0.1-3.5 s per search); the last 10 questions took 8 minutes
- 2026-11-22 · — · P3.6 · R0 re-drafted on dev (vLLM) and R1 scored against R0 and S0: R1 14/20, R0 9/20, S0 4/20 (R1 vs R0 McNemar p = 0.125). Scoring oddities for the team: financebench_id_02119 has the same answer (82.31 USD/share) scored correct for R0 and incorrect for R1; 00684 and 03473 count two different values as correct
- 2026-11-22 · — · P3.6 · Scoring mismatch on financebench_id_02119 explained: R0's hedge ("cannot be computed", then lists $82.31 and the gold $66.56) was judged correct. Logged as a judge error; judge_v1 stays primary, nothing rescored (2026-11-08 strict-scoring entry); hedging rule added for human labellers (DECISIONS 2026-11-22, LABELING_PROTOCOL §3, §6)
- 2026-11-22 · — · P3.6 · Trace review of the 20 R1 dev traces (drafted by an agent, checked by a human): bad CIK in the first search (5), number-named calculator variables (2), round limit (2+1), redundant fetch (2), formula differs from gold (4), gold debatable (2), wrong year column (1), 10-Q section filter mismatch (1), conclusion contradicts gold (2); PayPal 00080 is a possible gold errata candidate
- 2026-11-22 · — · P3.6 · Fixes from the trace review: R1 prompts ask for the 10-digit CIK as returned, name the 10-K/10-Q sections, limit fetch_filing to filings search can't find, and (R1) want calculator variable names that start with a letter; search_filings rejects a non-10-digit CIK with a message and maps a bare "Item 1"-"Item 4" in a 10-Q search to Part I ("Item 1A" to Part II); 12 new tests
- 2026-11-22 · — · P3.6 · R1 re-run on dev with the fixes (`2026-11-22_r1_v0_cb06742`, 20 drafts, 0 failed): 12/20 vs 14/20 before (2 flips to incorrect, 0 the other way, McNemar p = 0.5); R0 9/20. Targeted problems: number-named calculator variables 0 (was 3 calls in each of 2 traces), redundant fetches 0 (was 2), bad-CIK searches 1 (was 5), round limit 2 (was 3), 3.5 rounds per question (was 4.4). Flips: Adobe 00591 ran out of rounds looking for capex (before, correct only by using the wrong year); Boeing 10285 gave $12,645 unscaled from a table whose scale is not stated in the chunk
- 2026-11-22 · — · P3.9 · R0+calc built: R0's single search, then calculate as often as needed (cap `max_agent_steps`, forced answer as in R1), prompt = R0's plus the calculator rule, traces saved like R1's; calculator and trace helpers shared with the agent; 19 new tests (DECISIONS 2026-11-22)
- 2026-11-22 · — · P3.9 · Dev runs of both ablations at cf7efcc (job 12068665, 0 failed except one R1−calc draft): R0 9/20, R0+calc 9/20 (0 discordant, p = 1.0), R1−calc 13/20 vs R1 12/20 (2 vs 1 discordant, p = 1.0), R0+calc vs R1 1 vs 4 (p = 0.375). R0+calc used the calculator on 9 of 20 questions (29 calls); on 2 (03473, 04481) it repeated one identical calculation until the 8-round limit, without changing either outcome. R1−calc 00723 failed: its Answer had no claims field (ValidationError), scored incorrect
- 2026-11-22 · — · P3.7 · Agent and 2 × 2 prompts frozen (five files in FROZEN.txt); no repeated-call fix for R0+calc; R0 to be re-run on test at the frozen commit with R1, R0+calc and R1−calc; fetched filings stay per job; the four PROPOSED entries of 2026-11-04/05 accepted (DECISIONS 2026-11-22)
- 2026-11-22 · — · P3.9 · `finqa report --milestone p3` writes `docs/RESULTS_P3.md` from the four newest full test runs (refuses runs from different commits, not from clean main, or incomplete): the 2 × 2 with counts and bootstrap CIs, five paired effects (difference with paired bootstrap CI, McNemar), accuracy by question type and efficiency per arm; 10 new tests. Test job 12070741 (four arms, main 7309952) queued
- 2026-11-22 · — · P3.9 · Labelling tools for the team (`scripts/labels.py`, `finqa.eval.labels`): blind shuffled judge-human sheets per labeller with a separate key and optional double coding, agreement per system with counts, CIs and Cohen's kappa, adjudication file, `Annotation` output; gold errata sheets for two annotators (question, gold and FinanceBench's own source only) and the errata-rule comparison; 18 new tests. Candidates: 00585, 05718, 04672, 04980, 04103, 06272 (test), 00080, 00283 (dev)
- 2026-11-22 · — · P3.7 · Freeze entry in DECISIONS now names the main commits of the frozen prompts (1b28a08, e1f234a, a6db083; freeze 7309952); the rebase merge changed the hashes, not the files
- 2026-11-22 · — · P3.9 · Gold errata sheets made (`runs/labels/errata/`, 8 candidates); both annotators are AI agents (two separate sessions, each blind to the other), at the team's decision because of time; no correction applies until a person checks and signs off on that item (DECISIONS 2026-11-22)
- 2026-11-22 · — · P3.9 · Gold errata outcome: the two agent annotators agree on all 8 candidates; 3 golds corrected for the errata sensitivity scoring after human sign-off (00585 Boeing, test; 00080 PayPal and 00283 Pfizer, dev); 5 stand (DECISIONS 2026-11-22)
- 2026-11-22 · — · P3.9 · Errata sensitivity scoring: `data/gold_errata.csv` (the three signed-off corrections), `scoring.load_errata` / `with_errata` (corrected golds keep their kind; strict scoring unchanged), and Table P3-E in `finqa report --milestone p3` (the 2 × 2 and effects with corrected golds, rescoring only corrected questions); 4 new tests
- 2026-11-22 · — · P4.1 · Phase 4 started before Gate 3 as a recorded exception (dev and fixtures only, no test-split verification until Gate 3, all Phase 4 work on branch `verifiers`, merged after Phase 3's PRs; DECISIONS 2026-11-22). Verifier interface and V0 built
- 2026-11-22 · — · P4.2 · V1 self-check built with a draft prompt (not frozen); 18 unit tests with a fake model; dev run on the R0 and R1 dev drafts pending
- 2026-11-22 · — · P4.3 · V2 cited-text check built; scale rule (USD claims must match a table's stated scale) and uncited-claim rule recorded in DECISIONS; 13 unit tests
- 2026-11-22 · — · P4.4 · V2 XBRL check built; metric-name aliases added to `metric_map.yaml` (drafted from dev drafts, review pending); unmapped metrics give ok=None
- 2026-11-22 · — · P4.5 · V2 recomputation check built; computed claims that cannot be recomputed fail (DECISIONS 2026-11-22)
- 2026-11-23 · — · P3.8, P3.9, G3 · Test split, all four arms at 7309952, strict scoring (`docs/RESULTS_P3.md`): R0 33/107, R0+calc 35/107, R1−calc 71/107, R1 76/107. Agent retrieval +35.5 pp without the calculator and +38.3 pp with it (McNemar p < 0.0001 for both); calculator +1.9 pp single-shot (p = 0.69) and +4.7 pp with the agent (p = 0.36). Errata scoring changes one test outcome each for R0 and R0+calc (00585), no conclusion. Gate 3 done
- 2026-11-23 · — · P4.6 · V2 assembled with its revision loop (V1's correction form, DECISIONS 2026-11-23); planted scale error corrected in one round with a fake model; real-model integration test to run on the cluster
- 2026-11-23 · — · P4.7 · Planted-error suite built (23 synthetic cases); V2's checks catch every checkable planted error without the model; V1's catch rate pending a cluster run of `scripts/planted_errors.py`
- 2026-11-23 · — · P4.2, P4.6 · `scripts/compare_verified.py`: V0 vs V1 vs V2 on a dev run, scored against gold, with flips, revisions, flags and failed verifications (dev only); dev job prepared (V1 and V2 on the R0 and R1 dev drafts, planted errors with the model, V2 real-model test)
- 2026-11-23 · — · P4.6, P4.7 · Dev job 12075270 (17 min, 0 failed verifications, real-model V2 test passed). Planted errors: V1 caught 14/18 (11/15 checkable), V2 15/18 (15/15), no false alarms on the 5 controls for either. Dev accuracy unchanged by V1 (R0 9/20, R1 12/20; V1 revised no claim); V2 R0 9/20, R1 13/20 (1 wrong to right). V2 fixes from the dev flags (unstated table scales, percent recomputation, uncited claims flagged not revised; DECISIONS 2026-11-23); V2 dev and planted runs to be repeated
- 2026-11-23 · — · P4.2, P4.6, P4.7 · V2 re-run after the fixes (job 12082410, 11 min, 0 failed): R0 V2 9/20 (2 revised, 2 flagged), R1 V2 13/20 (4 revised, 3 flagged; 1 wrong to right, 0 right to wrong); remaining flags all genuine. V1 and V2 prompts frozen; V2 design rules and metric aliases approved (DECISIONS 2026-11-23)
- 2026-11-23 · — · P4.1–P4.7 · Verifiers merged to main in #33 (squash merge: the branch's two merges from main could not be rebased); V1 and V2 prompts frozen. Next: the test-split grid (P4.8)
- 2026-11-23 · — · P5.1 · Phase 5 started before Gate 4 as a recorded exception (fixtures, synthetic and dev only; no test claims exported until Gate 4; branch `annotation`). Annotation guidelines drafted with six open questions for the team
- 2026-11-26 · — · P4.8, G4 · Test-split grid done (job 12083578, main at 90cc1e1): six verified cells, 107/107 questions each, 0 failed verifications. Gate 4 met; feature freeze. Next: score the cells against gold (analysis) and annotation (Phase 5)
- 2026-11-26 · — · P5.1 · Annotation guidelines: the six open questions decided (non-answer claims checked against the filing; four new note tags); waiting for team approval before the pilot
- 2026-11-26 · — · P5.2 · Claim export tooling (claim-sheets, claim-labels); the six test cells hold 803 distinct claims to label. Next: decide the pilot sample, then the pilot (P5.3)
- 2026-11-26 · — · P5.3 · Pilot sheets made: 30 dev claims for all five annotators
- 2026-11-26 · — · P5.5 · Claim agreement and adjudication tooling built (kappa definitions proposed in DECISIONS, to confirm with the team)
- 2026-11-26 · — · P5.3, P5.4 · For time: pilot reduced to 15 dev claims; main round a random sample of 200 test claims (two labels each)
- 2026-11-26 · — · P5.3 · Pilot skipped for time; straight to the 200-claim main round after the guidelines are approved
- 2026-11-26 · — · P5.4 · Main round switched to a disclosed AI annotator on the 200-claim sample (team to confirm); human check recommended
- 2026-11-27 · — · P5.4 · 200 sampled test claims labelled by the disclosed AI annotator; 33 uncertain rows to check by a human
