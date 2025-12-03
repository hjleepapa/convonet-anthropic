# Convonet Voice Assistant - Presentation Flow

## Complete System Architecture Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CONVONET VOICE ASSISTANT - COMPLETE FLOW                  │
└─────────────────────────────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════════════════
PHASE 1: AUTHENTICATION (Steps 1-7)
═══════════════════════════════════════════════════════════════════════════════

👤 User Browser
    │
    │ 1. Connect WebSocket
    ▼
🔌 WebSocket Server (Socket.IO)
    │
    │ 2. Request Authentication
    ▼
🔐 PIN Auth Module
    │
    │ 3. Validate PIN
    ▼
🗄️ PostgreSQL Database
    │
    │ 4. User Data (ID, Name, Teams)
    ▼
🔐 PIN Auth Module
    │
    │ 5. Create Session
    ▼
📦 Redis Cache
    │
    │ 6. Authenticated
    ▼
🔌 WebSocket Server
    │
    │ 7. Session ID
    ▼
👤 User Browser ✅ Authenticated

═══════════════════════════════════════════════════════════════════════════════
PHASE 2: NORMAL CONVERSATION LOOP (Steps 8-31)
═══════════════════════════════════════════════════════════════════════════════

👤 User Browser
    │
    │ 8. Start Recording
    ▼
🔌 WebSocket Server
    │
    │ 9. Audio Chunks (WebRTC)
    ▼
🎤 WebRTC Voice Server
    │
    │ 10. Buffer Audio Data
    ▼
📦 Redis Cache
    │
    │ 11. Send Audio Buffer
    ▼
🎙️ Deepgram STT
    │
    │ 12. Transcribed Text
    ▼
🎤 WebRTC Voice Server
    │
    │ 13. User Input Text
    ▼
🤖 LangGraph Agent
    │
    │ 14. Process Intent
    ▼
🧠 Claude LLM
    │
    │ 15. Response + Tool Calls
    ▼
🤖 LangGraph Agent
    │
    │ 16-21. Execute Tools (if needed)
    │         ├─ Database Operations (PostgreSQL)
    │         ├─ Calendar Operations (Google Calendar)
    │         └─ PBX Metadata (FusionPBX)
    │
    │ 22. Generate Final Response
    ▼
🧠 Claude LLM
    │
    │ 23. Response Text
    ▼
🤖 LangGraph Agent
    │
    │ 24. AI Response
    ▼
🎤 WebRTC Voice Server
    │
    │ 25. Convert to Speech
    ▼
🔊 TTS Engine
    │
    │ 26. Audio Response
    ▼
🎤 WebRTC Voice Server
    │
    │ 27. Buffer Response Audio
    ▼
📦 Redis Cache
    │
    │ 28. Stream Audio
    ▼
🔌 WebSocket Server
    │
    │ 29. Play Response
    ▼
👤 User Browser 🔊 Audio Response

    ═══════════════════════════════════════════════════════════════════════
    🔄 LOOP: Steps 8-31 repeat for each user utterance
    ═══════════════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════════════════════
PHASE 3: TRANSFER REQUEST (Steps 30-38)
═══════════════════════════════════════════════════════════════════════════════

👤 User Browser
    │
    │ 30. "Transfer to Agent"
    ▼
🔌 WebSocket Server
    │
    │ 31. Transfer Intent
    ▼
🎤 WebRTC Voice Server
    │
    │ 32. Detect Transfer Intent
    ▼
🤖 LangGraph Agent
    │
    │ 33. Confirm Transfer
    ▼
🧠 Claude LLM
    │
    │ 34. Transfer Command
    ▼
🤖 LangGraph Agent
    │
    │ 35. Set Transfer Flag
    ▼
📦 Redis Cache
    │
    │ 36. Transfer Initiated
    ▼
🎤 WebRTC Voice Server
    │
    │ 37. Transfer Event
    ▼
🔌 WebSocket Server
    │
    │ 38. Show Transfer Status
    ▼
👤 User Browser 📞 Transfer Status

═══════════════════════════════════════════════════════════════════════════════
PHASE 4: TWILIO TRANSFER FLOW (Steps 39-52)
═══════════════════════════════════════════════════════════════════════════════

🎤 WebRTC Voice Server
    │
    │ 39. POST /transfer_bridge
    │    SIP: sip:2001@FREEPBX_DOMAIN
    ▼
☁️ Twilio API
    │
    │ 40. SIP INVITE to Extension 2001
    ▼
📞 FusionPBX (Google Cloud)
    │
    │ 41. Ring Extension 2001
    ▼
👨‍💼 Agent Dashboard (JsSIP)
    │
    │ 42. Fetch User Info
    ▼
🗄️ PostgreSQL Database
    │
    │ 43. User Data
    ▼
👨‍💼 Agent Dashboard
    │
    │ 44. Show User Info Popup
    │    Display Call Controls
    │
    │ 45. Agent Answers Call
    ▼
📞 FusionPBX
    │
    │ 46. Call Connected
    ▼
☁️ Twilio API
    │
    │ 47. Bridge Audio (User Leg)
    │ 48. Bridge Audio (Agent Leg)
    ▼
👤 User Browser ────────────────┐
                                │
                                │ 🎉 Live Conversation
                                │
👨‍💼 Agent Dashboard ─────────────┘

═══════════════════════════════════════════════════════════════════════════════
TECHNOLOGY STACK
═══════════════════════════════════════════════════════════════════════════════

Component              Technology
─────────────────────────────────────────────────────────────────────────────
WebSocket              Socket.IO (Flask)
Database               PostgreSQL (SQLAlchemy)
Cache                  Redis
Speech-to-Text         Deepgram STT
AI Agent               LangGraph + Claude LLM
Text-to-Speech         Deepgram TTS
Telephony              Twilio + FusionPBX
Agent Client           JsSIP (WebRTC)
```


