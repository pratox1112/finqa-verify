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
| Dheepak Karan Elumalai Santhakumari | *TBD* |
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
| P0.9 | Branch protection and local hooks | in-progress | Pratosh Karthikeyan | `branch-protection-hooks` | 2026-10-30 | pre-commit (ruff, .env guard, uv sync on lock change), CONTRIBUTING.md, CODEOWNERS draft. Pending: teammate usernames for CODEOWNERS, shared artifact location, GitHub branch protection [HUMAN]. |
| P0.10 | Progress check | todo | | | | |
| P0.11 | Claude Code guardrails | todo | | | | |
| P0.2 | Configuration system | todo | | | | |
| P0.3 | Shared schemas | todo | | | | |
| P0.4 | LLM wrapper | todo | | | | |
| P0.5 | Tracing | todo | | | | |
| P0.6 | Model pilot | todo | | | | |
| G0 | **GATE 0** | todo | | | | |


## Phase 1: Data

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P1.1 | FinanceBench audit | todo | | | | |
| P1.2 | Gold value extraction | todo | | | | |
| P1.3 | Company table | todo | | | | |
| P1.4 | Filing download | todo | | | | |
| P1.5 | Section parsing | todo | | | | |
| P1.6 | Chunking and unit scale | todo | | | | |
| P1.7 | Embedding and index | todo | | | | |
| P1.8 | XBRL cache and lookup | todo | | | | |
| P1.9 | Quality checks | todo | | | | |
| G1 | **GATE 1** | todo | | | | |


## Phase 2: Evaluation harness

| ID | Task | Status | Owner | Branch / PR | Updated | Notes |
|---|---|---|---|---|---|---|
| P2.1 | Question types and split | todo | | | | |
| P2.2 | Runner | todo | | | | |
| P2.3 | Scoring | todo | | | | |
| P2.4 | Results tables | todo | | | | |
| P2.5 | Rule-based error classifier | todo | | | | |
| P2.6 | Retrieval diagnostic | todo | | | | |
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
- 2026-10-30 · Pratosh Karthikeyan (with Claude Code) · P0.9 · Pre-commit hooks, CONTRIBUTING.md, CODEOWNERS draft · PR link pending
