# R1 trace review (dev, run 2026-11-21_r1_v0_0236238)

> Notes drafted by an AI agent from the saved traces (2026-11-22) and checked by a human reviewer against the trace page. Figures marked "derived" are computed from the filing's own numbers.

Notes on method:
- "Rounds" = `steps_used` (tool rounds; parallel calls in one AI turn count as one round; the final Answer call is not counted). Limit 8.
- Saved tool outputs are truncated to 2,500 chars. In several traces the agent cites chunks (and uses figures) that are not visible in the saved output. Where it mattered, I checked the figure against `data/chunks/<cik>/<accession>.jsonl`; those checks are marked "(checked in chunks)".
- Any number below that is not quoted from a trace or chunk is a derived value I computed from those figures, and is marked "derived".

## Summary of patterns

| Pattern | Traces (ids) | Count | Suggested fix |
|---|---|---|---|
| A. First search uses a bad CIK (ticker, name, or wrong number), issued in parallel with `resolve_company` | 00283 ("4818"), 00288 ("768706"), 00563 ("2"), 00807 ("3M"), 02119 ("JPM") | 5 | Make `search_filings` reject a non-10-digit CIK with an explicit "call resolve_company first" message, or resolve tickers/names inside the tool. Prompt: don't search before the resolver returns. Cost is small (1 empty search each, same round as the resolve). |
| B. Calculator variables named with plain numbers (`{"9585": 9585}`) | 00723, 06741 | 2 | Tool description: say names must start with a letter, or accept literal-only expressions with no `variables`. Each case cost 3 errors / 1 round. |
| C. Runs out of rounds hunting one line item (primary statement table never surfaces) | 00540 (total cost of sales), 04481 (cash-flow D&A); partly 00807 (balance sheet line items) | 2 (+1) | Primary statements are hard to hit by vector search. Options: a statement-type filter / "get statement" tool, or boost chunks headed "CONSOLIDATED STATEMENTS OF ...". Also stop the model padding queries with guessed numbers (00540 "12,200", "10,000 11,000 12,000"). |
| D. `fetch_filing` on an already-indexed filing | 00807, 04481 | 2 | Reply already says "already indexed"; it costs 1 round each. Could tell the model in the search result header that the filing is indexed, or note in the prompt that fetch is only for missing filings. |
| E. Right tables/figures found, but number differs from gold because of a definition choice | 00216 (quick ratio), 00540 (inventory turnover: average vs ending inventory), 00807 (quick ratio), 02119 (book value vs tangible book value per share) | 4 | Not a retrieval problem. Research-design question: whether the prompt should state FinanceBench's conventions; probably leave as a documented error type. |
| F. No period/form filter, answer from the wrong filing | 00283 | 1 | Prompt: always filter by form + fiscal_year/period of the question's filing. |
| G. Gold debatable / possible gold errata | 00080 (could not reproduce $1.6B), 00283 (77.78 looks like a misreading of the filing) | 2 | Send to reviewer for `financebench_audit.csv` / DECISIONS.md. |
| **New** H. Year-column misread in a multi-year table | 00591 (FY2020 net income used as FY2021) | 1 | Scored correct anyway. Hard to fix by prompt; a verifier would catch it. |
| **New** I. Section filter that doesn't match 10-Q section names (`"section": "Item 1"` vs stored "Part I, Item 1") | 00807 | 1 | Normalise section filters in `search_filings` (accept "Item 1" for 10-Qs) or list valid values in the tool description. |
| **New** J. Agent's yes/no conclusion contradicts gold even though the figures are defensible | 00216, 00807 (both say liquidity is "reasonably healthy"; gold says "No") | 2 | Part of E; worth tracking separately because the judge scores the conclusion. |

Scoring observations (not agent failures, but relevant to the reviewer): 02119, where R0's hedged answer (it also listed the gold $66.56) was judged correct and R1's $82.31 incorrect (logged as a judge error, DECISIONS 2026-11-22); a hedged "I could not fully answer this" answer scored correct (04481); a gold with very coarse rounding (03473); a judge tolerating 0.9 vs 0.8 (00684). See per-trace notes.

Rejected / not seen: none of the candidate patterns was rejected outright, but F is rarer than expected (1 of 20): almost every search was filtered by form and fiscal_year/period.

## Per-trace notes

