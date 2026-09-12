"""Test individual candidate evaluation end-to-end."""
import logging
logging.basicConfig(level=logging.INFO)

from app.db import SessionLocal
from app import crud
from app.models import Evaluation

candidate_id = "4c2ae691-f5c3-4d56-97f7-1e936f13dfd2"
job_id = "fea8f63f-6735-457b-ab9e-8cb4f3bfba57"

db = SessionLocal()

candidate = crud.get_candidate(db, candidate_id)
job = crud.get_job(db, job_id)
cand_name = candidate.name if candidate else "NOT FOUND"
job_title = job.title if job else "NOT FOUND"
print("Candidate:", cand_name)
print("Job:", job_title)

from app.evaluation import evaluate_candidate as llm_evaluate, retrieve_candidate

question = job.description or job.title

print("\n--- STEP 1: Retrieve from KB ---")
results = retrieve_candidate(candidate_id=candidate_id, question=question)
if isinstance(results, dict):
    retrieval_count = len(results.get("retrievalResults", []))
else:
    retrieval_count = len(results) if isinstance(results, list) else 0
print("Result type:", type(results).__name__)
print("Retrieval count:", retrieval_count)

if retrieval_count == 0:
    print("ERROR: No retrieval results.")
else:
    print("\n--- STEP 2: LLM Evaluate ---")
    llm_result = llm_evaluate(candidate_id=candidate_id, job_description=question, results=results)
    print("Status:", llm_result.get("status"))
    print("Score:", llm_result.get("match_score"))
    print("Recommendation:", llm_result.get("recommendation"))
    summary = llm_result.get("summary", "")
    print("Summary length:", len(summary))
    print("Summary:", summary[:300])
    print("Strengths:", llm_result.get("strengths", [])[:3])
    print("Gaps:", llm_result.get("gaps", [])[:3])

    if llm_result.get("error_message"):
        print("Error:", llm_result["error_message"])

    # Persist
    if llm_result.get("status") == "FAILED":
        ev = crud.create_evaluation(
            db, candidate_id=candidate_id, job_id=job_id,
            match_score=0.0, recommendation="EVALUATION_FAILED",
            summary=llm_result.get("summary") or "Evaluacion fallida.",
            strengths=[], gaps=[], status="FAILED",
            error_message=llm_result.get("error_message") or "EVALUATION_FAILED",
        )
    else:
        ev = crud.create_evaluation(
            db, candidate_id=candidate_id, job_id=job_id,
            match_score=float(llm_result.get("match_score", 0)),
            recommendation=llm_result.get("recommendation", "LOW_MATCH"),
            summary=summary,
            strengths=llm_result.get("strengths", []),
            gaps=llm_result.get("gaps", []),
            status="COMPLETED",
            error_message=None,
        )
    print("\n--- PERSISTED ---")
    print("Eval ID:", ev.id)
    print("Status:", ev.status)
    print("Score:", ev.match_score)
    print("Valid:", crud.is_evaluation_complete(ev))

print("\n--- DB AFTER ---")
evals = db.query(Evaluation).filter(
    Evaluation.candidate_id == candidate_id,
    Evaluation.job_id == job_id
).order_by(Evaluation.created_at).all()
print("Total evaluations:", len(evals))
for e in evals:
    slen = len(e.summary.strip()) if e.summary else 0
    print("  status=%s score=%s rec=%s summary_len=%s created=%s" % (
        e.status, e.match_score, e.recommendation, slen, e.created_at))

db.close()
