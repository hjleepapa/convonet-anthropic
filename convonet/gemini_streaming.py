"""
Hybrid Streaming Implementation for Gemini using Native SDK
This module provides real-time streaming for Gemini while maintaining LangGraph integration
"""
import asyncio
import gc
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
            # Get tool schema - handle both Pydantic models and dicts
            schema = {}
            try:
                if hasattr(tool, 'args_schema') and tool.args_schema:
                    # Check if args_schema is a Pydantic model (has schema() method)
                    if hasattr(tool.args_schema, 'schema'):
                        schema = tool.args_schema.schema()
                    # Check if args_schema is already a dict
                    elif isinstance(tool.args_schema, dict):
                        schema = tool.args_schema
                    # Try get_input_schema() method (LangChain standard)
                    elif hasattr(tool, 'get_input_schema'):
                        schema = tool.get_input_schema().schema() if hasattr(tool.get_input_schema(), 'schema') else tool.get_input_schema()
                # Fallback: try get_input_schema() directly on tool
                elif hasattr(tool, 'get_input_schema'):
                    input_schema = tool.get_input_schema()
                    if hasattr(input_schema, 'schema'):
                        schema = input_schema.schema()
                    elif isinstance(input_schema, dict):
                        schema = input_schema
            except Exception as e:
                print(f"⚠️ Error getting schema for tool {tool.name}: {e}", flush=True)
                # Use empty schema as fallback
                schema = {}
            
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
        
        print(f"🔧 Converted {len(gemini_tools)} tools to Gemini format", flush=True)
        if len(gemini_tools) > 0:
            first_tool_decl = gemini_tools[0].get('function_declarations', [{}])
            if first_tool_decl:
                print(f"🔧 First tool: {first_tool_decl[0].get('name', 'unknown')}", flush=True)
                print(f"🔧 First tool description: {first_tool_decl[0].get('description', '')[:50]}...", flush=True)
            else:
                print(f"⚠️ First tool has no function_declarations", flush=True)
        else:
            print(f"⚠️ No tools converted!", flush=True)
        
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
        iteration = 0  # Track iteration for debug logging
        
        try:
            # Use async generate_content_stream for streaming
            # Note: system_instruction may need to be passed differently or included in contents
            # Build the request parameters
            # Google GenAI SDK format: tools should be in config, not as separate parameter
            request_params = {
                "model": self.model,
                "contents": gemini_messages,
            }
            
            # Add tools to generation config (correct format for Google GenAI SDK)
            if tools_config:
                # Flatten tools_config - combine all function_declarations into one list
                all_function_declarations = []
                for tool_config in tools_config:
                    if isinstance(tool_config, dict) and 'function_declarations' in tool_config:
                        all_function_declarations.extend(tool_config['function_declarations'])
                
                if all_function_declarations:
                    # Tools should be passed in config, not as separate parameter
                    generation_config["tools"] = [{"function_declarations": all_function_declarations}]
                    print(f"🔧 Added {len(all_function_declarations)} function declaration(s) to config", flush=True)
                    if len(all_function_declarations) > 0:
                        print(f"🔧 First tool in config: {all_function_declarations[0].get('name', 'unknown')}", flush=True)
                else:
                    print(f"⚠️ No function_declarations found in tools_config", flush=True)
            else:
                print(f"⚠️ No tools_config to add to request", flush=True)
            
            # Add generation config to request
            request_params["config"] = generation_config
            
            # Add system instruction if available - try different parameter names
            if system_instruction:
                # Try passing as system_instruction first, if that fails, include in contents
                request_params["system_instruction"] = system_instruction
            
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
                            if gemini_messages and gemini_messages[0].get("role") != "system":
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
                    # Debug: Log chunk structure (first chunk only)
                    if len(tool_calls) == 0 and full_text == "":
                        chunk_attrs = [attr for attr in dir(chunk) if not attr.startswith('_')]
                        print(f"🔍 First chunk attributes: {chunk_attrs[:15]}...", flush=True)
                        print(f"🔍 Chunk type: {type(chunk)}", flush=True)
                        # Try to inspect chunk contents
                        try:
                            chunk_dict = chunk.__dict__ if hasattr(chunk, '__dict__') else {}
                            print(f"🔍 Chunk dict keys: {list(chunk_dict.keys())[:10]}...", flush=True)
                            
                            # Check candidates for function calls
                            if hasattr(chunk, 'candidates') and chunk.candidates:
                                print(f"🔍 Found {len(chunk.candidates)} candidate(s)", flush=True)
                                candidate = chunk.candidates[0]
                                candidate_attrs = [attr for attr in dir(candidate) if not attr.startswith('_')]
                                print(f"🔍 Candidate attributes: {candidate_attrs[:15]}...", flush=True)
                                
                                # Check for function_calls in candidate
                                if hasattr(candidate, 'function_calls'):
                                    print(f"🔍 Candidate has function_calls: {candidate.function_calls}", flush=True)
                                if hasattr(candidate, 'content'):
                                    print(f"🔍 Candidate has content: {type(candidate.content)}", flush=True)
                                    if hasattr(candidate.content, 'parts'):
                                        print(f"🔍 Content has {len(candidate.content.parts)} part(s)", flush=True)
                                        for i, part in enumerate(candidate.content.parts):
                                            part_attrs = [attr for attr in dir(part) if not attr.startswith('_')]
                                            print(f"🔍 Part {i} attributes: {part_attrs[:10]}...", flush=True)
                                            if hasattr(part, 'function_call') and part.function_call:
                                                print(f"🔍 Part {i} has function_call!", flush=True)
                                                # Extract function call immediately
                                                func_call = part.function_call
                                                tool_call = {
                                                    "name": func_call.name if hasattr(func_call, 'name') else getattr(func_call, 'function_name', 'unknown'),
                                                    "id": getattr(func_call, 'id', None),
                                                    "args": func_call.args if hasattr(func_call, 'args') else (func_call.arguments if hasattr(func_call, 'arguments') else {})
                                                }
                                                print(f"🔧 Extracted function call: {tool_call['name']} with args: {tool_call['args']}", flush=True)
                                                if not any(tc.get('name') == tool_call['name'] and tc.get('id') == tool_call['id'] for tc in tool_calls):
                                                    tool_calls.append(tool_call)
                                                    function_calls_detected = True
                                                    if self.on_tool_call:
                                                        self.on_tool_call(tool_call)
                        except Exception as e:
                            print(f"⚠️ Error inspecting chunk: {e}", flush=True)
                            import traceback
                            traceback.print_exc()
                    
                    # Handle text chunks
                    if hasattr(chunk, 'text') and chunk.text:
                        text_chunk = chunk.text
                        full_text += text_chunk
                        
                        # Emit text chunk via callback
                        if self.on_text_chunk:
                            self.on_text_chunk(text_chunk)
                    
                    # Handle function calls (check multiple possible attribute names)
                    function_calls_detected = False
                    
                    # Method 1: Check function_calls attribute
                    if hasattr(chunk, 'function_calls') and chunk.function_calls:
                        print(f"🔧 Found function_calls in chunk: {len(chunk.function_calls)}", flush=True)
                        for func_call in chunk.function_calls:
                            tool_call = {
                                "name": func_call.name if hasattr(func_call, 'name') else getattr(func_call, 'function_name', 'unknown'),
                                "id": getattr(func_call, 'id', None),
                                "args": func_call.args if hasattr(func_call, 'args') else (func_call.arguments if hasattr(func_call, 'arguments') else {})
                            }
                            tool_calls.append(tool_call)
                            function_calls_detected = True
                            
                            # Emit tool call via callback
                            if self.on_tool_call:
                                self.on_tool_call(tool_call)
                    
                    # Method 2: Check function_call (singular) attribute
                    if hasattr(chunk, 'function_call') and chunk.function_call:
                        print(f"🔧 Found function_call in chunk", flush=True)
                        if not current_tool_call:
                            current_tool_call = {
                                "name": chunk.function_call.name if hasattr(chunk.function_call, 'name') else getattr(chunk.function_call, 'function_name', 'unknown'),
                                "id": getattr(chunk.function_call, 'id', None),
                                "args": {}
                            }
                        
                        # Accumulate function call arguments
                        if hasattr(chunk.function_call, 'args'):
                            current_tool_call["args"].update(chunk.function_call.args)
                        elif hasattr(chunk.function_call, 'arguments'):
                            current_tool_call["args"].update(chunk.function_call.arguments)
                        function_calls_detected = True
                    
                    # Method 3: Check candidates[0].content.parts for function_call (Gemini API format)
                    if hasattr(chunk, 'candidates') and chunk.candidates:
                        for candidate in chunk.candidates:
                            # Check candidate.function_calls directly
                            if hasattr(candidate, 'function_calls') and candidate.function_calls:
                                print(f"🔧 Found function_calls in candidate: {len(candidate.function_calls)}", flush=True)
                                for func_call in candidate.function_calls:
                                    tool_call = {
                                        "name": func_call.name if hasattr(func_call, 'name') else getattr(func_call, 'function_name', 'unknown'),
                                        "id": getattr(func_call, 'id', None),
                                        "args": func_call.args if hasattr(func_call, 'args') else (func_call.arguments if hasattr(func_call, 'arguments') else {})
                                    }
                                    tool_calls.append(tool_call)
                                    function_calls_detected = True
                                    
                                    if self.on_tool_call:
                                        self.on_tool_call(tool_call)
                            
                            # Check candidate.content.parts for function_call
                            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                                for part in candidate.content.parts:
                                    if hasattr(part, 'function_call') and part.function_call:
                                        print(f"🔧 Found function_call in content.parts!", flush=True)
                                        func_call = part.function_call
                                        tool_call = {
                                            "name": func_call.name if hasattr(func_call, 'name') else getattr(func_call, 'function_name', 'unknown'),
                                            "id": getattr(func_call, 'id', None),
                                            "args": func_call.args if hasattr(func_call, 'args') else (func_call.arguments if hasattr(func_call, 'arguments') else {})
                                        }
                                        # Only add if not already in tool_calls
                                        if not any(tc.get('name') == tool_call['name'] and tc.get('id') == tool_call['id'] for tc in tool_calls):
                                            tool_calls.append(tool_call)
                                            function_calls_detected = True
                                            
                                            if self.on_tool_call:
                                                self.on_tool_call(tool_call)
                
                # Finalize any pending tool call
                if current_tool_call:
                    tool_calls.append(current_tool_call)
                    if self.on_tool_call:
                        self.on_tool_call(current_tool_call)
                
                # IMPORTANT: Check the final aggregated response for function calls
                # The streaming chunks might not contain function calls, but the final response might
                # Try to get the aggregated response from the stream
                try:
                    # Some SDKs provide an aggregated response object
                    if hasattr(response_stream, 'response') or hasattr(response_stream, 'aggregate'):
                        final_response_obj = getattr(response_stream, 'response', None) or getattr(response_stream, 'aggregate', None)
                        if final_response_obj:
                            print(f"🔍 Checking final response object for function calls...", flush=True)
                            # Check candidates[0].content.parts for function calls
                            if hasattr(final_response_obj, 'candidates') and final_response_obj.candidates:
                                candidate = final_response_obj.candidates[0]
                                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                                    for part in candidate.content.parts:
                                        if hasattr(part, 'function_call') and part.function_call:
                                            func_call = part.function_call
                                            print(f"🔧 Found function_call in final response part: {func_call.name if hasattr(func_call, 'name') else 'unknown'}", flush=True)
                                            tool_call = {
                                                "name": func_call.name if hasattr(func_call, 'name') else 'unknown',
                                                "id": getattr(func_call, 'id', None),
                                                "args": func_call.args if hasattr(func_call, 'args') else (func_call.arguments if hasattr(func_call, 'arguments') else {})
                                            }
                                            # Only add if not already in tool_calls
                                            if not any(tc.get('name') == tool_call['name'] and tc.get('id') == tool_call['id'] for tc in tool_calls):
                                                tool_calls.append(tool_call)
                                                print(f"🔧 Found function call in final response: {tool_call['name']}", flush=True)
                                                if self.on_tool_call:
                                                    self.on_tool_call(tool_call)
                except Exception as e:
                    print(f"⚠️ Error checking final response object: {e}", flush=True)
                
                # Debug: Log tool calls found
                if tool_calls:
                    print(f"🔧 Total tool calls detected: {len(tool_calls)}", flush=True)
                    for tc in tool_calls:
                        print(f"🔧   - {tc.get('name', 'unknown')} with args: {tc.get('args', {})}", flush=True)
                else:
                    print(f"⚠️ No tool calls detected in streaming response", flush=True)
                
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
    Convenience function to stream Gemini response with tool support and execution
    
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
    all_tool_calls = []
    conversation_messages = messages + [HumanMessage(content=prompt)]
    max_iterations = 5  # Prevent infinite loops
    
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
        all_tool_calls.append(tool_call)
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
        
        # Loop: Get response → Execute tools → Feed results back → Get final response
        iteration = 0
        final_text = ""
        
        while iteration < max_iterations:
            iteration += 1
            print(f"🔄 Gemini iteration {iteration}/{max_iterations}", flush=True)
            
            # Stream response from Gemini
            response_text, tool_calls = await handler.stream_response(
                messages=conversation_messages,
                session_id=session_id,
            )
            
            # If there are tool calls, execute them and continue the loop
            if tool_calls and len(tool_calls) > 0:
                print(f"🔧 Executing {len(tool_calls)} tool call(s) from Gemini...", flush=True)
                
                # Execute each tool call
                tool_results = []
                for tc in tool_calls:
                    tool_name = tc.get('name', 'unknown')
                    tool_args = tc.get('args', {})
                    tool_id = tc.get('id', None)
                    
                    # Find the tool
                    tool = None
                    for t in tools:
                        if t.name == tool_name:
                            tool = t
                            break
                    
                    if tool:
                        try:
                            print(f"🔧 Executing tool: {tool_name} with args: {tool_args}", flush=True)
                            # Execute tool (with timeout)
                            if hasattr(tool, 'ainvoke'):
                                result = await asyncio.wait_for(tool.ainvoke(tool_args), timeout=6.0)
                            else:
                                result = await asyncio.wait_for(asyncio.to_thread(tool.invoke, tool_args), timeout=6.0)
                            
                            tool_result = {
                                'name': tool_name,
                                'id': tool_id,
                                'response': str(result)
                            }
                            tool_results.append(tool_result)
                            print(f"✅ Tool {tool_name} completed: {str(result)[:100]}...", flush=True)
                        except asyncio.TimeoutError:
                            tool_result = {
                                'name': tool_name,
                                'id': tool_id,
                                'response': "I'm sorry, the operation timed out. Please try again."
                            }
                            tool_results.append(tool_result)
                            print(f"⏰ Tool {tool_name} timed out", flush=True)
                        except Exception as e:
                            error_str = str(e)
                            tool_result = {
                                'name': tool_name,
                                'id': tool_id,
                                'response': f"I encountered an error: {error_str[:200]}"
                            }
                            tool_results.append(tool_result)
                            print(f"❌ Tool {tool_name} error: {error_str}", flush=True)
                    else:
                        tool_result = {
                            'name': tool_name,
                            'id': tool_id,
                            'response': f"Tool {tool_name} not found"
                        }
                        tool_results.append(tool_result)
                        print(f"⚠️ Tool {tool_name} not found", flush=True)
                
                # Add tool results to conversation as ToolMessages
                for tr in tool_results:
                    tool_message = ToolMessage(
                        content=tr['response'],
                        name=tr['name'],
                        tool_call_id=tr.get('id', None)
                    )
                    conversation_messages.append(tool_message)
                
                # Continue loop to get final response with tool results
                print(f"🔄 Feeding tool results back to Gemini for final response...", flush=True)
                continue
            else:
                # No tool calls - this is the final response
                final_text = response_text
                break
        
        # Log final response for debugging
        print(f"📝 Gemini final response length: {len(final_text)} chars", flush=True)
        print(f"📝 Gemini final response preview: {final_text[:200]}...", flush=True)
        
        # Emit final chunk marker
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
        
        return final_text, all_tool_calls
    finally:
        # Cleanup: Clear handler and client references to help with garbage collection
        if handler is not None:
            # Clear client references
            handler.client = None
            handler._response_stream = None
            handler = None
        
        # Clear local accumulators to free memory
        text_chunks.clear()
        all_tool_calls.clear()
        
        # Force garbage collection for large objects
        gc.collect()

