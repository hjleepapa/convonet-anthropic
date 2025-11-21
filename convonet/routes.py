from flask import Blueprint, request, jsonify, render_template, Response
from flask_socketio import emit, join_room, leave_room
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph
from typing import Optional
import asyncio
import json
import os
import logging
import time
import sentry_sdk

# Apply nest_asyncio to allow nested event loops (needed for eventlet compatibility)
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass  # nest_asyncio not available, may cause issues with eventlet

from twilio.twiml.voice_response import VoiceResponse, Connect, Gather
from .state import AgentState
from .assistant_graph_todo import get_agent, TodoAgent
from .voice_intent_utils import has_transfer_intent
from langchain_mcp_adapters.client import MultiServerMCPClient

# Import new authentication and team routes (optional - commented out as api_routes moved to archive)
# from .api_routes.auth_routes import auth_bp
# from .api_routes.team_routes import team_bp
# from .api_routes.team_todo_routes import team_todo_bp

# Set up logging
logger = logging.getLogger(__name__)

# Global agent graph cache (initialized on first use)
_agent_graph_cache = None
_agent_graph_model = None  # Track which model was used for the cached graph
_agent_graph_lock = asyncio.Lock()

convonet_todo_bp = Blueprint(
    'convonet_todo',
    __name__,
    url_prefix='/anthropic/convonet_todo',
    template_folder='templates',
    static_folder='static'
)

def get_webhook_base_url():
    """Get the webhook base URL for Twilio webhooks."""
    # Prefer explicit setting, then Render URL, then fallback
    return (
        os.getenv('WEBHOOK_BASE_URL')
        or os.getenv('RENDER_EXTERNAL_URL')
        or 'https://convonet-anthropic.onrender.com'
    )

def get_websocket_url():
    """Get the WebSocket URL for Twilio Media Streams."""
    # Prefer explicit setting, then derive from Render URL, then fallback
    websocket_url = os.getenv('WEBSOCKET_BASE_URL')
    if websocket_url:
        return websocket_url
    
    # Derive from Render URL or use default
    base_url = os.getenv('RENDER_EXTERNAL_URL') or 'https://convonet-anthropic.onrender.com'
    return base_url.replace('https://', 'wss://').replace('http://', 'ws://') + '/anthropic/convonet_todo/ws'

# --- Twilio Voice Routes ---
@convonet_todo_bp.route('/twilio/call', methods=['POST'])
def twilio_call_webhook():
    """
    Handles incoming calls from Twilio.
    Asks for PIN authentication before allowing access to the assistant.
    """
    # Get the current webhook base URL
    webhook_base_url = get_webhook_base_url()
    
    # Check if this is a continuation of the conversation
    is_continuation = request.args.get('is_continuation', 'false').lower() == 'true'
    # Check if user is already authenticated in this session
    is_authenticated = request.args.get('authenticated', 'false').lower() == 'true'
    
    response = VoiceResponse()
    
    # If not authenticated, ask for PIN
    if not is_authenticated and not is_continuation:
        gather = response.gather(
            input='dtmf speech',  # Accept both DTMF (keypad) and speech
            action='/anthropic/convonet_todo/twilio/verify_pin',
            method='POST',
            timeout=10,
            finish_on_key='#'  # Press # to finish (for DTMF), no num_digits requirement
        )
        gather.say("Welcome to Convonet productivity assistant. Please enter or say your 4 to 6 digit PIN, then press pound.", voice='Polly.Amy')
        
        response.say("I didn't receive a PIN. Please try again.", voice='Polly.Amy')
        response.redirect('/anthropic/convonet_todo/twilio/call')
        
        print(f"Generated TwiML for PIN request: {str(response)}")
        return Response(str(response), mimetype='text/xml')
    
    # User is authenticated, proceed with normal conversation
    gather = response.gather(
        input='speech',
            action='/anthropic/convonet_todo/twilio/process_audio',
        method='POST',
        speech_timeout='auto',
        timeout=10,
        barge_in=True
    )
    
    # Only say the welcome message if this is the first authenticated interaction
    if not is_continuation:
        gather.say("How can I help you today?", voice='Polly.Amy')
    
    # Fallback if no speech is detected
    response.say("I didn't hear anything. Please try again.", voice='Polly.Amy')
    response.redirect('/anthropic/convonet_todo/twilio/call?is_continuation=true&authenticated=true')
    
    print(f"Generated TwiML for incoming call: {str(response)}")
    return Response(str(response), mimetype='text/xml')