### financebench_id_00080 · PayPal · R1 incorrect
Right filing (PayPal 10-K FY2022, balance sheet chunk item-8-95 on the first search). No wasted rounds (3 rounds). The agent's figures match the filing exactly: total current assets 57,517 and total current liabilities 45,101 ($M), giving 12,416 ($12.4B); it also flagged that customer funds (36,357 receivable / 40,107 payable) dominate both sides. I could not find a calculation from the balance-sheet lines that gives the gold's $1.6B: the standard definition gives 12,416, and excluding customer funds gives 16,166 (derived: (57,517 − 36,357) − (45,101 − 40,107)); a brute-force search over sums/differences of 2–3 balance-sheet lines found only meaningless combinations near 1,600. **Possible gold errata candidate** (unsure: the gold may use a definition I did not think of; 16,166 → "$1.6Bn" would need a decimal slip, which is speculation).  Patterns: G (E if a definition is found)

### financebench_id_00216 · Verizon · R1 incorrect
Right filing (Verizon 10-K FY2022). Wasted rounds: 4 searches (rounds 1–4, three near-identical "consolidated balance sheet" queries) returned notes tables instead of the balance sheet, which surfaced on the 5th search; 6 rounds total, no empty searches. Agent used quick ratio = (current assets − inventories) / current liabilities = (37,857 − 2,388) / 50,171 = 0.71. Gold 0.54 matches (cash 2,605 + receivables net 24,506) / 50,171 = 0.540 (derived), so a definition difference, not a retrieval error. The agent also concluded liquidity is "reasonably healthy", while gold says "No".  Patterns: E, J (repeated searches: C-like but did not hit the limit)

### financebench_id_00283 · Pfizer · R1 incorrect
Wrong filing: the gold document is Pfizer's Q2 2023 10-Q, but none of the 4 searches had a form/year/period filter, and the answer came from the FY2021 10-K ("approximately $700 million ... ~75% incurred"). Wasted: 1 empty search with bad CIK "4818" (issued in parallel with resolve). (checked in chunks) The Q2 2023 10-Q (0000078003-23-000088) says "We expect to incur costs of approximately $700 million in connection with separating Upjohn, of which approximately 90% has been incurred". The remaining amount by a plain reading would be about $70M (derived, 10% × 700); the gold 77.78 equals 700 / 9 (derived), i.e. treating $700M as the 90% already incurred. The agent's $700M (total, not future) is wrong under either reading, but the gold looks debatable.  Patterns: A, F, G

