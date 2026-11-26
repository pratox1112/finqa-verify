"""Claim annotation sheets (P5.2) on synthetic runs. No network."""

import csv
import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

from finqa.eval import annotation, stats
from finqa.eval.runner import RunRefused
from finqa.eval.scoring import Gold
from finqa.generators.base import Question
from finqa.schemas import Annotation, Chunk, Claim, Draft, ErrorType, VerifiedResult

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = {
    "q1": Question(
        "q1",
        "Northwind Industries",
        "What was FY2022 net sales growth?",
        "NW_2022_10K",
        "10k",
        2022,
        "calculation",
    ),
    "q2": Question(
        "q2", "Contoso", "What were FY2022 net sales?", "CT_2022_10K", "10k", 2022, "single_fact"
    ),
    "q3": Question(
        "q3", "Contoso", "Why did margins fall?", "CT_2022_10K", "10k", 2022, "qualitative"
    ),
}
GOLD = {
    "q1": Gold("q1", "9.4%", "number", 9.4, "%"),
    "q2": Gold("q2", "$9,870 million", "number", 9_870_000_000.0, "USD"),
    "q3": Gold("q3", "Higher input costs.", "text", None, ""),
}
CHUNK = Chunk(
    chunk_id="k1",
    cik="0000000001",
    ticker="NW",
    form="10-K",
    fiscal_year=2022,
    period="FY2022",
    section="Item 8",
    is_table=True,
    unit_scale=1e6,
    text="Net sales | 12,450 | 11,380",
    source_accession="0000000001-23-000001",
)
REV22 = Claim(
    claim_id="c1",
    metric="net sales",
    value=12_450_000_000,
    unit="USD",
    period="FY2022",
    chunk_ids=["k1"],
)
REV21 = Claim(
    claim_id="c2",
    metric="net sales",
    value=11_380_000_000,
    unit="USD",
    period="FY2021",
    chunk_ids=["k1"],
)
GROWTH = Claim(
    claim_id="c3",
    metric="net sales growth",
    value=9.4,
    unit="%",
    period="FY2022",
    chunk_ids=[],
    derived_from=["c1", "c2"],
    expression="(c1 - c2) / c2 * 100",
)
CT_SALES = Claim(
    claim_id="c1", metric="net sales", value=9_870, unit="USD", period="FY2022", chunk_ids=["k9"]
)


def draft(qid: str, claims: list[Claim], answer: str | None, error: str | None = None) -> Draft:
    return Draft(
        question_id=qid,
        retrieval_arm="agent",
        answer_text=f"answer to {qid}",
        claims=claims,
        answer_claim_id=answer,
        evidence={"k1": CHUNK},
        trace_id="t",
        latency_s=0,
        tokens_in=0,
        tokens_out=0,
        error=error,
    )


def result(d: Draft, arm: str, after: list[Claim] | None = None) -> VerifiedResult:
    return VerifiedResult(
        question_id=d.question_id,
        retrieval_arm=d.retrieval_arm,
        verification_arm=arm,
        claims_before=d.claims,
        claims_after=d.claims if after is None else after,
        verdicts=[],
        revisions_used=0,
        flagged_claim_ids=[],
        latency_s=0,
        tokens_in=0,
        tokens_out=0,
    )


def write_run(
    runs_dir: Path, run_id: str, drafts: list[Draft], after: dict[str, dict[str, list[Claim]]]
) -> None:
    """after[arm][question_id] = that verifier's claims (default: the draft's)."""
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run_meta.json").write_text(json.dumps({"split": "dev", "config_name": "x"}))
    (run_dir / "drafts.jsonl").write_text("".join(d.model_dump_json() + "\n" for d in drafts))
    for arm in annotation.ARMS:
        lines = [result(d, arm, after.get(arm, {}).get(d.question_id)) for d in drafts]
        (run_dir / f"verified_{arm}.jsonl").write_text(
            "".join(r.model_dump_json() + "\n" for r in lines)
        )


