"""Ranking repository."""

from datetime import datetime, timezone
from typing import Any
from sqlalchemy.orm import Session, joinedload

from app.models import Job, Ranking, RankingItem, Evaluation
from app.domains.evaluations.repository import is_evaluation_complete


def get_ranking_metadata(db: Session, job_id: str) -> Ranking | None:
    return db.query(Ranking).filter(Ranking.job_id == job_id).order_by(Ranking.ranking_version.desc()).first()


def upsert_ranking_metadata(
    db: Session,
    job_id: str,
    version: int,
    mode: str = "full",
    scope: str = "assigned",
) -> Ranking:
    now = datetime.now(timezone.utc)
    existing = get_ranking_metadata(db, job_id)

    if existing:
        existing.generated_at = now
        existing.ranking_version = version
        existing.mode = mode
        existing.notes = f"scope:{scope}"
    else:
        existing = Ranking(job_id=job_id, ranking_version=version, generated_at=now, mode=mode, notes=f"scope:{scope}")
        db.add(existing)

    db.commit()
    db.refresh(existing)
    return existing


def insert_ranking_items(db: Session, *, ranking_id: str, items: list[dict[str, Any]]) -> int:
    db.query(RankingItem).filter(RankingItem.ranking_id == ranking_id).delete()
    db.flush()

    count = 0
    for item in items:
        db.add(RankingItem(ranking_id=ranking_id, candidate_id=item["candidate_id"], score=item["score"], position=item["position"]))
        count += 1
    db.commit()
    return count


def get_ranking_items(db: Session, ranking_id: str) -> list[RankingItem]:
    return db.query(RankingItem).filter(RankingItem.ranking_id == ranking_id).order_by(RankingItem.position).all()


def build_ranking_response(
    db: Session,
    job_id: str,
    *,
    page: int = 1,
    page_size: int = 10,
    min_score: float = 0,
    max_score: float = 100,
    recommendation: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    job = db.query(Job).filter(Job.id == job_id).first()
    meta = get_ranking_metadata(db, job_id)

    if not meta:
        requested_scope = scope or "assigned"
        return {
            "job_id": job_id,
            "job_title": job.title if job else "",
            "ranking_generated_at": None,
            "ranking_version": None,
            "ranking_scope": requested_scope,
            "scope_mismatch": False,
            "ranking_total": 0,
            "total": 0,
            "total_pages": 0,
            "page": page,
            "page_size": page_size,
            "pending_candidates": 0,
            "score_min": None,
            "score_max": None,
            "candidates": [],
        }

    ranking_scope = "assigned"
    if meta.notes and meta.notes.startswith("scope:"):
        candidate_scope = meta.notes.split(":", 1)[1].strip()
        if candidate_scope in {"assigned", "all"}:
            ranking_scope = candidate_scope

    if scope is not None and scope != ranking_scope:
        return {
            "job_id": job_id,
            "job_title": job.title if job else "",
            "ranking_generated_at": meta.generated_at.isoformat() if meta.generated_at else None,
            "ranking_version": meta.ranking_version,
            "ranking_scope": ranking_scope,
            "scope_mismatch": True,
            "ranking_total": 0,
            "total": 0,
            "total_pages": 0,
            "page": page,
            "page_size": page_size,
            "pending_candidates": 0,
            "score_min": None,
            "score_max": None,
            "candidates": [],
        }

    items = db.query(RankingItem).options(joinedload(RankingItem.candidate)).filter(RankingItem.ranking_id == meta.id).all()
    candidate_ids = [item.candidate_id for item in items]

    latest_evaluation_by_candidate = {}
    if candidate_ids:
        evaluations = db.query(Evaluation).filter(Evaluation.job_id == job_id, Evaluation.candidate_id.in_(candidate_ids)).order_by(Evaluation.created_at.desc()).all()
        for evaluation in evaluations:
            latest_evaluation_by_candidate.setdefault(evaluation.candidate_id, evaluation)

    candidates = []
    for item in items:
        evaluation = latest_evaluation_by_candidate.get(item.candidate_id)
        candidate_name = item.candidate.name if item.candidate else ""

        if is_evaluation_complete(evaluation):
            candidates.append({
                "position": 0,
                "candidate_id": item.candidate_id,
                "match_score": evaluation.match_score,
                "candidate_name": candidate_name,
                "recommendation": evaluation.recommendation,
                "status": "COMPLETED",
                "strengths": evaluation.strengths or [],
                "gaps": evaluation.gaps or [],
                "error_message": None,
            })
        elif evaluation and evaluation.status == "FAILED":
            candidates.append({
                "position": 0,
                "candidate_id": item.candidate_id,
                "match_score": None,
                "candidate_name": candidate_name,
                "recommendation": "EVALUATION_FAILED",
                "status": "FAILED",
                "strengths": [],
                "gaps": [],
                "error_message": _sanitize_error_message(evaluation.error_message) or "Evaluacion fallida",
            })
        else:
            candidates.append({
                "position": 0,
                "candidate_id": item.candidate_id,
                "match_score": None,
                "candidate_name": candidate_name,
                "recommendation": "PENDING",
                "status": "PENDING",
                "strengths": [],
                "gaps": [],
                "error_message": "Evaluacion pendiente",
            })

    status_order = {"COMPLETED": 0, "FAILED": 1, "PENDING": 2}

    def sort_key(candidate):
        score = candidate.get("match_score")
        numeric_score = float(score) if score is not None else -1.0
        return (
            status_order.get(candidate.get("status"), 99),
            -numeric_score,
            (candidate.get("candidate_name") or "").lower(),
            candidate.get("candidate_id") or "",
        )

    candidates.sort(key=sort_key)

    for position, candidate in enumerate(candidates, start=1):
        candidate["position"] = position

    ranking_total = len(candidates)
    filtered = candidates

    if recommendation:
        filtered = [c for c in filtered if c.get("recommendation") == recommendation]

    if min_score > 0 or max_score < 100:
        filtered = [c for c in filtered if c.get("status") == "COMPLETED" and c.get("match_score") is not None and min_score <= float(c["match_score"]) <= max_score]

    total = len(filtered)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    start = (page - 1) * page_size
    end = start + page_size
    page_candidates = filtered[start:end]

    completed_scores = [float(c["match_score"]) for c in filtered if c.get("status") == "COMPLETED" and c.get("match_score") is not None]
    pending_candidates = sum(1 for c in filtered if c.get("status") == "PENDING")

    return {
        "job_id": job_id,
        "job_title": job.title if job else "",
        "ranking_generated_at": meta.generated_at.isoformat() if meta.generated_at else None,
        "ranking_version": meta.ranking_version,
        "ranking_scope": ranking_scope,
        "scope_mismatch": False,
        "ranking_total": ranking_total,
        "total": total,
        "total_pages": total_pages,
        "page": page,
        "page_size": page_size,
        "pending_candidates": pending_candidates,
        "score_min": min(completed_scores) if completed_scores else None,
        "score_max": max(completed_scores) if completed_scores else None,
        "candidates": page_candidates,
    }


def _sanitize_error_message(error_message: str | None) -> str | None:
    if not error_message:
        return None
    aws_indicators = [
        "AccessDeniedException",
        "arn:aws",
        "assumed-role",
        "AmazonLightsailInstanceRole",
        "knowledge-base/",
        "bedrock:Retrieve",
        "bedrock:InvokeModel",
        "is not authorized to perform",
    ]
    for indicator in aws_indicators:
        if indicator in error_message:
            return "No fue posible completar la evaluación. Intente recalcular el ranking."
    return error_message