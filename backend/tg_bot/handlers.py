from __future__ import annotations

import asyncio
import logging
from functools import wraps
from typing import Callable, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from tg_bot.pairing import is_paired, verify_pairing_code, unpair_user, get_paired_users
from services import project_scanner, session_manager, system_info
from services.scaffolder import list_templates, create_project

# Reference to the telegram bot app, set during startup
_bot_app = None
# Cache project info for dead sessions (so Trust & Retry can find the path)
_dead_session_info: Dict[str, Dict] = {}


def set_bot_app(app):
    global _bot_app
    _bot_app = app


async def notify_blocked_session(session_id: str, project_name: str, prompt_text: str, project_path: str = ""):
    """Called by session_manager when a session blocks on a prompt or exits with error."""
    if not _bot_app:
        return

    import re as _re
    clean = _re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", prompt_text)
    clean = clean.strip()[:500]

    is_trust = clean.startswith("[TRUST]")
    is_error = clean.startswith("[EXITED]")

    if is_trust:
        clean = clean[7:].strip()
        _dead_session_info[session_id] = {
            "project_name": project_name,
            "project_path": project_path,
        }
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Trust & Retry", callback_data=f"s:tr:{session_id}")],
            [InlineKeyboardButton("<< Menu", callback_data="menu")],
        ])
        text = f"*Workspace not trusted:* {project_name}\n\n```\n{clean}\n```\n\nTrust this workspace and retry?"
    elif is_error:
        clean = clean[8:].strip()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("<< Menu", callback_data="menu")],
        ])
        text = f"*Session failed:* {project_name}\n\n```\n{clean}\n```"
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Approve (y)", callback_data=f"s:y:{session_id}"),
             InlineKeyboardButton("Deny (n)", callback_data=f"s:n:{session_id}")],
            [InlineKeyboardButton("Stop Session", callback_data=f"s:k:{session_id}")],
        ])
        text = f"*Session blocked:* {project_name}\n\n```\n{clean}\n```\n\nApprove or deny?"

    for user_id in get_paired_users():
        try:
            await _bot_app.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")


