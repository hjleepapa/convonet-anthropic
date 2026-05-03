"""
Carrier-initiated voice transfer (Twilio or Telnyx TeXML) for WebRTC → FusionPBX bridge.

Phase 4: Telnyx TeXML outbound call mirrors Twilio client.calls.create to a SIP URI
with a webhook URL that returns Dial TeXML/TwiML.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional, Tuple

from twilio.rest import Client


def use_telnyx_for_carrier_transfer() -> bool:
    """
    Use Telnyx TeXML outbound when fully configured.

    Set USE_TWILIO_VOICE_TRANSFER=true to force Twilio even if Telnyx vars exist.
    """
    if os.getenv("USE_TWILIO_VOICE_TRANSFER", "").strip().lower() in ("1", "true", "yes"):
        return False
    return bool(
        os.getenv("TELNYX_API_KEY")
        and os.getenv("TELNYX_TEXML_APP_ID")
        and (
            os.getenv("TELNYX_PHONE_NUMBER")
            or os.getenv("TELNYX_TRANSFER_CALLER_ID")
        )
    )


def _telnyx_caller_id() -> Optional[str]:
    return (
        os.getenv("TELNYX_TRANSFER_CALLER_ID")
        or os.getenv("TELNYX_PHONE_NUMBER")
        or os.getenv("TWILIO_TRANSFER_CALLER_ID")
        or os.getenv("TWILIO_CALLER_ID")
        or os.getenv("TWILIO_PHONE_NUMBER")
        or os.getenv("TWILIO_NUMBER")
    )


def _twilio_caller_id() -> Optional[str]:
    return (
        os.getenv("TWILIO_TRANSFER_CALLER_ID")
        or os.getenv("TWILIO_CALLER_ID")
        or os.getenv("TWILIO_NUMBER")
        or os.getenv("TWILIO_PHONE_NUMBER")
    )


def _texml_account_sid() -> str:
    return (
        os.getenv("TELNYX_TEXML_ACCOUNT_SID")
        or os.getenv("TELNYX_TEXML_APP_ID")
        or ""
    )


def initiate_carrier_transfer(
    *,
    extension: str,
    sip_target: str,
    transfer_url: str,
    session_data: dict | None,
    cache_call_center_profile: Callable[..., None],
) -> Tuple[bool, Dict[str, Any]]:
    """
    Originate an outbound call to sip_target; carrier fetches TeXML/TwiML from transfer_url.
    """
    details: Dict[str, Any] = {
        "extension": extension,
        "transfer_url": transfer_url,
        "agent_call_sid": None,
        "user_call_sid": None,
    }

    if use_telnyx_for_carrier_transfer():
        return _telnyx_texml_dial(
            extension=extension,
            sip_target=sip_target,
            transfer_url=transfer_url,
            caller_id=_telnyx_caller_id(),
            session_data=session_data,
            cache_call_center_profile=cache_call_center_profile,
            details=details,
        )

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    caller_id = _twilio_caller_id()
    if not (account_sid and auth_token and caller_id):
        missing = []
        if not account_sid:
            missing.append("TWILIO_ACCOUNT_SID")
        if not auth_token:
            missing.append("TWILIO_AUTH_TOKEN")
        if not caller_id:
            missing.append(
                "TWILIO_TRANSFER_CALLER_ID / TWILIO_CALLER_ID / TWILIO_NUMBER / TWILIO_PHONE_NUMBER"
            )
        msg = f"Transfer aborted: missing configuration values: {', '.join(missing)}"
        print(f"⚠️ {msg}")
        details["error"] = msg
        return False, details

    client = Client(account_sid, auth_token)
    try:
        agent_call = client.calls.create(
            to=sip_target, from_=caller_id, url=transfer_url, method="POST"
        )
        details["agent_call_sid"] = agent_call.sid
        print(
            f"📞 ✅ Initiated agent call via Twilio (Call SID: {agent_call.sid}) to {sip_target}"
        )
        if agent_call.sid and session_data:
            cache_call_center_profile(
                extension, session_data, call_sid=agent_call.sid
            )
        return True, details
    except Exception as e:
        message = str(e)
        if "401" in message or "Authenticate" in message or "20003" in message:
            print(
                "❌ Twilio 401 (Invalid credentials): check TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN."
            )
        print(f"❌ Failed to originate Twilio agent call: {message}")
        details["error"] = message
        return False, details


def _telnyx_texml_dial(
    *,
    extension: str,
    sip_target: str,
    transfer_url: str,
    caller_id: Optional[str],
    session_data: dict | None,
    cache_call_center_profile: Callable[..., None],
    details: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
    from telnyx import Telnyx

    account_sid = _texml_account_sid()
    application_sid = os.getenv("TELNYX_TEXML_APP_ID") or ""
    if not caller_id:
        msg = "Transfer aborted: set TELNYX_PHONE_NUMBER or TELNYX_TRANSFER_CALLER_ID"
        print(f"⚠️ {msg}")
        details["error"] = msg
        return False, details
    if not (account_sid and application_sid):
        msg = "Transfer aborted: TELNYX_TEXML_APP_ID (and optional TELNYX_TEXML_ACCOUNT_SID) required"
        print(f"⚠️ {msg}")
        details["error"] = msg
        return False, details

    client = Telnyx(api_key=os.environ.get("TELNYX_API_KEY"))
    try:
        result = client.texml.accounts.calls.calls(
            account_sid=account_sid,
            application_sid=application_sid,
            from_=caller_id,
            to=sip_target,
            url=transfer_url,
            url_method="POST",
        )
        sid = getattr(result, "sid", None)
        if sid is None and hasattr(result, "model_dump"):
            sid = result.model_dump().get("sid")
        details["agent_call_sid"] = sid
        print(
            f"📞 ✅ Initiated agent call via Telnyx TeXML (Call SID: {sid}) to {sip_target}"
        )
        if sid and session_data:
            cache_call_center_profile(extension, session_data, call_sid=sid)
        return True, details
    except Exception as e:
        msg = str(e)
        print(f"❌ Failed to originate Telnyx TeXML call: {msg}")
        details["error"] = msg
        return False, details
