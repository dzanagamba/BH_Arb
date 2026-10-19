import asyncio
import logging
import sys

import uvicorn

# Fix Windows ProactorEventLoop for Playwright
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from config.settings import HOST, LOG_LEVEL, PORT

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

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
    uvicorn.run(
        "server.app:app", host=HOST, port=PORT, reload=False, log_level=LOG_LEVEL.lower()
    )