@convonet_todo_bp.route('/twilio/verify_pin', methods=['POST'])
def verify_pin_webhook():
    """
    Verifies the user's PIN and authenticates the session.
    """
    try:
        # Get PIN from either DTMF digits or speech
        pin = request.form.get('Digits', '') or request.form.get('SpeechResult', '')
        call_sid = request.form.get('CallSid', '')
        
        print(f"Verifying PIN for call {call_sid}: {pin}")
        
        if not pin:
            response = VoiceResponse()
            response.say("I didn't receive a PIN. Please try again.", voice='Polly.Amy')
            response.redirect('/anthropic/convonet_todo/twilio/call')
            return Response(str(response), mimetype='text/xml')
        
        # Convert spoken numbers to digits
        number_words = {
            'zero': '0', 'oh': '0', 'o': '0',
            'one': '1', 'two': '2', 'three': '3', 'four': '4', 'five': '5',
            'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
            'ten': '10', 'eleven': '11', 'twelve': '12'
        }
        
        # Clean up the PIN - remove non-alphanumeric except spaces
        # This handles cases like "1234." from DTMF or "one two three four" from speech
        cleaned_input = pin.strip()
        
        # First, try to extract any digits directly (handles DTMF like "1234" or "1234.")
        digits_only = ''.join(c for c in cleaned_input if c.isdigit())
        
        # If we got digits directly (DTMF input), use them
        if digits_only and len(digits_only) >= 4:
            clean_pin = digits_only
        else:
            # No direct digits, try speech-to-digit conversion
            words = cleaned_input.lower().replace('-', ' ').replace(',', ' ').replace('.', ' ').split()
            converted_digits = []
            for word in words:
                if word in number_words:
                    converted_digits.append(number_words[word])
                elif word.isdigit():
                    converted_digits.append(word)
            clean_pin = ''.join(converted_digits)
        
        print(f"🔧 Original PIN: '{pin}' → Cleaned PIN: '{clean_pin}'")
        
        if not clean_pin or len(clean_pin) < 4 or len(clean_pin) > 6:
            response = VoiceResponse()
            response.say("Invalid PIN format. Please enter a 4 to 6 digit PIN.", voice='Polly.Amy')
            response.redirect('/anthropic/convonet_todo/twilio/call')
            return Response(str(response), mimetype='text/xml')
        
        # Verify PIN - use direct database query (fast, <100ms, avoids Twilio timeout)
        try:
            # Import here to avoid circular import
            from convonet.mcps.local_servers.db_todo import _init_database, SessionLocal
            from convonet.models.user_models import User as UserModel
            
            # Initialize database if needed
            _init_database()
            
            if SessionLocal is None:
                raise Exception("Database not initialized - DB_URI not configured")
            
            # Quick database lookup
            with SessionLocal() as session:
                user = session.query(UserModel).filter(
                    UserModel.voice_pin == clean_pin,
                    UserModel.is_active == True
                ).first()
            
            # Check if authentication succeeded
            if user:
                # Extract user info
                user_id = str(user.id)
                user_name = user.first_name
                
                # Store user ID in session (use call_sid as session key)
                # In production, use Redis or database for session storage
                
                response = VoiceResponse()
                gather = response.gather(
                    input='speech',
                    action=f'/anthropic/convonet_todo/twilio/process_audio?user_id={user_id}',
                    method='POST',
                    speech_timeout='auto',
                    timeout=10,
                    barge_in=True,
                    speech_model='experimental_conversations',  # Better conversational recognition
                    enhanced=True,  # Use enhanced speech recognition
                    language='en-US'  # Explicitly set language
                )
                
                # Welcome message
                gather.say(f"Welcome back, {user_name}! How can I help you today?", voice='Polly.Amy')
                
                response.say("I didn't hear anything. Please try again.", voice='Polly.Amy')
                response.redirect(f'/anthropic/convonet_todo/twilio/call?is_continuation=true&authenticated=true&user_id={user_id}')
                
                print(f"✅ PIN verified for user {user_id} ({user.email})")
                return Response(str(response), mimetype='text/xml')
            else:
                # Invalid PIN
                response = VoiceResponse()
                response.say("Invalid PIN. Please try again.", voice='Polly.Amy')
                response.redirect('/anthropic/convonet_todo/twilio/call')
                print(f"❌ Invalid PIN: {clean_pin}")
                return Response(str(response), mimetype='text/xml')
        
        except Exception as e:
            print(f"Error in database query: {e}")
            import traceback
            traceback.print_exc()
            response = VoiceResponse()
            response.say("There was an error verifying your PIN. Please try again.", voice='Polly.Amy')
            response.redirect('/anthropic/convonet_todo/twilio/call')
            return Response(str(response), mimetype='text/xml')
            
    except Exception as e:
        print(f"Error in verify_pin_webhook: {e}")
        import traceback
        traceback.print_exc()
        response = VoiceResponse()
        response.say("Sorry, there was a system error. Please try again.", voice='Polly.Amy')
        response.redirect('/anthropic/convonet_todo/twilio/call')
        return Response(str(response), mimetype='text/xml')

@convonet_todo_bp.route('/twilio/transfer', methods=['POST'])
def transfer_to_agent():
    """
    Transfer the call to a FreePBX extension/queue.
    Expects POST parameters:
    - extension: The FreePBX extension or queue number to transfer to
    - call_sid: The Twilio Call SID
    """
    try:
        extension = request.form.get('extension') or request.args.get('extension', '2001')
        call_sid = request.form.get('CallSid', '')
        caller_number = request.form.get('From', '')
        
        logger.info(f"Transferring call {call_sid} from {caller_number} to extension {extension}")
        
        # Create TwiML response for transfer
        response = VoiceResponse()
        response.say("Transferring you to an agent. Please wait.", voice='Polly.Amy')
        
        # Get configuration
        freepbx_domain = os.getenv('FREEPBX_DOMAIN', '136.115.41.45')
        transfer_timeout = int(os.getenv('TRANSFER_TIMEOUT', '30'))
        sip_username = os.getenv('FREEPBX_SIP_USERNAME', '')
        sip_password = os.getenv('FREEPBX_SIP_PASSWORD', '')
        
        # Build SIP URI for FusionPBX extension
        # FusionPBX routing: Use 'internal' context for extension routing
        # The 'internal' context is where FusionPBX routes calls to extensions
        sip_context = os.getenv('FREEPBX_SIP_CONTEXT', 'internal')  # Default to 'internal' context
        sip_uri = f"sip:{extension}@{sip_context};transport=udp"
        logger.info(f"Transferring to SIP URI: {sip_uri}")
        logger.info(f"FusionPBX Domain: {freepbx_domain}, Extension: {extension}, Context: {sip_context}")
        logger.info(f"Transfer Timeout: {transfer_timeout} seconds")
        
        # Create Dial verb with transfer settings
        dial = response.dial(
            answer_on_bridge=True,  # Wait for agent to answer before connecting
            timeout=transfer_timeout,
            caller_id=caller_number,
            action=f'/anthropic/convonet_todo/twilio/transfer_callback?extension={extension}'
        )
        
        # Add SIP destination
        if sip_username and sip_password:
            # Use SIP authentication if configured
            dial.sip(sip_uri, username=sip_username, password=sip_password)
            logger.info(f"Using SIP auth with username: {sip_username}")
        else:
            # Use IP-based authentication (requires FusionPBX to whitelist Twilio IPs)
            dial.sip(sip_uri)
            logger.info("Using IP-based SIP authentication (FusionPBX must whitelist Twilio IPs)")
            logger.warning("⚠️ If transfer fails, configure FusionPBX to accept SIP from Twilio IP ranges:")
            logger.warning("   54.172.60.0/23, 54.244.51.0/24, 177.71.206.192/26, 54.252.254.64/26, 54.169.127.128/26")
        
        # If dial fails, provide fallback message
        response.say("I'm sorry, the transfer failed. Please try again later.", voice='Polly.Amy')
        response.hangup()
        
        logger.info(f"Transfer TwiML generated for call {call_sid}")
        logger.info(f"TwiML content: {str(response)}")
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"Error in transfer endpoint: {e}")
        import traceback
        traceback.print_exc()
        
        response = VoiceResponse()
        response.say("I'm sorry, there was an error transferring your call. Please try again.", voice='Polly.Amy')
        response.hangup()
        return Response(str(response), mimetype='text/xml')

