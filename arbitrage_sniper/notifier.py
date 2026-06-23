"""Telegram notifier with HTML-formatted alert messages."""

from __future__ import annotations

import html
import logging
from typing import Optional

from .browser import http_client
from .config import settings
from .models import Alert

logger = logging.getLogger("arbitrage_sniper.notifier")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _esc(text: object) -> str:
    """Escape text for Telegram HTML parse mode."""
    return html.escape(str(text), quote=False)


def _fmt_money(value: Optional[float], currency: str = "EUR") -> str:
    if value is None:
        return "n/a"
    symbol = {"EUR": "\u20ac", "RON": "lei", "USD": "$", "GBP": "\u00a3"}.get(currency, currency)
    return f"{value:,.0f} {symbol}"


def render_alert(alert: Alert) -> str:
    """Build the HTML message body for a single triggered alert."""
    item = alert.item
    lines: list[str] = []

    lines.append(f"\U0001F4F8 <b>{_esc(item.title)}</b>")
    lines.append(f"\U0001F517 <a href=\"{_esc(item.link)}\">{_esc(item.platform.upper())} listing</a>")
    if item.location:
        lines.append(f"\U0001F4CD {_esc(item.location)}")
    lines.append("")

    lines.append(f"\U0001F4B0 <b>Buy price:</b> {_fmt_money(item.price, item.currency)}")

    # Safety / risk-zero gain (MPB floor).
    safe_pct = f" (+{alert.safe_gain_pct:.0f}%)" if alert.safe_gain_pct else ""
    lines.append(
        f"\U0001F6E1 <b>MPB floor:</b> {_fmt_money(alert.mpb_price)} \u2192 "
        f"risk-zero gain <b>{_fmt_money(alert.safe_gain)}</b>{safe_pct}"
    )

    # Retail / potential gain (eBay sold + F64).
    if alert.ebay_price is not None:
        lines.append(
            f"\U0001F4C8 <b>eBay sold avg:</b> {_fmt_money(alert.ebay_price)} \u2192 "
            f"max gain <b>{_fmt_money(alert.potential_gain)}</b>"
        )
    if alert.f64_price is not None:
        lines.append(f"\U0001F3EC <b>F64 used:</b> {_fmt_money(alert.f64_price)}")

    flags = alert.red_flags
    if flags:
        lines.append("")
        lines.append("\u26A0\uFE0F <b>Red flags:</b> " + ", ".join(_esc(f) for f in flags))

    lines.append("")
    lines.append(f"<i>target: {_esc(alert.target_label)} \u00b7 margin {alert.margin_used:.0%}</i>")
    return "\n".join(lines)


class TelegramNotifier:
    """Sends messages via the Telegram Bot API (async, no extra deps)."""

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None) -> None:
        self.token = token or settings.telegram_token
        self.chat_id = chat_id or settings.telegram_chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    async def _send(
        self,
        text: str,
        *,
        disable_preview: bool = False,
        chat_id: Optional[str] = None,
        message_thread_id: Optional[int] = None,
    ) -> bool:
        target_chat = chat_id or self.chat_id
        if not (self.token and target_chat):
            logger.warning("telegram disabled (missing token/chat id); message dropped")
            logger.info("would have sent:\n%s", text)
            return False
        payload = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        }
        # Route to a specific forum topic (supergroup with Topics enabled).
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        url = TELEGRAM_API.format(token=self.token)
        try:
            async with http_client() as client:
                resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.error("telegram error %s: %s", resp.status_code, resp.text[:300])
                return False
            return True
        except Exception as exc:  # pragma: no cover - network failures
            logger.error("telegram send failed: %s", exc)
            return False

    async def send_alert(
        self,
        alert: Alert,
        *,
        chat_id: Optional[str] = None,
        message_thread_id: Optional[int] = None,
    ) -> bool:
        return await self._send(
            render_alert(alert),
            chat_id=chat_id,
            message_thread_id=message_thread_id,
        )

    async def send_text(self, text: str) -> bool:
        return await self._send(text, disable_preview=True)

    async def get_updates(self, offset: int = 0, timeout: int = 0) -> list[dict]:
        """Poll Telegram getUpdates once. Returns the list of update objects."""
        if not self.token:
            return []
        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        params = {"timeout": timeout, "allowed_updates": '["message"]'}
        if offset:
            params["offset"] = offset
        try:
            async with http_client(timeout=timeout + 15) as client:
                resp = await client.get(url, params=params)
            data = resp.json()
            if not data.get("ok"):
                logger.error("telegram getUpdates error: %s", data)
                return []
            return data.get("result", [])
        except Exception as exc:  # pragma: no cover - network
            logger.error("telegram getUpdates failed: %s", exc)
            return []

    async def send_summary(self, *, scanned: int, new_ads: int, alerts: int) -> bool:
        text = (
            "\U0001F3AF <b>ArbitrageSniper run complete</b>\n"
            f"\u2022 scanned: {scanned}\n"
            f"\u2022 new ads: {new_ads}\n"
            f"\u2022 alerts: {alerts}"
        )
        return await self._send(text, disable_preview=True)
