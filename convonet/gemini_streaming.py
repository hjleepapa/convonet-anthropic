"""
Hybrid Streaming Implementation for Gemini using Native SDK
This module provides real-time streaming for Gemini while maintaining LangGraph integration
"""
import asyncio
import json
import os
import sys
from typing import Optional, Dict, Any, Callable, List
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

try:
    from google import genai
    from google.genai import types
    GEMINI_SDK_AVAILABLE = True
except ImportError:
    GEMINI_SDK_AVAILABLE = False
    print("⚠️ Google GenAI SDK not available. Install with: pip install google-genai")


class GeminiStreamingHandler:
    """
    Handles Gemini streaming using native SDK while maintaining LangGraph compatibility
    """
    
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        tools: Optional[List[BaseTool]] = None,
        system_prompt: Optional[str] = None,
        on_text_chunk: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_complete: Optional[Callable[[str, List[Dict]], None]] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.tools = tools or []
        self.system_prompt = system_prompt
        self.on_text_chunk = on_text_chunk
        self.on_tool_call = on_tool_call
        self.on_complete = on_complete
        
        if not GEMINI_SDK_AVAILABLE:
            raise ImportError("Google GenAI SDK not available. Install with: pip install google-genai")
        
        # Initialize client (use async client for streaming)
        # Note: genai.Client should be reused, but we'll ensure proper cleanup
        self.client = genai.Client(api_key=api_key)
        # Don't create duplicate client - use self.client.aio if available
        self._response_stream = None  # Track active stream for cleanup
    
    def _convert_tools_to_gemini_format(self) -> List[Dict[str, Any]]:
        """Convert LangChain tools to Gemini function declarations"""
        gemini_tools = []
        for tool in self.tools:
            # Get tool schema
            schema = tool.args_schema.schema() if hasattr(tool, 'args_schema') and tool.args_schema else {}
            
            # Convert to Gemini format
            gemini_tool = {
                "function_declarations": [{
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": schema.get("properties", {}),
                        "required": schema.get("required", [])
                    }
                }]
            }
            gemini_tools.append(gemini_tool)
        
        return gemini_tools
    
    async def stream_response(
        self,
        messages: List[Any],
        session_id: Optional[str] = None,
    ) -> tuple[str, List[Dict[str, Any]]]:
        """
        Stream response from Gemini using native SDK
        
        Args:
            messages: List of LangChain messages
            session_id: Optional session ID for WebSocket emission
            
        Returns:
            Tuple of (final_text, tool_calls)
        """
        # Convert LangChain messages to Gemini format
        gemini_messages = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                # System messages are handled separately
                continue
            elif isinstance(msg, HumanMessage):
                gemini_messages.append({
                    "role": "user",
                    "parts": [{"text": msg.content}]
                })
            elif isinstance(msg, AIMessage):
                gemini_messages.append({
                    "role": "model",
                    "parts": [{"text": msg.content}]
                })
            elif isinstance(msg, ToolMessage):
                # Convert tool result to Gemini format
                gemini_messages.append({
                    "role": "user",
                    "parts": [{
                        "function_response": {
                            "name": getattr(msg, 'name', 'unknown'),
                            "response": msg.content
                        }
                    }]
                })
        
        # Prepare generation config
        generation_config = {
            "temperature": 0.0,
        }
        
        # Add tools if available
        tools_config = None
        if self.tools:
            tools_config = self._convert_tools_to_gemini_format()
        
        # Prepare system instruction
        system_instruction = self.system_prompt if self.system_prompt else None
        
        # Stream response
        full_text = ""
        tool_calls = []
        current_tool_call = None
        
        try:
            # Use async generate_content_stream for streaming
            # Note: system_instruction may need to be passed differently or included in contents
            # Build the request parameters
            request_params = {
                "model": self.model,
                "contents": gemini_messages,
                "config": generation_config,
            }
            
            # Add system instruction if available - try different parameter names
            if system_instruction:
                # Try passing as system_instruction first, if that fails, include in contents
                request_params["system_instruction"] = system_instruction
            
            # Add tools if available
            if tools_config:
                request_params["tools"] = tools_config
            
            # Use async generate_content_stream for streaming
            response_stream = None
            try:
                if hasattr(self.client, 'aio'):
                    try:
                        response_stream = await self.client.aio.models.generate_content_stream(**request_params)
                        self._response_stream = response_stream  # Track for cleanup
                    except TypeError as e:
                        # If system_instruction parameter is not supported, try without it
                        if "system_instruction" in str(e):
                            print(f"⚠️ system_instruction parameter not supported, including in contents instead", flush=True)
                            # Remove system_instruction from params and add as first message
                            request_params.pop("system_instruction", None)
                            # Prepend system instruction as a user message with special role
                            if gemini_messages and gemini_messages[0].get("role") != "system"):
                                gemini_messages.insert(0, {
                                    "role": "user",
                                    "parts": [{"text": f"System: {system_instruction}"}]
                                })
                            response_stream = await self.client.aio.models.generate_content_stream(**request_params)
                            self._response_stream = response_stream
                        else:
                            raise
                else:
                    # Fallback to sync streaming (will need to wrap in executor)
                    import asyncio
                    try:
                        response_stream = await asyncio.to_thread(
                            lambda: self.client.models.generate_content_stream(**request_params)
                        )
                        self._response_stream = response_stream
                    except TypeError as e:
                        # If system_instruction parameter is not supported, try without it
                        if "system_instruction" in str(e):
                            print(f"⚠️ system_instruction parameter not supported, including in contents instead", flush=True)
                            request_params.pop("system_instruction", None)
                            if gemini_messages and gemini_messages[0].get("role") != "system":
                                gemini_messages.insert(0, {
                                    "role": "user",
                                    "parts": [{"text": f"System: {system_instruction}"}]
                                })
                            response_stream = await asyncio.to_thread(
                                lambda: self.client.models.generate_content_stream(**request_params)
                            )
                            self._response_stream = response_stream
                        else:
                            raise
                
                async for chunk in response_stream:
                    # Handle text chunks
                    if hasattr(chunk, 'text') and chunk.text:
                        text_chunk = chunk.text
                        full_text += text_chunk
                        
                        # Emit text chunk via callback
                        if self.on_text_chunk:
                            self.on_text_chunk(text_chunk)
                    
                    # Handle function calls
                    if hasattr(chunk, 'function_calls') and chunk.function_calls:
                        for func_call in chunk.function_calls:
                            tool_call = {
                                "name": func_call.name,
                                "id": getattr(func_call, 'id', None),
                                "args": func_call.args if hasattr(func_call, 'args') else {}
                            }
                            tool_calls.append(tool_call)
                            
                            # Emit tool call via callback
                            if self.on_tool_call:
                                self.on_tool_call(tool_call)
                    
                    # Handle function call deltas (streaming tool arguments)
                    if hasattr(chunk, 'function_call') and chunk.function_call:
                        if not current_tool_call:
                            current_tool_call = {
                                "name": chunk.function_call.name,
                                "id": getattr(chunk.function_call, 'id', None),
                                "args": {}
                            }
                        
                        # Accumulate function call arguments
                        if hasattr(chunk.function_call, 'args'):
                            current_tool_call["args"].update(chunk.function_call.args)
                
                # Finalize any pending tool call
                if current_tool_call:
                    tool_calls.append(current_tool_call)
                    if self.on_tool_call:
                        self.on_tool_call(current_tool_call)
                
                # Call completion callback
                if self.on_complete:
                    self.on_complete(full_text, tool_calls)
                
                return full_text, tool_calls
            finally:
                # Cleanup: Clear response stream reference to allow garbage collection
                if response_stream is not None:
                    # Try to close/cleanup the stream if it has a close method
                    if hasattr(response_stream, 'close'):
                        try:
                            if asyncio.iscoroutinefunction(response_stream.close):
                                await response_stream.close()
                            else:
                                response_stream.close()
                        except:
                            pass
                    # Clear reference
                    self._response_stream = None
                    response_stream = None
                    
        except Exception as e:
            print(f"❌ Gemini streaming error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            # Ensure cleanup even on error
            if 'response_stream' in locals() and response_stream is not None:
                self._response_stream = None
                response_stream = None
            raise


async def stream_gemini_with_tools(
    prompt: str,
    api_key: str,
    model: str,
    tools: List[BaseTool],
    system_prompt: str,
    messages: List[Any],
    socketio=None,
    session_id: Optional[str] = None,
) -> tuple[str, List[Dict[str, Any]]]:
    """
    Convenience function to stream Gemini response with tool support
    
    Args:
        prompt: User prompt
        api_key: Gemini API key
        model: Model name
        tools: List of LangChain tools
        system_prompt: System prompt
        messages: Conversation history
        socketio: Optional SocketIO instance for real-time emission
        session_id: Optional session ID
        
    Returns:
        Tuple of (response_text, tool_calls)
    """
    text_chunks = []
    tool_calls = []
    
    def on_text_chunk(chunk: str):
        """Emit text chunk via WebSocket"""
        text_chunks.append(chunk)
        if socketio and session_id:
            socketio.emit(
                'agent_stream_chunk',
                {
                    'session_id': session_id,
                    'text_chunk': chunk,
                    'is_final': False
                },
                namespace='/voice',
                room=session_id
            )
    
    def on_tool_call(tool_call: Dict[str, Any]):
        """Emit tool call via WebSocket"""
        tool_calls.append(tool_call)
        if socketio and session_id:
            socketio.emit(
                'agent_stream_chunk',
                {'tool_call': tool_call, 'type': 'tool'},
                namespace='/voice',
                room=session_id
            )
    
    handler = None
    try:
        handler = GeminiStreamingHandler(
            api_key=api_key,
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            on_text_chunk=on_text_chunk,
            on_tool_call=on_tool_call,
        )
        
        # Add current prompt to messages
        full_messages = messages + [HumanMessage(content=prompt)]
        
        final_text, final_tool_calls = await handler.stream_response(
            messages=full_messages,
            session_id=session_id,
        )
        
        # Log final response for debugging
        print(f"📝 Gemini final response length: {len(final_text)} chars", flush=True)
        print(f"📝 Gemini final response preview: {final_text[:200]}...", flush=True)
        
        # Ensure we return the complete text (use handler's full_text, not just accumulated chunks)
        # The handler's full_text should be complete, but verify
        if final_text and len(final_text) > 0:
            # Emit final chunk marker if needed
            if socketio and session_id:
                socketio.emit(
                    'agent_stream_chunk',
                    {
                        'session_id': session_id,
                        'text_chunk': '',  # Empty chunk to signal completion
                        'is_final': True
                    },
                    namespace='/voice',
                    room=session_id
                )
        
        return final_text, final_tool_calls
    finally:
        # Cleanup: Clear handler and client references to help with garbage collection
        if handler is not None:
            # Clear client references
            handler.client = None
            handler._response_stream = None
            handler = None
        
        # Clear local accumulators to free memory
        text_chunks.clear()
        tool_calls.clear()
        
        # Force garbage collection for large objects
        gc.collect()

