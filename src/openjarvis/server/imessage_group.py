"""iMessage (SendBlue) handler that works in group chats.

The stock ``/webhooks/sendblue`` route only replies one-to-one and sends
"Message received / still working" acknowledgements, which is wrong for a
group chat. This route:

- accepts SendBlue ``receive`` webhooks for both direct and group messages,
- verifies a shared secret carried in the URL (``?key=``) so it does not
  depend on SendBlue's webhook header name,
- in a group, answers only when addressed ("jarvis ..." / "@jarvis" /
  "hey jarvis") unless ``IMESSAGE_REPLY_TO_ALL=1``,
- only listens to allowed senders (``JARVIS_OWNER_PHONE``, ``JARVIS_PARTNER_PHONE``,
  or ``IMESSAGE_ALLOWED_NUMBERS`` comma list),
- keeps a short per-chat history so follow-ups make sense,
- runs the server's configured agent (persona, tools, skills) and replies via
  SendBlue's send-message / send-group-message API.

Env: ``SENDBLUE_API_KEY_ID``, ``SENDBLUE_API_SECRET_KEY``, ``SENDBLUE_FROM_NUMBER``,
``IMESSAGE_WEBHOOK_KEY`` (the ``?key=`` value; falls back to ``OPS_WEBHOOK_KEY``).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import threading
import time
import urllib.request
from collections import OrderedDict, deque
from typing import Any, Deque, Dict

from fastapi import APIRouter, Request, Response

logger = logging.getLogger("openjarvis.server.imessage")

_API = "https://api.sendblue.com"
_ADDRESS_RE = re.compile(r"^\s*(?:@?jarvis\b|hey\s+jarvis\b|ok\s+jarvis\b)[\s,:!-]*", re.I)
_MENTION_RE = re.compile(r"\bjarvis\b", re.I)

_seen: "OrderedDict[str, float]" = OrderedDict()
_history: Dict[str, Deque[Dict[str, str]]] = {}
_locks: Dict[str, threading.Lock] = {}
_state_lock = threading.Lock()


def _allowed_numbers() -> set[str]:
    nums = {
        os.environ.get("JARVIS_OWNER_PHONE", "").strip(),
        os.environ.get("JARVIS_PARTNER_PHONE", "").strip(),
    }
    nums.update(n.strip() for n in os.environ.get("IMESSAGE_ALLOWED_NUMBERS", "").split(","))
    return {n for n in nums if n}


def _sb_headers() -> Dict[str, str]:
    return {
        "sb-api-key-id": os.environ.get("SENDBLUE_API_KEY_ID", ""),
        "sb-api-secret-key": os.environ.get("SENDBLUE_API_SECRET_KEY", ""),
        "Content-Type": "application/json",
    }


def _sb_post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    req = urllib.request.Request(
        _API + path, data=json.dumps(body).encode(), headers=_sb_headers(), method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode() or "{}")


def send_imessage(text: str, *, number: str = "", group_id: str = "") -> bool:
    """Send *text* to a number or a group through SendBlue."""
    frm = os.environ.get("SENDBLUE_FROM_NUMBER", "").strip()
    try:
        if group_id:
            _sb_post("/api/send-group-message", {"group_id": group_id, "content": text, "from_number": frm})
        else:
            payload = {"number": number, "content": text}
            if frm:
                payload["from_number"] = frm
            _sb_post("/api/send-message", payload)
        return True
    except Exception:
        logger.exception("SendBlue send failed")
        return False


def _dedupe(handle: str) -> bool:
    """Return True if this message handle was already processed."""
    with _state_lock:
        now = time.time()
        for k in [k for k, t in _seen.items() if now - t > 3600]:
            _seen.pop(k, None)
        if handle in _seen:
            return True
        _seen[handle] = now
        return False


def _plain(text: str) -> str:
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"^\s*[-*]\s+", "- ", text, flags=re.M)
    return text.strip()


def _run_agent(app, chat_key: str, who: str, text: str, is_group: bool) -> str:
    from openjarvis.agents._stubs import AgentContext
    from openjarvis.core.types import Message

    agent = getattr(app.state, "agent", None)
    if agent is None:
        return ""
    with _state_lock:
        hist = _history.setdefault(chat_key, deque(maxlen=12))
        lock = _locks.setdefault(chat_key, threading.Lock())
    ctx = AgentContext()
    for m in list(hist):
        ctx.conversation.add(Message(role=m["role"], content=m["content"]))
    where = "an iMessage GROUP chat with the two partners, Moe and Maikl" if is_group else "a one-to-one iMessage"
    prompt = (
        f"[iMessage from {who} in {where}. Reply in plain text, no markdown, "
        f"short enough for a phone screen. You were addressed by name.]\n{text}"
    )
    with lock:
        result = agent.run(prompt, context=ctx)
        reply = _plain(getattr(result, "content", "") or "")
        hist.append({"role": "user", "content": f"{who}: {text}"})
        if reply:
            hist.append({"role": "assistant", "content": reply})
    return reply


def create_imessage_group_router() -> APIRouter:
    router = APIRouter(prefix="/webhooks", tags=["imessage"])

    @router.post("/imessage")
    async def imessage_incoming(request: Request) -> Response:
        expected = os.environ.get("IMESSAGE_WEBHOOK_KEY", "") or os.environ.get("OPS_WEBHOOK_KEY", "")
        provided = request.query_params.get("key", "") or request.headers.get("x-sendblue-secret", "")
        if not expected or not hmac.compare_digest(provided, expected):
            return Response("forbidden", status_code=403)

        try:
            payload = await request.json()
        except Exception:
            return Response("bad json", status_code=400)
        if payload.get("is_outbound"):
            return Response("OK")
        sender = (payload.get("from_number") or "").strip()
        content = (payload.get("content") or "").strip()
        group_id = (payload.get("group_id") or "").strip()
        handle = payload.get("message_handle") or payload.get("event_id") or ""
        if not sender or not content:
            return Response("OK")
        if handle and _dedupe(handle):
            return Response("OK")

        allowed = _allowed_numbers()
        if allowed and sender not in allowed:
            logger.info("iMessage from non-allowed number ignored")
            return Response("OK")

        is_group = bool(group_id)
        reply_all = os.environ.get("IMESSAGE_REPLY_TO_ALL", "") == "1"
        if is_group and not reply_all and not _MENTION_RE.search(content):
            # Keep a little context even when not addressed, so "Jarvis, what do
            # you think?" after a few messages has something to work with.
            with _state_lock:
                _history.setdefault(group_id, deque(maxlen=12)).append(
                    {"role": "user", "content": f"{_who(sender)}: {content}"}
                )
            return Response("OK")

        text = _ADDRESS_RE.sub("", content, count=1).strip() or content
        chat_key = group_id or sender
        who = _who(sender)
        app = request.app

        def _work() -> None:
            try:
                reply = _run_agent(app, chat_key, who, text, is_group)
            except Exception:
                logger.exception("iMessage agent run failed")
                reply = "Sorry, I hit an error on that one."
            if reply:
                for chunk in _split(reply, 1400):
                    send_imessage(chunk, number=sender, group_id=group_id)

        asyncio.create_task(asyncio.to_thread(_work))
        return Response("OK")

    return router


def _who(number: str) -> str:
    if number and number == os.environ.get("JARVIS_OWNER_PHONE", "").strip():
        return "Moe"
    if number and number == os.environ.get("JARVIS_PARTNER_PHONE", "").strip():
        return "Maikl"
    return "a partner"


def _split(text: str, n: int) -> list[str]:
    if len(text) <= n:
        return [text]
    out, cur = [], ""
    for para in text.split("\n"):
        if len(cur) + len(para) + 1 > n and cur:
            out.append(cur.strip())
            cur = ""
        cur += para + "\n"
    if cur.strip():
        out.append(cur.strip())
    return out