@convonet_todo_bp.route('/twilio/transfer_callback', methods=['POST'])
def transfer_callback():
    """
    Callback handler for transfer status.
    Logs transfer results and handles failures.
    """
    try:
        dial_call_status = request.form.get('DialCallStatus', 'unknown')
        call_sid = request.form.get('CallSid', '')
        extension = request.args.get('extension', '2001')
        
        logger.info(f"Transfer callback for call {call_sid}: status={dial_call_status}, extension={extension}")
        
        response = VoiceResponse()
        
        if dial_call_status == 'completed':
            # Transfer succeeded - call is now connected to agent
            logger.info(f"✅ Transfer successful for call {call_sid} to extension {extension}")
            # Call will continue on the agent side
            
        elif dial_call_status == 'busy':
            response.say("The agent is currently busy. Please try again later.", voice='Polly.Amy')
            response.hangup()
            logger.warning(f"⚠️ Transfer failed - agent busy: call {call_sid}")
            
        elif dial_call_status == 'no-answer':
            response.say("The agent did not answer. Please try again later.", voice='Polly.Amy')
            response.hangup()
            logger.warning(f"⚠️ Transfer failed - no answer: call {call_sid}")
            
        elif dial_call_status == 'failed' or dial_call_status == 'canceled':
            # Get more details about the failure
            dial_call_sid = request.form.get('DialCallSid', 'N/A')
            dial_call_duration = request.form.get('DialCallDuration', 'N/A')
            error_message = request.form.get('ErrorMessage', 'No error details')
            
            logger.error(f"❌ Transfer failed: call {call_sid}, status={dial_call_status}")
            logger.error(f"   Dial Call SID: {dial_call_sid}")
            logger.error(f"   Dial Duration: {dial_call_duration} seconds")
            logger.error(f"   Error Message: {error_message}")
            logger.error(f"   Possible causes:")
            logger.error(f"   1. FusionPBX is not accepting SIP from Twilio IP ranges")
            logger.error(f"   2. Firewall blocking SIP traffic on port 5060")
            logger.error(f"   3. Extension {extension} does not exist or is not reachable")
            logger.error(f"   4. FusionPBX requires SIP authentication (set FREEPBX_SIP_USERNAME and FREEPBX_SIP_PASSWORD)")
            
            response.say("The transfer could not be completed. Please call back later.", voice='Polly.Amy')
            response.hangup()
            
        else:
            response.say("An unexpected error occurred. Please try again.", voice='Polly.Amy')
            response.hangup()
            logger.error(f"❌ Unknown transfer status: {dial_call_status} for call {call_sid}")
        
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        logger.error(f"Error in transfer callback: {e}")
        import traceback
        traceback.print_exc()
        
        response = VoiceResponse()
        response.say("An error occurred. Goodbye.", voice='Polly.Amy')
        response.hangup()
        return Response(str(response), mimetype='text/xml')


@convonet_todo_bp.route('/twilio/voice_assistant/transfer_bridge', methods=['GET', 'POST'])
def voice_assistant_transfer_bridge():
    """
    TwiML endpoint used by the WebRTC voice assistant to connect callers directly
    to a FusionPBX/SIP extension instead of a conference bridge.
    """
    # Handle GET requests for testing
    if request.method == 'GET':
        extension = request.args.get('extension', '2001')
        logger.info(f"[VoiceAssistantBridge] GET request received - testing endpoint with extension={extension}")
        return jsonify({
            'status': 'ok',
            'endpoint': 'transfer_bridge',
            'extension': extension,
            'message': 'Endpoint is accessible. Use POST for actual transfers.'
        }), 200
    
    try:
        extension = request.args.get('extension') or request.form.get('extension') or '2001'
        call_sid = request.form.get('CallSid', '')
        caller_number = request.form.get('From') or os.getenv('TWILIO_PHONE_NUMBER', '')
        
        logger.info(f"[VoiceAssistantBridge] ===== TRANSFER BRIDGE CALLED =====")
        logger.info(f"[VoiceAssistantBridge] Call SID: {call_sid}")
        logger.info(f"[VoiceAssistantBridge] Extension: {extension}")
        logger.info(f"[VoiceAssistantBridge] Caller: {caller_number}")
        logger.info(f"[VoiceAssistantBridge] Request method: {request.method}")
        logger.info(f"[VoiceAssistantBridge] Request URL: {request.url}")
        logger.info(f"[VoiceAssistantBridge] Request args: {dict(request.args)}")
        logger.info(f"[VoiceAssistantBridge] Request form: {dict(request.form)}")
        logger.info(f"[VoiceAssistantBridge] Request headers: {dict(request.headers)}")
        
        freepbx_domain = os.getenv('FREEPBX_DOMAIN', '136.115.41.45')
        transfer_timeout = int(os.getenv('TRANSFER_TIMEOUT', '30'))
        sip_username = os.getenv('FREEPBX_SIP_USERNAME', '')
        sip_password = os.getenv('FREEPBX_SIP_PASSWORD', '')
        
        # FusionPBX routing: Use 'internal' context for extension routing
        # The 'internal' context is where FusionPBX routes calls to extensions
        # If this doesn't work, try: sip:{extension}@{freepbx_domain};transport=udp
        sip_context = os.getenv('FREEPBX_SIP_CONTEXT', 'internal')  # Default to 'internal' context
        sip_uri = f"sip:{extension}@{sip_context};transport=udp"
        logger.info(f"[VoiceAssistantBridge] Using SIP context: {sip_context} (set FREEPBX_SIP_CONTEXT to change)")
        
        logger.info(f"[VoiceAssistantBridge] Dialing {sip_uri} for call {call_sid}")
        logger.info(f"[VoiceAssistantBridge] FusionPBX Domain: {freepbx_domain}")
        logger.info(f"[VoiceAssistantBridge] Transfer Timeout: {transfer_timeout} seconds")
        
        # Get base URL for absolute callback URL
        webhook_base_url = get_webhook_base_url()
        callback_url = f"{webhook_base_url}/anthropic/convonet_todo/twilio/transfer_callback?extension={extension}"
        logger.info(f"[VoiceAssistantBridge] Callback URL: {callback_url}")
        
        response = VoiceResponse()
        dial = response.dial(
            answer_on_bridge=True,
            timeout=transfer_timeout,
            caller_id=caller_number,
            action=callback_url  # Use absolute URL
        )
        
        if sip_username and sip_password:
            dial.sip(sip_uri, username=sip_username, password=sip_password)
            logger.info(f"[VoiceAssistantBridge] Using SIP authentication (username: {sip_username})")
        else:
            dial.sip(sip_uri)
            logger.info("[VoiceAssistantBridge] Using IP-based SIP authentication")
            logger.warning("[VoiceAssistantBridge] ⚠️ FusionPBX must whitelist Twilio IP ranges for IP-based auth")
        
        # Fallback message if dial fails
        response.say("I'm sorry, the transfer failed. Please try again later.", voice='Polly.Amy')
        response.hangup()
        
        twiml_content = str(response)
        logger.info(f"[VoiceAssistantBridge] Generated TwiML for call {call_sid}")
        logger.info(f"[VoiceAssistantBridge] TwiML preview: {twiml_content[:200]}...")
        
        return Response(twiml_content, mimetype='text/xml')
    
    except Exception as e:
        logger.error(f"[VoiceAssistantBridge] ❌ Error connecting to agent: {e}")
        import traceback
        logger.error(f"[VoiceAssistantBridge] Traceback: {traceback.format_exc()}")
        
        response = VoiceResponse()
        response.say("I'm sorry, there was an error connecting you to an agent. Please try again later.", voice='Polly.Amy')
        response.hangup()
        return Response(str(response), mimetype='text/xml')

