from fastapi import APIRouter, Depends, HTTPException

from core.auth import get_current_user

router = APIRouter(tags=["health"])


@router.get("/api/")
def root():
    return {"service": "AI Recruiter API", "status": "ok"}


@router.get("/api/health")
def health():
    return {"status": "healthy"}


@router.get("/api/debug/retrieve/{candidate_id}")
def debug_retrieve(
    candidate_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        from core.llm import retrieve_candidate

        results = retrieve_candidate(
            candidate_id=candidate_id,
            question="Python AWS Kubernetes APIs REST desarrollo backend",
        )
        return {
            "candidate_id": candidate_id,
            "count": len(results),
            "results": results,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
