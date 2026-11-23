"""Labelling sheets, judge-human agreement and gold errata, on fake runs. No network."""

import csv
import importlib.util
import json
from pathlib import Path

import pytest
from test_report import FIXTURE, IDS

from finqa.config import CONFIGS_DIR, Config
from finqa.eval import labels, runner, stats, tables
from finqa.eval.questions import load_questions
from finqa.eval.scoring import Gold, Judgment, load_gold
from finqa.generators.base import Question, RunContext
from finqa.schemas import Annotation, Claim, Draft

ROOT = Path(__file__).resolve().parents[1]
CLEAN_MAIN = runner.GitState(commit="e" * 40, short="eeeeeee", branch="main", dirty=False)
# fb_synth_001 has a number gold; the other two are text golds
GOLD = {
    "fb_synth_001": Gold("fb_synth_001", "42", "number", 42.0, "USD"),
    "fb_synth_002": Gold("fb_synth_002", "Yes, 1.4.", "text_with_numbers", None, ""),
    "fb_synth_003": Gold("fb_synth_003", "Revenue grew.", "text", None, ""),
}


def answer_for(cfg: Config, qid: str) -> tuple[str, list[Claim], str | None]:
    """(answer text, claims, error): R0 refuses fb_synth_003; R1 answers everything."""
    if cfg.name == "r0_v0" and qid == "fb_synth_003":
        return "This cannot be determined from the excerpts.", [], None
    claim = Claim(claim_id="c1", metric="m", value=1.4, unit="ratio", period="FY2022", chunk_ids=[])
    return f"{cfg.name} answer to {qid}", [claim], None


def fake_generate(question: Question, cfg: Config, ctx: RunContext) -> Draft:
    text, claims, error = answer_for(cfg, question.question_id)
    return Draft(
        question_id=question.question_id,
        retrieval_arm=cfg.retrieval.arm,
        answer_text=text,
        claims=claims,
        answer_claim_id="c1" if claims else None,
        evidence={},
        trace_id=ctx.trace_id,
        latency_s=0.0,
        tokens_in=0,
        tokens_out=0,
        error=error,
    )


def judge_yes_for_r1(question: str, gold_answer: str, model_answer: str) -> Judgment:
    return Judgment(correct=model_answer.startswith("r1_v0"), reason="fake judge")


@pytest.fixture
def runs(tmp_path: Path):
    splits = tmp_path / "splits.json"
    types = dict(zip(IDS, ["single_fact", "calculation", "qualitative"], strict=True))
    splits.write_text(json.dumps({"dev": [], "test": IDS, "question_types": types}))
    runs_dir = tmp_path / "runs"
    questions = {q.question_id: q for q in load_questions("test", splits, FIXTURE)}
    run_ids = []
    for config in ("grid/r0_v0.yaml", "grid/r1_v0.yaml"):
        runner.draft_command(
            str(CONFIGS_DIR / config),
            split="test",
            runs_dir=runs_dir,
            splits_path=splits,
            financebench_path=FIXTURE,
            git=CLEAN_MAIN,
            generator=fake_generate,
        )
    for run_dir in sorted(runs_dir.iterdir()):
        drafts = runner.read_jsonl(run_dir / "drafts.jsonl", Draft)
        rows = tables.score_run(drafts, questions, GOLD, 0.01, judge_yes_for_r1)
        tables.write_rows(rows, run_dir / "scores.jsonl")
        run_ids.append(run_dir.name)
    return runs_dir, run_ids, questions


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def fill(path: Path, answers: dict[str, str], notes: dict[str, str] | None = None) -> None:
    rows = read(path)
    for r in rows:
        r["correct"] = answers.get(r["row_id"], r["correct"])
        r["note"] = (notes or {}).get(r["row_id"], r["note"])
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=labels.SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)


# --- Which answers are labelled -----------------------------------------------------------------


def test_only_judged_text_gold_answers_are_labelled(runs) -> None:
    runs_dir, run_ids, questions = runs
    items = labels.judged_items(runs_dir, run_ids, questions, GOLD)
    got = sorted((i.config_name, i.question_id) for i in items)
    # number gold (001) and R0's refusal on 003 are scored without the judge
    assert got == [("r0_v0", "fb_synth_002"), ("r1_v0", "fb_synth_002"), ("r1_v0", "fb_synth_003")]
    item = next(i for i in items if i.config_name == "r1_v0" and i.question_id == "fb_synth_003")
    assert item.model_answer == "r1_v0 answer to fb_synth_003"  # what the judge saw
    assert item.gold_answer == "Revenue grew." and item.claim_id == "c1"


