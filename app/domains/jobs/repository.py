"""Jobs repository."""

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models import Candidate, Job, JobCandidate


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


def list_jobs_page(
    db: Session,
    *,
    owner_sub: str,
    page: int,
    page_size: int,
    sort: str,
    q: str = "",
):
    """Return one globally sorted page of jobs with owner-scoped candidate counts."""

    filters = [Job.owner_sub == owner_sub]
    search = str(q or "").strip()
    if search:
        filters.append(Job.title.ilike(f"%{search}%"))

    total = int(db.query(func.count(Job.id)).filter(*filters).scalar() or 0)
    candidate_count = func.count(Candidate.id).label("candidate_count")

    query = (
        db.query(Job, candidate_count)
        .outerjoin(JobCandidate, JobCandidate.job_id == Job.id)
        .outerjoin(
            Candidate,
            and_(
                Candidate.id == JobCandidate.candidate_id,
                Candidate.owner_sub == owner_sub,
            ),
        )
        .filter(*filters)
        .group_by(Job.id)
    )

    if sort == "candidates_desc":
        query = query.order_by(candidate_count.desc(), Job.created_at.desc(), Job.id.asc())
    elif sort == "candidates_asc":
        query = query.order_by(candidate_count.asc(), Job.created_at.desc(), Job.id.asc())
    elif sort == "created_asc":
        query = query.order_by(Job.created_at.asc(), Job.id.asc())
    else:
        query = query.order_by(Job.created_at.desc(), Job.id.asc())

    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def create_job(
    db: Session,
    *,
    title: str,
    description: str | None = None,
    indeed_description: str | None = None,
    ai_description: str | None = None,
    active_description_source: str = "indeed",
    owner_sub: str | None = None,
    country_code: str | None = None,
    city: str | None = None,
    employment_type: str | None = None,
    public_slug: str | None = None,
    published_at=None,
    evaluation_profile: dict | None = None,
) -> Job:
    job = Job(
        title=title,
        description=description,
        indeed_description=indeed_description,
        ai_description=ai_description,
        active_description_source=active_description_source,
        owner_sub=owner_sub,
        country_code=country_code,
        city=city,
        employment_type=employment_type,
        public_slug=public_slug,
        published_at=published_at,
        evaluation_profile=evaluation_profile or {},
        evaluation_version=1,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_job(
    db: Session,
    job: Job,
    *,
    title: str | None = None,
    description: str | None = None,
    indeed_description: str | None = None,
    ai_description: str | None = None,
    active_description_source: str | None = None,
    country_code: str | None = None,
    city: str | None = None,
    employment_type: str | None = None,
    public_slug: str | None = None,
    published_at=None,
    evaluation_profile: dict | None = None,
    evaluation_version: int | None = None,
    commit: bool = True,
) -> Job:
    if title is not None:
        job.title = title
    if description is not None:
        job.description = description
    if indeed_description is not None:
        job.indeed_description = indeed_description
    if ai_description is not None:
        job.ai_description = ai_description
    if active_description_source is not None:
        job.active_description_source = active_description_source
    if evaluation_profile is not None:
        job.evaluation_profile = evaluation_profile
    if evaluation_version is not None:
        job.evaluation_version = int(evaluation_version)

    for name, value in {
        "country_code": country_code,
        "city": city,
        "employment_type": employment_type,
        "public_slug": public_slug,
        "published_at": published_at,
    }.items():
        if value is not None:
            setattr(job, name, value)

    if commit:
        db.commit()
        db.refresh(job)
    else:
        db.flush()
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
    query = (
        db.query(JobCandidate)
        .join(Candidate, Candidate.id == JobCandidate.candidate_id)
        .filter(JobCandidate.job_id == job_id)
    )
    if owner_sub is not None:
        query = query.filter(Candidate.owner_sub == owner_sub)
    return query.count()