@pytest.fixture
def runs(tmp_path: Path) -> Path:
    runs_dir = tmp_path / "runs"
    fixed = REV21.model_copy(update={"value": 11_380_000_000.0, "period": "FY2021"})
    v2_ct = CT_SALES.model_copy(update={"value": 9_870_000_000.0})
    r1 = [
        draft("q1", [REV22, REV21, GROWTH], "c3"),
        draft("q2", [CT_SALES], "c1"),
        draft("q3", [], None),  # qualitative, no claims
    ]
    # V1 changes nothing; V2 fixes the Contoso scale error
    write_run(runs_dir, "r1run", r1, {"grounded": {"q2": [v2_ct]}})
    # R0: the same claims for q1 (a separate draft set, so separate rows), a failed q2
    r0 = [draft("q1", [REV22, REV21, GROWTH], "c3"), draft("q2", [], None, error="boom")]
    write_run(runs_dir, "r0run", r0, {"self_check": {"q1": [REV22, fixed, GROWTH]}})
    return runs_dir


def rows(runs_dir: Path) -> list[annotation.Row]:
    return annotation.collect_rows(runs_dir, ["r1run", "r0run"], QUESTIONS, GOLD, 0.01)


def by_key(rs: list[annotation.Row]) -> dict[tuple[str, str, str, str], annotation.Row]:
    return {(r.run_id, r.question_id, r.claim_id, r.sheet["value"]): r for r in rs}


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_claims_deduplicated_within_a_draft_run_only(runs: Path) -> None:
    rs = by_key(rows(runs))
    # r1: q1's three claims shared by all cells; q2 has the draft claim and V2's fixed one
    assert rs[("r1run", "q1", "c3", "9.4")].arms == ["none", "self_check", "grounded"]
    assert rs[("r1run", "q2", "c1", "9,870")].arms == ["none", "self_check"]
    assert rs[("r1run", "q2", "c1", "9,870,000,000")].arms == ["grounded"]
    # r0: identical q1 claims are separate rows from r1's; failed drafts give no rows
    assert rs[("r0run", "q1", "c1", "12,450,000,000")].arms == list(annotation.ARMS)
    assert not any(k[:2] == ("r0run", "q2") for k in rs)
    assert len(rs) == 3 + 2 + 3


def test_a_claim_is_a_new_row_when_one_of_its_inputs_changed() -> None:
    # V1's value-equal "fixed" c2 is identical, so r0's c3 stays one row; a real change splits it
    changed = REV21.model_copy(update={"value": 11_000_000_000.0})
    a = annotation.signature(GROWTH, [REV22, REV21, GROWTH])
    b = annotation.signature(GROWTH, [REV22, changed, GROWTH])
    assert a != b
    assert annotation.signature(REV22, [REV22, REV21, GROWTH]) == annotation.signature(
        REV22, [REV22, changed, GROWTH]
    )


def test_sheet_fields(runs: Path) -> None:
    rs = by_key(rows(runs))
    growth = rs[("r1run", "q1", "c3", "9.4")].sheet
    assert growth["company"] == "Northwind Industries"
    assert growth["filing"] == "NW_2022_10K"
    assert growth["gold_answer"] == "9.4%"
    assert growth["answer_claim"] == "yes"
    assert growth["expression"] == "(c1 - c2) / c2 * 100"
    assert growth["inputs"].splitlines() == [
        "c1: net sales = 12,450,000,000 USD, FY2022",
        "c2: net sales = 11,380,000,000 USD, FY2021",
    ]
    assert growth["cited_text"] == "(cites nothing)"
    assert growth["pre_label"] == "matches gold"
    sales = rs[("r1run", "q1", "c1", "12,450,000,000")].sheet
    assert sales["answer_claim"] == "no"
    assert sales["pre_label"] == ""
    assert sales["cited_text"] == (
        "[k1] NW | 10-K | FY2022 | Item 8 | table in units of 1,000,000\n"
        "Net sales | 12,450 | 11,380"
    )
    contoso = rs[("r1run", "q2", "c1", "9,870")].sheet
    assert contoso["pre_label"] == "does not match gold"
    assert contoso["cited_text"] == "[k9] (not in the retrieved evidence)"
    assert rs[("r1run", "q2", "c1", "9,870,000,000")].sheet["pre_label"] == "matches gold"