@convonet_todo_bp.route('/twilio/process_audio', methods=['POST'])
def process_audio_webhook():
    """
    Handles audio processing requests from Twilio.
    Processes the audio and returns TwiML with the agent's response.
    
    Features:
    - Barge-in capability: Users can interrupt the agent while it's speaking
    - Continuous conversation flow
    - Graceful error handling
    """
    # Start Sentry transaction for performance monitoring
    with sentry_sdk.start_transaction(op="voice_call", name="process_audio") as transaction:
        try:
            # Get the transcribed text from the request
            transcribed_text = request.form.get('SpeechResult', '')
            call_sid = request.form.get('CallSid', '')
            user_id = request.args.get('user_id')
            
            # Set Sentry context for this call
            sentry_sdk.set_context("voice_call", {
                "call_sid": call_sid,
                "user_id": user_id,
                "transcribed_text": transcribed_text[:100]  # First 100 chars
            })
            sentry_sdk.set_user({"id": user_id} if user_id else None)
        
            print(f"Processing audio for call {call_sid}: {transcribed_text}")
        
            if not transcribed_text or len(transcribed_text.strip()) < 2:
                response = VoiceResponse()
                
                # Get authenticated user_id for redirect
                user_param = f'&user_id={user_id}' if user_id else ''
                
                # Use Gather with barge-in for "didn't catch that" response
                gather = Gather(
                    input='speech',
                    action=f'/anthropic/convonet_todo/twilio/process_audio?user_id={user_id}' if user_id else '/anthropic/convonet_todo/twilio/process_audio',
                    method='POST',
                    speech_timeout='auto',
                    timeout=10,
                    barge_in=True,
                    speech_model='experimental_conversations',  # Better conversational recognition
                    enhanced=True,  # Use enhanced speech recognition
                    language='en-US'  # Explicitly set language
                )
                gather.say("I didn't catch that. Could you please repeat?", voice='Polly.Amy')
                response.append(gather)
                
                # Fallback
                response.say("I didn't hear anything. Please try again.", voice='Polly.Amy')
                response.redirect(f'/anthropic/convonet_todo/twilio/call?is_continuation=true&authenticated=true{user_param}')
                return Response(str(response), mimetype='text/xml')
            
            transfer_requested = has_transfer_intent(transcribed_text)
            if transfer_requested:
                webhook_base_url = get_webhook_base_url()
                response = VoiceResponse()
                response.redirect(f'{webhook_base_url}/anthropic/convonet_todo/twilio/transfer?extension=2001')
                logger.info(f"Redirecting call to transfer endpoint based on user request: {transcribed_text}")
                return Response(str(response), mimetype='text/xml')
            
            # Check if user wants to end the call
            exit_phrases = ['exit', 'goodbye', 'bye', 'that\'s it', 'that is it', 'thank you', 'thanks', 'done', 'finished', 'end call', 'hang up']
            if any(phrase in transcribed_text.lower() for phrase in exit_phrases):
                # End the call gracefully
                response = VoiceResponse()
                response.say("Thank you for using Convonet productivity assistant! Have a great day!", voice='Polly.Amy')
                response.hangup()
                return Response(str(response), mimetype='text/xml')
            
            # Check if this user's thread needs to be reset (after previous timeout/error)
            reset_thread = False
            if user_id and hasattr(_run_agent_async, '_reset_threads') and user_id in _run_agent_async._reset_threads:
                reset_thread = True
                _run_agent_async._reset_threads.remove(user_id)
                print(f"🔄 Resetting conversation thread for user {user_id} (previous timeout/error)")
                print(f"🔄 Reset threads set contains: {_run_agent_async._reset_threads}")
                
                # Track thread reset in Sentry
                sentry_sdk.capture_message(
                    "Conversation thread reset after timeout/error",
                    level="info",
                    extras={"user_id": user_id}
                )
        
            # Process with the agent (with timeout to prevent hanging)
            # Note: Twilio HTTP timeout is ~15 seconds, so we must respond faster
            start_time = time.time()
            transfer_marker = None
            
            with sentry_sdk.start_span(op="agent_processing", description="LangGraph agent execution"):
                try:
                    agent_result = asyncio.run(asyncio.wait_for(
                        _run_agent_async(
                            transcribed_text,
                            user_id=user_id,
                            reset_thread=reset_thread,
                            include_metadata=True
                        ),
                        timeout=12.0  # Reduced from 30 to 12 seconds to stay under Twilio's 15s timeout
                    ))
                    if isinstance(agent_result, dict):
                        agent_response = agent_result.get("response", "")
                        transfer_marker = agent_result.get("transfer_marker")
                    else:
                        agent_response = agent_result
                        transfer_marker = None
                    processing_time = time.time() - start_time
                    sentry_sdk.set_measurement("agent_processing_time", processing_time, "second")
                except asyncio.TimeoutError:
                    processing_time = time.time() - start_time
                    print(f"⏰ Outer timeout: Agent took more than 12 seconds (actual: {processing_time:.2f}s)")
                    
                    # Track timeout in Sentry
                    sentry_sdk.capture_message(
                        "Agent processing timeout",
                        level="warning",
                        extras={
                            "user_id": user_id,
                            "call_sid": call_sid,
                            "prompt": transcribed_text,
                            "timeout_duration": processing_time
                        }
                    )
                    
                    # Mark user for thread reset
                    if user_id:
                        if not hasattr(_run_agent_async, '_reset_threads'):
                            _run_agent_async._reset_threads = set()
                        _run_agent_async._reset_threads.add(user_id)
                        print(f"🔄 Marked user {user_id} for thread reset")
                    agent_response = "I'm sorry, that operation is taking too long. The task may still complete in the background. Please check your calendar or todo list."
                except Exception as e:
                    processing_time = time.time() - start_time
                    print(f"Error in agent processing (outer): {e}")
                    
                    # Capture exception in Sentry
                    sentry_sdk.capture_exception(e)
                    
                    agent_response = f"AGENT_ERROR:unexpected:{str(e)[:100]}"
        
            # Check if agent returned an error marker and handle accordingly
            if agent_response.startswith("AGENT_TIMEOUT:"):
                print(f"⏰ Agent timed out internally")
                if user_id:
                    if not hasattr(_run_agent_async, '_reset_threads'):
                        _run_agent_async._reset_threads = set()
                    _run_agent_async._reset_threads.add(user_id)
                    print(f"🔄 Marked user {user_id} for thread reset")
                agent_response = "I'm sorry, that operation is taking too long. Please try a simpler request."
                
            elif agent_response.startswith("AGENT_ERROR:"):
                # Parse error type and message
                parts = agent_response.split(":", 2)
                error_type = parts[1] if len(parts) > 1 else "unknown"
                error_msg = parts[2] if len(parts) > 2 else ""
                
                print(f"🔧 Agent returned error: type={error_type}, msg={error_msg}")
                
                # Track error in Sentry
                sentry_sdk.capture_message(
                    f"Agent error: {error_type}",
                    level="error",
                    extras={
                        "error_type": error_type,
                        "error_message": error_msg,
                        "user_id": user_id,
                        "call_sid": call_sid
                    }
                )
                
                # Mark user for thread reset on these error types
                if error_type in ["tool_call_incomplete", "broken_resource"]:
                    if user_id:
                        if not hasattr(_run_agent_async, '_reset_threads'):
                            _run_agent_async._reset_threads = set()
                        _run_agent_async._reset_threads.add(user_id)
                        print(f"🔄 Marked user {user_id} for thread reset due to {error_type}")
                
                # User-friendly messages
                if error_type == "tool_call_incomplete":
                    agent_response = "I had trouble with the previous operation. Please try your request again."
                elif error_type == "broken_resource":
                    agent_response = "I encountered a connection issue. The operation may have completed. Please check your calendar or todo list."
                else:
                    agent_response = "I'm sorry, I encountered an error. Please try again or rephrase your question."
            
            # Check if agent response indicates a transfer request
            transfer_marker_value = transfer_marker
            if not transfer_marker_value and isinstance(agent_response, str) and agent_response.startswith("TRANSFER_INITIATED:"):
                transfer_marker_value = agent_response
            
            if transfer_marker_value:
                if not transfer_requested:
                    logger.info("Transfer marker detected but caller did not request a human. Suppressing automatic transfer.")
                    transfer_marker_value = None
                else:
                    transfer_data = transfer_marker_value.replace("TRANSFER_INITIATED:", "")
                    parts = transfer_data.split("|")
                    target_extension = parts[0] if len(parts) > 0 else "2001"
                    
                    webhook_base_url = get_webhook_base_url()
                    response = VoiceResponse()
                    response.redirect(f'{webhook_base_url}/anthropic/convonet_todo/twilio/transfer?extension={target_extension}')
                    logger.info(f"Agent initiated transfer to extension {target_extension}")
                    if user_id:
                        if not hasattr(_run_agent_async, '_reset_threads'):
                            _run_agent_async._reset_threads = set()
                        _run_agent_async._reset_threads.add(user_id)
                    return Response(str(response), mimetype='text/xml')
            
            # Return TwiML with the agent's response and barge-in capability
            response = VoiceResponse()
            
            # Preserve user_id in redirects
            user_param = f'?user_id={user_id}' if user_id else ''
            auth_param = f'&authenticated=true' if user_id else ''
            
            # Enhanced Twilio speech recognition configuration
            gather = Gather(
                input='speech',
                action=f'/anthropic/convonet_todo/twilio/process_audio{user_param}',
                method='POST',
                speech_timeout='auto',
                timeout=15,  # Increased from 10s
                barge_in=True,
                speech_model='experimental_conversations',
                enhanced=True,
                language='en-US',
                # Add speech hints for better recognition
                speech_hints='create todo reminder calendar team member assign task complete delete update schedule meeting appointment'
            )
        
            # Add the agent's response to the gather
            gather.say(agent_response, voice='Polly.Amy')
            response.append(gather)
            
            # Fallback if no speech is detected after the response
            response.say("I didn't hear anything. Please try again.", voice='Polly.Amy')
            response.redirect(f'/anthropic/convonet_todo/twilio/call?is_continuation=true{auth_param}{user_param}')
            
            print(f"Generated TwiML response: {str(response)}")
            return Response(str(response), mimetype='text/xml')
            
        except Exception as e:
            print(f"Error processing audio: {e}")
            sentry_sdk.capture_exception(e)
            response = VoiceResponse()
            
            # Preserve user_id in error redirects
            user_param = f'?user_id={user_id}' if user_id else ''
            auth_param = f'&authenticated=true' if user_id else ''
            
            # Use Gather with barge-in for error messages too
            gather = Gather(
                input='speech',
                action=f'/anthropic/convonet_todo/twilio/process_audio{user_param}',
                method='POST',
                speech_timeout='auto',
                timeout=10,
                barge_in=True
            )
            gather.say("I'm sorry, I encountered an error processing your request. Please try again.", voice='Polly.Amy')
            response.append(gather)
            
            # Fallback
            response.say("I didn't hear anything. Please try again.", voice='Polly.Amy')
            response.redirect(f'/anthropic/convonet_todo/twilio/call?is_continuation=true{auth_param}{user_param}')
            return Response(str(response), mimetype='text/xml')