def test_unknown_run_is_refused(runs) -> None:
    runs_dir, _, questions = runs
    with pytest.raises(runner.RunRefused, match="no run nope"):
        labels.judged_items(runs_dir, ["nope"], questions, GOLD)


# --- Sheets -------------------------------------------------------------------------------------


@pytest.mark.parametrize("n, people, double", [(10, 3, 4), (7, 2, 7), (5, 4, 0), (9, 3, 9)])
def test_assignment_is_even_and_pairs_are_distinct(n: int, people: int, double: int) -> None:
    names = [f"p{i}" for i in range(people)]
    who = labels.assign(n, names, double)
    assert [len(w) for w in who] == [2] * double + [1] * (n - double)
    assert all(len(set(w)) == len(w) for w in who)
    load = [sum(name in w for w in who) for name in names]
    assert max(load) - min(load) <= 2


def test_assignment_rejects_impossible_requests() -> None:
    with pytest.raises(ValueError):
        labels.assign(3, ["a"], 1)
    with pytest.raises(ValueError):
        labels.assign(3, ["a", "b"], 4)
    with pytest.raises(ValueError):
        labels.assign(3, [], 0)


def test_sheets_are_blind_shuffled_and_keyed(runs, tmp_path: Path) -> None:
    runs_dir, run_ids, questions = runs
    items = labels.judged_items(runs_dir, run_ids, questions, GOLD)
    out = tmp_path / "labels" / "j"
    counts = labels.write_judge_sheets(items, ["ann", "ben"], 1, out, seed=7)
    assert counts == {"ann": 2, "ben": 2}  # 3 rows, one of them double-coded
    key = read(out / labels.KEY_FILE)
    assert [k["row_id"] for k in key] == ["r0001", "r0002", "r0003"]
    assert key[0]["labellers"].count(";") == 1 and ";" not in key[1]["labellers"]
    for name in ("ann", "ben"):
        sheet = read(out / f"sheet_{name}.csv")
        assert list(sheet[0]) == labels.SHEET_COLUMNS
        text = (out / f"sheet_{name}.csv").read_text(encoding="utf-8")
        for secret in (*run_ids, "eeeeeee", "fake judge"):
            assert secret not in text  # no run, commit or judge verdict
        assert all(r["correct"] == "" for r in sheet)
    again = tmp_path / "labels" / "j2"
    labels.write_judge_sheets(items, ["ann", "ben"], 1, again, seed=7)
    assert read(again / labels.KEY_FILE) == key  # seeded
    with pytest.raises(runner.RunRefused, match="not empty"):
        labels.write_judge_sheets(items, ["ann", "ben"], 1, out, seed=7)


# --- Agreement ----------------------------------------------------------------------------------


def make_sheets(runs, tmp_path: Path) -> tuple[Path, dict[tuple[str, str], str]]:
    runs_dir, run_ids, questions = runs
    items = labels.judged_items(runs_dir, run_ids, questions, GOLD)
    out = runs_dir / "labels" / "j"
    labels.write_judge_sheets(items, ["ann", "ben"], 3, out, seed=1)  # all rows double
    key = read(out / labels.KEY_FILE)
    rows = {(k["config_name"], k["question_id"]): k["row_id"] for k in key}
    return out, rows


