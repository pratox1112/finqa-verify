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

## 2026-10-30 · Pratosh Karthikeyan (team adopted the proposed answers) · Schema review

Decisions from the P0.3 schema review, applied to `src/finqa/schemas.py` and guide §0.4. These rules also go into `docs/LABELING_PROTOCOL.md` when it is written (P2.5).

1. **Claim identity.** Claim IDs stay short and local to a draft (`c1`, `c2`). `Annotation` gains a required `question_id`, so an annotation is identified by (`run_id`, `question_id`, `claim_id`). A claim revised by a verifier keeps its `claim_id`; a new claim gets a new one. *Why:* a required field is validated, a naming convention is not; stable IDs make before/after flip matrices (P9.5) possible.
2. **Failures.** `Draft` and `VerifiedResult` gain `error: str | None` (short reason such as `structured_output_invalid`, `step_limit`, `api_error: 429`). A failed generation is scored **incorrect and never dropped**, and failure counts are reported per cell. A failed verification leaves `claims_after = claims_before` and is counted separately. *Why:* empty `claims` is legitimate for qualitative questions; dropping failures would flatter unreliable systems.
3. **Answer-level scoring.** `Draft` gains `answer_claim_id: str | None` (None for qualitative questions). Answer-level correctness = the answer claim's value against the gold value within tolerance; claim-level correctness checks every claim. Scoring reads claims only, so no revised answer text is stored. Qualitative questions are scored from `Draft.answer_text`, separately; verification does not change them, so RQ1's verification comparison covers numeric questions (state this in Methods). *Why:* without it, answer-level scoring would have to guess which claim answers the question.
4. **Periods.** `Claim.period` and `Chunk.period` must match `FY2022`, `Q3 FY2022`, or year-to-date `6M FY2022` / `9M FY2022`, always the company's own fiscal year as reported (Apple FY2022 ends September 2022), with "as of" balance-sheet values using the period they close. *Why:* consistent with XBRL fiscal periods, which the `wrong_period` rule needs; typos fail validation instead of silently never matching.
5. **Units and values.** `Claim.unit` is one of `USD`, `USD/share`, `%`, `shares`, `ratio`, `days`. Values are in full units, never pre-scaled ($394.3B is `394300000000`; `unit_scale` is applied when the claim is made). Percentages are stored as the percent number (12.5% is `12.5`). If the FinanceBench audit (P1.1) finds non-USD answers, the unit list is extended through a recorded schema change. *Why:* `wrong_unit_or_scale` detection depends on unscaled values; scoring, verification and gold parsing (P1.2) must share one convention.

## 2026-10-30 · Pratosh Karthikeyan · Model pilot design

**Decision:** The model pilot (P0.6) runs on 20 questions proposed by `scripts/select_pilot_questions.py` (fixed seed; 7 metrics-generated, 7 domain-relevant, 6 novel-generated; ~3/4 with a number in the gold answer; 10-K and 10-Q only; spread across companies) and approved by a human in `data/pilot_questions.json`. **These 20 questions are reserved for the dev split (P2.1).** FinanceBench's gold evidence stands in for retrieval. Tool-call success = valid tool calls / attempted tool calls, where a Groq `tool_use_failed` error or answering without any tool call counts as one invalid call; structured-output validity = a forced `PilotAnswer` call that parses with the shared `Unit` and `Period` formats.

**Why:** Prompts and tool descriptions may be adjusted while looking at pilot output, so these questions must never be scored as test questions. Using gold evidence isolates the model's mechanics (tool calling, structured output, token use) from retrieval quality, which doesn't exist yet.

**Data licence:** the FinanceBench public sample is CC-BY-NC-4.0 (PatronusAI); the raw file stays out of Git (`data/financebench/`), and only question IDs and derived files are committed.

## 2026-10-30 · Pratosh Karthikeyan · Start Phase 1 before Gate 0 sign-off

**Decision:** Phase 1 starts once the model pilot (P0.6) has been run and reviewed, without waiting for the remaining Gate 0 items that need teammates: the post-merge team review of `schemas.py` (P0.3), CODEOWNERS usernames, approvals back to 1 and code-owner review (P0.9), and every teammate running the checks locally. Gate 0 stays `todo` in `PROGRESS.md` until those are done.

**Why:** The outstanding items are review and setup steps; no Phase 1 code depends on them, and the midterm timeline is tight. Risk: if the schema review asks for changes, Phase 1 code that uses the schemas must follow, through the normal freeze-change process.

## 2026-10-30 · Pratosh Karthikeyan · Phase 1 on one branch

**Decision:** All of Phase 1 (P1.1–P1.9) is built on one branch, `phase-1-data`, with **one commit per task** (descriptive messages, no task IDs). A draft PR is opened at the first push so CI runs on every commit. Each task's `PROGRESS.md` row moves to `review` when its commit lands and to `done` (with the shared PR link) when the branch merges. The PR is merged with **Rebase and merge**, so each task stays a separate commit on `main` (still linear history). This is an exception to T7 (one task per branch), T8 (small PRs) and T10 (squash merge) for Phase 1 only.

**Why:** One person is working, and the Phase 1 tasks depend on each other in sequence (download → parse → chunk → index). One commit per task, CI on every push, and rebase-merge keep the reviewability and history the rules protect. [HUMAN] steps (P1.1 scope decision, P1.9 quality checks) still stop for a person.

## 2026-10-30 · Pratosh Karthikeyan · Free tier caps a single request at 7,000 input tokens

**Finding:** During the pilot, Groq refused a 7,810-input-token request with HTTP 413: the free tier has a separate **input-tokens-per-minute limit of 7,000** (below the 8,000 total TPM on the limits page), so any single request larger than that can never succeed on this tier. The wrapper does not retry 413 (retrying can't help).

**Decision:** The pilot reports such tests as "skipped: request too large for the Groq plan" and leaves them out of both rates (they measure the plan, not the model); the dummy search returns the evidence only once per question so the conversation doesn't grow by a full copy per search. This strengthens the case for the Developer tier before agent (R1) runs, whose growing context will exceed 7,000 input tokens.

## 2026-10-30 · Pratosh Karthikeyan · Model pilot passed

**Result:** `docs/PILOT.md` (run `2026-10-30_pilot_6de325e`): tool-call success 55/55 (100.0%), structured-output validity 20/20 (100.0%), no requests skipped; tokens per call mean 1,344, max 2,783. Target was >= 95% on both, so the model and thinking setting stand and the project continues as planned.

**Also found:** the free tier limits **output tokens to 1,000 per minute** (OTPM), in addition to 7,000 input tokens per minute and 1,000 requests / 200,000 tokens per day. The wrapper's 429 retries absorbed it during the pilot; long generations on the free tier will be slow.
