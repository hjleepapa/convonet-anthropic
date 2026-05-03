# Migration Plan: Convonet-Anthropic (Twilio → Telnyx)

> Telnyx Twilio Migration Skill — Phase 2 planning  
> Date: 2026-05-02  
> Project: Convonet voice AI (Flask, FusionPBX transfer)

## Project Overview

| Field | Value |
|-------|-------|
| Project Root | `/Users/hj/Web Development Projects/2. Convonet-Anthropic` (adjust per machine) |
| Primary Language(s) | Python, JavaScript (browser) |
| Framework(s) | Flask, Flask-SocketIO, LiveKit (WebRTC media) |
| Twilio Products in Use | Voice (TwiML + REST `calls.create` for transfer bridge) |
| Estimated Files to Modify | Core: `convonet/routes.py`, `convonet/webrtc_voice_server_socketio.py`; docs/templates referencing Twilio |
| Current Branch | `main` (use `migrate/twilio-to-telnyx` for implementation) |

## Migration Scope

| Twilio Product | Telnyx Replacement | Files Affected | Complexity | Notes |
|----------------|-------------------|----------------|------------|-------|
| Voice (inbound PSTN) | **TeXML** + Voice webhooks | `convonet/routes.py` | Medium | PIN + `Gather` speech loop + SIP `Dial` to FusionPBX — maps to TeXML verbs |
| Voice (outbound transfer leg) | **TeXML Application** + Voice API dial (or Call Control if required by API shape) | `convonet/webrtc_voice_server_socketio.py` | Medium | Replace `twilio.rest.Client` … `calls.create` with Telnyx outbound call to same bridge URL pattern |
| “Twilio WebRTC” | **N/A (LiveKit)** | Browser / LiveKit paths | Low | Assistant audio is **not** Twilio Client SDK; keep LiveKit. Only the **PSTN carrier leg** for agent bridge moves from Twilio to Telnyx. |
| Webhook validation | Ed25519 + nested JSON | `routes` handlers | Medium | Replace Twilio signature validation per `references/webhook-migration.md` |

### Out of scope (for this pass)

- Messaging, Verify, Twilio Flex/Studio, etc. (not in current scan)
- Porting phone numbers (optional later; FastPort when ready)
- Rewriting FusionPBX dialplans beyond SIP endpoint / ACL updates for **Telnyx** SIP ranges (ops task)

## Decision Points

### Voice approach: **TeXML-first** (with optional Call Control only where needed)

**Chosen: TeXML** as the primary programmable-voice model.

| Scenario | Rationale |
|----------|-----------|
| **1. PSTN → voice AI → transfer to FusionPBX** | Today this is **HTTP webhooks returning TwiML** (`VoiceResponse`, `Gather`, `Say`, `Redirect`, `Dial` + `Sip`). Telnyx **TeXML** is designed for near drop-in compatibility with TwiML-style flows. Lowest risk and smallest diff for PIN, speech gather, and SIP transfer. |
| **2. WebRTC (voice-assistant) → same AI → transfer to FusionPBX** | Browser media path is **LiveKit + Socket.IO**, not Twilio Client. Twilio is used to **originate a carrier call** that fetches **TwiML** from `voice_assistant/transfer_bridge` (SIP dial to FusionPBX). After migration, that leg becomes a **Telnyx outbound voice** action targeting the same **TeXML** (or equivalent webhook) URL. Still **XML-orchestrated**, not a full rewrite to event-driven Call Control. |
| **Call Control** | Reserve for later if you add **bidirectional streaming** (e.g. media fork / custom audio) where imperative call-leg APIs fit better. Current production PSTN path uses **Gather speech**, not Twilio `<Stream>` for the agent loop. |

**Summary:** Use a **TeXML Application** in Mission Control for inbound (and outbound profile association as per Telnyx docs). Implement webhook handlers that return **TeXML** mirroring current routes; swap REST client for **Telnyx** outbound dial for the WebRTC-initiated transfer leg.