# WebSocket server is now handled by a separate process
# See websocket_server.py for the Twilio voice streaming implementation

# --- Web/API Routes ---
@convonet_todo_bp.route('/')
def index():
    template_path = os.path.join(os.path.dirname(__file__), 'templates', 'convonet_todo_index.html')
    if os.path.exists(template_path):
        return render_template('convonet_todo_index.html')
    return "Convonet Todo: Convonet + MCP integration is ready. POST to /anthropic/convonet_todo/run_agent with JSON {prompt: str}."


async def _get_agent_graph() -> StateGraph:
    """Helper to initialize the agent graph with tools (cached for performance)."""
    global _agent_graph_cache, _agent_graph_model
    
    # Get current model name (from env var or default)
    # Use actual model ID from Anthropic API
    current_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    
    # Return cached graph if available AND model hasn't changed
    if _agent_graph_cache is not None and _agent_graph_model == current_model:
        print(f"♻️ Using cached agent graph (model: {current_model})")
        return _agent_graph_cache
    
    # Clear cache if model changed
    if _agent_graph_cache is not None and _agent_graph_model != current_model:
        print(f"🔄 Model changed from {_agent_graph_model} to {current_model}, clearing cache")
        _agent_graph_cache = None
        _agent_graph_model = None
    
    # Use lock to prevent multiple simultaneous initializations
    async with _agent_graph_lock:
        # Check again after acquiring lock (another thread might have initialized)
        if _agent_graph_cache is not None:
            return _agent_graph_cache
        
        print("🔧 Initializing agent graph (first time only)...")
        
        config_path = os.path.join(os.path.dirname(__file__), 'mcps', 'mcp_config.json')
        if not os.path.exists(config_path):
            # Fallback path for when running from the root directory
            config_path = os.path.join('convonet', 'mcps', 'mcp_config.json')
        
        if not os.path.exists(config_path):
            error_msg = f"❌ MCP config file not found. Tried: {os.path.join(os.path.dirname(__file__), 'mcps', 'mcp_config.json')} and {config_path}"
            print(error_msg)
            raise FileNotFoundError(error_msg)

        with open(config_path) as f:
            mcp_config = json.load(f)
        
        # Set working directory to project root for MCP servers
        # __file__ is: /Users/hj/Web Development Projects/1. Main/convonet/routes.py
        # We need: /Users/hj/Web Development Projects/1. Main
        project_root = os.path.dirname(os.path.dirname(__file__))
        original_cwd = os.getcwd()
        os.chdir(project_root)
        
        # Update the MCP config with absolute paths and environment variables
        for server_name, server_config in mcp_config["mcpServers"].items():
            if "args" in server_config and len(server_config["args"]) > 0:
                # Convert relative path to absolute path
                relative_path = server_config["args"][0]
                if not os.path.isabs(relative_path):
                    absolute_path = os.path.join(project_root, relative_path)
                    server_config["args"][0] = absolute_path
            
            # Handle environment variable substitution in env section
            if "env" in server_config:
                for env_key, env_value in server_config["env"].items():
                    if isinstance(env_value, str) and env_value.startswith("${") and env_value.endswith("}"):
                        # Extract environment variable name
                        env_var_name = env_value[2:-1]
                        env_var_value = os.getenv(env_var_name)
                        if env_var_value:
                            server_config["env"][env_key] = env_var_value
                            print(f"🔧 MCP config: Set {env_key}={env_var_name} from environment")
                        else:
                            print(f"⚠️  MCP config: Environment variable {env_var_name} not found")
        
        # Initialize tools list to avoid UnboundLocalError
        tools = []
        
        try:
            # Initialize MCP client (langchain-mcp-adapters 0.1.0+ does not support context manager)
            print("🔧 Creating MCP client...")
            client = MultiServerMCPClient(connections=mcp_config["mcpServers"])
            print("🔧 Getting tools from MCP client...")
            # Wrap in a task to better catch exceptions from nested coroutines
            try:
                # Create a wrapper function to catch any exceptions from nested coroutines
                async def safe_get_tools():
                    try:
                        return await client.get_tools()
                    except (UnboundLocalError, NameError) as e:
                        # Re-raise as a different exception type so we can catch it
                        raise RuntimeError(f"MCP library UnboundLocalError: {e}") from e
                    except Exception as e:
                        error_str = str(e)
                        if "UnboundLocalError" in error_str or "cannot access local variable 'tools'" in error_str:
                            raise RuntimeError(f"MCP library UnboundLocalError (wrapped): {e}") from e
                        raise
                
                tools = await asyncio.wait_for(safe_get_tools(), timeout=10.0)
                print(f"✅ MCP client initialized successfully with {len(tools)} tools")
            except RuntimeError as e:
                # Catch our wrapped UnboundLocalError
                if "UnboundLocalError" in str(e):
                    print(f"⚠️ MCP library error (UnboundLocalError): {e}")
                    print("⚠️ Continuing with empty tools list")
                    tools = []  # Ensure tools is set to empty list
                else:
                    raise
            except (UnboundLocalError, NameError) as e:
                # Handle library bug where tools variable is referenced before assignment
                print(f"⚠️ MCP library error (UnboundLocalError/NameError): {e}")
                print("⚠️ Continuing with empty tools list")
                tools = []  # Ensure tools is set to empty list
            except Exception as e:
                # Check if the error message contains UnboundLocalError (might be wrapped)
                error_str = str(e)
                if "UnboundLocalError" in error_str or "cannot access local variable 'tools'" in error_str:
                    print(f"⚠️ MCP library error (wrapped UnboundLocalError): {e}")
                    print("⚠️ Continuing with empty tools list")
                    tools = []  # Ensure tools is set to empty list
                else:
                    # Handle any other errors from get_tools()
                    print(f"⚠️ Error getting MCP tools: {e}")
                    print("⚠️ Continuing with empty tools list")
                    tools = []  # Ensure tools is set to empty list
            
            # Add call transfer tools (non-MCP tools) - optional
            try:
                from .mcps.local_servers.call_transfer import get_transfer_tools
                transfer_tools = get_transfer_tools()
                tools.extend(transfer_tools)
                print(f"✅ Added {len(transfer_tools)} call transfer tools")
            except ImportError as e:
                print(f"⚠️ Call transfer tools not available: {e}")
                print("⚠️ Continuing without call transfer tools")
            except Exception as e:
                print(f"⚠️ Failed to load call transfer tools: {e}")
                print("⚠️ Continuing without call transfer tools")
            
            # Add Composio integration tools (optional)
            try:
                from .composio_tools import get_all_integration_tools, test_composio_connection
                if test_composio_connection():
                    composio_tools = get_all_integration_tools()
                    tools.extend(composio_tools)
                    print(f"✅ Added {len(composio_tools)} Composio integration tools")
                else:
                    print("⚠️ Composio connection test failed, skipping external integrations")
            except ImportError as e:
                print(f"⚠️ Composio not available: {e}")
                print("⚠️ Continuing without external integrations")
            except Exception as e:
                print(f"⚠️ Failed to load Composio tools: {e}")
                print("⚠️ Continuing without external integrations")
            
        except asyncio.TimeoutError:
            print("❌ MCP client initialization timed out after 10 seconds")
            # Continue with empty tools list instead of raising
            print("⚠️ Continuing with empty tools list")
            tools = []
        except (UnboundLocalError, NameError) as e:
            # Handle library bug where tools variable is referenced before assignment
            print(f"❌ MCP library error (UnboundLocalError/NameError): {e}")
            print("⚠️ Continuing with empty tools list")
            tools = []  # Ensure tools is set to empty list
        except Exception as e:
            error_str = str(e)
            # Check if the error is related to tools variable
            if "UnboundLocalError" in error_str or "cannot access local variable 'tools'" in error_str:
                print(f"❌ MCP library error (wrapped UnboundLocalError): {e}")
                print("⚠️ Continuing with empty tools list")
                tools = []  # Ensure tools is set to empty list
            else:
                print(f"❌ Error initializing MCP client: {e}")
                print(f"❌ Error type: {type(e)}")
                import traceback
                print(f"❌ Traceback: {traceback.format_exc()}")
                print("⚠️ Continuing with empty tools list")
                tools = []  # Ensure tools is set to empty list
        
        # Build agent graph with whatever tools we have (even if empty)
        # This ensures we always try to build the graph, even if MCP tools failed
        try:
            print(f"🔧 Building agent graph with {len(tools)} tools...")
            print(f"🔧 Using model: {current_model} (from env var or default)")
            # Explicitly pass the model to ensure it uses the current env var value
            _agent_graph_cache = TodoAgent(tools=tools, model=current_model).build_graph()
            _agent_graph_model = current_model  # Store the model used for this cache
            print(f"✅ Agent graph cached for future requests (model: {current_model})")
            return _agent_graph_cache
        except Exception as e:
            print(f"❌ Error building agent graph: {e}")
            import traceback
            print(f"❌ Traceback: {traceback.format_exc()}")
            # Don't raise - try to build with empty tools as last resort
            print("⚠️ Attempting to build graph with empty tools list as fallback...")
            try:
                _agent_graph_cache = TodoAgent(tools=[]).build_graph()
                _agent_graph_model = current_model  # Store the model used for this cache
                print(f"✅ Agent graph built with empty tools list (fallback, model: {current_model})")
                return _agent_graph_cache
            except Exception as fallback_error:
                print(f"❌ Even fallback graph building failed: {fallback_error}")
                raise Exception(f"Failed to build agent graph even with empty tools: {str(e)}")
        finally:
            os.chdir(original_cwd)