async def _run_blocking(func, *args):
    """Run a blocking function in a thread executor to avoid freezing the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, func, *args)

logger = logging.getLogger(__name__)

ITEMS_PER_PAGE = 8


def require_paired(func: Callable):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not is_paired(user_id):
            await update.effective_message.reply_text(
                "You are not paired. Send /pair <code> to pair this device."
            )
            return
        return await func(update, context)
    return wrapper


# --- /pair and /unpair ---

async def cmd_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"cmd_pair called by user {update.effective_user.id}, args={context.args}")
    if not context.args:
        await update.message.reply_text("Usage: /pair <code>")
        return
    code = context.args[0]
    user_id = update.effective_user.id
    if verify_pairing_code(code, user_id):
        await update.message.reply_text("Paired successfully! You now have full access. Send /start to begin.")
    else:
        await update.message.reply_text("Invalid or expired pairing code. Get a new one from the API.")


@require_paired
async def cmd_unpair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    unpair_user(update.effective_user.id)
    await update.message.reply_text("Unpaired. You will no longer receive commands.")


# --- /start ---

@require_paired
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Projects", callback_data="p:l:0"),
         InlineKeyboardButton("New Project", callback_data="sc:l")],
        [InlineKeyboardButton("Sessions", callback_data="s:l"),
         InlineKeyboardButton("Maintenance", callback_data="m:l")],
    ])
    await update.effective_message.reply_text("Claude Code Launcher", reply_markup=keyboard)


# --- Callback router ---

@require_paired
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("p:"):
        await _handle_projects(query, data)
    elif data.startswith("s:"):
        await _handle_sessions(query, data)
    elif data.startswith("sc:"):
        await _handle_scaffold(query, data, context)
    elif data.startswith("m:"):
        await _handle_maintenance(query, data)
    elif data == "menu":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Projects", callback_data="p:l:0"),
             InlineKeyboardButton("New Project", callback_data="sc:l")],
            [InlineKeyboardButton("Sessions", callback_data="s:l"),
             InlineKeyboardButton("Maintenance", callback_data="m:l")],
        ])
        await query.edit_message_text("Claude Code Launcher", reply_markup=keyboard)


# --- Projects ---

async def _handle_projects(query, data: str):
    parts = data.split(":")
    action = parts[1]

    if action == "l":
        page = int(parts[2]) if len(parts) > 2 else 0
        projects = project_scanner.scan_projects()
        start = page * ITEMS_PER_PAGE
        page_projects = projects[start:start + ITEMS_PER_PAGE]

        buttons = [[InlineKeyboardButton(p.name, callback_data=f"p:d:{p.slug}")] for p in page_projects]

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("<< Prev", callback_data=f"p:l:{page - 1}"))
        if start + ITEMS_PER_PAGE < len(projects):
            nav.append(InlineKeyboardButton("Next >>", callback_data=f"p:l:{page + 1}"))
        if nav:
            buttons.append(nav)
        buttons.append([InlineKeyboardButton("<< Menu", callback_data="menu")])

        await query.edit_message_text(
            f"Projects ({len(projects)} total, page {page + 1}):",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    elif action == "d":
        slug = parts[2]
        project = project_scanner.get_project(slug)
        if not project:
            await query.edit_message_text("Project not found.")
            return
        text = (
            f"*{project.name}*\n"
            f"Path: `{project.path}`\n"
            f"Markers: {', '.join(project.markers)}\n"
            f"CLAUDE.md: {'Yes' if project.has_claude_md else 'No'}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Launch Claude RC", callback_data=f"p:rc:{slug}")],
            [InlineKeyboardButton("<< Projects", callback_data="p:l:0"),
             InlineKeyboardButton("<< Menu", callback_data="menu")],
        ])
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")

    elif action == "rc":
        slug = parts[2]
        project = project_scanner.get_project(slug)
        if not project:
            await query.edit_message_text("Project not found.")
            return
        session = await session_manager.start_session(project.path, project.name)
        await query.edit_message_text(
            f"Session started for *{project.name}*\n"
            f"Session ID: `{session.session_id}`\n"
            f"PID: {session.pid}\n\n"
            f"Open Claude Code mobile app to connect.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("<< Menu", callback_data="menu")],
            ]),
        )


# --- Sessions ---

async def _handle_sessions(query, data: str):
    parts = data.split(":")
    action = parts[1]

    if action == "l":
        sessions = session_manager.list_sessions()
        if not sessions:
            await query.edit_message_text(
                "No active sessions.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("<< Menu", callback_data="menu")],
                ]),
            )
            return

        buttons = []
        text_lines = ["*Active Sessions:*\n"]
        for s in sessions:
            mins = s["uptime_seconds"] // 60
            text_lines.append(f"- {s['project_name']} ({mins}m) PID:{s['pid']}")
            buttons.append([
                InlineKeyboardButton(f"Stop {s['project_name']}", callback_data=f"s:k:{s['session_id']}")
            ])
        buttons.append([InlineKeyboardButton("<< Menu", callback_data="menu")])

        await query.edit_message_text(
            "\n".join(text_lines),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown",
        )

    elif action in ("y", "n"):
        session_id = parts[2]
        response = "y" if action == "y" else "n"
        success = await session_manager.respond_to_prompt(session_id, response)
        if success:
            await query.edit_message_text(
                f"Sent '{response}' to session.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Sessions", callback_data="s:l"),
                     InlineKeyboardButton("<< Menu", callback_data="menu")],
                ]),
            )
        else:
            await query.edit_message_text(
                "Session not found or no longer blocked.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("<< Menu", callback_data="menu")],
                ]),
            )

    elif action == "tr":
        # Trust & Retry: trust the workspace then re-launch remote-control
        session_id = parts[2]
        info = _dead_session_info.pop(session_id, None)
        if not info or "project_path" not in info:
            await query.edit_message_text(
                "Could not find project info for retry.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("<< Menu", callback_data="menu")],
                ]),
            )
            return

        await query.edit_message_text(f"Trusting workspace for *{info['project_name']}*...", parse_mode="Markdown")

        try:
            session = await session_manager.trust_and_launch(
                info["project_path"], info["project_name"]
            )
            await query.edit_message_text(
                f"Session started for *{info['project_name']}*\n"
                f"Session ID: `{session.session_id}`\n"
                f"PID: {session.pid}\n\n"
                f"Open Claude Code mobile app to connect.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("<< Menu", callback_data="menu")],
                ]),
            )
        except Exception as e:
            logger.error(f"Trust & retry failed: {e}")
            await query.edit_message_text(
                f"Trust & retry failed: {str(e)[:200]}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("<< Menu", callback_data="menu")],
                ]),
            )

    elif action == "k":
        session_id = parts[2]
        stopped = await session_manager.stop_session(session_id)
        msg = "Session stopped." if stopped else "Session not found."
        await query.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Sessions", callback_data="s:l"),
                 InlineKeyboardButton("<< Menu", callback_data="menu")],
            ]),
        )


# --- Scaffold ---

async def _handle_scaffold(query, data: str, context):
    parts = data.split(":")
    action = parts[1]

    if action == "l":
        templates = list_templates()
        buttons = [
            [InlineKeyboardButton(t["name"], callback_data=f"sc:t:{t['key']}")]
            for t in templates
        ]
        buttons.append([InlineKeyboardButton("<< Menu", callback_data="menu")])
        await query.edit_message_text(
            "Select a project template:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    elif action == "t":
        template_key = parts[2]
        context.user_data["scaffold_template"] = template_key
        await query.edit_message_text(
            f"Template: *{template_key}*\nSend the project name as a text message.",
            parse_mode="Markdown",
        )


@require_paired
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages — used for scaffold project name input."""
    template = context.user_data.get("scaffold_template")
    if not template:
        return

    name = update.message.text.strip()
    del context.user_data["scaffold_template"]

    result = create_project(template, name)
    if "error" in result:
        await update.message.reply_text(f"Error: {result['error']}")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Launch Claude RC", callback_data=f"p:rc:{result['slug']}")],
        [InlineKeyboardButton("<< Menu", callback_data="menu")],
    ])
    await update.message.reply_text(
        f"Project created: *{result['name']}*\n"
        f"Path: `{result['path']}`",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


# --- Maintenance ---

async def _handle_maintenance(query, data: str):
    parts = data.split(":")
    action = parts[1]

    if action == "l":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("System Status", callback_data="m:status")],
            [InlineKeyboardButton("Git Status", callback_data="m:git"),
             InlineKeyboardButton("Git Pull All", callback_data="m:pull")],
            [InlineKeyboardButton("Cleanup", callback_data="m:clean"),
             InlineKeyboardButton("Processes", callback_data="m:proc")],
            [InlineKeyboardButton("Sleep", callback_data="m:pw:sleep"),
             InlineKeyboardButton("Restart", callback_data="m:pw:restart")],
            [InlineKeyboardButton("<< Menu", callback_data="menu")],
        ])
        await query.edit_message_text("System Maintenance:", reply_markup=keyboard)

    elif action == "status":
        status = await _run_blocking(system_info.get_system_status)
        text = (
            f"*System Status*\n"
            f"Host: {status['hostname']}\n"
            f"CPU: {status['cpu']['percent']}% ({status['cpu']['cores']} cores)\n"
            f"RAM: {status['memory']['used_gb']}/{status['memory']['total_gb']} GB ({status['memory']['percent']}%)\n"
            f"Disk: {status['disk']['used_gb']}/{status['disk']['total_gb']} GB ({status['disk']['percent']}%)\n"
        )
        bat = status.get("battery", {})
        if bat.get("available"):
            text += f"Battery: {bat['percent']}% {'(charging)' if bat['charging'] else ''}\n"

        uptime_h = status["uptime_seconds"] // 3600
        uptime_m = (status["uptime_seconds"] % 3600) // 60
        text += f"Uptime: {uptime_h}h {uptime_m}m"

        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("<< Maintenance", callback_data="m:l"),
                 InlineKeyboardButton("<< Menu", callback_data="menu")],
            ]),
        )

    elif action == "git":
        from services.git_ops import check_all_status
        repos = await _run_blocking(check_all_status)
        lines = ["*Git Status:*\n"]
        for r in repos[:20]:
            icon = "clean" if r["clean"] else f"{r['changes']} changes"
            lines.append(f"- {r['name']} [{r['branch']}] {icon}")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("<< Maintenance", callback_data="m:l")],
            ]),
        )

    elif action == "pull":
        from services.git_ops import pull_all
        results = await _run_blocking(pull_all)
        lines = ["*Git Pull All:*\n"]
        for r in results[:20]:
            lines.append(f"- {r['name']}: {r['result'][:50]}")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("<< Maintenance", callback_data="m:l")],
            ]),
        )

    elif action == "clean":
        from services.cleanup import run_cleanup
        result = await _run_blocking(run_cleanup, ["brew", "pip", "logs"])
        lines = ["*Cleanup Results:*\n"]
        for k, v in result.items():
            lines.append(f"- {k}: {str(v)[:80]}")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("<< Maintenance", callback_data="m:l")],
            ]),
        )

    elif action == "proc":
        from services.process_manager import get_top_processes
        procs = await _run_blocking(get_top_processes, 10)
        lines = ["*Top Processes:*\n"]
        for p in procs:
            lines.append(f"- {p['name']} (PID:{p['pid']}) CPU:{p['cpu_percent']}% MEM:{p['memory_percent']}%")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("<< Maintenance", callback_data="m:l")],
            ]),
        )

    elif action == "pw":
        power_action = parts[2]
        import subprocess
        cmds = {"sleep": ["pmset", "sleepnow"], "restart": ["sudo", "shutdown", "-r", "now"]}
        cmd = cmds.get(power_action)
        if cmd:
            await query.edit_message_text(f"Executing {power_action}...")
            subprocess.Popen(cmd)
