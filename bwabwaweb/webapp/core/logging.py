"""Logging webapp: request_id per request dan redaksi data sensitif."""
import logging
import re
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_SENSITIVE_PATTERN = re.compile(
    r"(?i)\b(password|passwd|token|secret|authorization|cookie|set-cookie|jwt)"
    r"(\s*[=:]\s*|\"\s*:\s*\")([^\s,;\"&]+)"
)
_LOG_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = _SENSITIVE_PATTERN.sub(r"\1\2[REDACTED]", message)
        record.args = ()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    handler.addFilter(RequestIdFilter())
    handler.addFilter(RedactingFilter())
    root = logging.getLogger("webapp")
    root.handlers = [handler]
    root.setLevel(level)
    root.propagate = False