def test_sheets_are_blind_shuffled_and_two_per_claim(runs: Path, tmp_path: Path) -> None:
    rs = rows(runs)
    out = tmp_path / "labels" / "main"
    names = ["ann", "ben", "cam", "dee", "eli"]
    counts = annotation.write_claim_sheets(rs, names, out, seed=1)
    assert sum(counts.values()) == 2 * len(rs)
    key = read(out / annotation.KEY_FILE)
    assert len(key) == len(rs)
    assert all(len(k["annotators"].split(";")) == 2 for k in key)
    sheet = read(out / "sheet_ann.csv")
    assert list(sheet[0]) == annotation.SHEET_COLUMNS
    for forbidden in ("run_id", "cells", "verification_arm", "question_id", "claim_id"):
        assert forbidden not in annotation.SHEET_COLUMNS
    text = (out / "sheet_ann.csv").read_text(encoding="utf-8-sig")
    assert "r1run" not in text and "grounded" not in text and "self_check" not in text
    # same seed, same order; another seed, another order
    again = tmp_path / "labels" / "again"
    annotation.write_claim_sheets(rs, names, again, seed=1)
    assert read(again / annotation.KEY_FILE) == key
    other = tmp_path / "labels" / "other"
    annotation.write_claim_sheets(rs, names, other, seed=2)
    assert [k["claim_id"] + k["question_id"] for k in read(other / annotation.KEY_FILE)] != [
        k["claim_id"] + k["question_id"] for k in key
    ]
    with pytest.raises(RunRefused, match="not empty"):
        annotation.write_claim_sheets(rs, names, out, seed=1)


def test_rotating_pairs_balance_pairs_and_people() -> None:
    names = ["a", "b", "c", "d", "e"]
    who = annotation.rotating_pairs(100, names)
    pairs = Counter(tuple(w) for w in who)
    assert len(pairs) == 10 and set(pairs.values()) == {10}
    people = Counter(n for w in who for n in w)
    assert set(people.values()) == {40}
    with pytest.raises(ValueError):
        annotation.rotating_pairs(3, ["a"])
    with pytest.raises(ValueError):
        annotation.rotating_pairs(3, ["a", "a"])


def test_pilot_sample_for_everyone(runs: Path, tmp_path: Path) -> None:
    rs = rows(runs)
    out = tmp_path / "labels" / "pilot"
    counts = annotation.write_claim_sheets(
        rs, ["a", "b", "c"], out, seed=3, everyone=True, sample=4
    )
    assert counts == {"a": 4, "b": 4, "c": 4}
    with pytest.raises(ValueError, match="sample"):
        annotation.write_claim_sheets(rs, ["a"], tmp_path / "x", seed=3, everyone=True, sample=99)


def test_missing_verifier_file_is_refused(runs: Path) -> None:
    (runs / "r0run" / "verified_grounded.jsonl").unlink()
    with pytest.raises(RunRefused, match="verified_grounded"):
        rows(runs)
    only = annotation.collect_rows(runs, ["r0run"], QUESTIONS, GOLD, 0.01, arms=["none"])
    assert {r.arms[0] for r in only} == {"none"}


def fill(path: Path, values: dict[str, tuple[str, str, str]]) -> None:
    rows_ = read(path)
    for r in rows_:
        if r["row_id"] in values:
            r["correct"], r["error_type"], r["note"] = values[r["row_id"]]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=annotation.SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows_)


