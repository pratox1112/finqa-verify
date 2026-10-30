"""FinanceBench audit and scope report, on a synthetic fixture. No network."""

import csv
from pathlib import Path

from finqa.ingestion import financebench as fb

FIXTURE = Path(__file__).parent / "fixtures" / "financebench_sample.jsonl"


def rows() -> list[dict]:
    return fb.audit_rows(fb.load(FIXTURE))


def test_audit_has_one_row_per_question_with_all_columns() -> None:
    audit = rows()
    assert [r["financebench_id"] for r in audit] == [
        "fb_synth_001",
        "fb_synth_002",
        "fb_synth_003",
        "fb_synth_004",
    ]
    assert all(set(r) == set(fb.AUDIT_COLUMNS) for r in audit)


def test_scope_keeps_10k_and_10q_only() -> None:
    by_id = {r["financebench_id"]: r for r in rows()}
    assert by_id["fb_synth_001"]["in_scope"] and by_id["fb_synth_002"]["in_scope"]
    assert by_id["fb_synth_003"]["exclusion_reason"] == "document type 8-K"
    assert by_id["fb_synth_004"]["exclusion_reason"] == "document type earnings release"


def test_answer_has_number() -> None:
    by_id = {r["financebench_id"]: r for r in rows()}
    assert by_id["fb_synth_001"]["answer_has_number"]
    assert by_id["fb_synth_002"]["answer_has_number"]
    assert not by_id["fb_synth_003"]["answer_has_number"]


def test_audit_csv_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "audit.csv"
    fb.write_audit(rows(), path)
    with path.open(encoding="utf-8", newline="") as f:
        read = list(csv.DictReader(f))
    assert len(read) == 4 and read[0]["answer"] == "$1,200.00"
    assert list(read[0]) == fb.AUDIT_COLUMNS


def test_scope_report_counts() -> None:
    report = fb.scope_report(rows())
    assert "| FinanceBench public sample | 4 | 2 |" in report
    assert "| **In scope** | **2** | **1** |" in report
    assert "| Excluded | 2 | 1 |" in report
    assert "- OtherCorp" in report
    assert "contains a number: 2 of 2" in report
