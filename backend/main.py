from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from routers import projects, sessions, system, power, scaffold, telegram_ctrl
from services.session_manager import recover_sessions, stop_all_sessions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Claude Code Launcher",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers under /api/v1
app.include_router(projects.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")
app.include_router(power.router, prefix="/api/v1")
app.include_router(scaffold.router, prefix="/api/v1")
app.include_router(telegram_ctrl.router, prefix="/api/v1")

# Track telegram app for clean shutdown
_telegram_app = None


@app.get("/api/v1/health")
async def health():
    return {"status": "ok"}


@app.on_event("startup")
async def startup():
    global _telegram_app
    recovered = recover_sessions()
    logger.info(f"Recovered {recovered} active session(s)")

    if config.TELEGRAM_ENABLED and config.TELEGRAM_BOT_TOKEN:
        try:
            from tg_bot.bot import start_telegram_bot
            _telegram_app = await start_telegram_bot()
            logger.info("Telegram bot started")
        except Exception as e:
            logger.error(f"Failed to start Telegram bot: {e}")


@app.on_event("shutdown")
async def shutdown():
    global _telegram_app
    logger.info("Shutting down...")

    # Stop telegram bot
    if _telegram_app:
        try:
            await _telegram_app.updater.stop()
            await _telegram_app.stop()
            await _telegram_app.shutdown()
            logger.info("Telegram bot stopped")
        except Exception as e:
            logger.warning(f"Telegram bot shutdown error: {e}")

    # Stop all Claude sessions
    stopped = await stop_all_sessions()
    logger.info(f"Stopped {stopped} Claude session(s)")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)