async def _run_agent_for_pin_verification(pin: str) -> str:
    """Run agent specifically for PIN verification."""
    try:
        agent_graph = await _get_agent_graph()
        
        # Create a state that will trigger verify_user_pin tool
        input_state = AgentState(
            messages=[HumanMessage(content=f"User is authenticating with PIN: {pin}. Please verify their PIN using the verify_user_pin tool.")],
            customer_id="",
            is_authenticated=False
        )
        config = {"configurable": {"thread_id": f"pin-verify-{pin}"}}
        
        # Stream through the graph
        stream = agent_graph.astream(input=input_state, stream_mode="values", config=config)
        
        async def process_stream():
            tool_result = None
            async for state in stream:
                # Look for tool messages which contain the actual verification result
                if "messages" in state:
                    for msg in state["messages"]:
                        # Check if this is a ToolMessage with our authentication result
                        if hasattr(msg, 'content') and 'AUTHENTICATED:' in str(msg.content):
                            tool_result = msg.content
                            break
            
            # Return the tool result if found, otherwise authentication failed
            if tool_result:
                return tool_result
            return "AUTHENTICATION_FAILED: Invalid PIN"
        
        return await asyncio.wait_for(process_stream(), timeout=20.0)
    except asyncio.TimeoutError:
        print(f"PIN verification timeout for PIN: {pin}")
        return "AUTHENTICATION_FAILED: Verification timeout"
    except Exception as e:
        print(f"Error in PIN verification: {e}")
        import traceback
        traceback.print_exc()
        return f"AUTHENTICATION_ERROR: {str(e)}"

