# Annotation guidelines

**Status: for team approval before the pilot (P5.3).** The six open questions of the first draft are decided (`docs/DECISIONS.md`, 2026-11-26). Everything else restates rules already decided in `docs/LABELING_PROTOCOL.md` and `docs/DECISIONS.md`; if this file and those disagree, those win and this file is fixed. The pilot may still change these rules; every change is recorded in `docs/DECISIONS.md`.

## 1. What you are labelling

Each row of your sheet is one **claim**: one number a system's answer relies on. You see:

- the **question** and the company;
- the **gold answer** (FinanceBench);
- the **system's answer text**;
- the **claim**: its metric (what the number is), value, unit, period, and, for a computed claim, its expression and the claims it is computed from;
- the **cited text**: the filing excerpts the claim cites, each with its header (company, form, period, section, and for a table the scale it is stated in);
- the **filing** the question is about (company, form, fiscal year), so you can look up a figure the cited text doesn't show (§3.2);
- an **automatic pre-label** (whether the claim's value matches the gold answer, where that can be checked by rule).

You do **not** see which system or verifier produced the claim, and rows are shuffled. Don't try to work it out. Label each row on its own.

For each claim you record (the frozen `Annotation` schema):

| Field | What to enter |
|---|---|
| `correct` | yes or no (§3) |
| `error_type` | for an incorrect claim, one type from §4; empty for a correct claim |
| `note` | optional; use the tags in §6 when they apply, and a few words on anything unusual |

Label alone. Don't discuss rows with the other annotator until both of you have finished; disagreements are settled in adjudication (P5.6).

## 2. Number conventions

These are the conventions every claim is written in (LABELING_PROTOCOL §2):

| Item | Rule |
|---|---|
| Values | Full units, never scaled: $394.3B is 394,300,000,000. A table "in millions" that shows 1,577 means 1,577,000,000 |
| Percentages | The percent number: 12.5% is 12.5, not 0.125 |
| Negatives | A minus sign or accounting parentheses: (1,234) is −1,234 |
| Units | USD, USD/share, %, shares, ratio, days |
| Periods | The company's own fiscal year as reported: FY2022, Q3 FY2022, 6M FY2022, 9M FY2022. A balance-sheet value belongs to the period it closes |
| Tolerance | Within 1% of the reference value counts as equal: \|value − reference\| ≤ 1% × \|reference\| |

## 3. When is a claim correct?

**3.1 The answer claim** (the claim that answers the question; it is marked on your sheet). It is correct when it matches the **gold answer** within 1%, in the right unit and scale (LABELING_PROTOCOL §3). Gold is the only reference for the answer: a verifier's verdict, the XBRL data and your own reading of the filing never override it. If you believe the gold is wrong, label against the gold anyway and add the `gold-ambiguous` tag (§6). When the gold is text, compare the answer claim with the figure the gold states for it; if the gold states no figure the claim can be compared with, label the claim as in 3.2 and add a short `note`.

**3.2 Other claims** (inputs and intermediate results). The gold answer usually states only the final figure, so an input claim (e.g. FY2017 revenue used for a growth rate) has no gold value. Such a claim is correct when its value is **what the company's filing reports** for that metric, company and period, within 1%. Check the cited text first; if it doesn't show the value, look in the filing itself (the sheet gives the filing). XBRL may help you find a figure but never decides correctness.

A claim whose value is true but **not in its cited text** (it cites the wrong excerpt, or nothing) is still correct; add the `unsupported` tag (§6). The label records whether the number is true; the tag records whether its evidence supports it.

**3.3 Computed claims.** A computed claim is correct when its value is the right result for the question's calculation **and** its inputs are correct. Recompute it from its inputs (a calculator is fine).

- **Wrong arithmetic** (the value doesn't follow from its inputs and expression): incorrect, `arithmetic`.
- **Right arithmetic on a wrong input:** incorrect, with the **wrong input's error type** (e.g. `wrong_period` if an input is from the wrong year), and the `from-input` tag (§6). If several inputs are wrong, use the type that comes first in the §4 order. The wrong input claim gets its own label as well; the tag lets the analysis count each root error once.
- **Both** (a wrong input and wrong arithmetic): `arithmetic`, with a `note` naming the wrong input.

## 4. Error types

For an incorrect claim, pick **one** type, checking in this order; the first that applies wins (LABELING_PROTOCOL §4). The examples are synthetic (fictional company "Northwind Industries"; `tests/planted/cases.py`).

| # | Type | Use when | Example |
|---|---|---|---|
| 1 | `wrong_unit_or_scale` | The value is right except for the scale or unit: off by a factor of 100, 1,000, a million or a billion, a fraction given for a percent, or the wrong unit | Net sales $12,450 from a table in millions (should be $12,450,000,000) |
| 2 | `wrong_period` | The value is the right metric for the right company, but another period | Net sales of FY2021 ($11,380M) given for FY2022 ($12,450M) |
| 3 | `wrong_line_item` | The value is another line item of the same company and period | Net income ($1,348M) given as operating income ($1,902M) |
| 4 | `wrong_company` | The value is the same metric and period at another company | Contoso's net sales ($9,870M) given for Northwind's |
| 5 | `arithmetic` | A computed claim whose value doesn't follow from its inputs and expression | Gross margin 35.0% from $4,635M / $12,450M (should be 37.2%) |
| 6 | `retrieval_miss` | The right figure isn't in any of the cited text, and the claim doesn't fit 1–5 (the system didn't have the evidence, or made the number up) | Net sales $13,100M, a number the cited table doesn't contain |
| 7 | `other` | Anything else, e.g. the right number with the wrong sign | Net income −$1,348M for a profit of $1,348M |

Notes:
- For types 2–4, check the cited text and, where it doesn't show the value, the filing, to see what the value actually is. XBRL may help you find it but never decides correctness.
- An answer may be wrong for a reason no single claim shows (e.g. the system answered a different question). Label the claims as they are, and add a short `note`.

## 5. Edge cases

Decided (LABELING_PROTOCOL §6, DECISIONS):

| Case | Rule |
|---|---|
| The question asks for rounding ("one decimal place") | The 1% tolerance covers it; the rounded figure is not required |
| Equivalent units ($1.6Bn and $1,600M) | Equal after the conventions in §2 |
| A restated figure | The gold follows the FinanceBench document; a value that matches only the restated figure is incorrect for the answer claim |
| The right number with the wrong sign | Incorrect; `other` unless another type fits. A cash outflow written as a negative number is **not** a sign error (filings print outflows in parentheses) |
| An answer that hedges between several numbers, or says it cannot answer and then lists figures | Incorrect for a text-gold answer (DECISIONS 2026-11-22, `financebench_id_02119`) |

Decided for annotation (DECISIONS 2026-11-26):

| Case | Rule |
|---|---|
| Right value, wrong citation: the cited excerpt doesn't contain the value, or the claim cites nothing | Correct if the value is true (§3.2), with the `unsupported` tag |
| Right value, wrong period label: the value is right, but the claim's `period` field names another period (FY2022 revenue labelled FY2021) | Correct, with the `label-error` tag. A value that **is** another period's figure is `wrong_period` (§4) |
| Right value, wrong unit label: the value is right in size and meaning, but the `unit` field is wrong (diluted EPS $4.12 labelled USD instead of USD/share) | Correct, with the `label-error` tag. A value off by a scale (1,000, a million…) or a fraction given for a percent is still `wrong_unit_or_scale` |
| A claim that is true but plays no part in answering the question (an extra figure the system mentioned) | Labelled like any other claim (§3.2), with the `irrelevant` tag. Don't skip it |
| Right arithmetic on a wrong input | §3.3: the input's error type, with the `from-input` tag |

## 6. Tags for the `note` field

| Tag | Use when |
|---|---|
| `gold-ambiguous` | The gold answer itself is unclear, disputable, contradicts the filing, or is one of several defensible answers |
| `technical-failure` | The problem is a pipeline failure (parsing, an API error, a malformed claim), not model behaviour |
| `unsupported` | The value is true, but the claim's cited text doesn't contain it, or the claim cites nothing (§3.2) |
| `from-input` | A computed claim is wrong only because one of its inputs is wrong; its error type is the input's (§3.3) |
| `label-error` | The value is right, but the claim's `period` or `unit` field is wrong (§5) |
| `irrelevant` | The claim plays no part in answering the question (§5) |

Several tags can apply; separate them with spaces (e.g. `unsupported irrelevant`). Add free text after the tags if it helps adjudication.

## 7. Process

1. **Pilot (P5.3):** all five annotators label the same 30 claims. The team discusses every disagreement and revises these guidelines. Pilot labels are not used in the results.
2. **Main round (P5.4):** each claim is labelled by two annotators, with pairs rotating so each pair shares about the same number of claims. Model-suggested error types are never shown (anchoring).
3. **Agreement (P5.5):** Cohen's κ for `correct` and for `error_type`, reported with the number of claims. The aim is κ ≥ 0.7.
4. **Adjudication (P5.6):** the pair discusses each disagreement; a third annotator decides any that remain. The adjudicated label is final.
