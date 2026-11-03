# Labeling protocol

How answers are scored and how errors are labelled, for every configuration. Code: `src/finqa/eval/scoring.py`, `src/finqa/eval/error_types.py`. Decisions behind each rule are in `docs/DECISIONS.md` (2026-10-30 schema review; 2026-11-02 scoring). This text is the basis of the report's Methods section.

## 1. Independence

- **Correctness comes only from FinanceBench gold answers**, the same way for every configuration (ROADMAP rule 10).
- A verifier's verdicts never decide correctness, and neither does XBRL. XBRL may only name an error's *type* (§4) or check our own parsing.
- The same rules apply to S0, R0, the Oracle baseline, R1 and every verification arm. A verifier is never graded by itself.

## 2. Number conventions

| Item | Rule |
|---|---|
| Values | Full units, never pre-scaled: $394.3B is `394300000000`. A table's `unit_scale` is applied when a claim is made |
| Percentages | The percent number: 12.5% is `12.5`, not `0.125` |
| Negatives | A minus sign or accounting parentheses: `(1,234)` is −1234 |
| Units | One of `USD`, `USD/share`, `%`, `shares`, `ratio`, `days` |
| Gold scale | A bare gold number takes the unit the question states ("in USD millions": `$1577.00` → 1,577,000,000) |
| Fiscal periods | The company's own fiscal year as reported: `FY2022`, `Q3 FY2022`, year-to-date `6M FY2022` / `9M FY2022`. Balance-sheet values use the period they close |
| Tolerance | Relative to the gold value: \|value − gold\| ≤ 1% × \|gold\| (`verification.tolerance`). A gold of 0 needs exactly 0 |
| Derived values | A computed claim carries `expression` (e.g. `(a - b) / b`) and `derived_from` (its input claim IDs). Variables are the input claim IDs or the letters a, b, c… in `derived_from` order. An expression that yields a fraction for a `%` claim is multiplied by 100 |

## 3. Outcome of an answer

Checked in this order; the first that applies decides.

| # | Case | Outcome | How |
|---|---|---|---|
| 1 | Generation failed (`Draft.error` set) | incorrect | Counted, never dropped; failures are also reported per configuration |
| 2 | No claims, and the answer declines ("cannot be determined", "not available", "insufficient information", "don't know") | **refused** | Counted apart from incorrect. Selective accuracy = correct / (correct + incorrect) |
| 3 | Gold is a single number (52 in-scope questions) | correct / incorrect | The **answer claim** (`Draft.answer_claim_id`) within tolerance (§2). No answer claim → incorrect. Other claims don't decide the answer |
| 4 | Gold is text, with or without numbers (75 questions) | correct / incorrect | **LLM judge** (`src/finqa/prompts/judge_v1.txt`): correct only if the answer reaches the gold's conclusion, every key figure matches up to rounding with the same unit and scale, and nothing contradicts the gold. Illustrative numbers (list markers, product names such as "737", company names such as "3M") are not key figures |

**Judge validation:** a random sample of about 25 judged answers is labelled by a person who doesn't see the judge's verdict, and the judge-human agreement is reported. The judge prompt is frozen before any test-set scoring. For the final report, prediction-powered inference (PPI) can combine the human sample with the judge's labels into one estimate with a confidence interval.

## 4. Error types (automatic, rule-based)

For every answer scored incorrect, one `ErrorType` is assigned. Rules are checked in order and the first that fires wins.

| # | Type | Fires when | Example |
|---|---|---|---|
| 1 | `wrong_unit_or_scale` | claimed ÷ gold ≈ 10^±2, 10^±3, 10^±6 or 10^±9 (within tolerance). 10^±2 covers a fraction given for a percent | Capex $1,577 thousand for $1,577 million |
| 2 | `wrong_period` | The claimed value equals the same metric, same company, in another fiscal year (±1, ±2, −3) in XBRL | 3M FY2017 capex given for FY2018 |
| 3 | `wrong_line_item` | The claimed value equals another mapped metric, same company and fiscal year | Revenue given for operating income |
| 4 | `wrong_company` | The claimed value equals the same metric and fiscal year at another in-scope company | Another company's FY2018 capex |
| 5 | `arithmetic` | Recomputing the claim's `expression` from its `derived_from` inputs gives a different value | Inputs 100 and 80, expression `(a - b) / b`, claimed 30% (correct 25%) |
| 6 | `retrieval_miss` | None of the draft's evidence chunks contains FinanceBench's gold evidence (retrieval diagnostic, P2.6) | The right table never reached the model |
| 7 | `other` | No rule fired | |

**Scope of the rules:**
- Rules 1–5 need a gold value, so a text-gold answer judged incorrect is `retrieval_miss` or `other`.
- Rules 2–4 use XBRL only when the answer claim's `metric` is a name in `data/metric_map.yaml` (e.g. `capital_expenditure`, `revenue`, `operating_income`), so generators are asked to use those names.
- Rules 2–4 run for annual (10-K) questions only, and are skipped when XBRL has no value.
- XBRL holds every reported value, including restatements: 3M's FY2017 operating income is both $7,820M (FY2017 10-K) and $7,692M (FY2018 10-K). A match with either counts for typing.

**Check of the automatic types:** 20 classified errors are checked by hand against the filings, and the agreement is reported in one sentence (ROADMAP M1.5).

## 5. Human labels and agreement

Used for the double-coded error sample (mid-term) and the full annotation (Phase 5). Labels use the frozen `Annotation` schema: `question_id`, `claim_id`, `run_id`, `annotator`, `correct`, `error_type`, `note`.

1. **Blind:** annotators see the question, the gold answer, the model answer and its cited text, but not which configuration produced it. Rows are shuffled.
2. **Two annotators per item, independently:** about 25 R0 errors at the mid-term. Each assigns one error type with the rules of §4 and, when needed, a tag in `note`:
   - `gold-ambiguous`: the gold answer itself is unclear, disputable or one of several defensible answers.
   - `technical-failure`: the failure is a pipeline problem (parsing, API error, malformed output), not model behaviour.
3. **Agreement:** Cohen's κ on the error type, reported with the number of items. Aim for κ ≥ 0.7.
4. **Adjudication:** disagreements are discussed; a third person decides any that remain. The adjudicated label is final.

## 6. Edge cases

| Case | Rule |
|---|---|
| Question asks for rounding ("round to one decimal place") | The 1% tolerance covers rounding differences; the rounded value is not required |
| Gold answer uses a different but equivalent unit ($1.6Bn vs $1,600M) | Equal after normalization (§2) |
| Restated figure | Gold follows the FinanceBench document; a claim matching only the restated value is incorrect, typed by §4 |
| Answer gives the right number with the wrong sign | Incorrect; typed `other` unless another rule fires |
| Answer hedges between two numbers | The answer claim decides (single-number gold); the judge decides (text gold) |
| Out-of-scope question (8-K, earnings release) | Not scored: outside `data/SCOPE.md` |
