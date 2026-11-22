"""Grounding and abstention, measured on a labelled synthetic set (tests/eval/grounding_cases.json).

The model is scripted, so this measures the deterministic checks in app/ai/rag.py only. It makes no network
calls and says nothing about how a real model behaves. Hard rules, checked on every case:
  - an answer never returns a citation to a source that was not retrieved;
  - text marked must_not_contain never appears in an answer.
Cases marked known_gap are reported but do not count toward accuracy: they describe limits of the checks.
"""

import json
import uuid
from pathlib import Path

import pytest

from app.ai.rag import Evidence, answer_question
from tests.fakes import FakeAI

CASES = json.loads((Path(__file__).parent / "eval" / "grounding_cases.json").read_text(encoding="utf-8"))["cases"]


def _doc(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"synthetic-doc:{name}")


def _evidence(items):
    return [
        Evidence(
            chunk_id=uuid.uuid4(),
            document_id=_doc(e["doc"]),
            title=e["title"],
            page_number=e["page"],
            content=e["content"],
            similarity=0.9,
        )
        for e in items
    ]


@pytest.mark.asyncio
async def test_grounding_hard_rules_hold_on_every_case():
    violations = []
    for case in CASES:
        evidence = _evidence(case["evidence"])
        allowed = {(str(e.document_id), e.page_number) for e in evidence}
        answer = await answer_question(case["question"], evidence, FakeAI(reply=case.get("reply", "")))
        returned = {(str(c.document_id), c.page) for c in answer.citations}
        if not returned <= allowed:
            violations.append((case["id"], "fabricated citation", sorted(returned - allowed)))
        for text in case.get("must_not_contain", []):
            if text in answer.text:
                violations.append((case["id"], "forbidden text shown", text))
    assert violations == []


@pytest.mark.asyncio
async def test_grounding_labelled_accuracy_is_reported():
    rows = []
    for case in CASES:
        evidence = _evidence(case["evidence"])
        answer = await answer_question(case["question"], evidence, FakeAI(reply=case.get("reply", "")))
        expected_answer = case["expected"] == "answer"
        outcome_ok = answer.abstained != expected_answer
        expected_cites = {(str(_doc(d)), p) for d, p in case.get("expected_citations", [])}
        returned = {(str(c.document_id), c.page) for c in answer.citations}
        cites_ok = (returned == expected_cites) if expected_answer else (not returned)
        rows.append({
            "id": case["id"],
            "known_gap": bool(case.get("known_gap")),
            "outcome_ok": outcome_ok,
            "citations_ok": outcome_ok and cites_ok,
        })

    labelled = [r for r in rows if not r["known_gap"]]
    gaps = [r for r in rows if r["known_gap"]]
    outcome_acc = sum(r["outcome_ok"] for r in labelled) / len(labelled)
    cite_acc = sum(r["citations_ok"] for r in labelled if r["outcome_ok"]) / max(
        1, sum(r["outcome_ok"] for r in labelled)
    )
    report = {
        "cases": len(CASES),
        "labelled": len(labelled),
        "known_gaps": len(gaps),
        "outcome_accuracy": round(outcome_acc, 3),
        "citation_accuracy_on_correct_outcomes": round(cite_acc, 3),
        "failed_labelled": [r["id"] for r in labelled if not r["outcome_ok"] or not r["citations_ok"]],
        "known_gap_results": {r["id"]: ("as labelled" if r["outcome_ok"] else "differs") for r in gaps},
    }
    print("\nGROUNDING EVAL " + json.dumps(report, sort_keys=True))
    # The threshold is the measured value on this set; it guards against regressions, not against the real world.
    assert outcome_acc >= 0.9
    assert cite_acc == 1.0
