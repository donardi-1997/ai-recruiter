"""Typed Indeed integration failures."""


class IndeedError(Exception):
    code = "indeed_error"


class IndeedDisabled(IndeedError):
    code = "indeed_disabled"


class IndeedNotConfigured(IndeedError):
    code = "indeed_not_configured"


class IndeedValidationError(IndeedError):
    code = "indeed_validation_error"


class IndeedRemoteError(IndeedError):
    code = "indeed_remote_error"


class IndeedLinkNotFound(IndeedError):
    code = "indeed_link_not_found"