### financebench_id_00288 · Best Buy · R1 correct
Right filings (10-K FY2023 and 10-Q Q2 FY2024), found with form+year/period filters. Wasted: 1 empty search with a wrong CIK "768706" (not Best Buy's 0000764478), in parallel with resolve. Cash fell from 1,874 to 1,093 ($M), −781; the agent did not state a percentage, but 781/1,874 = 41.7% (derived) is consistent with the gold's ~42%, and the judge accepted the "Yes".  Patterns: A

### financebench_id_00540 · AES Corporation · R1 incorrect
Right filing (AES 10-K FY2022). Inventory note found in round 2, but total cost of sales took 6 more searches (rounds 3–8), two of them stuffed with guessed numbers ("12,200", "10,000 11,000 12,000"); the income statement (item-8-124) surfaced only in round 8, then the forced-finalize nudge. Agent computed 10,069 / average inventory 829.5 = 12.14 (no calculator call; computed in the answer). Gold 9.5 matches cost of sales / ending inventory: 10,069 / 1,055 = 9.54 (derived) (cost of sales checked in chunks). So a definition choice (average vs ending inventory). The answer text is also internally inconsistent: "roughly 10.5 times" and then "≈ 12.1 times".  Patterns: C, E

### financebench_id_00563 · AMD · R1 correct
Right filing (AMD 10-K FY2022). Wasted: 1 empty search with CIK "2" (in parallel with resolve). Segment table (cited item-8-64, not visible in the truncated saved output) gave Data Center +63.6%, Gaming +21.4%, Client −10.0%; Data Center matches gold. Calculator got literal expressions, so the `c1`/`c2` variables were unused but harmless.  Patterns: A

### financebench_id_00591 · Adobe · R1 correct (with a data error)
Right filing (Adobe 10-K FY2022); 5 rounds, one search (round 3) returned the PP&E note instead of the cash flow statement. FY2022 conversion 155.5% matches gold (156%). But the FY2021 figure is wrong: the agent used net income 5,260 for FY2021, which is the FY2020 column; (checked in chunks, item-8-59) FY2021 net income is 4,822, giving 6,882 / 4,822 = 142.7% (derived), which matches the gold's 143%. OCF 7,230 and capex 348 for FY2021 are correct. Conclusion ("improved") is right either way, so the judge marked it correct.  Patterns: H

### financebench_id_00684 · Amcor · R1 correct
Right filing (Amcor 10-K FY2023); MD&A gross-profit table (item-7-30) found in round 2 with 18.5% (FY2023) vs 19.4% (FY2022). Rounds 3–4 (net sales, explanatory text) were extra but harmless; 5 rounds. Why R1 and R0 differ yet both score correct: gold is text ("No ... slight decline ... by 0.8%"), so it is judged. R1 says No, 19.4% → 18.5% (a 0.9 pp drop from the rounded MD&A percentages); R0's answer number is −0.9%. Gold 0.8 matches unrounded figures: 2,820/14,544 = 19.39% and 2,725/14,694 = 18.54%, a 0.84 pp drop (derived; 14,544 and 14,694 are in the trace). Both answers have the same conclusion and a figure within rounding, so the judge accepted both. Note the scored claim (c4 = 18.5%) is the FY2023 level, not the decline.  Patterns: none (correct)

### financebench_id_00702 · Pfizer · R1 correct
Right filing (Pfizer 10-K FY2019); the first search already returned the $8.1B pre-tax gain on the GSK Consumer Healthcare JV (item-8-118), which matches gold. The next 4 searches (rounds 2–5) were mostly spent looking for net income, one with a figure "17,682" in the query that does not appear in the earlier visible outputs. Net income figures 16,272 / 11,152 checked in chunks.  Patterns: none (minor extra searching)

### financebench_id_00723 · American Express · R1 correct
Right filing (AmEx 10-K FY2022); income statement found in round 3. Wasted: 1 round with 3 calculator errors (variables named "9585", "52862", …). Correct because gold says operating margin is not how performance is measured, and the agent said exactly that (no "operating income" line) before giving a pretax-margin proxy (18.1% in 2022 vs 25.2% in 2021).  Patterns: B

### financebench_id_00807 · 3M · R1 incorrect
Right filing (3M 10-Q Q2 FY2023). Wasted: 2 empty searches (bad CIK "3M" in round 1; `section: "Item 1"` in round 6, which doesn't match "Part I, Item 1"), 1 fetch on an already-indexed filing (round 7), and repeated balance-sheet searches in rounds 2–5 that mostly returned Q1 tables; hit the 8-round limit right after the calculation. (checked in chunks, item-1-97) The agent's figures match the filing: cash 4,258, current marketable securities 56, receivables 4,947, total current liabilities 10,936, giving (4,258 + 56 + 4,947) / 10,936 = 0.85. Gold 0.96 matches (total current assets 15,754 − total inventories 5,280) / 10,936 = 0.958 (derived), i.e. a broader definition that keeps prepaids and other current assets. **Agent definition choice, not a gold error.** The agent also answered "Yes, reasonably healthy", which contradicts the gold's "No".  Patterns: A, C (partial), D, E, I, J

### financebench_id_00995 · AMD · R1 correct
Right filing (AMD 10-K FY2022), 2 rounds. Correct because the four-segment product list matches the gold text closely. Oddity: it emitted placeholder claims with value 1 and unit "ratio" for each segment, and `answer_claim_id` is null; the cited chunk (item-1-5) is not in the visible saved output.  Patterns: none (note placeholder claims)

### financebench_id_02119 · JPMorgan · R1 incorrect
Right filing (JPM 10-Q Q1 FY2021). Wasted: 1 empty search with CIK "JPM". Agent computed common equity 249,151 / 3,027,128,112 shares = $82.31, which is exactly the book value per share reported in the 10-Q. (checked in chunks) Gold $66.56 is the tangible book value per share reported in the same filing. So a definition choice (whether goodwill/intangibles count in liquidation). R0's answer claim was also 82.31, but its text said the value "cannot be computed" and listed the gold $66.56 as a second proxy; the judge credited that, which is logged as a judge error (DECISIONS 2026-11-22). R1's incorrect verdict stands.  Patterns: A, E

### financebench_id_03282 · Netflix · R1 correct
Right filing (Netflix 10-K FY2017), balance sheet on the first search (2 rounds). 5,466,312 thousand = $5,466.3M, matches gold $5,466.  Patterns: none

### financebench_id_03473 · Coca-Cola · R1 correct
Right filing (Coca-Cola 10-K FY2017); 4 rounds, no waste. Agent: 1,283 / average total assets 87,583 = 1.46% (1,283 is consolidated net income, including noncontrolling interests; attributable net income is 1,248, checked in chunks, giving 1.42%, derived). Why R1 (1.46%) and R0 (1.25%) both score correct: gold is the number 0.01 (ratio), and the question says "round to two decimal places", so the scorer converts % to ratio (0.0146, 0.0125) and accepts anything within half a unit of 0.01, i.e. roughly 0.5%–1.5%. The gold is so coarse that it can't distinguish the two answers. I did not see R0's trace, so I can't say how it got 1.25%.  Patterns: none (gold precision issue)

### financebench_id_03838 · Block · R1 correct
Right filing (Block 10-K FY2020), revenue table on the first search; 3 rounds. 9,497,578 vs 4,713,500 thousand → 101.5%, matches gold. (Used a geographic revenue table, whose total equals total net revenue.)  Patterns: none

### financebench_id_04481 · PepsiCo · R1 correct (hedged)
Right filing (PepsiCo 10-K FY2022). 8 rounds, 9 searches and 1 fetch on an already-indexed filing (round 6); the cash flow statement chunk never surfaced, then the nudge. What happened: the agent took D&A from the segment table (item-8-75): depreciation and other amortization 2,685 + amortization of intangibles 78 = 2,763, and said in the text it could not confirm the cash-flow figure. (checked in chunks) The cash flow statement (item-8-61) shows "Depreciation and amortization 2,763", so the proxy equals the requested line exactly. (11,512 + 2,763) / 86,392 = 16.5%, matching gold. It scored correct because the gold is a number, so only the answer claim c7 = 16.5 is scored; the refusal check only fires when there are no claims. The hedge "I could not fully answer this" doesn't affect numeric scoring.  Patterns: C, D

### financebench_id_06741 · Walmart · R1 correct
Right filing (Walmart 10-K FY2020); income and cash-flow statements found in round 2. Wasted: 1 round with 3 calculator errors (numeric variable names). Margins 6.19%, 6.34%, 6.02% → average 6.19%, matches gold 6.2%.  Patterns: B

### financebench_id_08135 · Amazon · R1 correct
Right filing (Amazon 10-K FY2017); 3 rounds. 135,987 → 177,866 = +30.8%, matches gold. The cited chunk (item-8-55) is not in the visible saved output (truncated).  Patterns: none

### financebench_id_10285 · Boeing · R1 correct
Right filing (Boeing 10-K FY2018); PP&E note found on the first search; 3 rounds. 31,213 − 18,568 = 12,645, matches gold (the calculation only re-checked the reported total).  Patterns: none

## Open questions for the reviewer

1. **00080 PayPal gold ($1.6B):** I could not reproduce it from the FY2022 balance sheet. Treat as a gold errata candidate or look for a definition I missed?
2. **00283 Pfizer gold (77.78):** it equals 700/9, which reads the 10-Q's "$700 million ... 90% incurred" as if $700M were the 90%. A plain reading gives about $70M remaining. Should this be logged as a debatable gold?
3. **02119 JPMorgan:** resolved. R0's verdict came from a hedged answer that listed the gold value; logged as a judge error, `judge_v1` stays primary (DECISIONS 2026-11-22).
4. **E cases (00216, 00540, 00807, 02119):** the agent's figures match the filing; the gap is the formula (quick ratio components, average vs ending inventory, BVPS vs TBVPS). Is this "different formula/definition than the gold" in LABELING_PROTOCOL terms, and should the prompt ever state FinanceBench's conventions? (Research-design question; I have not changed anything.)
5. **04481 PepsiCo:** correct by numeric scoring despite the hedge. Fine as is, or should hedged numeric answers be flagged for the human labellers?
6. **03473 Coca-Cola:** gold 0.01 with "two decimal places" accepts roughly 0.5%–1.5%. Worth noting as a low-information item?
7. **Resolver metadata:** `resolve_company` reported Amcor's fiscal year end as 12-31, but the filing says "Years ended June 30". It did not affect this answer; worth checking the companies table.
8. **Truncated traces:** the review export cut tool outputs at 2,500 characters (the saved traces in `runs/` are complete), so for 00563, 00591, 00702, 00807, 00995, 02119, 04481, 08135 the cited chunks/figures are not visible in the trace. I checked the figures that mattered in the chunk files, but the reviewer can't verify from the trace alone. A later export can show them in full.
9. Pattern A cost is small (the bad search runs in parallel with the resolve). Is it worth a fix, or just a note?