async def _run_agent_async(
    prompt: str,
    user_id: Optional[str] = None,
    user_name: Optional[str] = None,
    reset_thread: bool = False,
    include_metadata: bool = False
) -> str | dict:
    """Runs the agent for a given prompt and returns the final response.
    
    Args:
        prompt: User's input text
        user_id: Authenticated user ID
        user_name: User's display name
        reset_thread: If True, starts a new conversation thread (used after timeouts/errors)
    """
    try:
        agent_graph = await _get_agent_graph()
    except Exception as e:
        print(f"❌ Failed to initialize agent: {e}")
        lower_prompt = prompt.lower()
        fallback_extension = os.getenv('VOICE_AGENT_FALLBACK_EXTENSION', '2001')
        fallback_department = os.getenv('VOICE_AGENT_FALLBACK_DEPARTMENT', 'support')
        transfer_keywords = [
            "transfer",
            "speak to a human",
            "human agent",
            "talk to an agent",
            "representative",
            "customer service",
            "live agent"
        ]
        if any(keyword in lower_prompt for keyword in transfer_keywords):
            reason = "Automated transfer triggered due to assistant service interruption"
            print(f"🔄 Fallback transfer to extension {fallback_extension} ({fallback_department}) because agent initialization failed.")
            return f"TRANSFER_INITIATED:{fallback_extension}|{fallback_department}|{reason}"
        return "I'm sorry, there's a temporary system issue. Please try again in a moment."

    input_state = AgentState(
        messages=[HumanMessage(content=prompt)],
        customer_id="",
        authenticated_user_id=user_id,
        authenticated_user_name=user_name,
        is_authenticated=bool(user_id)
    )
    
    # Use timestamped thread ID after errors to start fresh conversation
    thread_suffix = f"-{int(time.time())}" if reset_thread else ""
    thread_id = f"user-{user_id}{thread_suffix}" if user_id else f"flask-thread-1{thread_suffix}"
    config = {"configurable": {"thread_id": thread_id}}
    
    # Debug logging
    if reset_thread:
        print(f"🆕 Using FRESH thread_id: {thread_id} (reset=True)")
    else:
        print(f"📝 Using existing thread_id: {thread_id} (reset=False)")

    # Stream through the graph to execute the agent logic with timeout
    try:
        # Create the async iterator first
        stream = agent_graph.astream(input=input_state, stream_mode="values", config=config)
        
        # Use wait_for to wrap the entire async for loop
        async def process_stream():
            transfer_marker = None
            
            # Check each state update for transfer markers in tool results
            async for state in stream:
                if "messages" in state:
                    for msg in state["messages"]:
                        # Check for TRANSFER_INITIATED in tool message content
                        if hasattr(msg, 'content') and isinstance(msg.content, str):
                            if 'TRANSFER_INITIATED:' in msg.content:
                                transfer_marker = msg.content
                                print(f"🔄 Transfer marker detected in tool result: {transfer_marker}")
            
            # Get final state and last message
            final_state = agent_graph.get_state(config=config)
            last_message = final_state.values.get("messages")[-1]
            final_response = getattr(last_message, 'content', "")
            
            # If transfer marker was found, return it (for WebRTC transfer detection)
            # Otherwise return the final response
            if include_metadata:
                return {
                    "response": final_response,
                    "transfer_marker": transfer_marker
                }
            if transfer_marker:
                return transfer_marker
            return final_response
        
        return await asyncio.wait_for(process_stream(), timeout=20.0)  # Increased to 20 seconds for multiple tool execution
    except asyncio.TimeoutError:
        # Return a special marker for timeout
        return "AGENT_TIMEOUT: Taking too long to process. Please try a simpler request."
    except Exception as e:
        print(f"Error in agent execution: {e}")
        error_str = str(e)
        
        # Check if it's a model 404 error - if so, clear cache and retry once
        # Check for various 404 error patterns
        is_model_404 = (
            "MODEL_404_ERROR" in error_str or 
            ("404" in error_str and ("model" in error_str.lower() or "not_found_error" in error_str)) or
            ("not_found_error" in error_str and "model:" in error_str.lower())
        )
        if is_model_404:
            print("🔄 Model 404 error detected, clearing cache and retrying...")
            print(f"🔄 Error details: {error_str[:200]}")
            global _agent_graph_cache, _agent_graph_model
            
            # Extract the failed model name from error
            failed_model = None
            if "model:" in error_str.lower():
                # Try to extract model name from error message
                import re
                model_match = re.search(r"model:\s*([^\s,}']+)", error_str, re.IGNORECASE)
                if model_match:
                    failed_model = model_match.group(1).strip()
                    print(f"🔄 Detected failed model: {failed_model}")
            
            _agent_graph_cache = None
            _agent_graph_model = None
            
            # Force a different model by setting env var to a known working model
            # Skip the failed model and try others (using actual model IDs from API)
            original_model = os.getenv("ANTHROPIC_MODEL")
            fallback_models = [
                "claude-sonnet-4-20250514",  # Claude Sonnet 4 (confirmed available)
                "claude-3-7-sonnet-20250219",  # Claude Sonnet 3.7 (confirmed available)
                "claude-3-opus-20240229",  # Claude Opus 3 (confirmed available)
                "claude-sonnet-4-5-20250929",  # Claude Sonnet 4.5 (newer)
            ]
            
            # Find a model that's different from the failed one and the original
            next_model = None
            for model in fallback_models:
                if model != failed_model and model != original_model:
                    next_model = model
                    break
            
            if not next_model:
                # Last resort - use the first available model that's different
                next_model = "claude-sonnet-4-20250514"  # Most reliable
            
            print(f"🔄 Temporarily setting ANTHROPIC_MODEL to {next_model} to try different model...")
            print(f"🔄 Original model was: {original_model}, failed model was: {failed_model}")
            os.environ["ANTHROPIC_MODEL"] = next_model
            
            # Retry once with fresh graph
            try:
                print(f"🔄 Retrying with fresh agent graph (will try model: {next_model})...")
                print(f"🔄 Current ANTHROPIC_MODEL env var: {os.getenv('ANTHROPIC_MODEL')}")
                agent_graph = await _get_agent_graph()
                stream = agent_graph.astream(input=input_state, stream_mode="values", config=config)
                
                async def process_stream_retry():
                    transfer_marker = None
                    async for state in stream:
                        if "messages" in state:
                            for msg in state["messages"]:
                                if hasattr(msg, 'content') and isinstance(msg.content, str):
                                    if 'TRANSFER_INITIATED:' in msg.content:
                                        transfer_marker = msg.content
                    final_state = agent_graph.get_state(config=config)
                    last_message = final_state.values.get("messages")[-1]
                    final_response = getattr(last_message, 'content', "")
                    if include_metadata:
                        return {"response": final_response, "transfer_marker": transfer_marker}
                    if transfer_marker:
                        return transfer_marker
                    return final_response
                
                result = await asyncio.wait_for(process_stream_retry(), timeout=20.0)
                # Restore original env var (after successful retry)
                if original_model:
                    os.environ["ANTHROPIC_MODEL"] = original_model
                elif "ANTHROPIC_MODEL" in os.environ:
                    os.environ.pop("ANTHROPIC_MODEL", None)
                return result
            except Exception as retry_error:
                # Restore original env var even if retry fails
                if original_model:
                    os.environ["ANTHROPIC_MODEL"] = original_model
                elif "ANTHROPIC_MODEL" in os.environ:
                    os.environ.pop("ANTHROPIC_MODEL", None)
                print(f"❌ Retry also failed: {retry_error}")
                retry_error_str = str(retry_error)
                if "404" in retry_error_str or "not_found_error" in retry_error_str:
                    return f"AGENT_ERROR:model_not_found:All Anthropic models returned 404. Please verify your API key has access to Anthropic models. Error: {retry_error_str[:150]}"
                return f"AGENT_ERROR:model_not_found:Unable to find a working Anthropic model. Please check your API key and model configuration."
        
        # Return special markers for specific errors so they can be detected upstream
        if "tool_call" in error_str.lower():
            return f"AGENT_ERROR:tool_call_incomplete:{error_str[:100]}"
        elif "BrokenResourceError" in error_str:
            return "AGENT_ERROR:broken_resource:Connection issue with database"
        else:
            return f"AGENT_ERROR:general:{error_str[:100]}"


