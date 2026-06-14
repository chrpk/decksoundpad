from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .paths import AppPaths, ensure_app_dirs


def setup_logging(paths: AppPaths, *, debug: bool = False) -> logging.Logger:
    ensure_app_dirs(paths)
    logger = logging.getLogger("decksoundpad")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    _add_rotating_file_handler(logger, paths.daemon_log_file, formatter)
    public_handler = _add_rotating_file_handler(
        logger,
        paths.public_daemon_log_file,
        formatter,
        optional=True,
    )
    if public_handler is not None:
        logger.info("public daemon log enabled path=%s", paths.public_daemon_log_file)
    return logger


def _add_rotating_file_handler(
    logger: logging.Logger,
    path: object,
    formatter: logging.Formatter,
    *,
    optional: bool = False,
) -> RotatingFileHandler | None:
    try:
        handler = RotatingFileHandler(
            path,
            maxBytes=512_000,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError as exc:
        if not optional:
            raise
        logger.warning("optional log file unavailable path=%s error=%s", path, exc)
        return None
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return handler
