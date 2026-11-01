class AppError(Exception):
    status_code = 400

    def __init__(self, code: str, message: str, remediation: str = "", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.remediation = remediation
        self.details = details or {}

    def as_dict(self) -> dict:
        body = {"code": self.code, "message": self.message}
        if self.remediation:
            body["remediation"] = self.remediation
        if self.details:
            body["details"] = self.details
        return {"error": body}


class ConfigurationError(AppError):
    status_code = 503


class AuthError(AppError):
    status_code = 401


class ForbiddenError(AppError):
    status_code = 403


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class QuotaError(AppError):
    status_code = 429


class RequestLimitError(AppError):
    status_code = 429


class ProviderError(AppError):
    status_code = 502

    def __init__(self, code: str, message: str, remediation: str = "", details: dict | None = None, *, ambiguous: bool = False, http_status: int | None = None):
        super().__init__(code, message, remediation, details)
        self.ambiguous = ambiguous
        self.http_status = http_status
