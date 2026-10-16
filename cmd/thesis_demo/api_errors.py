"""Stable public API failures; internal exceptions are never UI messages."""
from http import HTTPStatus


class ApiError(ValueError):
    def __init__(self, code: str, message: str, status: int = HTTPStatus.BAD_REQUEST,
                 *, fields: tuple[str, ...] = ()):
        super().__init__(message)
        self.code = code
        self.status = status
        self.fields = fields