def test_agreement_report_and_annotations(runs, tmp_path: Path) -> None:
    runs_dir = runs[0]
    out, rows = make_sheets(runs, tmp_path)
    r0_002 = rows[("r0_v0", "fb_synth_002")]  # judge: incorrect
    r1_002 = rows[("r1_v0", "fb_synth_002")]  # judge: correct
    r1_003 = rows[("r1_v0", "fb_synth_003")]  # judge: correct
    # both labellers: r0_002 no (agrees), r1_002 yes (agrees), r1_003 no (disagrees with judge)
    fill(out / "sheet_ann.csv", {r0_002: "no", r1_002: "Yes", r1_003: "n"}, {r1_003: "hedges"})
    fill(out / "sheet_ben.csv", {r0_002: "N", r1_002: "y", r1_003: "no"})
    report, annotations = labels.judge_agreement(out, runs_dir)
    md = report.read_text(encoding="utf-8")
    assert "Rows labelled and resolved: 3. Still blank: 0. To adjudicate (two labellers " in md
    assert "| r0_v0 | 1 | 1/1, 100.0% [" in md
    assert "| r1_v0 | 2 | 1/2, 50.0% [" in md and "| 1 | 0 |" in md
    assert "| **all** | 3 | 2/3, 66.7% [" in md
    assert "on 3 double-coded rows: 3/3, 100.0%" in md
    assert f"| {r1_003} | r1_v0 | fb_synth_003 | correct | incorrect | fake judge | hedges |" in md
    notes = [Annotation.model_validate_json(line) for line in annotations.read_text().splitlines()]
    assert len(notes) == 3 and {a.annotator for a in notes} == {"ann+ben"}
    assert {(a.question_id, a.correct) for a in notes if a.run_id.endswith("r1_v0_eeeeeee")} == {
        ("fb_synth_002", True),
        ("fb_synth_003", False),
    }


def test_conflicts_wait_for_adjudication(runs, tmp_path: Path) -> None:
    runs_dir = runs[0]
    out, rows = make_sheets(runs, tmp_path)
    row = rows[("r1_v0", "fb_synth_003")]
    others = {r: "yes" for r in rows.values() if r != row}
    fill(out / "sheet_ann.csv", {**others, row: "yes"})
    fill(out / "sheet_ben.csv", {**others, row: "no"})
    md = labels.judge_agreement(out, runs_dir)[0].read_text(encoding="utf-8")
    assert "To adjudicate (two labellers disagree): 1" in md and f"): {row}" in md
    (out / "adjudication.csv").write_text(f"row_id,correct,note\n{row},no,third person\n")
    md = labels.judge_agreement(out, runs_dir)[0].read_text(encoding="utf-8")
    assert "To adjudicate (two labellers disagree): 0" in md
    assert "third person" in md  # the adjudicated row disagrees with the judge


def test_blank_rows_are_counted_not_guessed(runs, tmp_path: Path) -> None:
    out, rows = make_sheets(runs, tmp_path)
    fill(out / "sheet_ann.csv", {r: "yes" for r in rows.values()})
    md = labels.judge_agreement(out, runs[0])[0].read_text(encoding="utf-8")
    assert "Rows labelled and resolved: 0. Still blank: 3." in md


def test_bad_labels_and_missing_scores_are_refused(runs, tmp_path: Path) -> None:
    runs_dir = runs[0]
    out, rows = make_sheets(runs, tmp_path)
    fill(out / "sheet_ann.csv", {next(iter(rows.values())): "maybe"})
    with pytest.raises(runner.RunRefused, match="not a yes/no label"):
        labels.judge_agreement(out, runs_dir)
    fill(out / "sheet_ann.csv", {r: "yes" for r in rows.values()})
    for scores in runs_dir.glob("*/scores.jsonl"):
        scores.unlink()
    with pytest.raises(runner.RunRefused, match="run `finqa report` first"):
        labels.judge_agreement(out, runs_dir)


def test_cohen_kappa_known_values() -> None:
    assert stats.cohen_kappa([], []) is None
    assert stats.cohen_kappa([True, False, True, False], [True, False, True, False]) == 1.0
    assert stats.cohen_kappa([True, True], [True, True]) is None  # chance agreement is 1
    # 2x2 counts: both yes 20, a only 5, b only 10, both no 15 -> kappa 0.4
    a = [True] * 20 + [True] * 5 + [False] * 10 + [False] * 15
    b = [True] * 20 + [False] * 5 + [True] * 10 + [False] * 15
    assert stats.cohen_kappa(a, b) == pytest.approx(0.4)
    with pytest.raises(ValueError):
        stats.cohen_kappa([True], [])


# --- Gold errata --------------------------------------------------------------------------------


def test_errata_candidates_are_real_questions() -> None:
    gold = load_gold()
    assert set(labels.ERRATA_CANDIDATES) <= set(gold)


RECORDS = {
    qid: {
        "financebench_id": qid,
        "company": "ExampleCo",
        "question": f"question {qid}?",
        "answer": "$1.6Bn",
        "doc_name": "EXAMPLECO_2022_10K",
        "doc_link": "https://example.com/doc.pdf",
        "evidence": [{"evidence_text": "Total 57,517", "evidence_page_num": 60}],
        "justification": "a+b",
    }
    for qid in labels.ERRATA_CANDIDATES
}


