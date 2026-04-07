from __future__ import annotations

import logging

from telegram.ext import Application, ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from config import TELEGRAM_BOT_TOKEN
from telegram.handlers import cmd_start, cmd_pair, cmd_unpair, callback_router, handle_text
from telegram.pairing import generate_pairing_code

logger = logging.getLogger(__name__)


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
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Generate initial pairing code (retrieve via /api/v1/telegram/pair-code)
    generate_pairing_code()
    logger.info("Telegram bot ready. Get pairing code via /api/v1/telegram/pair-code")

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    logger.info("Telegram bot polling started")
    return app
