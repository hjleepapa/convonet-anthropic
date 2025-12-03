"""
Example: Using the Tool Execution Viewer
This shows how to track and display tool execution status
"""

import asyncio
from convonet.tool_execution_viewer import (
    create_tracker,
    ToolExecutionViewer,
    ToolStatus
)
from convonet.logger import get_logger

logger = get_logger(__name__, component="tool")


async def simulate_tool_execution():
    """Simulate agent processing with tool calls"""
    
    # Create a tracker for this request
    tracker = create_tracker(request_id="example_req_001", user_id="user_123")
    
    # Simulate multiple tool calls
    tools_to_execute = [
        {
            "name": "create_todo",
            "id": "tool_call_001",
            "args": {"title": "Buy groceries", "priority": "high"}
        },
        {
            "name": "get_todos",
            "id": "tool_call_002",
            "args": {"completed": False}
        },
        {
            "name": "create_calendar_event",
            "id": "tool_call_003",
            "args": {"title": "Team meeting", "start": "2025-01-20T10:00:00"}
        }
    ]
    
    # Execute each tool
    for tool_info in tools_to_execute:
        tool_name = tool_info["name"]
        tool_id = tool_info["id"]
        tool_args = tool_info["args"]
        
        # Start tracking
        execution = tracker.start_tool(tool_name, tool_id, tool_args)
        logger.tool_execution(
            tool_name=tool_name,
            tool_id=tool_id,
            status="executing",
            arguments=tool_args
        )
        
        try:
            import time
            start_time = time.time()
            
            # Simulate tool execution
            await asyncio.sleep(0.1)  # Simulate work
            
            # Simulate different outcomes
            if tool_name == "create_todo":
                result = {"todo_id": "todo_789", "status": "created"}
                duration = time.time() - start_time
                tracker.complete_tool(tool_id, result)
                execution.complete(result)
                logger.tool_execution(
                    tool_name=tool_name,
                    tool_id=tool_id,
                    status="success",
                    duration_ms=duration * 1000,
                    result=result
                )
                
            elif tool_name == "get_todos":
                result = {"todos": [{"id": "todo_1", "title": "Task 1"}]}
                duration = time.time() - start_time
                tracker.complete_tool(tool_id, result)
                execution.complete(result)
                logger.tool_execution(
                    tool_name=tool_name,
                    tool_id=tool_id,
                    status="success",
                    duration_ms=duration * 1000,
                    result=result
                )
                
            elif tool_name == "create_calendar_event":
                # Simulate a failure
                raise ValueError("Calendar API unavailable")
                
        except Exception as e:
            import traceback
            duration = time.time() - start_time
            error_str = str(e)
            error_type = type(e).__name__
            stack = traceback.format_exc()
            
            tracker.fail_tool(tool_id, error_str, error_type, stack)
            execution.fail(error_str, error_type, stack)
            logger.tool_execution(
                tool_name=tool_name,
                tool_id=tool_id,
                status="failed",
                duration_ms=duration * 1000,
                error=error_str,
                arguments=tool_args
            )
    
    # Finish tracking and display summary
    tracker.finish()
    ToolExecutionViewer.display_summary(tracker)
    
    # Also get programmatic summary
    summary = tracker.get_summary()
    print(f"\n📊 Summary: {summary['successful']}/{summary['total_tools']} tools successful")
    if not summary['all_successful']:
        print(f"⚠️  {summary['failed']} failed, {summary['timeout']} timed out")


if __name__ == "__main__":
    print("Running tool execution viewer example...\n")
    asyncio.run(simulate_tool_execution())