def test_errata_sheets_show_the_source_not_any_answer(tmp_path: Path) -> None:
    paths = labels.write_errata_sheets(RECORDS, ["ann", "ben"], tmp_path / "e")
    assert [p.name for p in paths] == ["errata_ann.csv", "errata_ben.csv"]
    rows = read(paths[0])
    assert list(rows[0]) == labels.ERRATA_COLUMNS and len(rows) == len(labels.ERRATA_CANDIDATES)
    assert rows[0]["evidence_pages"] == "60" and rows[0]["financebench_evidence"] == "Total 57,517"
    text = paths[0].read_text(encoding="utf-8")
    for reason in labels.ERRATA_CANDIDATES.values():
        assert reason not in text  # why it was flagged is not shown
    with pytest.raises(ValueError):
        labels.write_errata_sheets(RECORDS, ["ann"], tmp_path / "e1")


def fill_errata(path: Path, verdicts: dict[str, tuple[str, str]]) -> None:
    rows = read(path)
    for r in rows:
        r["verdict"], r["correct_value"] = verdicts.get(r["financebench_id"], ("", ""))
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=labels.ERRATA_COLUMNS)
        w.writeheader()
        w.writerows(rows)


def test_errata_outcomes_follow_the_rule(tmp_path: Path) -> None:
    out = tmp_path / "e"
    a, b = labels.write_errata_sheets(RECORDS, ["ann", "ben"], out)
    ids = list(labels.ERRATA_CANDIDATES)
    fill_errata(
        a,
        {
            ids[0]: ("contradicts", "12.4"),
            ids[1]: ("contradicts", "389"),
            ids[2]: ("matches", ""),
            ids[3]: ("Matches", ""),
            ids[4]: ("unclear", ""),
        },
    )
    fill_errata(
        b,
        {
            ids[0]: ("contradicts", "12.4"),
            ids[1]: ("contradicts", "0.39"),
            ids[2]: ("matches", ""),
            ids[3]: ("contradicts", "4.6"),
            ids[4]: ("unclear", ""),
        },
    )
    md = labels.compare_errata(out).read_text(encoding="utf-8")
    assert (
        f"| {ids[0]} | contradicts (12.4) | contradicts (12.4) | **correct the gold to 12.4**" in md
    )
    assert f"| {ids[1]} |" in md and "both say contradicts, values differ" in md
    assert f"| {ids[2]} | matches | matches | gold stands |" in md
    assert f"| {ids[3]} | matches | contradicts (4.6) | third person decides |" in md
    assert f"| {ids[4]} | unclear | unclear | third person decides |" in md
    assert f"| {ids[5]} | — | — | not finished |" in md
    fill_errata(a, {ids[0]: ("wrong", "")})
    with pytest.raises(runner.RunRefused, match="verdict must be one of"):
        labels.compare_errata(out)


# --- Script -------------------------------------------------------------------------------------


def load_script():
    spec = importlib.util.spec_from_file_location("labels_script", ROOT / "scripts" / "labels.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_runs_agreement_and_reports_refusals(runs, tmp_path: Path, capsys) -> None:
    script = load_script()
    runs_dir = runs[0]
    out, rows = make_sheets(runs, tmp_path)
    for name in ("ann", "ben"):
        fill(out / f"sheet_{name}.csv", {r: "yes" for r in rows.values()})
    assert script.main(["judge-agreement", "--name", "j"], runs_dir=runs_dir) == 0
    assert (out / "agreement.md").exists() and (out / "annotations.jsonl").exists()
    assert script.main(["errata-compare", "--name", "missing"], runs_dir=runs_dir) == 2
    assert "refused: expected two errata sheets" in capsys.readouterr().err


def test_script_parser() -> None:
    parser = load_script().build_parser()
    args = parser.parse_args(
        [
            "judge-sheets",
            "--name",
            "t",
            "--runs",
            "a",
            "b",
            "--labellers",
            "x",
            "y",
            "--double",
            "5",
        ]
    )
    assert args.runs == ["a", "b"] and args.labellers == ["x", "y"] and args.double == 5
    assert args.split == "test"
