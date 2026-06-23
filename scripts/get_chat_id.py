#!/usr/bin/env python3
"""Helper: print the chat id(s) that have interacted with the bot.

Usage:
    TELEGRAM_TOKEN=123:abc python scripts/get_chat_id.py

Steps:
    1. Open Telegram and send any message (e.g. /start) to your bot.
       For a channel/group, add the bot and post a message there.
    2. Run this script. It prints every chat id seen in recent updates.
    3. Put the value into the TELEGRAM_CHAT_ID secret.

The token is read from the environment and never written anywhere.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request


def main() -> int:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("ERROR: set TELEGRAM_TOKEN in the environment first.", file=sys.stderr)
        return 2

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # pragma: no cover - network
        print(f"ERROR calling Telegram API: {exc}", file=sys.stderr)
        return 1

    if not data.get("ok"):
        print(f"Telegram API error: {data}", file=sys.stderr)
        return 1

    results = data.get("result", [])
    if not results:
        print(
            "No updates yet. Send a message (e.g. /start) to your bot, "
            "then run this script again."
        )
        return 0

    seen: dict[int, str] = {}
    topics: dict[tuple, str] = {}
    for upd in results:
        msg = (
            upd.get("message")
            or upd.get("channel_post")
            or upd.get("edited_message")
            or {}
        )
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is None:
            continue
        title = chat.get("title") or chat.get("username") or chat.get("first_name") or ""
        seen[cid] = f"{chat.get('type', '?')} {title}".strip()

        # Forum topic (supergroup with Topics enabled): message_thread_id.
        thread = msg.get("message_thread_id")
        if thread is not None:
            topic_name = (msg.get("forum_topic_created") or {}).get("name", "")
            topics[(cid, thread)] = topic_name

    print("Discovered chats (use one of these as TELEGRAM_CHAT_ID):")
    for cid, desc in seen.items():
        print(f"  chat_id={cid}\t{desc}")

    if topics:
        print("\nDiscovered forum topics (use as 'topic_id' in thresholds.json channels):")
        for (cid, thread), name in topics.items():
            print(f"  chat_id={cid}  topic_id={thread}\t{name}")
    else:
        print(
            "\n(No forum topics seen. To route by topic, create a supergroup with "
            "Topics enabled, add the bot, post in a topic, then re-run.)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
