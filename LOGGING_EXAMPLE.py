"""
Example: How to use the new structured logger
Replace your print() statements with beautiful, structured logs
"""

from convonet.logger import get_logger

# Create loggers for different components
agent_logger = get_logger("agent", component="agent")
tool_logger = get_logger("tools", component="tool")
db_logger = get_logger("database", component="database")

# Example 1: Basic logging
agent_logger.info("Agent initialized successfully")
agent_logger.warning("High memory usage detected", context={"memory_mb": 512})
agent_logger.error("Failed to connect to API", context={"api_url": "https://api.example.com"}, exc_info=True)

# Example 2: Agent-specific logging
agent_logger.agent(
    "Processing user request",
    user_id="user-123",
    prompt="Create a todo for team meeting",
    response="I've created the todo 'Team Meeting' with high priority."
)

# Example 3: Tool execution logging
import time

start = time.time()
# ... execute tool ...
result = {"todo_id": "todo-456", "success": True}
duration = time.time() - start

tool_logger.tool(
    tool_name="create_todo",
    action="executed",
    success=True,
    duration=duration,
    todo_id=result["todo_id"]
)

# Example 4: Performance logging
start = time.time()
# ... slow operation ...
duration = time.time() - start

agent_logger.performance(
    "agent_processing",
    duration,
    user_id="user-123",
    message_count=5
)

# Example 5: Error with full context
try:
    # ... some operation ...
    raise ValueError("Something went wrong")
except Exception as e:
    agent_logger.error(
        "Operation failed",
        context={
            "user_id": "user-123",
            "operation": "create_todo",
            "error_type": type(e).__name__
        },
        exc_info=True  # Includes full stack trace
    )

# Example 6: Using the decorator
from convonet.logger import log_function

@log_function(agent_logger)
async def process_user_request(user_id: str, text: str):
    """This function will be automatically logged"""
    # Your code here
    return {"result": "success"}

# When you call it:
# await process_user_request("user-123", "Create a todo")
# Automatically logs: function call, duration, errors

