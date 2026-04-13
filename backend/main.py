from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import config
from routers import projects, sessions, system, power, scaffold, telegram_ctrl, terminal, settings_api
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
app.include_router(terminal.router, prefix="/api/v1")
app.include_router(settings_api.router, prefix="/api/v1")

# Track telegram app for clean shutdown
_telegram_app = None


@app.get("/api/v1/health")
async def health():
    from services.hub_pairing import is_paired
    from services.shared_trust import get_trust_token_hash
    return {
        "status": "ok",
        "machine_name": config.MACHINE_NAME,
        "registration_open": not is_paired(),
        "trust_hash": get_trust_token_hash(),
    }


@app.post("/api/v1/pair-hub")
async def pair_hub():
    from services.hub_pairing import pair_hub as do_pair
    result = do_pair()
    if result is None:
        raise HTTPException(status_code=403, detail="Already paired")
    return {"data": result}


@app.on_event("startup")
async def startup():
    global _telegram_app
    recovered = recover_sessions()
    logger.info(f"Recovered {recovered} active session(s)")

    # Update local machine URL with Tailscale IP for display
    try:
        from services.discovery import get_tailscale_self_ip
        from services.machine_registry import get_registry
        ts_ip = await get_tailscale_self_ip()
        if ts_ip:
            get_registry().update_local_url(f"http://{ts_ip}:{config.PORT}")
    except Exception as e:
        logger.debug(f"Could not get Tailscale self IP: {e}")

    if config.TELEGRAM_ENABLED and config.TELEGRAM_BOT_TOKEN:
        from tg_bot.leader import try_acquire_leadership
        if try_acquire_leadership():
            config.set_hub_status(True)
            try:
                from tg_bot.bot import start_telegram_bot
                _telegram_app = await start_telegram_bot()
                logger.info("Telegram bot started (this machine is hub)")
            except Exception as e:
                logger.error(f"Failed to start Telegram bot: {e}")
        else:
            logger.info("Running as node (another machine is Telegram hub)")


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

    # Release Telegram leadership lock
    try:
        from tg_bot.leader import release_leadership
        release_leadership()
    except Exception:
        pass

    # Stop all Claude sessions
    stopped = await stop_all_sessions()
    logger.info(f"Stopped {stopped} Claude session(s)")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)
