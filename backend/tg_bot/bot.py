from __future__ import annotations

import asyncio
import logging

from telegram.ext import Application, ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from config import TELEGRAM_BOT_TOKEN
from tg_bot.handlers import (
    cmd_start, cmd_pair, cmd_unpair, cmd_addmachine,
    callback_router, handle_text,
    set_bot_app, notify_blocked_session, notify_remote_session,
    notify_machine_discovered,
)
from tg_bot.pairing import generate_pairing_code
from services.session_manager import set_prompt_callback
from services.machine_registry import init_registry
from services.discovery import discovery_loop
from services.session_poller import poller_loop

logger = logging.getLogger(__name__)


async def _refresh_loop(registry, interval: int = 60):
    """Periodically refresh machine online/offline status."""
    while True:
        try:
            await registry.refresh_status()
        except Exception as e:
            logger.error(f"Status refresh error: {e}")
        await asyncio.sleep(interval)


async def start_telegram_bot() -> Application:
    """Start the Telegram bot alongside FastAPI. Returns the app for clean shutdown."""
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set, skipping Telegram bot")
        return None

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("pair", cmd_pair))
    app.add_handler(CommandHandler("unpair", cmd_unpair))
    app.add_handler(CommandHandler("projects", cmd_start))
    app.add_handler(CommandHandler("sessions", cmd_start))
    app.add_handler(CommandHandler("maintenance", cmd_start))
    app.add_handler(CommandHandler("addmachine", cmd_addmachine))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Generate initial pairing code (retrieve via /api/v1/telegram/pair-code)
    generate_pairing_code()
    logger.info("Telegram bot ready. Get pairing code via /api/v1/telegram/pair-code")

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram bot polling started")

    # Wire up prompt notifications: session_manager -> telegram (local sessions)
    set_bot_app(app)
    set_prompt_callback(notify_blocked_session)

    # Initialize machine registry and start hub background tasks
    registry = init_registry()

    # Wire discovery callback so new machines trigger Telegram notifications
    registry.set_discovery_callback(
        lambda mid, name, url: asyncio.create_task(notify_machine_discovered(mid, name, url))
    )

    # Background tasks: discovery, polling, status refresh
    asyncio.create_task(discovery_loop(registry, interval=60))
    asyncio.create_task(poller_loop(registry, notify_remote_session, interval=5))
    asyncio.create_task(_refresh_loop(registry, interval=60))
    logger.info("Hub background tasks started (discovery, polling, status)")

    return app
