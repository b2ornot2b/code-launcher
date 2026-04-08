from __future__ import annotations

import asyncio
import logging
import re as _re
from functools import wraps
from typing import Callable, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from tg_bot.pairing import is_paired, verify_pairing_code, unpair_user, get_paired_users
from services import project_scanner, session_manager, system_info
from services.scaffolder import list_templates, create_project

logger = logging.getLogger(__name__)

# Reference to the telegram bot app, set during startup
_bot_app = None
# Cache project info for dead sessions (so Trust & Retry can find the path)
_dead_session_info: Dict[str, Dict] = {}

ITEMS_PER_PAGE = 8

# Project type icons based on markers
_MARKER_ICONS = {
    "build.gradle.kts": "\U0001f4f1",  # mobile phone
    "pubspec.yaml": "\U0001f4f1",
    "Cargo.toml": "\U0001f980",  # crab
    "go.mod": "\U0001f4e6",  # package
    "pyproject.toml": "\U0001f40d",  # snake
    "package.json": "\U0001f310",  # globe
    "CMakeLists.txt": "\u2699\ufe0f",  # gear
    "Makefile": "\u2699\ufe0f",
}


def _project_icon(markers: list) -> str:
    for marker, icon in _MARKER_ICONS.items():
        if marker in markers:
            return icon
    return "\U0001f4c2"  # open folder


def _status_icon(status: str) -> str:
    if status == "blocked":
        return "\U0001f7e1"  # yellow
    if status == "dead":
        return "\U0001f534"  # red
    return "\U0001f7e2"  # green


def _clean_ansi(text: str) -> str:
    return _re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


def set_bot_app(app):
    global _bot_app
    _bot_app = app


async def _run_blocking(func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, func, *args)


# --- Notifications ---

async def notify_blocked_session(session_id: str, project_name: str, prompt_text: str, project_path: str = ""):
    if not _bot_app:
        return

    clean = _clean_ansi(prompt_text).strip()[:500]
    is_trust = clean.startswith("[TRUST]")
    is_worktree = clean.startswith("[WORKTREE]")
    is_error = clean.startswith("[EXITED]")

    if is_trust:
        clean = clean[7:].strip()
        _dead_session_info[session_id] = {
            "project_name": project_name,
            "project_path": project_path,
        }
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001f513 Trust & Retry", callback_data=f"s:tr:{session_id}")],
            [InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
        ])
        text = f"\u26a0\ufe0f *Workspace not trusted:* {project_name}\n\nTrust this workspace and retry?"
    elif is_worktree:
        clean = clean[10:].strip()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
        ])
        text = f"\U0001f9ea *Experiment not available:* {project_name}\n\nThis project is not a git repository. Experiment mode requires git. Use Launch instead."
    elif is_error:
        clean = clean[8:].strip()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
        ])
        text = f"\u274c *Session failed:* {project_name}\n\n```\n{clean}\n```"
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("\u2705 Approve", callback_data=f"s:y:{session_id}"),
             InlineKeyboardButton("\u274c Deny", callback_data=f"s:n:{session_id}")],
            [InlineKeyboardButton("\U0001f6d1 Stop", callback_data=f"s:k:{session_id}")],
        ])
        text = f"\u23f8\ufe0f *Session blocked:* {project_name}\n\n```\n{clean}\n```\n\nApprove or deny?"

    for user_id in get_paired_users():
        try:
            await _bot_app.bot.send_message(
                chat_id=user_id, text=text,
                parse_mode="Markdown", reply_markup=keyboard,
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")


# --- Auth ---

def require_paired(func: Callable):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not is_paired(user_id):
            await update.effective_message.reply_text(
                "\U0001f512 Not paired. Send /pair <code> to pair this device."
            )
            return
        return await func(update, context)
    return wrapper


async def cmd_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"cmd_pair called by user {update.effective_user.id}, args={context.args}")
    if not context.args:
        await update.message.reply_text("Usage: /pair <code>")
        return
    code = context.args[0]
    user_id = update.effective_user.id
    if verify_pairing_code(code, user_id):
        await update.message.reply_text("\u2705 Paired successfully! Send /start to begin.")
    else:
        await update.message.reply_text("\u274c Invalid or expired pairing code.")


@require_paired
async def cmd_unpair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    unpair_user(update.effective_user.id)
    await update.message.reply_text("\U0001f513 Unpaired.")


# --- Main Menu ---

