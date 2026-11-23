"""Planted-error suite (ROADMAP P4.7, guide §4.5): hand-made drafts, each with one known error.

Every figure here is SYNTHETIC: "Northwind Industries" and "Contoso Ltd" are fictional
companies with made-up, internally consistent statements (gross profit = net sales - cost
of sales, and so on), and the XBRL values in FACTS are the same made-up figures. Nothing here
is a real filing or a real result.

Each case is one draft with one planted error in one claim (`planted`), the error type it
belongs to (docs/LABELING_PROTOCOL.md §4), the value that claim should have (`truth`, to see
whether a revision fixed it), and `caught_by`: exactly the V2 checks that should fail on the
draft as written. An empty `caught_by` marks an error V2 cannot see by design (each one says
why in `note`); those are reported, not hidden. Controls have no error and must not be flagged.

    tests/test_planted.py       V2's checks against `caught_by` (no model)
    scripts/planted_errors.py   V1 and V2 with the model on every case -> docs/PLANTED_ERRORS.md
"""

from __future__ import annotations

from dataclasses import dataclass

from finqa.schemas import Chunk, Claim, Draft, ErrorType

NWD = "0000000001"  # fictional CIKs
CONTOSO = "0000000002"
COMPANY = "Northwind Industries"


def _chunk(cid: str, text: str, *, scale: float | None = 1e6, cik: str = NWD) -> Chunk:
    return Chunk(
        chunk_id=cid,
        cik=cik,
        ticker="NWD" if cik == NWD else "CTSO",
        form="10-K",
        fiscal_year=2022,
        period="FY2022",
        section="Item 8" if scale else "Item 7",
        is_table=scale is not None,
        unit_scale=scale,
        text=text,
        source_accession="0000000001-23-000001" if cik == NWD else "0000000002-23-000001",
    )


INCOME = _chunk(
    "is",
    "| | 2022 | 2021 |\n"
    "| Net sales | 12,450 | 11,380 |\n"
    "| Cost of sales | 7,815 | 7,240 |\n"
    "| Gross profit | 4,635 | 4,140 |\n"
    "| Research and development | 845 | 790 |\n"
    "| Operating income | 1,902 | 1,655 |\n"
    "| Net income | 1,348 | 1,190 |\n"
    "| Diluted earnings per share | $ 4.12 | $ 3.61 |",
)
CASH_FLOW = _chunk(
    "cf",
    "| | 2022 | 2021 |\n"
    "| Net cash provided by operating activities | 2,214 | 1,987 |\n"
    "| Purchases of property, plant and equipment | (612) | (548) |",
)
BALANCE = _chunk(
    "bs",
    "| | 2022 | 2021 |\n"
    "| Inventories | 1,488 | 1,302 |\n"
    "| Total current assets | 5,630 | 5,210 |\n"
    "| Total current liabilities | 3,940 | 3,705 |",
)
MDA = _chunk(
    "mda",
    "Net sales increased 9.4% to $12.5 billion in fiscal 2022, driven by higher volumes. "
    "The effective tax rate was 21.3% compared with 22.0% in fiscal 2021.",
    scale=None,
)
CONTOSO_INCOME = _chunk(
    "ct",
    "| | 2022 | 2021 |\n| Net sales | 9,870 | 9,120 |\n| Net income | 1,026 | 948 |",
    cik=CONTOSO,
)
EVIDENCE = [INCOME, CASH_FLOW, BALANCE, MDA]

# (cik, metric, period) -> values, the fake XBRL the checks and the script look up
FACTS: dict[tuple[str, str, str], list[float]] = {
    (NWD, "revenue", "FY2022"): [12.45e9],
    (NWD, "revenue", "FY2021"): [11.38e9],
    (NWD, "cost_of_revenue", "FY2022"): [7.815e9],
    (NWD, "gross_profit", "FY2022"): [4.635e9],
    (NWD, "operating_income", "FY2022"): [1.902e9],
    (NWD, "net_income", "FY2022"): [1.348e9],
    (NWD, "eps_diluted", "FY2022"): [4.12],
    (NWD, "operating_cash_flow", "FY2022"): [2.214e9],
    (NWD, "capital_expenditure", "FY2022"): [0.612e9],
    (NWD, "inventory", "FY2022"): [1.488e9],
    (NWD, "current_assets", "FY2022"): [5.63e9],
    (NWD, "current_liabilities", "FY2022"): [3.94e9],
    (NWD, "effective_tax_rate", "FY2022"): [21.3],
    (CONTOSO, "revenue", "FY2022"): [9.87e9],
}


