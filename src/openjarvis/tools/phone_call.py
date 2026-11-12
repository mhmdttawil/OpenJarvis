"""Outbound phone call and SMS tools backed by Twilio.

OpenJarvis ships a Twilio *channel* (inbound/outbound SMS routed through an
agent), but no way for an agent to decide on its own to *ring* the owner. This
module adds two agent-callable tools:

- ``phone_call``: places a voice call and reads a message aloud (Twilio TwiML
  ``<Say>``). Optionally repeats the message and asks the callee to press a key
  to acknowledge.
- ``send_sms``: sends a text message.

Both default to the owner's number from ``JARVIS_OWNER_PHONE`` so the agent can
be told "call me" without ever being given a phone number in the prompt. Numbers
other than the owner's are refused unless ``JARVIS_ALLOW_ANY_NUMBER=1``.

Required env vars: ``TWILIO_ACCOUNT_SID``, ``TWILIO_AUTH_TOKEN``,
``TWILIO_PHONE_NUMBER`` (the Twilio number to call/text from),
``JARVIS_OWNER_PHONE``. Optional ``JARVIS_VOICE_URL`` (Twilio Function URL of
``twilio/voice-inbound.js``) lets the owner talk back after hearing the message.
Requires the ``channel-twilio`` extra (``twilio>=9.0``).
"""

from __future__ import annotations

import os
import time
from typing import Any
from xml.sax.saxutils import escape

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _twilio_client():  # noqa: ANN202
    from twilio.rest import Client

    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    tok = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not sid or not tok:
        raise RuntimeError("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not set")
    return Client(sid, tok)


def _resolve_to(to: str) -> str:
    owner = os.environ.get("JARVIS_OWNER_PHONE", "").strip()
    to = (to or "").strip() or owner
    if not to:
        raise RuntimeError("No destination: pass `to` or set JARVIS_OWNER_PHONE")
    if to != owner and os.environ.get("JARVIS_ALLOW_ANY_NUMBER", "") != "1":
        raise RuntimeError(
            "Refusing to contact a number other than the owner's "
            "(set JARVIS_ALLOW_ANY_NUMBER=1 to allow)"
        )
    return to


def _from_number() -> str:
    frm = os.environ.get("TWILIO_PHONE_NUMBER", "").strip()
    if not frm:
        raise RuntimeError("TWILIO_PHONE_NUMBER not set")
    return frm


@ToolRegistry.register("phone_call")
class PhoneCallTool(BaseTool):
    """Ring the owner's phone and speak a message."""

    tool_id = "phone_call"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="phone_call",
            description=(
                "Place a phone call to the owner and read a short spoken message "
                "aloud. Use for urgent items that should not wait for a text "
                "(a job running late, a payment problem, a same-day dispatch). "
                "Keep the message under 60 words and do not include phone numbers, "
                "codes or passwords."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "What to say on the call, in plain spoken English.",
                    },
                    "to": {
                        "type": "string",
                        "description": "Optional E.164 number. Defaults to the owner's phone.",
                    },
                    "repeat": {
                        "type": "integer",
                        "description": "How many times to read the message (1-3). Default 2.",
                    },
                },
                "required": ["message"],
            },
            category="communication",
            requires_confirmation=False,
            timeout_seconds=30.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        t0 = time.time()
        message = str(params.get("message", "")).strip()
        if not message:
            return ToolResult(tool_name="phone_call", content="message is required", success=False)
        repeat = max(1, min(int(params.get("repeat", 2) or 2), 3))
        try:
            to = _resolve_to(str(params.get("to", "")))
            client = _twilio_client()
            said = escape(message)
            body = "".join(
                f'<Say voice="Polly.Matthew">{said}</Say><Pause length="1"/>' for _ in range(repeat)
            )
            voice_url = os.environ.get("JARVIS_VOICE_URL", "").strip()
            if voice_url:
                # Hand the call to the inbound voice handler so the owner can talk back.
                tail = (
                    f'<Gather input="speech" action="{escape(voice_url)}" method="POST" speechTimeout="auto">'
                    '<Say voice="Polly.Matthew">Say something if you want to reply, or hang up.</Say></Gather>'
                    '<Say voice="Polly.Matthew">Goodbye.</Say>'
                )
            else:
                tail = '<Say voice="Polly.Matthew">Goodbye.</Say>'
            twiml = (
                '<Response><Say voice="Polly.Matthew">This is Jarvis with an update.</Say>'
                f'<Pause length="1"/>{body}{tail}</Response>'
            )
            call = client.calls.create(to=to, from_=_from_number(), twiml=twiml)
            return ToolResult(
                tool_name="phone_call",
                content=f"Call placed (sid {call.sid}, status {call.status}).",
                success=True,
                latency_seconds=time.time() - t0,
                metadata={"sid": call.sid, "status": call.status},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_name="phone_call",
                content=f"Call failed: {exc}",
                success=False,
                latency_seconds=time.time() - t0,
            )


@ToolRegistry.register("send_sms")
class SendSmsTool(BaseTool):
    """Text the owner."""

    tool_id = "send_sms"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="send_sms",
            description=(
                "Send a text message to the owner's phone. Use for non-urgent "
                "updates, confirmations and summaries. Keep it under 300 characters; "
                "never include passwords, codes or account numbers."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "The text to send."},
                    "to": {
                        "type": "string",
                        "description": "Optional E.164 number. Defaults to the owner's phone.",
                    },
                },
                "required": ["message"],
            },
            category="communication",
            timeout_seconds=30.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        t0 = time.time()
        message = str(params.get("message", "")).strip()
        if not message:
            return ToolResult(tool_name="send_sms", content="message is required", success=False)
        try:
            to = _resolve_to(str(params.get("to", "")))
            msg = _twilio_client().messages.create(body=message[:1600], from_=_from_number(), to=to)
            return ToolResult(
                tool_name="send_sms",
                content=f"SMS sent (sid {msg.sid}).",
                success=True,
                latency_seconds=time.time() - t0,
                metadata={"sid": msg.sid},
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                tool_name="send_sms",
                content=f"SMS failed: {exc}",
                success=False,
                latency_seconds=time.time() - t0,
            )
