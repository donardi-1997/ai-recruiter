"""Jobs repository."""

from sqlalchemy.orm import Session

from app.models import Job


def get_job(db: Session, job_id: str, owner_sub: str | None = None) -> Job | None:
    query = db.query(Job).filter(Job.id == job_id)
    if owner_sub is not None:
        query = query.filter(Job.owner_sub == owner_sub)
    return query.first()


def list_jobs(db: Session, owner_sub: str | None = None) -> list[Job]:
    query = db.query(Job)
    if owner_sub is not None:
        query = query.filter(Job.owner_sub == owner_sub)
    return query.order_by(Job.created_at.desc()).all()


def create_job(
    db: Session,
    *,
    title: str,
    description: str | None = None,
    owner_sub: str | None = None,
) -> Job:
    job = Job(title=title, description=description, owner_sub=owner_sub)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job(db: Session, job: Job, *, title: str | None = None, description: str | None = None) -> Job:
    if title is not None:
        job.title = title
    if description is not None:
        job.description = description
    db.commit()
    db.refresh(job)
    return job


def delete_job(
    db: Session,
    job_id: str,
    *,
    owner_sub: str | None = None,
    delete_candidates: bool = False,
) -> tuple[bool, int]:
    from app.domains.candidates.repository import delete_candidate
    from app.models import Candidate, Evaluation, JobCandidate, Ranking, RankingItem

    job = get_job(db, job_id, owner_sub=owner_sub)
    if not job:
        return False, 0

    try:
        candidate_query = db.query(JobCandidate.candidate_id).filter(JobCandidate.job_id == job_id)
        if owner_sub is not None:
            candidate_query = candidate_query.join(
                Candidate, Candidate.id == JobCandidate.candidate_id
            ).filter(Candidate.owner_sub == owner_sub)

        candidate_ids = [cid for (cid,) in candidate_query.all()]
        deleted_candidate_count = 0

        if delete_candidates and candidate_ids:
            db.query(JobCandidate).filter(JobCandidate.candidate_id.in_(candidate_ids)).delete(synchronize_session=False)
            db.query(Evaluation).filter(Evaluation.candidate_id.in_(candidate_ids)).delete(synchronize_session=False)
            db.query(RankingItem).filter(RankingItem.candidate_id.in_(candidate_ids)).delete(synchronize_session=False)
            db.query(Candidate).filter(Candidate.id.in_(candidate_ids)).delete(synchronize_session=False)
            deleted_candidate_count = len(candidate_ids)

        ranking_ids = [rid for (rid,) in db.query(Ranking.id).filter(Ranking.job_id == job_id).all()]
        if ranking_ids:
            db.query(RankingItem).filter(RankingItem.ranking_id.in_(ranking_ids)).delete(synchronize_session=False)

        db.query(Ranking).filter(Ranking.job_id == job_id).delete(synchronize_session=False)
        db.query(Evaluation).filter(Evaluation.job_id == job_id).delete(synchronize_session=False)
        db.query(JobCandidate).filter(JobCandidate.job_id == job_id).delete(synchronize_session=False)

        db.delete(job)
        db.commit()
        return True, deleted_candidate_count

    except Exception:
        db.rollback()
        raise


def count_candidates_for_job(db: Session, job_id: str, owner_sub: str | None = None) -> int:
    from app.models import JobCandidate, Candidate
    query = db.query(JobCandidate).join(Candidate, Candidate.id == JobCandidate.candidate_id).filter(JobCandidate.job_id == job_id)
    if owner_sub is not None:
        query = query.filter(Candidate.owner_sub == owner_sub)
    return query.count()