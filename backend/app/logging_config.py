"""Structured JSON logging with correlation IDs for API and worker runs."""
from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "correlation_id", None):
            record.correlation_id = correlation_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key in ("job_id", "event_id", "dataset_id", "duration_ms", "status"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", structured: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(CorrelationFilter())
    if structured:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(correlation_id)s] %(name)s: %(message)s")
        )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Quiet noisy third-party loggers while retaining warnings.
    for noisy in ("rasterio", "botocore", "urllib3", "h5py"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
