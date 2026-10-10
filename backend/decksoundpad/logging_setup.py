from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

from .paths import AppPaths, ensure_app_dirs, user_owner
from .safe_files import open_regular_file


class NoFollowRotatingFileHandler(RotatingFileHandler):
    def __init__(
        self,
        filename: Path,
        *,
        owner: tuple[int, int] | None = None,
        permissions: int = 0o600,
        **kwargs: object,
    ) -> None:
        self._safe_owner = owner
        self._safe_permissions = permissions
        super().__init__(filename, **kwargs)

    def _open(self) -> TextIO:
        handle = open_regular_file(
            Path(self.baseFilename),
            self.mode,
            encoding=self.encoding,
            permissions=self._safe_permissions,
            enforce_permissions=True,
            owner=self._safe_owner,
        )
        return handle  # type: ignore[return-value]


def setup_logging(paths: AppPaths, *, debug: bool = False) -> logging.Logger:
    ensure_app_dirs(paths)
    logger = logging.getLogger("decksoundpad")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    _add_rotating_file_handler(logger, paths.backend_log_file, formatter)
    public_handler = _add_rotating_file_handler(
        logger,
        paths.public_backend_log_file,
        formatter,
        optional=True,
        owner=user_owner(paths),
        permissions=0o640,
    )
    if public_handler is not None:
        logger.info("public backend log enabled path=%s", paths.public_backend_log_file)
    return logger


def _add_rotating_file_handler(
    logger: logging.Logger,
    path: Path,
    formatter: logging.Formatter,
    *,
    optional: bool = False,
    owner: tuple[int, int] | None = None,
    permissions: int = 0o600,
) -> NoFollowRotatingFileHandler | None:
    try:
        handler = NoFollowRotatingFileHandler(
            path,
            maxBytes=512_000,
            backupCount=3,
            encoding="utf-8",
            owner=owner,
            permissions=permissions,
        )
    except OSError as exc:
        if not optional:
            raise
        logger.warning("optional log file unavailable path=%s error=%s", path, exc)
        return None
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return handler
