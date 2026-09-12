"""Domain exceptions for candidate imports."""


class CandidateImportError(Exception):
    """Base class for candidate-import application failures."""


class JobNotFound(CandidateImportError):
    pass


class ImportBatchNotFound(CandidateImportError):
    pass


class InvalidImportManifest(CandidateImportError):
    pass


class UploadVerificationFailed(CandidateImportError):
    pass


class QueueDispatchFailed(CandidateImportError):
    pass


class IdentityConflict(CandidateImportError):
    """Strong identities resolve to different candidates."""

