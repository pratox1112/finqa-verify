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

## 2026-10-30 · Pratosh Karthikeyan · Config defaults

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

**Decision:** All of Phase 1 (P1.1–P1.9) is built on one branch, `data-prep`, with **one commit per task** (descriptive messages, no task IDs). The branch is pushed after each task, so CI runs on every commit and the work is backed up; the single PR is opened once the data work is complete. Each task's `PROGRESS.md` row moves to `review` when its commit lands and to `done` (with the shared PR link) when the branch merges. The PR is merged with **Rebase and merge**, so each task stays a separate commit on `main` (still linear history). This is an exception to T7 (one task per branch), T8 (small PRs) and T10 (squash merge) for Phase 1 only.

**Why:** One person is working, and the Phase 1 tasks depend on each other in sequence (download → parse → chunk → index). One commit per task, CI on every push, and rebase-merge keep the reviewability and history the rules protect. [HUMAN] steps (P1.1 scope decision, P1.9 quality checks) still stop for a person.

## 2026-10-30 · Pratosh Karthikeyan · Free tier caps a single request at 7,000 input tokens

**Finding:** During the pilot, Groq refused a 7,810-input-token request with HTTP 413: the free tier has a separate **input-tokens-per-minute limit of 7,000** (below the 8,000 total TPM on the limits page), so any single request larger than that can never succeed on this tier. The wrapper does not retry 413 (retrying can't help).

**Decision:** The pilot reports such tests as "skipped: request too large for the Groq plan" and leaves them out of both rates (they measure the plan, not the model); the dummy search returns the evidence only once per question so the conversation doesn't grow by a full copy per search. This strengthens the case for the Developer tier before agent (R1) runs, whose growing context will exceed 7,000 input tokens.

## 2026-10-30 · Pratosh Karthikeyan · Model pilot passed

**Result:** `docs/PILOT.md` (run `2026-10-30_pilot_6de325e`): tool-call success 55/55 (100.0%), structured-output validity 20/20 (100.0%), no requests skipped; tokens per call mean 1,344, max 2,783. Target was >= 95% on both, so the model and thinking setting stand and the project continues as planned.

**Also found:** the free tier limits **output tokens to 1,000 per minute** (OTPM), in addition to 7,000 input tokens per minute and 1,000 requests / 200,000 tokens per day. The wrapper's 429 retries absorbed it during the pilot; long generations on the free tier will be slow.

## 2026-10-30 · Pratosh Karthikeyan · Phase 1 data decisions

1. **Scope: 10-K and 10-Q only.** 127 of the 150 FinanceBench questions are in scope (31 of 32 companies). Excluded: 9 questions on 8-Ks and 14 on earnings releases; Foot Locker has only such questions and drops out. Exact counts go in `data/SCOPE.md`. *Why:* those documents have no standard item structure or XBRL facts, so they would need separate parsing and V2 could not check them.
2. **Filing window, per company:** from 2 fiscal years before the company's earliest FinanceBench document year through 1 year after its latest (~830 10-K/10-Q filings). *Why:* covers every question plus the earlier years restatement detection needs, without indexing years nobody asks about; the on-demand fetch tool (P3.3) can add others.
3. **Gold values stated in the question's unit:** when a question asks for a figure "in USD millions" (or thousands, billions) and the gold answer is a bare number, the stated unit is applied, so `$1577.00` becomes 1,577,000,000 (full units, per the schema rule). *Why:* otherwise a correct model claim in full units would be scored wrong.
4. **Fiscal labels from the filing's XBRL cover page:** `fiscal_year` and the quarter in `period` come from `DocumentFiscalYearFocus` / `DocumentFiscalPeriodFocus`, falling back to the period-of-report date when missing (each fallback logged). *Why:* follows the company's own fiscal calendar (Apple FY2022 ends September 2022) and matches the XBRL facts the verifier uses.
5. **Sections kept:** 10-K Items 1, 1A, 7, 7A, 8; 10-Q Part I Items 1–4 and Part II Item 1A. *Why:* covers the FinanceBench evidence while keeping the index focused.
6. **Long jobs** (filing download, embedding) are run by the AI assistant in the session, with the counts reported; outputs stay in gitignored `data/`.
7. **Restatement check (P1.8):** The AI assistant proposes a candidate restated item from the XBRL data; a human confirms it against the filings.
8. **Quality checks (P1.9):** Pratosh inspects a few companies now; the team completes the rest later. Gate 1 stays open until every company is checked.

## 2026-10-30 · Pratosh Karthikeyan · Gold values and units from the question

**Decision:** `finqa.verifiers.numbers` reads every number as (value, unit) in full units. For a gold answer that is a single number, the unit comes from the answer itself when it has one (`$`, `%`, `x`, "per share"), otherwise from the question: "in USD millions/billions/thousands" → USD at that scale (the answer is scaled unless it already carries a scale word); "percent", "%", "margin", "growth rate" → %; "per share", EPS → USD/share; "days", cash conversion cycle, DSO/DIO/DPO → days; "ratio", "turnover", "times", return on assets/equity → ratio. Bare four-digit years are not numbers. Result on the 127 in-scope questions: 52 single-number gold answers (19 USD, 15 %, 13 ratio, 4 days, 1 unitless zero), 49 text answers containing numbers, 26 text only (`data/SCOPE.md`).

**Open for P2.3 (scoring):** for the 49 text answers containing numbers, which number is "the" gold value, or whether they are scored claim by claim against all extracted numbers, is a scoring decision to make before P2.3.

## 2026-10-30 · Pratosh Karthikeyan · Filing download details

**Decision:** Only original 10-K and 10-Q filings are downloaded; amendments (10-K/A, 10-Q/A) are not, since they are usually partial and the XBRL facts already record restated values (P1.8). Each filing is saved as Markdown (tables kept) plus the kept sections as split by edgartools, so parsing (P1.5) needs no network. The manifest `data/filings_manifest.csv` (accession, form, fiscal year and period, label source, paths) is small and is committed, so the exact set of filings is reproducible; the filings themselves stay in gitignored `data/raw/`.

## 2026-10-30 · Pratosh Karthikeyan · Fiscal labels from filing order (replaces Phase 1 decision 4)

**Finding:** After the download, companies' own XBRL fiscal labels turned out to be wrong in a few places (AES: six different 10-Qs all labelled "Q2 FY2022"; Corning: a June 10-Q labelled Q3; Best Buy: two years of filings a year behind its own naming), while the date-based fallback was wrong for others (Ulta names a fiscal year after the year it starts in; Amcor's June year end later moved to December, so the SEC's current year end misdates its older filings).

**Decision:** Fiscal labels come from the **order of the filings**: each 10-K closes a fiscal year and the 10-Qs before it are that year's Q1–Q3 (counted back from the year end); 10-Qs after the last 10-K belong to the next year. The year number is the 10-K's year-end year (52/53-week years ending in the first week of a month count as the previous month) plus the company's convention, taken as the **majority** of its own 10-K XBRL labels (0 for most, −1 for start-year naming like Ulta). The manifest keeps the filing's own XBRL label (`xbrl_label`) and marks each row `xbrl` (agrees), `corrected` (differs) or `sequence` (no XBRL label). In the trial on the downloaded filings this changed 14 of 819 labels (AES 5, Best Buy 7, Corning 1, Amcor 1), removed every duplicate label, and still matched all 72 FinanceBench documents. Fully automatic; no manual labelling.

**Why:** Neither source alone is reliable; filing order is unambiguous, and taking each company's naming convention from the majority of its own labels lets one bad label never override it.

## 2026-10-30 · Pratosh Karthikeyan · Section parsing method and known gaps

**Decision:** Sections are cut from each filing's **Markdown** (so tables stay tables), using edgartools' section boundaries: the edgartools section's opening and closing words are located in the Markdown by comparing letters and digits only; where an opening appears several times (table of contents, cross-references), the occurrence whose following text best matches the section wins, and where closing boilerplate repeats, the occurrence nearest the expected end wins. Spans are widened to whole lines, the section's own "Item N." heading is pulled in, and the next item's heading is trimmed off (edgartools splits items a few words off). Where edgartools has no section, the section's own heading is used (logged as `heading` fallback). Markdown escapes are removed except `\|`. Result on all 819 filings: 4,003 of 4,095 expected sections from edgartools boundaries, 8 by heading fallback, 0 failed, 84 absent from the filing (`data/parse_stats.csv`).

**Known gaps (not FinanceBench documents; text still in the full Markdown):** (1) 5 of 206 10-Ks put their financial statements and MD&A in Exhibit 13, which is not downloaded: Microsoft FY2014–FY2015, Walmart FY2016–FY2017, Verizon FY2019. (2) Netflix 10-Qs Q1 FY2013–Q3 FY2016 (12 filings) have no findable "Part I, Item 1" (financial statements) heading and no edgartools section. The other absent sections are mostly 10-Q "Part II, Item 1A", which filers omit when risk factors are unchanged. Revisit if retrieval needs these years.

## 2026-10-30 · Pratosh Karthikeyan · Chunk sizes smaller than the roadmap; unit scale never guessed

**Decision:** (1) Text chunks are at most **450 tokens** with **~60 tokens** of overlap (the previous chunk's closing sentences), cut on paragraph boundaries; tables are split into row groups above **800 tokens**, each repeating the caption and header row. These replace the roadmap's 500–800 / ~100 / ~1,500 and live in the `chunking:` section of `configs/base.yaml`. Tokens are counted as words plus punctuation marks (no tokenizer dependency); P1.7 can check this against the embedding model's tokenizer. (2) `unit_scale` comes only from what the table states: its header row ("(Millions)"), else its caption (up to two short lines above it, or the last sentence of a long paragraph above it: "...as follows (in thousands):"), else its first row. When nothing is stated, `unit_scale` is **None**; it is not inherited from earlier tables. Tables marked "except per share" keep the table's scale; the verifier handles per-share figures.

**Why:** (1) `BAAI/bge-base-en-v1.5` reads only the first 512 tokens of a chunk, so text past that could never be retrieved; and on Groq's free tier, five 1,500-token chunks would exceed the 7,000-token request limit (HTTP 413, as in the pilot). Five 800-token chunks plus the prompt fit. (2) An inherited scale can be wrong (share-count or per-share tables after a "millions" table); an empty scale is honest and the verifier can treat it as unknown.

**Result on all 819 filings:** 82,800 text chunks and 93,992 table chunks from 89,012 tables (4,155 split); unit scale stated on 39.2% of all tables and 77.7% of tables with dollar amounts (`data/chunk_stats.csv`). Two companies state the scale once for a whole section in prose ("Unless otherwise noted, tabular dollars are in millions": PepsiCo, American Water Works); these tables are left at None for now (open question below).

**Open question (for the team):** should an explicit section-wide statement like PepsiCo's set `unit_scale` for that section's tables that state nothing themselves? It is stated, not guessed, but it is not on the table.

## 2026-10-31 · Pratosh Karthikeyan · Search index: build on a free GPU; embedding libraries in their own group

**Decision:** (1) The Chroma index (`src/finqa/ingestion/index.py`) is built once on a free **Kaggle GPU** with the same code and model (`docs/BUILD_INDEX.md`), then downloaded into `data/chroma/` (gitignored, shared through the shared artifact location). (2) `torch` (CPU-only, from PyTorch's CPU index) and `sentence-transformers` are in an `embed` dependency group that `uv sync` installs by default; CI skips it (`--no-group embed`) since unit tests use a fake embedder. `chromadb` is a main dependency. (3) Documents are embedded as they are; queries get the model card's instruction prefix (`embedding.query_instruction` in `configs/base.yaml`); vectors are L2-normalized; the collection uses cosine distance and records the model name, refusing a different one.

**Why:** On this laptop's CPU (Intel Core Ultra 7 155U) bge-base embeds about 3 chunks per second, about 16 hours for 177,000 chunks; a GPU takes about 20 minutes. GPU and CPU vectors differ only by rounding. Keeping torch out of CI keeps every push fast.

**Observations from the trial:** real bge token counts are lower than the chunker's estimate (sample of 128 chunks from a 3M 10-K: mean 262, 3 over 512), so the 450-token limit leaves headroom. A filtered search (3M, FY2018, 10-K, Item 8) returns only matching chunks, but for "capital expenditure" it does not rank the cash-flow statement ("Purchases of property, plant and equipment") in the top 3. That vocabulary gap is part of what the retrieval arms are measured on; not tuned here.

## 2026-11-01 · Pratosh Karthikeyan · XBRL lookup and metric map

**Decision:** (1) `src/finqa/ingestion/xbrl.py` looks up every value a company reported for a us-gaap concept and period, across all its filings (10-K, 10-Q and 8-K recasts), each with accession, form and filing date. Periods are matched by actual dates (end date plus length: instant, 3, 6, 9 or 12 months), never by the filing's fiscal-year label. A schema Period ("FY2018", "Q3 FY2022", "9M FY2022") is turned into an end date through the manifest's labels; "6M"/"9M" close with the Q2/Q3 10-Q. (2) `data/metric_map.yaml` maps 25 base line items used by FinanceBench questions to every concept the 31 companies use for them (e.g. revenue has six, including `RevenuesNetOfInterestExpense` for JPMorgan and American Express; inventory adds Nike's, Ulta's and Boeing's own tags). A metric lookup returns the values of all mapped concepts, each tagged with its concept. Ratios (DPO, ROA, margins) are computed from these, not mapped. A company with no value (banks have no current assets) gets "no mapping": unverifiable, not an error. Percentages are converted from XBRL fractions (0.234 → 23.4). Coverage per company: `data/xbrl_coverage.csv`.

**Restatement example (P1.8 acceptance, human-confirmed below):** 3M's 2017 operating income was $7,820M in its FY2017 10-K (0001558370-18-000535) and $7,692M in its FY2018 10-K (0001558370-19-000470), first recast in an 8-K of May 2018 (0001558370-18-004256), consistent with the 2018 pension-cost reclassification (ASU 2017-07). The test uses an unchanged extract of 3M's SEC facts (`tests/fixtures/xbrl/`). Confirmed against both 10-K income statements by Pratosh Karthikeyan, 2026-11-01 (2017: 7,820 → 7,692; 2016: 7,223 → 7,027).

**Finding for RQ2a:** the scan lists 11–161 "same period, different value" cases per company (Ulta 0). Most are recasts (accounting changes, discontinued operations, segment changes) rather than error corrections; both are conflicting sources. Phase 6 selects its cases from these.

**Why:** dates are the only reliable period key (a 10-K's comparatives carry the later filing's fiscal year); listing every concept in use avoids silently missing a company's own tag; returning all values keeps the restated and original figures side by side, which RQ2a needs.

## 2026-11-01 · Pratosh Karthikeyan · Financial statements outside Item 8; edgartools mis-splits

**Finding (P1.9 quality checks):** 35 of 206 10-Ks had no financial statements in the parsed Item 8, affecting 16 of the 127 in-scope questions. Item 8 only said "see Item 15" and the statements were printed elsewhere: after Item 15 or the signatures (Activision FY2017–20, Netflix FY2013–18, PayPal FY2020–23, Ulta FY2021–22, Corning FY2018–23), inside the span edgartools calls Item 7 (PepsiCo FY2019–23), or in Exhibit 13, which was not downloaded (CVS FY2016–18, Pfizer FY2019, Verizon FY2019, Walmart FY2016–17). Separately, edgartools split Corning's 10-Ks wrongly, taking note numbers ("7. Income Taxes") for items, so Corning's Item 1, 1A and 7 held the wrong text.

**Decision:** (1) The download also saves each 10-K's Exhibit 13 (`<accession>.ex13.md`; 7 filings have one). (2) When a 10-K's Item 8 has neither a balance-sheet nor a cash-flow row, the parser adds the statements to Item 8 from wherever the filer printed them, in this order: Item 8 cut at its own headings; statements after Item 8; statements outside every kept section; Exhibit 13; statements inside another kept section (which then ends where they begin). Logged as method `statements` / `exhibit13`; counted in `data/parse_stats.csv` (`item8_statements_added`: 34). (3) An edgartools section that doesn't open with its item's title (letters only, so "Busines s" still matches) is replaced by the filing's own heading span, but only if that span is at least 2,000 characters, its first line carries the title without a subtitle dash, and edgartools' span lies mostly elsewhere; this rejects JPMorgan's "see pages…" cross-references and Pfizer's "Item 1. Business–Government Regulation" subsection titles.

**Result:** 63 of 64 FinanceBench 10-Ks have their statements in Item 8. Sections: 3,955 edgartools, 22 heading, 34 Item 8s completed, 84 absent, 0 failed. Chunks: 84,654 text + 97,316 tables (unit scale on 78.0% of dollar tables). 36 filings' chunks changed; `index --sync` re-indexes only those.

**Known limitations:** (1) General Mills FY2022–23: edgartools renders the statements as one value per paragraph instead of tables; the numbers are present and in order, but not as tables (FinanceBench uses GM FY2022). (2) MGM FY2021: statements present, but "Total assets" is not on its own table row, so the automatic check flags it. (3) The earlier "Exhibit 13" gap is closed: Walmart FY2016–17 and Verizon FY2019 now take their statements from Exhibit 13, and Microsoft FY2014–15 turn out to have theirs in Item 8 after all (the earlier note was wrong about them).

## 2026-11-01 · Pratosh Karthikeyan · Unit scale in multi-row table headers

**Finding (P1.9 quality checks):** the General Mills FY2020 review sheet showed its three financial statements with unit scale **none**, although each states "(In Millions, Except per Share Data)". The filing renders a multi-row header as body rows: the title row, then the company name, then the scale. The same layout hides the scale in JPMorgan ("(in millions, except ratios)"), Pfizer ("(MILLIONS)"), Nike, American Express and others.

**Decision:** amends the 2026-10-30 unit-scale rule. After the header row, caption and first row, `table_scale` also reads the **label cell** (first column) of the **second and third body rows** (`SCALE_LABEL_ROWS` in `chunk.py`). Only the label cell, and only at the top of the table, so a row-specific unit further down ("Shares (in millions)") does not set the table's scale. Still never guessed: no stated scale stays None.

**Result:** chunks unchanged in number and text; tables with a stated scale rose from 36,281 to 39,237 of 92,182 (39.4% → 42.6% of all tables). A sample of the new detections were all table-wide statements ("(MILLIONS)", "(in millions, except ratios)", "December 31, (in millions)"). The index takes the change through `index --sync`, which updates metadata in place without re-embedding when only the metadata changed. About 500 table chunks still state a scale lower down or in a multi-cell row (MGM most); left as None.

## 2026-11-01 · Pratosh Karthikeyan · Automated quality checks replace the manual review

**Decision (Pratosh, for time; teammates to confirm):** P1.9's manual review of one 10-K per company is replaced by automated checks on **all 206 parsed 10-Ks** (`src/finqa/ingestion/qa_check.py`, results in `data/QA_CHECKS.md`). No person reviewed the sheets; `data/QA_CHECKS.md` says so. The 31 review sheets in `data/qa_sheets/` stay for spot checks by hand.

**Method:** (1) **Line items:** total assets, revenue, net income and operating cash flow must appear in an Item 8 table row, at the table's detected unit scale, equal (up to the rounding shown) to the company's own XBRL value for that fiscal year; otherwise the check reports where the value did turn up (a row with no label, another section, another scale, nowhere). (2) **Sections:** each kept section opens with its item's title. (3) **Text:** no U+FFFD, mojibake, or Windows-1252 control characters. XBRL is used here only to check our own parsing, never to score answers (LABELING_PROTOCOL). Not covered: tables other than these four line items, and where sections end.

**Result (2026-11-01, first run):** 148 pass, 32 warn, 26 flag. Line items: 790 pass, 14 no label, 9 missing, 6 scale, 5 outside Item 8; no other scale errors after the multi-row-header fix. What the flags are (FinanceBench 10-K questions affected in brackets):
- **General Mills FY2022–23:** all four missing. Known: statements rendered as text, not tables (2026-11-01 Item 8 entry) [1].
- **JPMorgan FY2020–24:** operating cash flow found only in Item 7. New: the consolidated statements sit inside what edgartools calls Item 7; Item 8 holds the parent-company statements, so the Item 8 completion never triggered [1].
- **American Water Works FY2018–23:** revenue matched only in an Item 8 table with no detected scale. Known open question: AWW states "in millions" once in prose for the whole section (2026-10-30 unit-scale entry) [3].
- **Block FY2015:** not a parsing error. XBRL holds only the later recast value (21,123 thousand); the FY2015 10-K prints 27,584.
- **Garbled text, 12 10-Ks** (AMD, Activision, General Mills, JPMorgan, Microsoft): Windows-1252 punctuation left as control characters ("Company\x92s"); across all filings 4,618 chunks (2.5%), mostly Microsoft, AMD, Activision and General Mills. Numbers are unaffected [2].
- **Warnings:** MGM FY2016–24 print "Total assets" (and from FY2020 net revenues) on a row with an empty label; the value is there [3]. Sections without their title at the start, mostly harmless (Adobe's forward-looking statement preamble, Pfizer's logo, a paragraph of the previous item), except **Corning FY2019–21 Item 7**: it holds 3,000–14,000 characters of a note and the real MD&A is missing, because its heading is not at a line start ("`<u>Index</u> # Item 7. Management…`") [2].

**Fixed (Pratosh's choice):** Corning's MD&A. A heading right after a page footer's link on the same line (`<u>Index</u> # Item 7.`) now counts, and the heading switch reads the first 120 characters for the title instead of the first line. Only Corning FY2019–21 changed (Item 7: 3,000–14,000 → about 100,000 characters); all six Corning 10-Ks now pass. Chunks: 84,753 text + 97,445 tables = 182,198.

**Final result:** 151 pass, 29 warn, 26 flag (`data/QA_CHECKS.md`).

**Known limitations, not fixed (for time):** the Windows-1252 characters (4,618 chunks); JPMorgan FY2020–24 statements in Item 7, so Phase 2 retrieval should not rely on the section label alone for JPMorgan; AWW's section-wide scale (the 2026-10-30 open question); General Mills FY2022–23 statements as text; MGM's unlabelled total rows.

## 2026-11-01 · Pratosh Karthikeyan · AI assistant files kept out of the repository

**Decision:** `CLAUDE.md` and `.claude/` (including `.claude/settings.json`) are removed from the repository and gitignored; they stay on Pratosh's machine. This changes P0.11, which had both committed so the rules applied to every teammate.

**Consequence:** a teammate who clones the repo gets neither the AI assistant instructions nor the permission deny list that blocks Git and GitHub commands (T17). Anyone who uses an AI coding assistant on this repo gets a copy of both files from Pratosh first. The rules themselves (frozen files, scoring only against gold answers, no test-split runs from branches) still hold for everyone through ROADMAP, CONTRIBUTING, CI and the frozen-file guard.

## 2026-11-04 · Rahul Vishnuvardhana · Start the S0 and R0 parts of Phase 3 before Gate 2 (PROPOSED, needs team agreement)

**Proposal:** build the company resolver (P3.1), the filing search tool (P3.2), the closed-book generator (P3.0) and single-shot RAG (P3.5) now, in parallel with Phase 2, and develop them only on the 20 pilot questions reserved for the dev split (`data/pilot_questions.json`). No test-split run until Gate 2 is passed and the S0/R0 prompts are frozen. Gate 2 and Gate 3 stay `todo`.

**Why:** M1 (due 2026-11-09) needs S0 and R0 numbers, and Phase 2 is unclaimed; none of this code depends on Phase 2 (same reasoning as "Start Phase 1 before Gate 0 sign-off", 2026-10-30). Risk: if the Phase 2 runner needs a different generator interface (`generate(question_id, company, question, *, run_id) -> Draft`), the generators follow it.

## 2026-11-04 · Rahul Vishnuvardhana · Company resolver and R0 search filters (PROPOSED, needs team agreement)

**Resolver (P3.1):** names are normalized (case, punctuation, "&" = "and", legal suffixes such as Inc/Corp/Co, share-class words such as "Class A") and scored with rapidfuzz `WRatio` against the FinanceBench name, SEC name, former names and aliases in `data/companies.csv`; a ticker (any share class or historical ticker) scores 100. One company is returned only if it scores at least **90** and leads the next company by at least **5** (`retrieval.resolver_threshold` / `resolver_margin` in `configs/base.yaml`); otherwise only ranked candidates come back, never a guess. Checked on all 31 FinanceBench names (each resolves to itself) and on brands, former names, typos and an ambiguous name (`tests/test_resolver.py`).

**R0 filters (P3.5):** the generators get the question text and the FinanceBench `company` field (as in the model pilot, `scripts/pilot.py`), never the gold document name or period. R0 derives its search filters from that: the company through the resolver; the fiscal year as the latest year the question mentions ("FY2019 - FY2020" -> 2020); a quarter (Q1-Q3) means that quarter's 10-Q, otherwise the 10-K. If the filtered search finds nothing, filters are dropped one at a time (period, form, year), keeping the company. The query is the question itself; no section filter.

**Why:** using FinanceBench's gold `doc_name` would make R0's retrieval an oracle and unfair to R1, which must choose its own filters. Rules, not an extra LLM call, keep R0 at one model call. **To confirm:** that passing the FinanceBench `company` field (rather than resolving it from the question text) is acceptable for every arm.

## 2026-11-05 · Rahul Vishnuvardhana · R0 retrieves tables plus one text chunk (PROPOSED, needs team agreement)

**Decision:** R0's single search returns the `top_k` (5) nearest **table** chunks plus `rag_text_chunks` (1) nearest text chunk, all under the same filters, instead of the 5 nearest chunks of any kind (`retrieval.rag_text_chunks` in `configs/base.yaml`). The query stays the full question.

**Why (dev only, the 20 pilot questions, no model calls):** a retrieval check counted how many of the numbers in FinanceBench's gold evidence appear in the retrieved chunks (gold evidence read only for this diagnostic). Mean recall: 5 chunks of any kind 0.127; first sentence of the question as query 0.118; 5 tables 0.301 (first sentence) / 0.355 (full question); 4 tables + 1 any 0.293; 3 tables + 2 any 0.218; **5 tables + 1 text 0.356**. Re-ranking toward "Consolidated ..." statement titles did worse (0.233). The filters chose the gold filing for 18 of 19 questions; the one exception (Pfizer, "in 2019", gold document FY2021) follows the latest-year rule. The text chunk keeps prose for qualitative questions (e.g. AMD's products).

**Known limit:** recall is still low for balance-sheet questions whose statement table ranks below note tables; R0 has one search by design, and this is what R1 is compared against.

## 2026-11-05 · Rahul Vishnuvardhana · Generator output handling: answering claim and refused tool calls (PROPOSED, needs team agreement)

**Decision:** (1) `answer_claim_id` is normalized in the generator: an ID written as "3" means "c3", "null" means unset, and when it is unset or unknown but claims exist, the last claim is used (the prompts now say to list inputs first and the answer last, and to write the ID exactly). Scoring reads it only when the gold answer is a number, so qualitative answers are unaffected. (2) When Groq refuses a call with `tool_use_failed` (its tool-call parser trips, e.g. the model names the tool "Call"), the model's answer is read back from Groq's `failed_generation` text and validated exactly like a normal answer; anything invalid (e.g. a repetition loop) stays an error draft and is scored incorrect. Token counts of recovered calls are unknown (0).

**Why (dev, the 20 pilot questions, scored with the Phase 2 runner and scoring):** before (1), correct answers were scored "no answer claim" (Block: 101.5% vs gold 101.5%, `answer_claim_id` left null). Before (2), Netflix's correct answer ($5,466.3M, cited) was lost to a misnamed tool. R0 dev accuracy: 6/20 (30%) before both and before the retrieval change, 8/20 (40%) after, 0 failed drafts; S0 3/20 (15%), 2 failed drafts that are real model repetition loops.