async def _build_menu_text() -> str:
    sessions = session_manager.list_sessions()
    projects = project_scanner.scan_projects()
    try:
        status = await _run_blocking(system_info.get_system_status)
        cpu = f"{status['cpu']['percent']}%"
        ram = f"{status['memory']['percent']}%"
        bat = status.get("battery", {})
        bat_str = f" \u00b7 \U0001f50b {bat['percent']}%" if bat.get("available") else ""
    except Exception:
        cpu = ram = "?"
        bat_str = ""

    return (
        f"\U0001f5a5 *Claude Code Launcher*\n\n"
        f"\U0001f4c2 {len(projects)} projects \u00b7 \u26a1 {len(sessions)} active sessions\n"
        f"\U0001f4bb CPU {cpu} \u00b7 RAM {ram}{bat_str}"
    )


def _menu_keyboard(session_count: int = 0) -> InlineKeyboardMarkup:
    sess_label = f"\u26a1 Sessions ({session_count})" if session_count else "\u26a1 Sessions"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001f4c2 Projects", callback_data="p:l:0"),
         InlineKeyboardButton("\u2795 New Project", callback_data="sc:l")],
        [InlineKeyboardButton(sess_label, callback_data="s:l"),
         InlineKeyboardButton("\U0001f527 Maintenance", callback_data="m:l")],
    ])


@require_paired
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await _build_menu_text()
    sessions = session_manager.list_sessions()
    await update.effective_message.reply_text(
        text, reply_markup=_menu_keyboard(len(sessions)), parse_mode="Markdown",
    )


# --- Callback Router ---

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
        text = await _build_menu_text()
        sessions = session_manager.list_sessions()
        await query.edit_message_text(
            text, reply_markup=_menu_keyboard(len(sessions)), parse_mode="Markdown",
        )


# --- Projects ---