@convonet_todo_bp.route('/run_agent', methods=['POST'])
def run_agent():
    data = request.get_json(silent=True) or {}
    prompt = data.get('prompt')
    if not prompt:
        return jsonify({"error": "Missing 'prompt' in JSON body"}), 400

    try:
        result = asyncio.run(_run_agent_async(prompt))
        return jsonify({"result": result})
    except Exception as e:
        # Log the full error for debugging
        print(f"Error in /run_agent: {e}")
        return jsonify({"error": str(e)}), 500


# WebSocket event handlers for Flask-SocketIO
@convonet_todo_bp.route('/ws')
def websocket_route():
    """WebSocket route for Twilio Media Streams."""
    return "WebSocket endpoint available via Socket.IO", 200


def register_socketio_events(socketio):
    """Register Socket.IO events for Convonet WebSocket functionality."""
    
    @socketio.on('connect', namespace='/anthropic/convonet_todo')
    def handle_connect():
        """Handle WebSocket connection from Twilio."""
        logger.info(f"WebSocket connection established from {request.remote_addr}")
        emit('status', {'msg': 'Connected to Convonet WebSocket'})
    
    @socketio.on('disconnect', namespace='/anthropic/convonet_todo')
    def handle_disconnect():
        """Handle WebSocket disconnection."""
        logger.info(f"WebSocket connection closed from {request.remote_addr}")
    
    @socketio.on('media', namespace='/anthropic/convonet_todo')
    def handle_media(data):
        """Handle media data from Twilio."""
        try:
            # Process media data from Twilio Media Streams
            logger.info(f"Received media data: {len(data)} bytes")
            
            # Here you would integrate with the twilio_handler logic
            # For now, just acknowledge receipt
            emit('ack', {'msg': 'Media received'})
            
        except Exception as e:
            logger.error(f"Error handling media: {str(e)}", exc_info=True)
            emit('error', {'msg': str(e)})
    
    @socketio.on('start', namespace='/anthropic/convonet_todo')
    def handle_start(data):
        """Handle start event from Twilio."""
        try:
            logger.info(f"Start event received: {data}")
            
            # Initialize conversation with Convonet agent
            emit('started', {'msg': 'Conversation started with Convonet agent'})
            
        except Exception as e:
            logger.error(f"Error handling start: {str(e)}", exc_info=True)
            emit('error', {'msg': str(e)})
    
    @socketio.on('stop', namespace='/anthropic/convonet_todo')
    def handle_stop(data):
        """Handle stop event from Twilio."""
        try:
            logger.info(f"Stop event received: {data}")
            
            # Clean up conversation
            emit('stopped', {'msg': 'Conversation ended'})
            
        except Exception as e:
            logger.error(f"Error handling stop: {str(e)}", exc_info=True)
            emit('error', {'msg': str(e)})


# Route to check Deepgram status
@convonet_todo_bp.route('/webrtc/whisper-status')
def whisper_status():
    """Check Deepgram status"""
    try:
        from deepgram_webrtc_integration import get_deepgram_webrtc_info
        info = get_deepgram_webrtc_info()
        return jsonify({
            'success': True,
            'transcriber': info.get('transcriber', 'deepgram'),
            'model': info.get('model', 'nova-2'),
            'accuracy': info.get('accuracy', '95%+'),
            'cost_per_minute': info.get('cost_per_minute', 0.0043),
            'privacy': info.get('privacy', 'processed on Deepgram servers'),
            'latency': info.get('latency', '200-500ms'),
            'webrtc_ready': info.get('webrtc_ready', True),
            'production_ready': info.get('production_ready', True),
            'api_key_configured': bool(os.getenv('DEEPGRAM_API_KEY')),
            'streaming_optimized': info.get('streaming_optimized', True),
            'webRTC_native': info.get('webRTC_native', True)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Failed to check Deepgram status',
            'transcriber': 'deepgram',
            'status': 'error'
        })