def test_parse_label() -> None:
    row = {"row_id": "c00001", "correct": " Yes ", "error_type": "", "note": "unsupported"}
    assert annotation.parse_label(row, "a") == annotation.Label(
        "c00001", "a", True, None, "unsupported"
    )
    row = {"row_id": "c00001", "correct": "no", "error_type": "Wrong_Period", "note": ""}
    assert annotation.parse_label(row, "a").error_type is ErrorType.WRONG_PERIOD
    assert annotation.parse_label({"row_id": "c1", "correct": "", "error_type": ""}, "a") is None
    for bad in (
        {"row_id": "c1", "correct": "yes", "error_type": "other"},
        {"row_id": "c1", "correct": "no", "error_type": ""},
        {"row_id": "c1", "correct": "no", "error_type": "typo"},
        {"row_id": "c1", "correct": "maybe", "error_type": ""},
        {"row_id": "c1", "correct": "", "error_type": "other"},
    ):
        with pytest.raises(ValueError):
            annotation.parse_label(bad, "a")


def test_labels_become_one_annotation_per_cell(runs: Path, tmp_path: Path) -> None:
    rs = rows(runs)
    out = tmp_path / "labels" / "main"
    annotation.write_claim_sheets(rs, ["ann", "ben"], out, seed=1)
    key = read(out / annotation.KEY_FILE)
    first = key[0]
    fill(out / "sheet_ann.csv", {first["row_id"]: ("no", "wrong_period", "from-input")})
    fill(out / "sheet_ben.csv", {k["row_id"]: ("yes", "", "") for k in key})
    path, n, blank, problems = annotation.collect_claim_labels(out)
    assert problems == []
    assert (n, blank) == (1 + len(key), len(key) - 1)
    anns = [Annotation.model_validate_json(x) for x in path.read_text().splitlines()]
    cells = sum(len(k["cells"].split(";")) for k in key)
    assert len(anns) == cells + len(first["cells"].split(";"))
    mine = [a for a in anns if a.annotator == "ann"]
    assert {a.run_id for a in mine} == {
        annotation.cell_run_id(first["run_id"], arm) for arm in first["cells"].split(";")
    }
    assert all(a.error_type is ErrorType.WRONG_PERIOD and a.note == "from-input" for a in mine)
    assert all(a.claim_id == first["claim_id"] for a in mine)


def test_invalid_labels_write_nothing(runs: Path, tmp_path: Path) -> None:
    out = tmp_path / "labels" / "main"
    annotation.write_claim_sheets(rows(runs), ["ann", "ben"], out, seed=1)
    row = read(out / "sheet_ann.csv")[0]["row_id"]
    fill(out / "sheet_ann.csv", {row: ("no", "", "")})
    path, _, _, problems = annotation.collect_claim_labels(out)
    assert len(problems) == 1 and "sheet_ann.csv" in problems[0] and row in problems[0]
    assert not path.exists()


def test_format_value() -> None:
    assert annotation.format_value(394_300_000_000) == "394,300,000,000"
    assert annotation.format_value(12.5) == "12.5"
    assert annotation.format_value(-1_234) == "-1,234"
    assert annotation.format_value(0.125) == "0.125"


