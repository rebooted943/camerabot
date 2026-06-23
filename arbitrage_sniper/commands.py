"""Parsing of Telegram bot commands into structured actions.

Supported commands (sent as Telegram messages to the bot):
    /scan                 -> run a full scan of all tracked targets now
    /scan <query>         -> one-off scan for <query>
    /search <query>       -> alias of /scan <query>
    /add <query>          -> add <query> to the tracked targets (persisted)
    /remove <query|index> -> remove a tracked target
    /list                 -> list tracked targets
    /help, /start         -> show help
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Command:
    action: str  # scan_all | scan_query | add | remove | list | help | unknown
    arg: str = ""


HELP_TEXT = (
    "\U0001F3AF <b>ArbitrageSniper bot</b>\n"
    "Commands:\n"
    "\u2022 <code>/scan</code> \u2014 scan all tracked targets now\n"
    "\u2022 <code>/scan &lt;query&gt;</code> \u2014 one-off scan (e.g. <code>/scan fujifilm x-t50</code>)\n"
    "\u2022 <code>/search &lt;query&gt;</code> \u2014 same as <code>/scan &lt;query&gt;</code>\n"
    "\u2022 <code>/add &lt;query&gt;</code> \u2014 add a target to the watch list\n"
    "\u2022 <code>/remove &lt;query|#&gt;</code> \u2014 remove a target\n"
    "\u2022 <code>/list</code> \u2014 show tracked targets\n"
    "\u2022 <code>/help</code> \u2014 this message"
)


def parse(text: str) -> Command:
    """Turn a raw message string into a :class:`Command`."""
    text = (text or "").strip()
    if not text.startswith("/"):
        return Command("unknown", text)

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    # Strip @botname suffix (Telegram adds it in groups, e.g. /scan@my_bot).
    if "@" in cmd:
        cmd = cmd.split("@", 1)[0]

    if cmd in ("/scan", "/snipe"):
        return Command("scan_query" if arg else "scan_all", arg)
    if cmd in ("/search", "/find"):
        return Command("scan_query", arg)
    if cmd == "/add":
        return Command("add", arg)
    if cmd in ("/remove", "/rm", "/del", "/delete"):
        return Command("remove", arg)
    if cmd in ("/list", "/targets"):
        return Command("list", arg)
    if cmd in ("/help", "/start"):
        return Command("help", arg)
    return Command("unknown", text)
