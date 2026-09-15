"""Jobs domain exceptions."""


class JobNotFound(Exception):
    """Requested job is not visible to the current owner."""