def load_script():
    spec = importlib.util.spec_from_file_location("labels_script", ROOT / "scripts/labels.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_claim_sheets_and_labels(runs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = load_script()
    monkeypatch.setattr(script, "load_questions", lambda split: list(QUESTIONS.values()))
    monkeypatch.setattr(script, "load_gold", lambda: GOLD)
    argv = [
        "claim-sheets",
        "--name",
        "t",
        "--runs",
        "r1run",
        "r0run",
        "--annotators",
        "a",
        "b",
        "--split",
        "dev",
    ]
    assert script.main(argv, runs_dir=runs) == 0
    out = runs / "labels" / "t"
    assert (out / "sheet_a.csv").exists() and (out / annotation.KEY_FILE).exists()
    assert script.main(["claim-labels", "--name", "t"], runs_dir=runs) == 0
    row = read(out / "sheet_a.csv")[0]["row_id"]
    fill(out / "sheet_a.csv", {row: ("perhaps", "", "")})
    assert script.main(["claim-labels", "--name", "t"], runs_dir=runs) == 2


# --- Agreement (P5.5) and final labels --------------------------------------------------------

WP, WS = ErrorType.WRONG_PERIOD, ErrorType.WRONG_UNIT


def lab(row: str, who: str, error: ErrorType | None = None, note: str = "") -> annotation.Label:
    """A synthetic label: correct when error is None."""
    return annotation.Label(row, who, error is None, error, note)


def key_rows(rows_: dict[str, str]) -> list[dict[str, str]]:
    """row_id -> "a;b" annotators, each row in two cells of run "r"."""
    return [
        {
            "row_id": r,
            "run_id": "r",
            "question_id": "q" + r,
            "claim_id": "c1",
            "cells": "none;grounded",
            "annotators": who,
        }
        for r, who in rows_.items()
    ]


def test_cohen_kappa_on_categories() -> None:
    # observed 3/4; a: x2 y1 z1, b: x1 y2 z1 -> chance (2*1 + 1*2 + 1*1)/16 = 5/16
    # kappa = (12/16 - 5/16) / (11/16) = 7/11
    assert stats.cohen_kappa(list("xxyz"), list("xyyz")) == pytest.approx(7 / 11)
    assert stats.cohen_kappa(["x", "x"], ["x", "x"]) is None
    assert stats.cohen_kappa([True, False], [True, False]) == 1.0


def two_annotator_rows() -> tuple[list[dict[str, str]], dict[str, list[annotation.Label]]]:
    key = key_rows({"r1": "ann;ben", "r2": "ann;ben", "r3": "ben;ann", "r4": "ann;ben"})
    labels = [
        lab("r1", "ann"),
        lab("r1", "ben"),
        lab("r2", "ann", WP),
        lab("r2", "ben", WP),
        lab("r3", "ann", WP),
        lab("r3", "ben", WS),
        lab("r4", "ann"),
        lab("r4", "ben", WS),
    ]
    rows_, incomplete = annotation.complete_rows(key, labels)
    assert incomplete == []
    return key, rows_


def test_kappa_for_two_annotators() -> None:
    _, rows_ = two_annotator_rows()
    pairs = annotation.pair_comparisons(rows_)
    assert list(pairs) == [("ann", "ben")]  # r3's "ben;ann" is ordered by name too
    cs = pairs[("ann", "ben")]
    # correct: ann T F F T, ben T F F F -> observed 3/4; chance .5*.25 + .5*.75 = .5
    # kappa = (.75 - .5) / .5 = .5
    assert annotation.on_correct(cs) == annotation.Agreement(4, 3, pytest.approx(0.5))
    # (a) combined: ann c wp wp c, ben c wp ws ws -> observed 2/4
    # chance: c 2*1 + wp 2*1 = 4/16 -> kappa (.5 - .25) / .75 = 1/3
    assert annotation.on_label(cs) == annotation.Agreement(4, 2, pytest.approx(1 / 3))
    # (b) both incorrect (r2, r3): ann wp wp, ben wp ws -> observed 1/2, chance 2*1/4 = .5
    # kappa = 0
    assert annotation.on_error_type(cs) == annotation.Agreement(2, 1, pytest.approx(0.0))
    assert annotation.disagreeing(rows_) == ["r3", "r4"]


def test_report_for_two_annotators() -> None:
    key, rows_ = two_annotator_rows()
    md = annotation.agreement_markdown(key, rows_, [], {}, None, None)
    assert "4 comparisons on 4 rows; agreement 3/4, 75%; Cohen's kappa 0.50" in md
    assert "Error type (a), combined label" in md
    assert "4 comparisons; agreement 2/4, 50%; Cohen's kappa 0.33" in md
    assert "Error type (b), among incorrect" in md
    assert "2 comparisons; agreement 1/2, 50%; Cohen's kappa 0.00" in md
    assert "| ann–ben | 4 | 3/4, 75% | 0.50 | 2/4, 50% | 0.33 | 1/2, 50% | 0.00 |" in md
    assert "No `final_labels.jsonl` written" in md


def test_pooled_and_per_pair_for_five_annotators() -> None:
    names = ["a", "b", "c", "d", "e"]
    key = key_rows({"r1": ";".join(names), "r2": ";".join(names)})
    labels = [lab("r1", n) for n in names]
    labels += [lab("r2", n) for n in "abc"] + [lab("r2", n, WS) for n in "de"]
    rows_, _ = annotation.complete_rows(key, labels)
    pairs = annotation.pair_comparisons(rows_)
    assert len(pairs) == 10 and all(len(cs) == 2 for cs in pairs.values())
    pooled = [c for cs in pairs.values() for c in cs]
    # 20 comparisons; r2's 6 pairs across {a,b,c} x {d,e} disagree -> observed 14/20 = .7
    # first rater (by name) says yes 19 times (only (d,e) on r2 is no); second 13 times
    # chance (19*13 + 1*7) / 400 = .635 -> kappa (.7 - .635) / .365 = 13/73
    assert annotation.on_correct(pooled) == annotation.Agreement(20, 14, pytest.approx(13 / 73))
    md = annotation.agreement_markdown(key, rows_, [], {}, None, None)
    table = [line for line in md.splitlines() if line.startswith("| ") and "–" in line]
    assert len(table) == 10
    assert "20 comparisons on 2 rows; agreement 14/20, 70%; Cohen's kappa 0.18" in md
    # a-b agree on everything, all yes: kappa undefined
    assert "| a–b | 2 | 2/2, 100% | n/a |" in md
    # a-d: a T T, d T F -> observed .5, chance 1*.5 + 0*.5 = .5 -> kappa 0
    assert "| a–d | 2 | 1/2, 50% | 0.00 |" in md
    # d-e: both T F (r2 wrong_unit_or_scale): chance .5*.5 + .5*.5 = .5 -> kappa 1 on correct
    # and on the combined label; (b) has one comparison with one label only -> n/a
    assert "| d–e | 2 | 2/2, 100% | 1.00 | 2/2, 100% | 1.00 | 1/1, 100% | n/a |" in md


def test_incomplete_rows_do_not_count() -> None:
    key = key_rows({"r1": "ann;ben", "r2": "ann;ben", "r3": "ann;ben"})
    labels = [lab("r1", "ann"), lab("r1", "ben"), lab("r2", "ann", WP)]
    rows_, incomplete = annotation.complete_rows(key, labels)
    assert list(rows_) == ["r1"] and incomplete == ["r2", "r3"]
    md = annotation.agreement_markdown(key, rows_, incomplete, {}, None, None)
    assert "Incomplete (left out): 2." in md and "r2, r3" in md
    assert "1 comparisons on 1 rows" in md


def test_final_labels_agreed_adjudicated_and_unresolved() -> None:
    key, rows_ = two_annotator_rows()
    rows_["r1"] = [lab("r1", "ann", note="unsupported"), lab("r1", "ben", note="irrelevant")]
    adjudicated = {"r3": annotation.Label("r3", "adjudicated", False, WP, "pair agreed")}
    anns, unresolved = annotation.final_labels(key, rows_, adjudicated)
    assert unresolved == ["r4"]
    # r1, r2 agreed and r3 adjudicated, each in two cells
    assert len(anns) == 6
    assert {a.run_id for a in anns} == {"r:none", "r:grounded"}
    by_q = {a.question_id: a for a in anns}
    assert by_q["qr1"].annotator == "ann+ben" and by_q["qr1"].note == "unsupported; irrelevant"
    assert by_q["qr1"].correct and by_q["qr1"].error_type is None
    assert by_q["qr2"].error_type is WP and not by_q["qr2"].correct
    assert by_q["qr3"].annotator == "adjudicated" and by_q["qr3"].note == "pair agreed"
    assert "qr4" not in by_q


def test_label_text() -> None:
    assert annotation.label_text(lab("c1", "ann", WP, "from-input")) == (
        "ann: no / wrong_period / from-input"
    )
    assert annotation.label_text(lab("c1", "ann")) == "ann: yes"
    assert annotation.label_text(lab("c1", "ann", note="unsupported")) == (
        "ann: yes / - / unsupported"
    )


def labelled_folder(runs_dir: Path) -> tuple[Path, list[dict[str, str]]]:
    """Two annotators: row 0 differs on error type, row 1 on correct, the last is half blank."""
    out = runs_dir / "labels" / "main"
    annotation.write_claim_sheets(rows(runs_dir), ["ann", "ben"], out, seed=1)
    key = read(out / annotation.KEY_FILE)
    ids = [k["row_id"] for k in key]
    ann = {r: ("yes", "", "") for r in ids}
    ben = {r: ("yes", "", "") for r in ids[:-1]}
    ann[ids[0]] = ("no", "wrong_period", "from-input")
    ben[ids[0]] = ("no", "arithmetic", "")
    ben[ids[1]] = ("no", "wrong_period", "")
    fill(out / "sheet_ann.csv", ann)
    fill(out / "sheet_ben.csv", ben)
    return out, key


def test_disagreement_sheet_has_no_cell_information(runs: Path) -> None:
    out, key = labelled_folder(runs)
    res = annotation.claim_agreement(out)
    assert res.problems == [] and res.final is None
    assert (res.counted, res.incomplete, res.disagree) == (len(key) - 1, 1, 2)
    sheet = read(res.disagreements)
    assert [r["row_id"] for r in sheet] == [key[0]["row_id"], key[1]["row_id"]]
    columns = list(sheet[0])
    for forbidden in ("run_id", "cells", "question_id", "claim_id", "annotators"):
        assert forbidden not in columns
    for needed in ("question", "gold_answer", "metric", "value", "unit", "period", "cited_text"):
        assert needed in columns
    assert columns[-3:] == annotation.FINAL_COLUMNS
    assert sheet[0]["label_1"] == "ann: no / wrong_period / from-input"
    assert sheet[0]["label_2"] == "ben: no / arithmetic"
    assert all(sheet[0][c] == "" for c in annotation.FINAL_COLUMNS)
    text = res.disagreements.read_text(encoding="utf-8-sig")
    assert "r1run" not in text and "r0run" not in text
    assert "grounded" not in text and "self_check" not in text
    assert res.report.exists() and not (out / annotation.FINAL_LABELS_FILE).exists()


def write_adjudication(out: Path, finals: dict[str, tuple[str, str, str]]) -> None:
    sheet = read(out / annotation.DISAGREEMENTS_FILE)
    for r in sheet:
        if r["row_id"] in finals:
            r["final_correct"], r["final_error_type"], r["final_note"] = finals[r["row_id"]]
    with (out / annotation.ADJUDICATION_FILE).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sheet[0]))
        w.writeheader()
        w.writerows(sheet)