async def _handle_projects(query, data: str):
    parts = data.split(":")
    action = parts[1]

    if action == "l":
        page = int(parts[2]) if len(parts) > 2 else 0
        projects = project_scanner.scan_projects()
        sessions = session_manager.list_sessions()
        active_projects = {s["project_name"] for s in sessions}

        start = page * ITEMS_PER_PAGE
        page_projects = projects[start:start + ITEMS_PER_PAGE]

        # Two projects per row
        buttons = []
        for i in range(0, len(page_projects), 2):
            row = []
            for p in page_projects[i:i + 2]:
                icon = _project_icon(p.markers)
                active = " \u26a1" if p.name in active_projects else ""
                row.append(InlineKeyboardButton(
                    f"{icon} {p.name}{active}",
                    callback_data=f"p:d:{p.slug}",
                ))
            buttons.append(row)

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("\u25c0 Prev", callback_data=f"p:l:{page - 1}"))
        if start + ITEMS_PER_PAGE < len(projects):
            nav.append(InlineKeyboardButton("Next \u25b6", callback_data=f"p:l:{page + 1}"))
        if nav:
            buttons.append(nav)
        buttons.append([InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")])

        total_pages = (len(projects) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        await query.edit_message_text(
            f"\U0001f4c2 *Projects* ({len(projects)}) \u00b7 Page {page + 1}/{total_pages}",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown",
        )

    elif action == "d":
        slug = parts[2]
        project = project_scanner.get_project(slug)
        if not project:
            await query.edit_message_text("Project not found.")
            return

        icon = _project_icon(project.markers)
        sessions = session_manager.list_sessions()
        active = [s for s in sessions if s["project_name"] == project.name]

        lines = [
            f"{icon} *{project.name}*",
            f"\u251c Path: `{project.path}`",
            f"\u251c Markers: {', '.join(project.markers)}",
        ]
        if active:
            s = active[0]
            mins = s["uptime_seconds"] // 60
            lines.append(f"\u251c Session: {_status_icon(s['status'])} Running ({mins}m)")
            lines.append(f"\u2514 tmux: `{s['tmux_session']}`")
        else:
            lines.append(f"\u2514 Session: \u2014 None")

        has_git = ".git" in project.markers
        launch_row = [InlineKeyboardButton("\U0001f680 Launch", callback_data=f"p:rc:{slug}")]
        if has_git:
            launch_row.append(InlineKeyboardButton("\U0001f9ea Experiment", callback_data=f"p:ex:{slug}"))
        keyboard = InlineKeyboardMarkup([
            launch_row,
            [InlineKeyboardButton("\U0001f4c2 Projects", callback_data="p:l:0"),
             InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
        ])
        await query.edit_message_text(
            "\n".join(lines), reply_markup=keyboard, parse_mode="Markdown",
        )

    elif action in ("rc", "ex"):
        slug = parts[2]
        experiment = action == "ex"
        project = project_scanner.get_project(slug)
        if not project:
            await query.edit_message_text("Project not found.")
            return
        session = await session_manager.start_session(project.path, project.name, experiment=experiment)
        mode = "\U0001f9ea Experiment" if experiment else "\U0001f680 Launch"
        await query.edit_message_text(
            f"{mode} *started:* {project.name}\n\n"
            f"\u26a1 Status: Connecting...\n"
            f"\U0001f4bb `tmux attach -t {session.tmux_session}`\n"
            f"\U0001f4f1 Open Claude Code app to connect",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\u26a1 Sessions", callback_data="s:l"),
                 InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
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
                "\u26a1 *Sessions*\n\nNo active sessions.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
                ]),
            )
            return

        buttons = []
        text_lines = [f"\u26a1 *Active Sessions* ({len(sessions)})\n"]
        for s in sessions:
            mins = s["uptime_seconds"] // 60
            icon = _status_icon(s["status"])
            text_lines.append(
                f"{icon} *{s['project_name']}* \u00b7 {mins}m\n"
                f"    `{s['tmux_session']}`"
            )
            buttons.append([
                InlineKeyboardButton(
                    f"\U0001f6d1 Stop {s['project_name']}",
                    callback_data=f"s:k:{s['session_id']}",
                )
            ])
        buttons.append([InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")])

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
                f"\u2705 Sent '{response}' to session.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\u26a1 Sessions", callback_data="s:l"),
                     InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
                ]),
            )
        else:
            await query.edit_message_text(
                "\u274c Session not found or no longer blocked.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
                ]),
            )

    elif action == "tr":
        session_id = parts[2]
        info = _dead_session_info.pop(session_id, None)
        if not info or "project_path" not in info:
            await query.edit_message_text(
                "\u274c Could not find project info for retry.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
                ]),
            )
            return

        await query.edit_message_text(
            f"\U0001f513 Trusting workspace for *{info['project_name']}*...",
            parse_mode="Markdown",
        )

        try:
            session = await session_manager.trust_and_launch(
                info["project_path"], info["project_name"]
            )
            await query.edit_message_text(
                f"\U0001f680 *Session started:* {info['project_name']}\n\n"
                f"\u26a1 Status: Connecting...\n"
                f"\U0001f4bb `tmux attach -t {session.tmux_session}`\n"
                f"\U0001f4f1 Open Claude Code app to connect",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\u26a1 Sessions", callback_data="s:l"),
                     InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
                ]),
            )
        except Exception as e:
            logger.error(f"Trust & retry failed: {e}")
            await query.edit_message_text(
                f"\u274c Trust & retry failed.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
                ]),
            )

    elif action == "k":
        session_id = parts[2]
        stopped = await session_manager.stop_session(session_id)
        msg = "\u2705 Session stopped." if stopped else "\u274c Session not found."
        await query.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\u26a1 Sessions", callback_data="s:l"),
                 InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
            ]),
        )


# --- Scaffold ---

