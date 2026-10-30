# Decisions

Every research-design and process decision, newest at the bottom. Format: date, who decided, decision, why.

---

## 2026-10-30 · Pratosh Karthikeyan · Commit small curated data files; ignore bulky data

**Decision:** Small, hand-curated files under `data/` are committed to Git: `splits.json`, `SCOPE.md`, `QA_CHECKS.md`, `metric_map.yaml`, `companies.csv`, `financebench_audit.csv`. Bulky or regenerable data (`data/raw/`, `data/xbrl/`, the Chroma index, caches, the downloaded FinanceBench sample) is gitignored and lives in the shared artifact location (CONTRIBUTING.md). `runs/` stays fully ignored.

**Why:** `splits.json` must be versioned for the frozen-file guard (ROADMAP P0.8) and reproducibility (P11.2); the other files are reviewed in PRs. Downloads are large and can be regenerated.

## 2026-10-30 · Pratosh Karthikeyan · No task IDs in Git names

**Decision:** Branch names, commit messages, and PR titles/descriptions never contain phase names or task IDs (e.g. `P1.6`, `Phase 0`). Use descriptive names instead: branch `section-chunking`, PR title "Section-aware chunking with unit scale". Task IDs are used only in `ROADMAP.md` and `PROGRESS.md`, where the *Branch / PR* column links each task to its branch.

**Why:** Team convention; IDs are internal planning references.

**Follow-up (P0.10):** the progress check can no longer detect "task branches" by name prefix. Resolved below.

## 2026-10-30 · Pratosh Karthikeyan · How the frozen-file guard decides what is frozen

**Decision:** `scripts/check_frozen.py` (run in CI on every PR) treats as frozen: `src/finqa/schemas.py`, `data/splits.json`, the `model:` section of `configs/base.yaml`, the manifest `src/finqa/prompts/FROZEN.txt`, and every prompt listed in it. A file is guarded only once it exists on `main`, so the PR that first creates it does not need the label. A PR that changes a guarded file fails unless it has the `approved-freeze-change` label. Freezing a prompt means adding its file name to `FROZEN.txt` (which itself needs the label once the manifest exists on `main`).

**Why:** Each frozen file is created before the team approves and freezes it; a manifest makes "which prompts are frozen" explicit and reviewable, and guarding the manifest stops silent unfreezing.

## 2026-10-30 · Pratosh Karthikeyan · Every PR updates PROGRESS.md

**Decision:** CI (`progress-updated` job) fails every pull request that does not modify `PROGRESS.md`, unless the PR has the label `no-progress-update` (for PRs with no task, e.g. a typo fix or a hotfix to a red `main`).

**Why:** Branch names carry no task IDs, so CI cannot tell task PRs from others by name; requiring the update everywhere is simple and hard to forget, and the label covers the rare exceptions.

## 2026-10-30 · Pratosh Karthikeyan (drafted by Claude Code) · Config defaults

**Decision:** In `configs/base.yaml`, `retrieval.calculator` defaults to `false` (the guide's sample said `true`), and every grid config sets `calculator` explicitly: R0 files `false`, R1 files `true`. `data.question_split` defaults to `dev` (the guide's sample said `test`).

**Why:** The design (guide §3.4) is that single-shot RAG (R0) has no calculator and the agent (R1) does; R0+calc and R1−calc are the ablations. A `true` default with `arm: rag` would have silently given R0 a calculator. Defaulting to `dev` means a forgotten `--split` never touches the test set (ROADMAP T12).

**Also:** experiment settings use plain Pydantic models; Pydantic Settings is used only for secrets (`Secrets`, read from env / `.env`), so environment variables can never change an experiment setting (rule 6).

## 2026-10-30 · Pratosh Karthikeyan · Model ID, thinking parameter, and Groq limits confirmed

**Decision:** Model ID `qwen/qwen3.8-27b` (config: `groq:qwen/qwen3.8-27b`). Thinking is turned off with `reasoning_effort="none"` ("instruct mode (non-thinking)"; `"default"` enables thinking). The project's fixed setting stays `thinking: "off"`. Client-side limits set to the free-tier values for this model: 30 requests/min and 8,000 tokens/min (the tier also caps 1,000 requests/day and 200,000 tokens/day, which the wrapper does not enforce: hitting them ends in a clear 429 error and the run resumes later from the cache).

**Source:** Groq model page https://console.groq.com/docs/model/qwen/qwen3.8-27b (context window 131,072; max output 16,384; tool use and JSON schema mode supported; $0.80 / $4.00 per million input / output tokens) and the Groq console limits page, both checked 2026-10-30.

**Open (team):** The free tier is enough for Phase 0 and dev work, but agent calls can exceed 8,000 tokens in a single request and full test runs need millions of tokens. Decide who pays for the Groq Developer tier, its spending limit, and whether official test runs use one account. Record the outcome here.
