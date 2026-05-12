from __future__ import annotations

import logging

from app.config import Settings, settings


def _log_level(value: str | None, *, default: int = logging.INFO) -> int:
    if not value:
        return default
    parsed = logging.getLevelName(value.upper())
    if isinstance(parsed, int):
        return parsed
    return default


def configure_logging(config: Settings = settings) -> None:
    base_level = _log_level(config.logging.level)

    logging.basicConfig(
        level=base_level,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    logging.getLogger("dingbridge").setLevel(base_level)
