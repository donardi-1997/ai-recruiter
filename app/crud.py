"""CRUD operations — compatibility facade re-exporting from domain repositories.

This module maintains backward compatibility for existing imports.
New code should import directly from app.domains.<domain>.repository
"""

# Jobs
from app.domains.jobs.repository import (
    get_job,
    list_jobs,
    create_job,
    update_job,
    delete_job,
    count_candidates_for_job,
)

# Candidates
from app.domains.candidates.repository import (
    get_candidate,
    list_candidates,
    create_candidate,
    delete_candidate,
    delete_all_candidates,
    list_candidates_for_job,
    assign_candidates_to_job,
)

# Evaluations
from app.domains.evaluations.repository import (
    VALID_RECOMMENDATIONS,
    MIN_SUMMARY_LENGTH,
    is_evaluation_complete,
    needs_evaluation,
    create_evaluation,
    get_evaluations_for_candidate,
    get_evaluation_for_job_candidate,
)

# Ranking
from app.domains.ranking.repository import (
    get_ranking_metadata,
    upsert_ranking_metadata,
    insert_ranking_items,
    get_ranking_items,
    build_ranking_response,
    _sanitize_error_message,
)

# Re-export for backward compatibility
__all__ = [
    # Jobs
    "get_job",
    "list_jobs",
    "create_job",
    "update_job",
    "delete_job",
    "count_candidates_for_job",
    # Candidates
    "get_candidate",
    "list_candidates",
    "create_candidate",
    "delete_candidate",
    "delete_all_candidates",
    "list_candidates_for_job",
    "assign_candidates_to_job",
    # Evaluations
    "VALID_RECOMMENDATIONS",
    "MIN_SUMMARY_LENGTH",
    "is_evaluation_complete",
    "needs_evaluation",
    "create_evaluation",
    "get_evaluations_for_candidate",
    "get_evaluation_for_job_candidate",
    # Ranking
    "get_ranking_metadata",
    "upsert_ranking_metadata",
    "insert_ranking_items",
    "get_ranking_items",
    "build_ranking_response",
    "_sanitize_error_message",
]