async def _handle_scaffold(query, data: str, context):
    parts = data.split(":")
    action = parts[1]

    if action == "l":
        templates = list_templates()
        _TEMPLATE_ICONS = {
            "android": "\U0001f4f1", "cli_python": "\U0001f40d",
            "website": "\U0001f310", "cloud_terraform": "\u2601\ufe0f",
            "hybrid": "\U0001f504", "fastapi": "\u26a1",
        }
        buttons = []
        for t in templates:
            icon = _TEMPLATE_ICONS.get(t["key"], "\U0001f4c4")
            buttons.append([InlineKeyboardButton(
                f"{icon} {t['name']}", callback_data=f"sc:t:{t['key']}",
            )])
        buttons.append([InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")])
        await query.edit_message_text(
            "\u2795 *New Project* \u2014 Select a template:",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown",
        )

    elif action == "t":
        template_key = parts[2]
        context.user_data["scaffold_template"] = template_key
        await query.edit_message_text(
            f"\U0001f4dd Template: *{template_key}*\n\nSend the project name as a text message.",
            parse_mode="Markdown",
        )


@require_paired
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    template = context.user_data.get("scaffold_template")
    if not template:
        return

    name = update.message.text.strip()
    del context.user_data["scaffold_template"]

    result = create_project(template, name)
    if "error" in result:
        await update.message.reply_text(f"\u274c {result['error']}")
        return

    # Invalidate project cache so the new project is immediately discoverable
    project_scanner.scan_projects(force=True)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001f680 Launch Claude RC", callback_data=f"p:rc:{result['slug']}")],
        [InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
    ])
    await update.message.reply_text(
        f"\u2705 *Project created:* {result['name']}\n"
        f"\U0001f4c2 `{result['path']}`",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


# --- Maintenance ---

async def _handle_maintenance(query, data: str):
    parts = data.split(":")
    action = parts[1]

    if action == "l":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001f4ca System Status", callback_data="m:status")],
            [InlineKeyboardButton("\U0001f4c1 Git Status", callback_data="m:git"),
             InlineKeyboardButton("\u2b07\ufe0f Git Pull All", callback_data="m:pull")],
            [InlineKeyboardButton("\U0001f9f9 Cleanup", callback_data="m:clean"),
             InlineKeyboardButton("\U0001f4cb Processes", callback_data="m:proc")],
            [InlineKeyboardButton("\U0001f4a4 Sleep", callback_data="m:pw:sleep"),
             InlineKeyboardButton("\U0001f504 Restart", callback_data="m:pw:restart")],
            [InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
        ])
        await query.edit_message_text(
            "\U0001f527 *System Maintenance*",
            reply_markup=keyboard, parse_mode="Markdown",
        )

    elif action == "status":
        status = await _run_blocking(system_info.get_system_status)
        bat = status.get("battery", {})
        bat_line = f"\U0001f50b Battery: {bat['percent']}% {'(charging)' if bat['charging'] else ''}\n" if bat.get("available") else ""
        uptime_h = status["uptime_seconds"] // 3600
        uptime_m = (status["uptime_seconds"] % 3600) // 60

        text = (
            f"\U0001f4ca *System Status*\n\n"
            f"\U0001f4bb CPU: {status['cpu']['percent']}% ({status['cpu']['cores']} cores)\n"
            f"\U0001f4be RAM: {status['memory']['used_gb']}/{status['memory']['total_gb']} GB ({status['memory']['percent']}%)\n"
            f"\U0001f4bd Disk: {status['disk']['used_gb']}/{status['disk']['total_gb']} GB ({status['disk']['percent']}%)\n"
            f"{bat_line}"
            f"\u23f1 Uptime: {uptime_h}h {uptime_m}m\n"
            f"\U0001f5a5 Host: {status['hostname']}"
        )
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f527 Maintenance", callback_data="m:l"),
                 InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
            ]),
        )

    elif action == "git":
        from services.git_ops import check_all_status
        repos = await _run_blocking(check_all_status)
        lines = ["\U0001f4c1 *Git Status*\n"]
        for r in repos[:20]:
            icon = "\u2705" if r["clean"] else f"\u270f\ufe0f {r['changes']}"
            lines.append(f"{icon} {r['name']} `[{r['branch']}]`")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f527 Maintenance", callback_data="m:l")],
            ]),
        )

    elif action == "pull":
        from services.git_ops import pull_all
        await query.edit_message_text("\u2b07\ufe0f Pulling all repos...")
        results = await _run_blocking(pull_all)
        lines = ["\u2b07\ufe0f *Git Pull All*\n"]
        for r in results[:20]:
            lines.append(f"\u2022 {r['name']}: {r['result'][:50]}")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f527 Maintenance", callback_data="m:l")],
            ]),
        )

    elif action == "clean":
        from services.cleanup import run_cleanup
        await query.edit_message_text("\U0001f9f9 Running cleanup...")
        result = await _run_blocking(run_cleanup, ["brew", "pip", "logs"])
        lines = ["\U0001f9f9 *Cleanup Results*\n"]
        for k, v in result.items():
            lines.append(f"\u2022 {k}: {str(v)[:80]}")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f527 Maintenance", callback_data="m:l")],
            ]),
        )

    elif action == "proc":
        from services.process_manager import get_top_processes
        procs = await _run_blocking(get_top_processes, 10)
        lines = ["\U0001f4cb *Top Processes*\n"]
        for p in procs:
            lines.append(f"`{p['pid']:>6}` {p['name'][:20]:20s} CPU:{p['cpu_percent']:5.1f}% MEM:{p['memory_percent']:5.1f}%")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f527 Maintenance", callback_data="m:l")],
            ]),
        )

    elif action == "pw":
        power_action = parts[2]
        import subprocess
        cmds = {"sleep": ["pmset", "sleepnow"], "restart": ["sudo", "shutdown", "-r", "now"]}
        cmd = cmds.get(power_action)
        if cmd:
            icons = {"sleep": "\U0001f4a4", "restart": "\U0001f504"}
            await query.edit_message_text(f"{icons.get(power_action, '')} Executing {power_action}...")
            subprocess.Popen(cmd)
