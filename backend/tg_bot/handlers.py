from __future__ import annotations

import asyncio
import logging
import re as _re
from functools import wraps
from pathlib import Path
from typing import Callable, Dict, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from tg_bot.pairing import is_paired, verify_pairing_code, unpair_user, get_paired_users
from services.machine_registry import get_registry

logger = logging.getLogger(__name__)

# Reference to the telegram bot app, set during startup
_bot_app = None
# Cache project info for dead sessions (so Trust & Retry can find the path)
_dead_session_info = {}  # type: Dict[str, Dict]
_MAX_DEAD_SESSION_CACHE = 50

ITEMS_PER_PAGE = 8

_TEMPLATE_ICONS = {
    "android": "\U0001f4f1", "cli_python": "\U0001f40d",
    "website": "\U0001f310", "cloud_terraform": "\u2601\ufe0f",
    "hybrid": "\U0001f504", "fastapi": "\u26a1",
}

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


def _get_machine(machine_id: str = "local"):
    """Get a MachineClient by id. Defaults to local."""
    return get_registry().get_machine(machine_id)


def _resolve_machine(parts, idx=2):
    """Parse machine_id and payload from callback parts with backward compat.

    Returns (machine, machine_id, payload) where payload is the next part after machine_id.
    If parts[idx] isn't a known machine, treats it as the payload and falls back to local.
    """
    mid = parts[idx] if len(parts) > idx else "local"
    payload = parts[idx + 1] if len(parts) > idx + 1 else mid
    machine = _get_machine(mid)
    if not machine:
        payload = mid
        mid = "local"
        machine = _get_machine("local")
    return machine, mid, payload


def _machine_label(machine_id: str, multi: bool) -> str:
    """Short label for multi-machine display."""
    if not multi:
        return ""
    m = _get_machine(machine_id)
    return f"[{m.name}] " if m else ""


def _is_multi_machine() -> bool:
    return len(get_registry().list_machines()) > 1


# --- Notifications ---

async def _notify_session(
    machine_id: str, machine_name: str, session_id: str,
    project_name: str, prompt_text: str, status: str = "", project_path: str = "",
):
    """Unified notification for session state changes (local or remote)."""
    if not _bot_app:
        return

    clean = _clean_ansi(prompt_text).strip()[:500]
    prefix = f"\U0001f5a5 *[{machine_name}]*\n" if _is_multi_machine() else ""

    is_trust = clean.startswith("[TRUST]")
    is_worktree = clean.startswith("[WORKTREE]")
    is_error = clean.startswith("[EXITED]") or status == "dead"

    if is_trust:
        clean = clean[7:].strip()
        # Evict oldest if cache is full
        if len(_dead_session_info) >= _MAX_DEAD_SESSION_CACHE:
            oldest = next(iter(_dead_session_info))
            del _dead_session_info[oldest]
        _dead_session_info[session_id] = {
            "project_name": project_name,
            "project_path": project_path,
            "machine_id": machine_id,
        }
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001f513 Trust & Retry", callback_data=f"s:tr:{machine_id}:{session_id}")],
            [InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
        ])
        text = prefix + f"\u26a0\ufe0f *Workspace not trusted:* {project_name}\n\nTrust this workspace and retry?"
    elif is_worktree:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
        ])
        text = prefix + f"\U0001f9ea *Experiment not available:* {project_name}\n\nNot a git repository. Use Launch instead."
    elif is_error:
        clean = clean[8:].strip() if clean.startswith("[EXITED]") else clean
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
        ])
        text = prefix + f"\u274c *Session failed:* {project_name}\n\n```\n{clean}\n```"
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("\u2705 Approve", callback_data=f"s:y:{machine_id}:{session_id}"),
             InlineKeyboardButton("\u274c Deny", callback_data=f"s:n:{machine_id}:{session_id}")],
            [InlineKeyboardButton("\U0001f6d1 Stop", callback_data=f"s:k:{machine_id}:{session_id}")],
        ])
        text = prefix + f"\u23f8\ufe0f *Session blocked:* {project_name}\n\n```\n{clean}\n```\n\nApprove or deny?"

    for user_id in get_paired_users():
        try:
            await _bot_app.bot.send_message(
                chat_id=user_id, text=text,
                parse_mode="Markdown", reply_markup=keyboard,
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")


async def notify_blocked_session(session_id: str, project_name: str, prompt_text: str, project_path: str = ""):
    """Local session notification (called by session_manager callback)."""
    local = _get_machine("local")
    await _notify_session("local", local.name if local else "local", session_id, project_name, prompt_text, project_path=project_path)


async def notify_remote_session(
    machine_id: str, machine_name: str, session_id: str,
    project_name: str, prompt_text: str, status: str, project_path: str = "",
):
    """Remote session notification (called by session_poller)."""
    await _notify_session(machine_id, machine_name, session_id, project_name, prompt_text, status, project_path)


async def notify_machine_discovered(machine_id: str, name: str, url: str):
    """Notification when a new CCL node is discovered on the tailnet."""
    if not _bot_app:
        return

    text = (
        f"\U0001f50d *New machine discovered*\n\n"
        f"\U0001f5a5 *{name}*\n"
        f"\U0001f310 `{url}`\n\n"
        f"Approve this machine?"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("\u2705 Approve", callback_data=f"mc:approve:{machine_id}"),
         InlineKeyboardButton("\u274c Deny", callback_data=f"mc:deny:{machine_id}")],
    ])

    for user_id in get_paired_users():
        try:
            await _bot_app.bot.send_message(
                chat_id=user_id, text=text,
                parse_mode="Markdown", reply_markup=keyboard,
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id} about discovery: {e}")


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
        machine = _get_machine("local")
        try:
            s = await machine.get_settings()
            configured = s.get("configured", False)
        except Exception:
            configured = False
        if configured:
            await update.message.reply_text("\u2705 Paired successfully! Send /start to begin.")
        else:
            await _send_onboarding(update.message)
    else:
        await update.message.reply_text("\u274c Invalid or expired pairing code.")


