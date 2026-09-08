"""Evaluations repository."""

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models import Evaluation
from app.domains.evaluations.schemas import VALID_RECOMMENDATIONS, MIN_SUMMARY_LENGTH


def is_evaluation_complete(evaluation: Evaluation | None) -> bool:
    if evaluation is None:
        return False
    if evaluation.status != "COMPLETED":
        return False
    if evaluation.match_score is None:
        return False
    if not (0 <= evaluation.match_score <= 100):
        return False
    if not evaluation.recommendation:
        return False
    if evaluation.recommendation not in VALID_RECOMMENDATIONS:
        return False
    if evaluation.recommendation == "EVALUATION_FAILED":
        return False
    if not evaluation.summary:
        return False
    if len(evaluation.summary.strip()) < MIN_SUMMARY_LENGTH:
        return False
    if evaluation.strengths is None:
        return False
    if evaluation.gaps is None:
        return False
    return True


def needs_evaluation(evaluation: Evaluation | None, *, force: bool = False) -> bool:
    if force:
        return True
    if evaluation is None:
        return True
    if evaluation.status == "FAILED":
        return True
    if evaluation.recommendation == "EVALUATION_FAILED":
        return True
    if not is_evaluation_complete(evaluation):
        return True
    return False


def create_evaluation(
    db: Session,
    *,
    candidate_id: str,
    job_id: str,
    match_score: float,
    recommendation: str,
    summary: str,
    strengths: list[str],
    gaps: list[str],
    requirements: list[dict] | None = None,
    status: str = "COMPLETED",
    error_message: str | None = None,
) -> Evaluation:
    existing = get_evaluation_for_job_candidate(db, job_id, candidate_id)

    if existing:
        existing.status = status
        existing.match_score = match_score
        existing.recommendation = recommendation
        existing.summary = summary
        existing.strengths = strengths
        existing.gaps = gaps
        if requirements is not None:
            existing.requirements = requirements
        existing.error_message = error_message
        existing.created_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)
        return existing

    evaluation = Evaluation(
        candidate_id=candidate_id,
        job_id=job_id,
        status=status,
        match_score=match_score,
        recommendation=recommendation,
        summary=summary,
        strengths=strengths,
        gaps=gaps,
        requirements=requirements or [],
        error_message=error_message,
    )
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)
    return evaluation


def get_evaluations_for_candidate(db: Session, candidate_id: str) -> list[Evaluation]:
    return db.query(Evaluation).filter(Evaluation.candidate_id == candidate_id).order_by(Evaluation.created_at.desc()).all()


def get_evaluation_for_job_candidate(db: Session, job_id: str, candidate_id: str) -> Evaluation | None:
    return db.query(Evaluation).filter(Evaluation.job_id == job_id, Evaluation.candidate_id == candidate_id).order_by(Evaluation.created_at.desc()).first()