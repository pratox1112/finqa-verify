"""Dev check for the S0 and R0 generators (ROADMAP P3.0, P3.5) on the 20 pilot questions.

Until the Phase 2 runner exists, this drafts every question in data/pilot_questions.json
(reserved for the dev split, never test) and checks the acceptance criterion: a valid Draft
for every question. It writes runs/drafts_pilot/<run_id>/drafts.jsonl and prints each
answer beside FinanceBench's gold answer for a person to read. It does not score: scoring
is P2.3. Real Groq calls; responses are cached, so reruns are free.

    uv run python scripts/draft_pilot.py configs/baselines/s0_closed_book.yaml
    uv run python scripts/draft_pilot.py configs/grid/r0_v0.yaml
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import subprocess
import sys
from pathlib import Path

from finqa.config import load_config
from finqa.generators.closed_book import ClosedBookGenerator
from finqa.generators.rag import RagGenerator
from finqa.ingestion import financebench
from finqa.llm import LLM
from finqa.tools.resolver import CompanyResolver
from finqa.tools.search import FilingSearch

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "data" / "pilot_questions.json"


def _short_commit() -> str:
    out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return out.stdout.strip() or "nogit"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    logging.basicConfig(level=logging.WARNING)
    cfg = load_config(argv[0])
    llm = LLM(cfg)
    if cfg.retrieval.arm == "closed_book":
        generator: ClosedBookGenerator | RagGenerator = ClosedBookGenerator(cfg, llm)
    elif cfg.retrieval.arm == "rag":
        generator = RagGenerator(cfg, llm, CompanyResolver.from_csv(), FilingSearch.open(cfg))
    else:
        print(f"{cfg.retrieval.arm!r} is not built yet (P3.6)")
        return 2

    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    gold = financebench.by_id(financebench.load())
    run_id = f"{dt.date.today().isoformat()}_{cfg.name}_pilot_{_short_commit()}"
    out = ROOT / "runs" / "drafts_pilot" / run_id / "drafts.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    errors = 0
    with out.open("w", encoding="utf-8") as f:
        for n, q in enumerate(questions, 1):
            qid = q["financebench_id"]
            d = generator.generate(qid, q["company"], q["question"], run_id=run_id)
            f.write(d.model_dump_json() + "\n")
            errors += d.error is not None
            print(
                f"[{n}/{len(questions)}] {qid} {q['company']}: {len(d.claims)} claims, "
                f"{len(d.evidence)} chunks, {d.tokens_in}+{d.tokens_out} tokens"
            )
            print(f"    model: {d.error or d.answer_text}")
            print(f"    gold:  {gold[qid]['answer']}"[:400])
    llm.tracer.flush()
    print(f"\n{len(questions) - errors}/{len(questions)} drafts without error -> {out}")
    print(f"LLM usage: {llm.usage}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