def lookup(cik: str, metric: str, period: str) -> list[float]:
    return FACTS.get((cik, metric, period), [])


def quoted(
    cid: str, metric: str, value: float, unit: str, cites: list[str], period: str = "FY2022"
) -> Claim:
    return Claim(
        claim_id=cid,
        metric=metric,
        value=value,
        unit=unit,  # type: ignore[arg-type]
        period=period,  # type: ignore[arg-type]
        chunk_ids=cites,
    )


def computed(
    cid: str, metric: str, value: float, unit: str, inputs: list[str], expression: str
) -> Claim:
    return Claim(
        claim_id=cid,
        metric=metric,
        value=value,
        unit=unit,  # type: ignore[arg-type]
        period="FY2022",
        chunk_ids=[],
        derived_from=inputs,
        expression=expression,
    )


@dataclass(frozen=True)
class Case:
    case_id: str
    error_type: ErrorType | None  # None for a control
    question: str
    answer_text: str
    claims: tuple[Claim, ...]
    planted: str | None  # the claim with the error; None for a control
    truth: float | None  # what that claim's value should be
    caught_by: frozenset[str]  # the V2 checks that should fail; empty: V2 cannot see it
    note: str
    extra_evidence: tuple[Chunk, ...] = ()

    def draft(self) -> Draft:
        evidence = {c.chunk_id: c for c in (*EVIDENCE, *self.extra_evidence)}
        return Draft(
            question_id=f"planted_{self.case_id}",
            retrieval_arm="rag",
            answer_text=self.answer_text,
            claims=list(self.claims),
            answer_claim_id=self.claims[-1].claim_id,
            evidence=evidence,
            trace_id=f"planted_{self.case_id}",
            latency_s=0.0,
            tokens_in=0,
            tokens_out=0,
        )


CITED, XBRL, RECOMPUTE = "cited_text", "xbrl", "recompute"
REVENUE_Q = f"What was {COMPANY}'s FY2022 net sales (in USD millions)?"
MARGIN_Q = f"What was {COMPANY}'s FY2022 gross margin (gross profit / net sales, in %)?"
RATIO_Q = f"What was {COMPANY}'s current ratio at the end of FY2022?"
GROWTH_Q = f"By how much did {COMPANY}'s net sales grow in FY2022, in %?"


def _margin(value: float) -> tuple[Claim, ...]:
    return (
        quoted("c1", "gross profit", 4.635e9, "USD", ["is"]),
        quoted("c2", "net sales", 12.45e9, "USD", ["is"]),
        computed("c3", "gross margin", value, "%", ["c1", "c2"], "c1 / c2 * 100"),
    )


def _ratio(value: float) -> tuple[Claim, ...]:
    return (
        quoted("c1", "total current assets", 5.63e9, "USD", ["bs"]),
        quoted("c2", "total current liabilities", 3.94e9, "USD", ["bs"]),
        computed("c3", "current ratio", value, "ratio", ["c1", "c2"], "c1 / c2"),
    )


def _growth(value: float) -> tuple[Claim, ...]:
    return (
        quoted("c1", "net sales", 12.45e9, "USD", ["is"]),
        quoted("c2", "net sales", 11.38e9, "USD", ["is"], period="FY2021"),
        computed("c3", "net sales growth", value, "%", ["c1", "c2"], "(c1 - c2) / c2 * 100"),
    )


