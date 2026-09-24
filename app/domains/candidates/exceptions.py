"""Candidates domain exceptions."""


class CandidateNotFound(Exception):
    """Requested candidate is not visible to the current owner."""


class JobNotFound(Exception):
    """Requested job is not visible to the current owner."""


class JobCandidateNotFound(Exception):
    """Requested candidate is not assigned to the requested job."""


class InvalidApplicationStatus(Exception):
    """Requested application status is not part of the local ATS state model."""



class CandidateRetentionProtected(Exception):
    """Operational hard-delete is disabled for retained candidates."""



class CandidateBanned(Exception):
    """The candidate is retained but excluded from new evaluation activity."""
