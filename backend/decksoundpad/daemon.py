from __future__ import annotations

import argparse
import signal
import threading

from .api_server import DeckSoundpadApp, create_server, start_healthcheck_loop, write_session
from .config import load_config
from .logging_setup import setup_logging
from .paths import resolve_paths


def main() -> int:
    parser = argparse.ArgumentParser(description="DeckSoundpad daemon")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    paths = resolve_paths()
    settings = load_config(paths)
    logger = setup_logging(paths)
    app = DeckSoundpadApp(paths, settings=settings, logger=logger)
    server = create_server(app, host=args.host, port=args.port)
    write_session(paths, server)
    stop_healthcheck = start_healthcheck_loop(app) if settings.background_healthcheck_enabled else threading.Event()
    if not settings.background_healthcheck_enabled:
        logger.info("background healthcheck disabled")

    stopped = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopped
        if stopped:
            return
        stopped = True
        logger.info("daemon shutdown requested")
        stop_healthcheck.set()
        app.player.stop_all()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    logger.info(
        "starting daemon bind_host=%s port=%s",
        server.server_address[0],
        server.server_address[1],
    )
    try:
        server.serve_forever()
    finally:
        stop_healthcheck.set()
        app.player.stop_all()
        server.server_close()
        logger.info("daemon stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
