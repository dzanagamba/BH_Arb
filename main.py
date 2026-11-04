import asyncio
import logging
import sys

import uvicorn

# Fix Windows ProactorEventLoop for Playwright
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from config.settings import HOST, LOG_FORMAT, LOG_LEVEL, PORT
from server.observability import configure_logging

configure_logging(LOG_LEVEL, LOG_FORMAT)

if __name__ == "__main__":
    print(f"""
    ==========================================
         SUREBET SCANNER v1.0
         Bosnian Market Arbitrage Tool
    ==========================================
      Dashboard: http://localhost:{PORT}
      API Docs:  http://localhost:{PORT}/docs
    ==========================================
    """)
    try:
        uvicorn.run(
            "server.app:app", host=HOST, port=PORT, reload=False, log_level=LOG_LEVEL.lower()
        )
    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt received, shutting down gracefully.")