def test_adjudication_gives_final_labels_per_cell(runs: Path) -> None:
    out, key = labelled_folder(runs)
    annotation.claim_agreement(out)
    write_adjudication(out, {key[0]["row_id"]: ("no", "arithmetic", "third person")})
    res = annotation.claim_agreement(out)
    assert res.problems == [] and res.final is not None and res.unresolved == 1
    anns = [Annotation.model_validate_json(x) for x in res.final.read_text().splitlines()]
    final_rows = [key[0], *key[2:-1]]  # adjudicated, agreed; row 1 unresolved, last incomplete
    assert len(anns) == sum(len(k["cells"].split(";")) for k in final_rows)
    adj = [a for a in anns if a.annotator == "adjudicated"]
    assert {a.run_id for a in adj} == {
        annotation.cell_run_id(key[0]["run_id"], arm) for arm in key[0]["cells"].split(";")
    }
    assert all(a.error_type is ErrorType.ARITHMETIC and a.note == "third person" for a in adj)
    assert {a.annotator for a in anns} == {"adjudicated", "ann+ben"}
    md = res.report.read_text(encoding="utf-8")
    assert "Adjudicated rows: 1." in md and key[1]["row_id"] in md.split("Still in")[1]


def test_invalid_adjudication_writes_nothing(runs: Path) -> None:
    out, key = labelled_folder(runs)
    annotation.claim_agreement(out)
    write_adjudication(out, {key[0]["row_id"]: ("no", "", ""), key[1]["row_id"]: ("maybe", "", "")})
    (out / annotation.AGREEMENT_FILE).unlink()
    (out / annotation.DISAGREEMENTS_FILE).unlink()
    adj = out / annotation.ADJUDICATION_FILE
    n_columns = len(read(adj)[0])
    with adj.open("a", encoding="utf-8", newline="") as f:
        f.write("c99999" + "," * (n_columns - 1) + "\r\n")
    res = annotation.claim_agreement(out)
    assert len(res.problems) == 3
    assert any(key[0]["row_id"] in p and "error_type" in p for p in res.problems)
    assert any(key[1]["row_id"] in p and "yes or no" in p for p in res.problems)
    assert any("c99999" in p and "not a row" in p for p in res.problems)
    assert not (out / annotation.AGREEMENT_FILE).exists()
    assert not (out / annotation.DISAGREEMENTS_FILE).exists()
    assert not (out / annotation.FINAL_LABELS_FILE).exists()
    # missing columns and duplicate rows are refused too
    adj.write_text("row_id,final_correct\nc00001,yes\n", encoding="utf-8")
    assert "needs the columns" in annotation.claim_agreement(out).problems[0]
    row = key[0]["row_id"]
    adj.write_text(
        f"row_id,final_correct,final_error_type,final_note\n{row},yes,,\n{row},yes,,\n",
        encoding="utf-8",
    )
    assert "twice" in annotation.claim_agreement(out).problems[0]


