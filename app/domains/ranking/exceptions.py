"""Ranking domain exceptions.

These exceptions are raised by the ranking service layer and mapped
to HTTP responses by the router.
"""


class RankingJobNotFound(Exception):
    """Raised when a job is not found or not accessible."""

    def __init__(self, message: str = "Vacante no encontrada."):
        self.message = message
        super().__init__(message)


class RankingNotFound(Exception):
    """Raised when a ranking does not exist for a job."""

    def __init__(self, message: str = "No existe ranking para esta vacante."):
        self.message = message
        super().__init__(message)


class RankingAlreadyRunning(Exception):
    """Raised when another recalculation is already in progress."""

    def __init__(self, message: str = "Otro proceso esta recalculando el ranking."):
        self.message = message
        super().__init__(message)