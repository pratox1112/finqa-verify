"""Retrieval diagnostic (ROADMAP P2.6): hand-made evidence/chunk pairs, hit@k."""

from finqa.config import BASE_CONFIG, load_config
from finqa.eval.retrieval_diag import diagnose, hit_at_k, hit_curve, overlap
from finqa.schemas import Chunk, Draft

CFG = load_config(BASE_CONFIG).diagnostics
N, T = CFG.evidence_shingle_size, CFG.evidence_overlap_threshold
GOLD = [
    "Purchases of property, plant and equipment (PP&E) (1,577) (1,373) (1,420) "
    "Proceeds from sale of PP&E and other assets 262 49 58"
]


def chunk(cid: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=cid,
        cik="0000066740",
        ticker="MMM",
        form="10-K",
        fiscal_year=2018,
        period="FY2018",
        section="Item 8",
        is_table=True,
        unit_scale=1e6,
        text=text,
        source_accession="x",
    )


MATCH = chunk(
    "c-match",
    "| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) | (1,420) |\n"
    "| Proceeds from sale of PP&E and other assets | 262 | 49 | 58 |",
)
OTHER_YEAR = chunk(
    "c-2017",
    "| Purchases of property, plant and equipment (PP&E) | (1,373) | (1,420) | (1,461) |\n"
    "| Proceeds from sale of PP&E and other assets | 49 | 58 | 24 |",
)
UNRELATED = chunk("c-risk", "Our business is subject to risks from global economic conditions.")


def draft(*chunks: Chunk) -> Draft:
    return Draft(
        question_id="q",
        retrieval_arm="rag",
        answer_text="",
        claims=[],
        evidence={c.chunk_id: c for c in chunks},
        trace_id="t",
        latency_s=0,
        tokens_in=0,
        tokens_out=0,
    )


def test_table_markdown_matches_pdf_text():
    assert overlap(MATCH.text, GOLD[0], N) >= T  # pipes and spacing don't matter


def test_other_years_table_and_unrelated_text_dont_match():
    assert overlap(OTHER_YEAR.text, GOLD[0], N) < T
    assert overlap(UNRELATED.text, GOLD[0], N) == 0


def test_diagnose_finds_the_best_chunk():
    d = diagnose(draft(UNRELATED, OTHER_YEAR, MATCH), GOLD, N, T)
    assert d.gold_evidence_retrieved and d.best_chunk_id == "c-match"
    missed = diagnose(draft(UNRELATED, OTHER_YEAR), GOLD, N, T)
    assert not missed.gold_evidence_retrieved


def test_no_evidence_means_not_retrieved():
    d = diagnose(draft(), GOLD, N, T)
    assert (d.gold_evidence_retrieved, d.best_chunk_id, d.best_overlap) == (False, None, 0.0)


def test_hit_at_k_and_curve():
    ranked = [UNRELATED, OTHER_YEAR, MATCH]
    hits = hit_at_k(ranked, GOLD, [1, 2, 3, 5], N, T)
    assert hits == {1: False, 2: False, 3: True, 5: True}
    curve = hit_curve([hits, hit_at_k([MATCH], GOLD, [1, 2, 3, 5], N, T)])
    assert curve == {1: (1, 2), 2: (1, 2), 3: (2, 2), 5: (2, 2)}


def test_each_evidence_page_is_compared_on_its_own():
    income = "Revenue Regulated 3,538 2,868 Non-Regulated 9,079 8,273 Total revenue 12,617 11,141"
    both_pages = [GOLD[0], income]
    d = diagnose(draft(MATCH), both_pages, N, T)  # the chunk holds only the first page
    assert d.gold_evidence_retrieved and (d.items_found, d.items) == (1, 2)