def test_invalid_sheet_refuses_agreement(runs: Path) -> None:
    out, key = labelled_folder(runs)
    fill(out / "sheet_ann.csv", {key[2]["row_id"]: ("yes", "other", "")})
    res = annotation.claim_agreement(out)
    assert len(res.problems) == 1 and "sheet_ann.csv" in res.problems[0]
    assert not (out / annotation.AGREEMENT_FILE).exists()


def test_no_disagreements_writes_final_labels(runs: Path) -> None:
    out = runs / "labels" / "main"
    annotation.write_claim_sheets(rows(runs), ["ann", "ben"], out, seed=1)
    key = read(out / annotation.KEY_FILE)
    for name in ("ann", "ben"):
        fill(out / f"sheet_{name}.csv", {k["row_id"]: ("yes", "", "") for k in key})
    res = annotation.claim_agreement(out)
    assert res.disagree == 0 and res.final is not None
    n = sum(len(k["cells"].split(";")) for k in key)
    assert len(res.final.read_text().splitlines()) == n
    assert read(res.disagreements) == []


def test_script_claim_agreement(runs: Path) -> None:
    script = load_script()
    out, key = labelled_folder(runs)
    assert script.main(["claim-agreement", "--name", "main"], runs_dir=runs) == 0
    assert (out / annotation.AGREEMENT_FILE).exists()
    assert not (out / annotation.FINAL_LABELS_FILE).exists()
    write_adjudication(out, {key[0]["row_id"]: ("perhaps", "", "")})
    assert script.main(["claim-agreement", "--name", "main"], runs_dir=runs) == 2
    write_adjudication(out, {key[0]["row_id"]: ("yes", "", "")})
    assert script.main(["claim-agreement", "--name", "main"], runs_dir=runs) == 0
    assert (out / annotation.FINAL_LABELS_FILE).exists()