@require_paired
async def cmd_unpair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    unpair_user(update.effective_user.id)
    await update.message.reply_text("\U0001f513 Unpaired.")


# --- Manual Machine Addition (fallback without Tailscale) ---

@require_paired
async def cmd_addmachine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /addmachine <ip_or_url>  — manually add a CCL node."""
    if not context.args:
        await update.message.reply_text(
            "Usage: /addmachine <ip\\_or\\_url>\n\n"
            "Example: `/addmachine 192.168.1.50`\n"
            "Example: `/addmachine http://100.64.0.5:8420`",
            parse_mode="Markdown",
        )
        return

    target = context.args[0]

    # Extract IP/hostname from input
    import ipaddress
    import re as _probe_re
    if target.startswith("http"):
        match = _probe_re.search(r"https?://([^:/]+)", target)
        ip_str = match.group(1) if match else target
    else:
        ip_str = target

    # Validate it's a proper IP, not a hostname (prevents SSRF via DNS)
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        await update.message.reply_text(
            "\u274c Please provide an IP address, not a hostname.",
        )
        return

    # Block link-local, loopback, and cloud metadata IPs
    if addr.is_loopback or addr.is_link_local or addr.is_multicast:
        await update.message.reply_text("\u274c Invalid IP address range.")
        return

    registry = get_registry()
    target_url = f"http://{ip_str}:8420"
    if registry.is_known_url(target_url):
        await update.message.reply_text("\u26a0\ufe0f This machine is already registered.")
        return

    # Probe the target
    try:
        from services.discovery import probe_peer
        url, health = await probe_peer(ip_str)
    except Exception:
        await update.message.reply_text(
            f"\u274c Could not reach CCL at `{target}`\n\nMake sure the node is running.",
            parse_mode="Markdown",
        )
        return

    name = health.get("machine_name", ip)
    mid = registry.add_pending(name, url)
    await update.message.reply_text(
        f"\U0001f50d Found *{name}* at `{url}`\n\nApprove?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\u2705 Approve", callback_data=f"mc:approve:{mid}"),
             InlineKeyboardButton("\u274c Deny", callback_data=f"mc:deny:{mid}")],
        ]),
    )


# --- Onboarding (always targets local/hub machine) ---

async def _send_onboarding(message):
    """First-time setup wizard after pairing."""
    machine = _get_machine("local")
    try:
        s = await machine.get_settings()
        claude = s.get("claude", {})
        dirs = await machine.detect_dirs()
    except Exception:
        claude = {"installed": False, "path": "?"}
        dirs = []

    lines = [
        "\u2705 *Paired!* Let's set up your launcher.\n",
        "\U0001f4bb *Claude CLI:* " + ("`" + str(claude.get("version", "?")) + "`" if claude.get("installed") else "\u274c Not found at " + str(claude.get("path", "?"))),
        "",
        "\U0001f4c2 *Detected project directories:*",
    ]

    buttons = []
    for d in dirs:
        lines.append(f"\u2022 `{d['path']}` ({d['project_count']} folders)")
        buttons.append([InlineKeyboardButton(
            f"\u2795 {d['path']}", callback_data=f"ob:add:{d['path'][:50]}",
        )])

    if not dirs:
        lines.append("\u2014 No common directories found")

    lines.append("\nSelect directories to scan for projects:")
    buttons.append([InlineKeyboardButton("\u2795 Add custom path", callback_data="ob:custom")])
    buttons.append([InlineKeyboardButton("\u2705 Done", callback_data="ob:done")])

    await message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _handle_onboarding(query, data: str, context):
    parts = data.split(":", 2)
    action = parts[1]
    machine = _get_machine("local")

    if action == "add":
        path = parts[2]
        try:
            result = await machine.update_project_root("add", path)
            added = result.get("success", False)
            roots = result.get("project_roots", [])
        except Exception:
            added = False
            roots = []

        try:
            projects = await machine.list_projects()
        except Exception:
            projects = []

        lines = [
            f"\u2705 Added `{path}`\n" if added else f"\u26a0\ufe0f Already added or not found\n",
            f"\U0001f4c2 *Configured paths:* ({len(roots)})",
        ]
        for r in roots:
            lines.append(f"\u2022 `{r}`")
        lines.append(f"\n\U0001f50d Found *{len(projects)}* projects")

        try:
            dirs = await machine.detect_dirs()
        except Exception:
            dirs = []
        buttons = []
        for d in dirs:
            if d["path"] not in roots:
                buttons.append([InlineKeyboardButton(
                    f"\u2795 {d['path']}", callback_data=f"ob:add:{d['path'][:50]}",
                )])
        buttons.append([InlineKeyboardButton("\u2795 Add custom path", callback_data="ob:custom")])
        buttons.append([InlineKeyboardButton("\u2705 Done \u2014 go to menu", callback_data="ob:done")])

        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    elif action == "custom":
        context.user_data["awaiting_custom_path"] = True
        await query.edit_message_text(
            "\U0001f4c2 Send the full path to your project directory as a text message.\n\n"
            "Example: `/Users/me/Projects`",
            parse_mode="Markdown",
        )

    elif action == "done":
        try:
            s = await machine.get_settings()
            configured = s.get("configured", False)
        except Exception:
            configured = False
        if not configured:
            try:
                dirs = await machine.detect_dirs()
                for d in dirs:
                    await machine.update_project_root("add", d["path"])
            except Exception:
                pass

        text, session_count = await _build_menu_text()
        await query.edit_message_text(
            text, reply_markup=_menu_keyboard(session_count), parse_mode="Markdown",
        )

    elif action == "rm":
        path = parts[2]
        try:
            await machine.update_project_root("remove", path)
        except Exception:
            pass
        await _show_settings(query)

    elif action == "detect":
        try:
            dirs = await machine.detect_dirs()
            s = await machine.get_settings()
            roots = s.get("project_roots", [])
            for d in dirs:
                if d["path"] not in roots:
                    await machine.update_project_root("add", d["path"])
        except Exception:
            pass
        await _show_settings(query)

    elif action == "rescan":
        # Rescan is implicit — projects are re-fetched on list
        await _show_settings(query)


async def _show_settings(query):
    """Show the settings/configuration screen."""
    machine = _get_machine("local")
    try:
        s = await machine.get_settings()
        roots = s.get("project_roots", [])
        claude = s.get("claude", {})
        projects = await machine.list_projects()
    except Exception:
        roots = []
        claude = {}
        projects = []

    lines = [
        "\u2699\ufe0f *Settings*\n",
        "\U0001f4bb Claude CLI: " + ("`" + str(claude.get("version", "?")) + "`" if claude.get("installed") else "\u274c Not found"),
        f"\U0001f50d {len(projects)} projects found\n",
        "\U0001f4c2 *Project directories:*",
    ]
    buttons = []
    for r in roots:
        lines.append(f"\u2022 `{r}`")
        buttons.append([InlineKeyboardButton(f"\u274c Remove {r}", callback_data=f"ob:rm:{r[:50]}")])

    if not roots:
        lines.append("\u2014 None configured")

    try:
        dirs = await machine.detect_dirs()
    except Exception:
        dirs = []
    untracked = [d for d in dirs if d["path"] not in roots]
    if untracked:
        buttons.append([InlineKeyboardButton(
            f"\u2795 Add detected dirs ({len(untracked)})", callback_data="ob:detect",
        )])
    buttons.append([InlineKeyboardButton("\u2795 Add custom path", callback_data="ob:custom")])
    buttons.append([InlineKeyboardButton("\U0001f504 Re-scan projects", callback_data="ob:rescan")])
    buttons.append([InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")])

    await query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# --- Helpers for aggregated data ---

async def _aggregate_from_machines(method_name: str) -> list:
    """Fetch data from all online machines concurrently, tag with machine info."""
    machines = get_registry().list_online_machines()

    async def fetch(m):
        try:
            items = await getattr(m, method_name)()
            for item in items:
                item["_machine_id"] = m.machine_id
                item["_machine_name"] = m.name
            return items
        except Exception:
            return []

    results = await asyncio.gather(*[fetch(m) for m in machines])
    return [item for batch in results for item in batch]


async def _all_sessions() -> list:
    return await _aggregate_from_machines("list_sessions")


async def _all_projects() -> list:
    return await _aggregate_from_machines("list_projects")


async def _await_job(machine, job_id: str, max_polls: int = 30, interval: float = 2.0):
    """Poll a background job until completion."""
    job = None
    for _ in range(max_polls):
        await asyncio.sleep(interval)
        job = await machine.get_job(job_id)
        if job and job.get("status") != "running":
            break
    return job


# --- Main Menu ---

async def _build_menu_text():
    """Returns (text, session_count) tuple to avoid double-fetching."""
    registry = get_registry()
    multi = _is_multi_machine()
    cpu = ram = "?"
    bat_str = ""

    # Fetch sessions from all machines concurrently (reuse for count)
    all_sessions = await _all_sessions()
    all_projects = await _all_projects()

    try:
        status = await _get_machine("local").get_system_status()
        cpu = f"{status['cpu']['percent']}%"
        ram = f"{status['memory']['percent']}%"
        bat = status.get("battery", {})
        bat_str = f" \u00b7 \U0001f50b {bat['percent']}%" if bat.get("available") else ""
    except Exception:
        pass

    machine_count = len(registry.list_machines())
    machine_line = f"\U0001f5a5 {machine_count} machines \u00b7 " if multi else ""

    text = (
        f"\U0001f5a5 *Claude Code Launcher*\n\n"
        f"{machine_line}\U0001f4c2 {len(all_projects)} projects \u00b7 \u26a1 {len(all_sessions)} active sessions\n"
        f"\U0001f4bb CPU {cpu} \u00b7 RAM {ram}{bat_str}"
    )
    return text, len(all_sessions)


def _menu_keyboard(session_count: int = 0) -> InlineKeyboardMarkup:
    sess_label = f"\u26a1 Sessions ({session_count})" if session_count else "\u26a1 Sessions"
    rows = [
        [InlineKeyboardButton("\U0001f4c2 Projects", callback_data="p:l:0"),
         InlineKeyboardButton("\u2795 New Project", callback_data="sc:l")],
        [InlineKeyboardButton(sess_label, callback_data="s:l"),
         InlineKeyboardButton("\U0001f527 Maintenance", callback_data="m:l")],
    ]
    if _is_multi_machine():
        machines = get_registry().list_machines()
        rows.append([InlineKeyboardButton(
            f"\U0001f5a5 Machines ({len(machines)})", callback_data="mc:l",
        )])
    rows.append([InlineKeyboardButton("\u2699\ufe0f Settings", callback_data="ob:settings")])
    return InlineKeyboardMarkup(rows)


@require_paired
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, session_count = await _build_menu_text()
    await update.effective_message.reply_text(
        text, reply_markup=_menu_keyboard(session_count), parse_mode="Markdown",
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
        await _handle_maintenance(query, data, context)
    elif data.startswith("mc:"):
        await _handle_machines(query, data)
    elif data.startswith("t:"):
        await _handle_terminal(query, data)
    elif data.startswith("ob:"):
        if data == "ob:settings":
            await _show_settings(query)
        else:
            await _handle_onboarding(query, data, context)
    elif data == "menu":
        text, session_count = await _build_menu_text()
        await query.edit_message_text(
            text, reply_markup=_menu_keyboard(session_count), parse_mode="Markdown",
        )


# --- Machines ---

async def _handle_machines(query, data: str):
    parts = data.split(":")
    action = parts[1]
    registry = get_registry()

    if action == "l":
        machines = registry.list_machines()
        pending = registry.list_pending()

        lines = ["\U0001f5a5 *Machines*\n"]
        buttons = []

        for m in machines:
            icon = "\U0001f7e2" if m.online else "\U0001f534"
            lines.append(f"{icon} *{m.name}* \u2014 `{m.base_url}`")
            buttons.append([InlineKeyboardButton(
                f"{icon} {m.name}", callback_data=f"mc:d:{m.machine_id}",
            )])

        if pending:
            lines.append("\n\u23f3 *Pending approval:*")
            for p in pending:
                lines.append(f"\u2022 {p['name']} ({p['url']})")
                buttons.append([
                    InlineKeyboardButton(f"\u2705 {p['name']}", callback_data=f"mc:approve:{p['id']}"),
                    InlineKeyboardButton("\u274c", callback_data=f"mc:deny:{p['id']}"),
                ])

        buttons.append([InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")])

        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    elif action == "d":
        mid = parts[2]
        machine = registry.get_machine(mid)
        if not machine:
            await query.edit_message_text("Machine not found.")
            return

        icon = "\U0001f7e2" if machine.online else "\U0001f534"
        lines = [
            f"{icon} *{machine.name}*",
            f"\U0001f310 `{machine.base_url}`",
        ]

        if machine.online:
            try:
                status = await machine.get_system_status()
                lines.append(f"\U0001f4bb CPU: {status['cpu']['percent']}% \u00b7 RAM: {status['memory']['percent']}%")
                bat = status.get("battery", {})
                if bat.get("available"):
                    lines.append(f"\U0001f50b Battery: {bat['percent']}%")
            except Exception:
                lines.append("\u26a0\ufe0f Could not fetch status")

            try:
                sessions = await machine.list_sessions()
                projects = await machine.list_projects()
                lines.append(f"\U0001f4c2 {len(projects)} projects \u00b7 \u26a1 {len(sessions)} sessions")
            except Exception:
                pass

        buttons = [
            [InlineKeyboardButton("\U0001f4c2 Projects", callback_data=f"p:l:0:{mid}"),
             InlineKeyboardButton("\u26a1 Sessions", callback_data=f"s:l:{mid}")],
            [InlineKeyboardButton("\U0001f527 Maintenance", callback_data=f"m:l:{mid}")],
        ]
        if mid != "local":
            buttons.append([InlineKeyboardButton("\U0001f5d1 Remove", callback_data=f"mc:rm:{mid}")])
        buttons.append([InlineKeyboardButton("\U0001f5a5 Machines", callback_data="mc:l"),
                        InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")])

        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    elif action == "approve":
        mid = parts[2]
        try:
            client = await registry.approve(mid)
            if client:
                await query.edit_message_text(
                    f"\u2705 *Machine approved:* {client.name}\n\nNow tracking this machine.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("\U0001f5a5 Machines", callback_data="mc:l"),
                         InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
                    ]),
                )
            else:
                await query.edit_message_text(
                    "\u274c Approval failed. Machine may already be paired with another hub.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("\U0001f5a5 Machines", callback_data="mc:l")],
                    ]),
                )
        except Exception as e:
            logger.error(f"Machine approval failed: {e}")
            await query.edit_message_text(
                f"\u274c Approval failed: could not reach machine.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001f5a5 Machines", callback_data="mc:l")],
                ]),
            )

    elif action == "deny":
        mid = parts[2]
        registry.reject(mid)
        await query.edit_message_text(
            "\u274c Machine rejected.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f5a5 Machines", callback_data="mc:l")],
            ]),
        )

    elif action == "rm":
        mid = parts[2]
        machine = registry.get_machine(mid)
        name = machine.name if machine else mid
        await registry.remove(mid)
        await query.edit_message_text(
            f"\U0001f5d1 Removed *{name}*.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f5a5 Machines", callback_data="mc:l"),
                 InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
            ]),
        )


# --- Projects ---

async def _handle_projects(query, data: str):
    parts = data.split(":")
    action = parts[1]

    if action == "l":
        page = int(parts[2]) if len(parts) > 2 else 0
        # Optional machine filter: p:l:0:machine_id
        machine_id = parts[3] if len(parts) > 3 else None

        if machine_id:
            machine = _get_machine(machine_id)
            if not machine:
                await query.edit_message_text("Machine not found.")
                return
            try:
                projects = await machine.list_projects()
                for p in projects:
                    p["_machine_id"] = machine_id
                sessions = await machine.list_sessions()
            except Exception:
                await query.edit_message_text("Could not reach machine.")
                return
        else:
            projects = await _all_projects()
            sessions = await _all_sessions()

        active_projects = set()
        for s in sessions:
            key = (s.get("_machine_id", "local"), s.get("project_name", ""))
            active_projects.add(key)

        start = page * ITEMS_PER_PAGE
        page_projects = projects[start:start + ITEMS_PER_PAGE]
        multi = _is_multi_machine()

        buttons = []
        for i in range(0, len(page_projects), 2):
            row = []
            for p in page_projects[i:i + 2]:
                icon = _project_icon(p.get("markers", []))
                mid = p.get("_machine_id", "local")
                active = " \u26a1" if (mid, p["name"]) in active_projects else ""
                label_prefix = f"[{p.get('_machine_name', '')[:6]}] " if multi else ""
                row.append(InlineKeyboardButton(
                    f"{icon} {label_prefix}{p['name']}{active}",
                    callback_data=f"p:d:{mid}:{p['slug']}",
                ))
            buttons.append(row)

        nav = []
        if page > 0:
            cb = f"p:l:{page - 1}" + (f":{machine_id}" if machine_id else "")
            nav.append(InlineKeyboardButton("\u25c0 Prev", callback_data=cb))
        if start + ITEMS_PER_PAGE < len(projects):
            cb = f"p:l:{page + 1}" + (f":{machine_id}" if machine_id else "")
            nav.append(InlineKeyboardButton("Next \u25b6", callback_data=cb))
        if nav:
            buttons.append(nav)
        buttons.append([InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")])

        total_pages = max(1, (len(projects) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        await query.edit_message_text(
            f"\U0001f4c2 *Projects* ({len(projects)}) \u00b7 Page {page + 1}/{total_pages}",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown",
        )

    elif action == "d":
        # p:d:machine_id:slug
        machine, mid, slug = _resolve_machine(parts)

        try:
            project = await machine.get_project(slug)
        except Exception:
            project = None
        if not project:
            await query.edit_message_text("Project not found.")
            return

        icon = _project_icon(project.get("markers", []))
        label = _machine_label(mid, _is_multi_machine())

        try:
            sessions = await machine.list_sessions()
        except Exception:
            sessions = []
        active = [s for s in sessions if s.get("project_name") == project["name"]]

        lines = [
            f"{icon} *{label}{project['name']}*",
            f"\u251c Path: `{project['path']}`",
            f"\u251c Markers: {', '.join(project.get('markers', []))}",
        ]
        if active:
            s = active[0]
            mins = s.get("uptime_seconds", 0) // 60
            lines.append(f"\u251c Session: {_status_icon(s['status'])} Running ({mins}m)")
            lines.append(f"\u2514 tmux: `{s.get('tmux_session', '')}`")
        else:
            lines.append(f"\u2514 Session: \u2014 None")

        has_git = ".git" in project.get("markers", [])
        launch_row = [InlineKeyboardButton("\U0001f680 Launch", callback_data=f"p:rc:{mid}:{slug}")]
        if has_git:
            launch_row.append(InlineKeyboardButton("\U0001f9ea Experiment", callback_data=f"p:ex:{mid}:{slug}"))
        keyboard = InlineKeyboardMarkup([
            launch_row,
            [InlineKeyboardButton("\U0001f5a5 Terminal", callback_data=f"t:new:{mid}:{slug}")],
            [InlineKeyboardButton("\U0001f4c2 Projects", callback_data="p:l:0"),
             InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
        ])
        await query.edit_message_text(
            "\n".join(lines), reply_markup=keyboard, parse_mode="Markdown",
        )

    elif action in ("rc", "ex"):
        # p:rc:machine_id:slug
        machine, mid, slug = _resolve_machine(parts)

        experiment = action == "ex"
        try:
            session = await machine.start_session(slug, experiment=experiment)
        except Exception as e:
            await query.edit_message_text(f"\u274c Failed to start session: {e}")
            return

        label = _machine_label(mid, _is_multi_machine())
        mode = "\U0001f9ea Experiment" if experiment else "\U0001f680 Launch"
        await query.edit_message_text(
            f"{mode} *started:* {label}{slug}\n\n"
            f"\u26a1 Status: Connecting...\n"
            f"\U0001f4bb `tmux attach -t {session.get('tmux_session', '?')}`\n"
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
        # Optional: s:l:machine_id
        machine_id = parts[2] if len(parts) > 2 else None

        if machine_id:
            machine = _get_machine(machine_id)
            if not machine:
                await query.edit_message_text("Machine not found.")
                return
            try:
                sessions = await machine.list_sessions()
                for s in sessions:
                    s["_machine_id"] = machine_id
                    s["_machine_name"] = machine.name
            except Exception:
                await query.edit_message_text("Could not reach machine.")
                return
        else:
            sessions = await _all_sessions()

        if not sessions:
            await query.edit_message_text(
                "\u26a1 *Sessions*\n\nNo active sessions.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
                ]),
            )
            return

        multi = _is_multi_machine()
        buttons = []
        text_lines = [f"\u26a1 *Active Sessions* ({len(sessions)})\n"]
        for s in sessions:
            mins = s.get("uptime_seconds", 0) // 60
            icon = _status_icon(s.get("status", ""))
            mid = s.get("_machine_id", "local")
            label = f"[{s.get('_machine_name', '')[:8]}] " if multi else ""
            text_lines.append(
                f"{icon} *{label}{s['project_name']}* \u00b7 {mins}m\n"
                f"    `{s.get('tmux_session', '')}`"
            )
            buttons.append([
                InlineKeyboardButton(
                    f"\U0001f5a5 Attach",
                    callback_data=f"t:att:{mid}:{s['session_id']}",
                ),
                InlineKeyboardButton(
                    f"\U0001f6d1 Stop",
                    callback_data=f"s:k:{mid}:{s['session_id']}",
                ),
            ])
        buttons.append([InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")])

        await query.edit_message_text(
            "\n".join(text_lines),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown",
        )

    elif action in ("y", "n"):
        # s:y:machine_id:session_id
        machine, mid, session_id = _resolve_machine(parts)

        response = "y" if action == "y" else "n"
        success = await machine.respond_to_prompt(session_id, response)
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
        # s:tr:machine_id:session_id
        mid = parts[2]
        session_id = parts[3] if len(parts) > 3 else parts[2]
        info = _dead_session_info.pop(session_id, None)
        if not info or "project_path" not in info:
            await query.edit_message_text(
                "\u274c Could not find project info for retry.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
                ]),
            )
            return

        machine_id = info.get("machine_id", mid)
        machine = _get_machine(machine_id)
        if not machine:
            machine = _get_machine("local")

        await query.edit_message_text(
            f"\U0001f513 Trusting workspace for *{info['project_name']}*...",
            parse_mode="Markdown",
        )

        try:
            session = await machine.trust_and_launch(
                info["project_path"], info["project_name"]
            )
            await query.edit_message_text(
                f"\U0001f680 *Session started:* {info['project_name']}\n\n"
                f"\u26a1 Status: Connecting...\n"
                f"\U0001f4bb `tmux attach -t {session.get('tmux_session', '?')}`\n"
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
        # s:k:machine_id:session_id
        machine, mid, session_id = _resolve_machine(parts)

        stopped = await machine.stop_session(session_id)
        msg = "\u2705 Session stopped." if stopped else "\u274c Session not found."
        await query.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\u26a1 Sessions", callback_data="s:l"),
                 InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
            ]),
        )


# --- Terminal ---

async def _handle_terminal(query, data: str):
    parts = data.split(":")
    action = parts[1]

    if action == "new":
        # t:new:machine_id:slug
        machine, mid, slug = _resolve_machine(parts)

        await query.edit_message_text(f"\U0001f5a5 Starting terminal for *{slug}*...", parse_mode="Markdown")
        try:
            terminal = await machine.start_terminal(slug)
        except Exception as e:
            await query.edit_message_text(f"\u274c Terminal failed: {e}")
            return

        label = _machine_label(mid, _is_multi_machine())
        await query.edit_message_text(
            f"\U0001f5a5 *Terminal ready:* {label}{slug}\n\n"
            f"\U0001f517 `{terminal.get('url', '?')}`\n\n"
            f"\u23f1 Expires in 30 min or on disconnect\n"
            f"\U0001f4bb tmux: `{terminal.get('tmux_session', '?')}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f4c2 Projects", callback_data="p:l:0"),
                 InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
            ]),
        )

    elif action == "att":
        # t:att:machine_id:session_id
        machine, mid, session_id = _resolve_machine(parts)

        try:
            session = await machine.get_session(session_id)
        except Exception:
            session = None
        if not session:
            await query.edit_message_text("Session not found.")
            return

        project_name = session.get("project_name", "?")
        await query.edit_message_text(f"\U0001f5a5 Attaching to *{project_name}*...", parse_mode="Markdown")

        try:
            terminal = await machine.attach_terminal(session_id)
        except Exception as e:
            await query.edit_message_text(f"\u274c Terminal attach failed: {e}")
            return

        label = _machine_label(mid, _is_multi_machine())
        url = terminal.get("url", "?")
        # Try to extract plain URL (strip credentials if present)
        if "@" in url:
            plain_url = f"http://{url.split('@')[1]}"
        else:
            plain_url = url

        await query.edit_message_text(
            f"\U0001f5a5 *Terminal attached:* {label}{project_name}\n\n"
            f"\U0001f517 URL: `{plain_url}`\n"
            f"\U0001f511 Credential: `{terminal.get('credential', '?')}`\n\n"
            f"\u23f1 Expires in 30 min or on disconnect\n"
            f"\U0001f4bb tmux: `{session.get('tmux_session', '?')}`",
            parse_mode="Markdown",
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
        # Scaffold always on local machine
        machine = _get_machine("local")
        try:
            templates = await machine.list_templates()
        except Exception:
            templates = []

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
    machine = _get_machine("local")

    # Handle custom path input for settings
    if context.user_data.get("awaiting_custom_path"):
        del context.user_data["awaiting_custom_path"]
        path = update.message.text.strip()
        if Path(path).is_dir():
            try:
                await machine.update_project_root("add", path)
                projects = await machine.list_projects()
            except Exception:
                projects = []
            await update.message.reply_text(
                f"\u2705 Added `{path}`\n\U0001f50d Found *{len(projects)}* projects",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\u2699\ufe0f Settings", callback_data="ob:settings"),
                     InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
                ]),
            )
        else:
            await update.message.reply_text(
                f"\u274c Directory not found: `{path}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\u2699\ufe0f Settings", callback_data="ob:settings"),
                     InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
                ]),
            )
        return

    template = context.user_data.get("scaffold_template")
    if not template:
        return

    name = update.message.text.strip()
    del context.user_data["scaffold_template"]

    try:
        result = await machine.create_project(template, name)
    except Exception as e:
        await update.message.reply_text(f"\u274c {e}")
        return

    if "error" in result:
        await update.message.reply_text(f"\u274c {result['error']}")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001f680 Launch Claude RC", callback_data=f"p:rc:local:{result['slug']}")],
        [InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
    ])
    await update.message.reply_text(
        f"\u2705 *Project created:* {result['name']}\n"
        f"\U0001f4c2 `{result['path']}`",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


# --- Maintenance ---

async def _handle_maintenance(query, data: str, context):
    parts = data.split(":")
    action = parts[1]

    # Optional machine_id: m:l:machine_id
    mid = parts[2] if len(parts) > 2 and action == "l" else context.user_data.get("maint_machine", "local")

    if action == "l":
        context.user_data["maint_machine"] = mid
        machine = _get_machine(mid)
        if not machine:
            mid = "local"
            machine = _get_machine("local")

        label = f" \u2014 {machine.name}" if _is_multi_machine() else ""

        # Machine selector for multi-machine
        machine_buttons = []
        if _is_multi_machine():
            row = []
            for m in get_registry().list_online_machines():
                marker = "\u2705 " if m.machine_id == mid else ""
                row.append(InlineKeyboardButton(
                    f"{marker}{m.name}", callback_data=f"m:l:{m.machine_id}",
                ))
            machine_buttons = [row]

        keyboard = InlineKeyboardMarkup(machine_buttons + [
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
            f"\U0001f527 *System Maintenance*{label}",
            reply_markup=keyboard, parse_mode="Markdown",
        )

    elif action == "status":
        machine = _get_machine(mid)
        if not machine:
            machine = _get_machine("local")
        try:
            status = await machine.get_system_status()
        except Exception:
            await query.edit_message_text(
                "\u274c Could not reach machine.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("\U0001f527 Maintenance", callback_data="m:l")],
                ]),
            )
            return

        bat = status.get("battery", {})
        bat_line = f"\U0001f50b Battery: {bat['percent']}% {'(charging)' if bat.get('charging') else ''}\n" if bat.get("available") else ""
        uptime_h = status.get("uptime_seconds", 0) // 3600
        uptime_m = (status.get("uptime_seconds", 0) % 3600) // 60
        label = f" ({machine.name})" if _is_multi_machine() else ""

        text = (
            f"\U0001f4ca *System Status*{label}\n\n"
            f"\U0001f4bb CPU: {status['cpu']['percent']}% ({status['cpu']['cores']} cores)\n"
            f"\U0001f4be RAM: {status['memory']['used_gb']}/{status['memory']['total_gb']} GB ({status['memory']['percent']}%)\n"
            f"\U0001f4bd Disk: {status['disk']['used_gb']}/{status['disk']['total_gb']} GB ({status['disk']['percent']}%)\n"
            f"{bat_line}"
            f"\u23f1 Uptime: {uptime_h}h {uptime_m}m\n"
            f"\U0001f5a5 Host: {status.get('hostname', '?')}"
        )
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f527 Maintenance", callback_data="m:l"),
                 InlineKeyboardButton("\U0001f3e0 Menu", callback_data="menu")],
            ]),
        )

    elif action == "git":
        machine = _get_machine(mid)
        if not machine:
            machine = _get_machine("local")
        try:
            repos = await machine.git_status()
        except Exception:
            repos = []

        lines = ["\U0001f4c1 *Git Status*\n"]
        for r in repos[:20]:
            icon = "\u2705" if r.get("clean") else f"\u270f\ufe0f {r.get('changes', '?')}"
            lines.append(f"{icon} {r['name']} `[{r.get('branch', '?')}]`")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f527 Maintenance", callback_data="m:l")],
            ]),
        )

    elif action == "pull":
        machine = _get_machine(mid)
        if not machine:
            machine = _get_machine("local")
        await query.edit_message_text("\u2b07\ufe0f Pulling all repos...")
        try:
            job_id = await machine.git_pull_all()
            job = await _await_job(machine, job_id)
            result_text = "Pull completed."
            if job and job.get("result"):
                result = job["result"]
                if isinstance(result, list):
                    lines = ["\u2b07\ufe0f *Git Pull All*\n"]
                    for r in result[:20]:
                        lines.append(f"\u2022 {r.get('name', '?')}: {str(r.get('result', ''))[:50]}")
                    result_text = "\n".join(lines)
        except Exception:
            result_text = "\u274c Pull failed."

        await query.edit_message_text(
            result_text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f527 Maintenance", callback_data="m:l")],
            ]),
        )

    elif action == "clean":
        machine = _get_machine(mid)
        if not machine:
            machine = _get_machine("local")
        await query.edit_message_text("\U0001f9f9 Running cleanup...")
        try:
            job_id = await machine.run_cleanup(["brew", "pip", "logs"])
            job = await _await_job(machine, job_id)
            lines = ["\U0001f9f9 *Cleanup Results*\n"]
            if job and isinstance(job.get("result"), dict):
                for k, v in job["result"].items():
                    lines.append(f"\u2022 {k}: {str(v)[:80]}")
            result_text = "\n".join(lines)
        except Exception:
            result_text = "\u274c Cleanup failed."

        await query.edit_message_text(
            result_text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("\U0001f527 Maintenance", callback_data="m:l")],
            ]),
        )

    elif action == "proc":
        machine = _get_machine(mid)
        if not machine:
            machine = _get_machine("local")
        try:
            procs = await machine.get_processes(10)
        except Exception:
            procs = []

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
        machine = _get_machine(mid)
        if not machine:
            machine = _get_machine("local")
        icons = {"sleep": "\U0001f4a4", "restart": "\U0001f504"}
        label = f" on {machine.name}" if _is_multi_machine() else ""
        await query.edit_message_text(f"{icons.get(power_action, '')} Executing {power_action}{label}...")
        try:
            await machine.power(power_action)
        except Exception:
            pass
