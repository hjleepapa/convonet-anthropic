"""Shared URL helpers for Twilio vs Telnyx (TeXML) voice webhooks on the same blueprint."""

from __future__ import annotations


def voice_ns_from_path(path: str | None) -> str:
    if path and "/telnyx/" in path:
        return "telnyx"
    return "twilio"


def voice_rel_path(path: str | None, endpoint: str) -> str:
    """
    Relative URL under /convonet_todo/{twilio|telnyx}/...

    endpoint: e.g. 'call', 'verify_pin', 'process_audio?user_id=1'
    """
    ns = voice_ns_from_path(path)
    return f"/convonet_todo/{ns}/{endpoint}"


def voice_abs_path(path: str | None, base_url: str, endpoint: str) -> str:
    base = (base_url or "").rstrip("/")
    return f"{base}{voice_rel_path(path, endpoint)}"
