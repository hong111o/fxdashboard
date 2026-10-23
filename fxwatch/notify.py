"""Send notifications: WhatsApp first, Telegram as fallback.

Configured through environment variables (GitHub Actions secrets):
  WHATSAPP_PHONE                          -> your number, e.g. +447700900123
  WA_TOKEN, WA_PHONE_NUMBER_ID            -> WhatsApp bot (Meta Cloud API)
  CALLMEBOT_APIKEY                        -> WhatsApp via CallMeBot
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID    -> Telegram bot

The WhatsApp bot can only send free-form messages within 24 hours of your last
message to it (outside that, Meta requires paid templates), so alerts use it only
while that window is open and otherwise go through CallMeBot.
"""

import json
import os
import urllib.parse
import urllib.request

from .http import USER_AGENT, get_json

CALLMEBOT = "https://api.callmebot.com/whatsapp.php"


def _whatsapp(text):
    phone, key = os.environ.get("WHATSAPP_PHONE"), os.environ.get("CALLMEBOT_APIKEY")
    if not (phone and key):
        return False
    url = f"{CALLMEBOT}?{urllib.parse.urlencode({'phone': phone, 'text': text, 'apikey': key})}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", "replace")
    # CallMeBot answers 200 with an HTML page; failures mention an error in the body.
    if "error" in body.lower() and "queued" not in body.lower():
        raise RuntimeError(f"CallMeBot rejected the message: {body[:200]}")
    return True


def _whatsapp_cloud(text):
    token, number_id = os.environ.get("WA_TOKEN"), os.environ.get("WA_PHONE_NUMBER_ID")
    phone = "".join(ch for ch in os.environ.get("WHATSAPP_PHONE", "") if ch.isdigit())
    if not (token and number_id and phone):
        return False
    version = os.environ.get("GRAPH_VERSION", "v23.0")
    body = json.dumps({"messaging_product": "whatsapp", "to": phone, "type": "text",
                       "text": {"body": text}}).encode()
    req = urllib.request.Request(f"https://graph.facebook.com/{version}/{number_id}/messages", data=body,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                          "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        json.loads(resp.read())
    return True


def _telegram(text):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    data = get_json(f"https://api.telegram.org/bot{token}/sendMessage", {"chat_id": chat, "text": text})
    if not data.get("ok"):
        raise RuntimeError(f"Telegram error: {data}")
    return True


def send(text, whatsapp_cloud=False):
    """Try the WhatsApp bot (if its 24h window is open), CallMeBot, then Telegram.

    Returns the channel used, or None.
    """
    channels = [("whatsapp-bot", _whatsapp_cloud)] if whatsapp_cloud else []
    channels += [("whatsapp", _whatsapp), ("telegram", _telegram)]
    errors = []
    for name, channel in channels:
        try:
            if channel(text):
                return name
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    if errors:
        raise RuntimeError("; ".join(errors))
    return None


def telegram_commands(offset=None):
    """Fetch new messages sent to the bot by you (TELEGRAM_CHAT_ID only).

    Returns (list of command texts, next offset). Telegram keeps unread messages
    for 24 hours, so an hourly run never misses one.
    """
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return [], offset
    params = {"timeout": 0, "allowed_updates": '["message"]'}
    if offset is not None:
        params["offset"] = offset
    data = get_json(f"https://api.telegram.org/bot{token}/getUpdates", params)
    texts = []
    for update in data.get("result", []):
        offset = update["update_id"] + 1
        msg = update.get("message") or {}
        if str(msg.get("chat", {}).get("id")) == str(chat) and msg.get("text", "").startswith("/"):
            texts.append(msg["text"])
    return texts, offset


def telegram_reply(text):
    return _telegram(text)


def whatsapp_reply(text):
    """Reply to a command sent to the WhatsApp bot (always inside the free 24h window)."""
    if not _whatsapp_cloud(text):
        send(text)