- [x] **Voice approach**: **TeXML** (primary); Call Control **deferred** unless a specific API gap requires it  
- [x] **WebRTC**: Keep **LiveKit** + app server; replace **Twilio Voice REST** only for the **transfer bridge** outbound call  
- [ ] **Webhook validation**: Ed25519 (recommended) — implement during Phase 4  
- [ ] **Migration strategy**: **Incremental** — voice webhooks + transfer REST first, then cleanup Twilio deps  

## Migration Order

- [ ] **Phase 0: Account Setup** — Telnyx API key, TeXML Application, number, OVP / whitelisted destinations as needed  
- [x] **Phase 3: Setup** — Branch `migrate/twilio-to-telnyx`, `telnyx>=4.0,<5.0` in requirements*, `.env.example` + Render YAML + docs (`TELNYX_API_KEY`, `TELNYX_PUBLIC_KEY`, `TELNYX_PHONE_NUMBER`, `TELNYX_TEXML_APP_ID`)  
- [x] **Phase 4: Voice (TeXML)** — Parallel `/convonet_todo/telnyx/*` routes mirror Twilio; TwiML XML unchanged; actions/redirects use `voice_rel_path` / `voice_abs_path`  
- [x] **Phase 4: Outbound transfer leg** — `voice_carrier_transfer.initiate_carrier_transfer`: Telnyx `client.texml.accounts.calls.calls` when `TELNYX_*` configured (override with `USE_TWILIO_VOICE_TRANSFER=true`)  
- [ ] **Phase 4: FusionPBX / SIP** — Update allowlists and docs from Twilio to **Telnyx** SIP signaling IPs  
- [ ] **Phase 5: Validation** — `validate-migration.sh`, `lint-telnyx-correctness.sh`, voice smoke tests  
- [ ] **Phase 6: Cleanup** — Remove `twilio` from `requirements.txt` after cutover; archive Twilio env vars  

## Environment Changes

| Variable | Current (Twilio) | New (Telnyx) | Notes |
|----------|------------------|--------------|-------|
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | In use | Remove after cutover | Bearer model on Telnyx |
| `TELNYX_API_KEY` | — | Set | Already in `.env` for preflight |
| `TELNYX_PUBLIC_KEY` | — | Fetch / set | Webhook Ed25519 verification |
| `TWILIO_PHONE_NUMBER` | Caller ID / DID | `TELNYX_PHONE_NUMBER` (or number on Telnyx) | E.164 |
| TeXML / voice app | Twilio URLs | `TELNYX_TEXML_APP_ID` or `TELNYX_CONNECTION_ID` | Per skill: one ID for TeXML app owning webhook URLs |

## Webhook URL Changes

| Endpoint | Current | New | Notes |
|----------|---------|-----|-------|
| Inbound voice | Twilio → `/convonet_todo/twilio/call` | Telnyx TeXML → **`/convonet_todo/telnyx/call`** (same handler) | TeXML callbacks: form fields align with Twilio-style (`webhook-migration.md`); optional Ed25519 for JSON events |
| PIN / audio / transfer | `/twilio/*` | **`/telnyx/verify_pin`**, **`/telnyx/process_audio`**, **`/telnyx/transfer`**, … | Configure TeXML app Voice URL to `/telnyx/...` paths when cut over |
| Transfer bridge | `/twilio/voice_assistant/transfer_bridge` | **`/telnyx/voice_assistant/transfer_bridge`** | WebRTC transfer uses Telnyx outbound when `use_telnyx_for_carrier_transfer()` |

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Gather / speech timeout differences | Medium | Medium | Test PIN + barge-in on staging number; compare TeXML verb attributes |
| SIP transfer to FusionPBX (ACL / auth) | Medium | High | Stage Telnyx SIP ranges on FusionPBX; keep credential auth if used today |
| Webhook payload rewrite breaks DB keyed by `CallSid` | Medium | High | Map Telnyx call identifiers in one layer; migrate `call_sid` columns if needed |
| Dual provider during cutover | Low | Medium | Feature flag or number-level routing until validation passes |

## Rollback Plan

1. `git checkout main` (or prior branch)  
2. Point voice number webhooks back to Twilio in Twilio Console  
3. Restore Twilio env vars in Render / `.env`  
4. Telnyx account remains available for retry  

---

*Updated for Convonet: TeXML-first voice migration; LiveKit WebRTC path unchanged except Twilio REST transfer leg.*