NONE: frozenset[str] = frozenset()
CASES: list[Case] = [
    # --- Controls: no error; V2 must not flag them ----------------------------------------
    Case(
        "control_revenue",
        None,
        REVENUE_Q,
        "Net sales were $12,450 million.",
        (quoted("c1", "net sales", 12.45e9, "USD", ["is"]),),
        None,
        None,
        NONE,
        "single fact from a millions table",
    ),
    Case(
        "control_margin",
        None,
        MARGIN_Q,
        "Gross margin was 37.2%.",
        _margin(37.23),
        None,
        None,
        NONE,
        "computed percent",
    ),
    Case(
        "control_ratio",
        None,
        RATIO_Q,
        "The current ratio was 1.43.",
        _ratio(1.43),
        None,
        None,
        NONE,
        "computed ratio, rounded to two decimals",
    ),
    Case(
        "control_prose",
        None,
        GROWTH_Q,
        "Net sales grew 9.4%.",
        (quoted("c1", "net sales growth", 9.4, "%", ["mda"]),),
        None,
        None,
        NONE,
        "percent quoted from prose",
    ),
    Case(
        "control_outflow",
        None,
        f"What were {COMPANY}'s FY2022 capital expenditures (in USD millions)?",
        "Capital expenditures were $612 million.",
        (quoted("c1", "capital expenditures", -0.612e9, "USD", ["cf"]),),
        None,
        None,
        NONE,
        "an outflow written as a negative number: sign is presentation, not an error",
    ),
    # --- Wrong unit or scale --------------------------------------------------------------
    Case(
        "scale_unscaled",
        ErrorType.WRONG_UNIT,
        REVENUE_Q,
        "Net sales were $12,450.",
        (quoted("c1", "net sales", 12450.0, "USD", ["is"]),),
        "c1",
        12.45e9,
        frozenset({CITED, XBRL}),
        "the table's 'in millions' was not applied",
    ),
    Case(
        "scale_thousands",
        ErrorType.WRONG_UNIT,
        f"What were {COMPANY}'s FY2022 capital expenditures (in USD millions)?",
        "Capital expenditures were $612 thousand.",
        (quoted("c1", "capital expenditures", 612e3, "USD", ["cf"]),),
        "c1",
        0.612e9,
        frozenset({CITED, XBRL}),
        "thousands for millions",
    ),
    Case(
        "unit_eps_as_usd",
        ErrorType.WRONG_UNIT,
        f"What was {COMPANY}'s FY2022 diluted EPS?",
        "Diluted EPS was $4.12.",
        (quoted("c1", "diluted EPS", 4.12, "USD", ["is"]),),
        "c1",
        4.12,
        frozenset({CITED}),
        "a per-share figure given unit USD: in a millions table a bare USD amount must be "
        "scaled, so the check fails; XBRL does not run (EPS is USD/share). The value itself "
        "is right, so a revision should change the unit, not the value",
    ),
    Case(
        "scale_percent_as_fraction",
        ErrorType.WRONG_UNIT,
        MARGIN_Q,
        "Gross margin was 0.37%.",
        _margin(0.3723),
        "c3",
        37.23,
        frozenset({RECOMPUTE}),
        "the expression multiplies by 100 (37.23) but the claim gives the fraction 0.3723",
    ),
    Case(
        "scale_fraction_formula",
        ErrorType.WRONG_UNIT,
        MARGIN_Q,
        "Gross margin was 0.37%.",
        (
            quoted("c1", "gross profit", 4.635e9, "USD", ["is"]),
            quoted("c2", "net sales", 12.45e9, "USD", ["is"]),
            computed("c3", "gross margin", 0.3723, "%", ["c1", "c2"], "c1 / c2"),
        ),
        "c3",
        37.23,
        NONE,
        "NOT CHECKABLE BY V2: the formula and the value agree (a fraction, 0.3723) and only "
        "the unit says %; recomputation reads a fraction as a percent only when the claim is "
        "1 or more, so a sub-1 percent and a fraction look the same",
    ),
    # --- Wrong period -----------------------------------------------------------------------
    Case(
        "period_revenue",
        ErrorType.WRONG_PERIOD,
        REVENUE_Q,
        "Net sales were $11,380 million.",
        (quoted("c1", "net sales", 11.38e9, "USD", ["is"]),),
        "c1",
        12.45e9,
        frozenset({XBRL}),
        "the FY2021 column claimed as FY2022: the number is in the cited table, so only "
        "XBRL sees it",
    ),
    Case(
        "period_inventory",
        ErrorType.WRONG_PERIOD,
        f"What were {COMPANY}'s inventories at the end of FY2022 (in USD millions)?",
        "Inventories were $1,302 million.",
        (quoted("c1", "inventories", 1.302e9, "USD", ["bs"]),),
        "c1",
        1.488e9,
        frozenset({XBRL}),
        "balance-sheet prior-year column",
    ),
    Case(
        "period_unmapped",
        ErrorType.WRONG_PERIOD,
        f"What was {COMPANY}'s FY2022 research and development expense (in USD millions)?",
        "R&D expense was $790 million.",
        (quoted("c1", "research and development", 0.79e9, "USD", ["is"]),),
        "c1",
        0.845e9,
        NONE,
        "NOT CHECKABLE BY V2: the number is in the cited table and R&D is not in "
        "metric_map.yaml, so no check can tell the columns apart",
    ),
    # --- Wrong line item ------------------------------------------------------------------
    Case(
        "line_item_net_for_operating",
        ErrorType.WRONG_LINE_ITEM,
        f"What was {COMPANY}'s FY2022 operating income (in USD millions)?",
        "Operating income was $1,348 million.",
        (quoted("c1", "operating income", 1.348e9, "USD", ["is"]),),
        "c1",
        1.902e9,
        frozenset({XBRL}),
        "net income's row read as operating income",
    ),
    Case(
        "line_item_gross_for_cost",
        ErrorType.WRONG_LINE_ITEM,
        f"What was {COMPANY}'s FY2022 cost of sales (in USD millions)?",
        "Cost of sales was $4,635 million.",
        (quoted("c1", "cost of sales", 4.635e9, "USD", ["is"]),),
        "c1",
        7.815e9,
        frozenset({XBRL}),
        "gross profit's row read as cost of sales",
    ),
    # --- Arithmetic ---------------------------------------------------------------------------
    Case(
        "arithmetic_margin",
        ErrorType.ARITHMETIC,
        MARGIN_Q,
        "Gross margin was 35.0%.",
        _margin(35.0),
        "c3",
        37.23,
        frozenset({RECOMPUTE}),
        "wrong division result",
    ),
    Case(
        "arithmetic_ratio",
        ErrorType.ARITHMETIC,
        RATIO_Q,
        "The current ratio was 1.52.",
        _ratio(1.52),
        "c3",
        1.4289,
        frozenset({RECOMPUTE}),
        "wrong division result",
    ),
    # --- Not in the evidence (retrieval miss or invented) -------------------------------
    Case(
        "unsupported_value",
        ErrorType.RETRIEVAL_MISS,
        REVENUE_Q,
        "Net sales were $13,100 million.",
        (quoted("c1", "net sales", 13.1e9, "USD", ["is"]),),
        "c1",
        12.45e9,
        frozenset({CITED, XBRL}),
        "a number the cited table does not contain",
    ),
    Case(
        "unretrieved_citation",
        ErrorType.RETRIEVAL_MISS,
        f"What was {COMPANY}'s FY2022 operating cash flow (in USD millions)?",
        "Operating cash flow was $2,214 million.",
        (quoted("c1", "net cash provided by operating activities", 2.214e9, "USD", ["k9"]),),
        "c1",
        2.214e9,
        frozenset({CITED}),
        "the value is right but cites an excerpt that was never retrieved; XBRL agrees, "
        "so only the citation fails",
    ),
    Case(
        "uncited_value",
        ErrorType.RETRIEVAL_MISS,
        f"What was {COMPANY}'s FY2022 operating cash flow (in USD millions)?",
        "Operating cash flow was $2,500 million.",
        (quoted("c1", "operating cash flow", 2.5e9, "USD", []),),
        "c1",
        2.214e9,
        frozenset({CITED, XBRL}),
        "a number with no citation",
    ),
    # --- Wrong company ----------------------------------------------------------------------
    Case(
        "wrong_company",
        ErrorType.WRONG_COMPANY,
        REVENUE_Q,
        "Net sales were $9,870 million.",
        (quoted("c1", "net sales", 9.87e9, "USD", ["ct"]),),
        "c1",
        12.45e9,
        frozenset({XBRL}),
        "Contoso's net sales, cited from Contoso's filing: the citation holds, XBRL for the "
        "question's company does not",
        extra_evidence=(CONTOSO_INCOME,),
    ),
    # --- Other: sign ---------------------------------------------------------------------------
    Case(
        "sign_computed",
        ErrorType.OTHER,
        GROWTH_Q,
        "Net sales fell 9.4%.",
        _growth(-9.4),
        "c3",
        9.4,
        frozenset({RECOMPUTE}),
        "growth with the wrong sign",
    ),
    Case(
        "sign_quoted",
        ErrorType.OTHER,
        f"What was {COMPANY}'s FY2022 net income (in USD millions)?",
        "Net loss was $1,348 million.",
        (quoted("c1", "net income", -1.348e9, "USD", ["is"]),),
        "c1",
        1.348e9,
        NONE,
        "NOT CHECKABLE BY V2: quoted values are compared ignoring sign (outflows are printed "
        "in parentheses; DECISIONS 2026-11-08, 2026-11-22)",
    ),
]

QUESTIONS = {f"planted_{c.case_id}": c.question for c in CASES}
