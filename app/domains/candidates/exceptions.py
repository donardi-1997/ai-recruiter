"""Candidates domain exceptions."""


class CandidateNotFound(Exception):
    """Requested candidate is not visible to the current owner."""


class JobNotFound(Exception):
    """Requested job is not visible to the current owner."""
