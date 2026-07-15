"""Logging configuration: API-key-leak filter + setup hook."""
import logging


class APIKeyFilter(logging.Filter):
    """Filter out any log message containing potential API key patterns."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.getMessage()).lower()
        blocked_patterns = [
            "sk-", "cfut_", "api_key", "apikey", "bearer ",
            "x-api-key", "authorization",
        ]
        return not any(p in msg for p in blocked_patterns)


def setup_logging() -> None:
    for logger_name in ("ai_service", "team_collaboration", "apikeys",
                        "key_vault_service", "security.crypto"):
        logging.getLogger(logger_name).addFilter(APIKeyFilter())
