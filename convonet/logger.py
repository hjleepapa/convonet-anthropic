"""
Structured Logging Utility for Convonet
Provides beautiful, structured logging with Sentry integration
"""

import logging
import sys
import json
from datetime import datetime
from typing import Optional, Dict, Any
from functools import wraps
import traceback

# Try to import Sentry
try:
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False

# Color codes for terminal output
class Colors:
    """ANSI color codes for terminal output"""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    
    # Log levels
    DEBUG = '\033[36m'      # Cyan
    INFO = '\033[32m'       # Green
    WARNING = '\033[33m'    # Yellow
    ERROR = '\033[31m'      # Red
    CRITICAL = '\033[35m'   # Magenta
    
    # Components
    AGENT = '\033[94m'      # Light Blue
    TOOL = '\033[93m'       # Light Yellow
    DATABASE = '\033[96m'   # Light Cyan
    API = '\033[95m'        # Light Magenta
    WEBSOCKET = '\033[92m'  # Light Green
    
    # Status
    SUCCESS = '\033[92m'    # Green
    FAILURE = '\033[91m'    # Red

# Emoji icons for different log types
class Icons:
    AGENT = "🤖"
    TOOL = "🔧"
    DATABASE = "🗄️"
    API = "🌐"
    WEBSOCKET = "🔌"
    AUTH = "🔐"
    CACHE = "📦"
    ERROR = "❌"
    SUCCESS = "✅"
    WARNING = "⚠️"
    INFO = "ℹ️"
    DEBUG = "🔍"
    TRANSFER = "📞"
    AUDIO = "🔊"
    PROCESSING = "⚙️"


class StructuredLogger:
    """
    Beautiful structured logger with Sentry integration
    """
    
    def __init__(self, name: str, component: Optional[str] = None):
        self.name = name
        self.component = component or name
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        # Create console handler if not exists
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(logging.DEBUG)
            formatter = self._create_formatter()
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
    
    def _create_formatter(self):
        """Create a beautiful formatter"""
        class ColoredFormatter(logging.Formatter):
            def format(self, record):
                # Get color based on level
                level_colors = {
                    'DEBUG': Colors.DEBUG,
                    'INFO': Colors.INFO,
                    'WARNING': Colors.WARNING,
                    'ERROR': Colors.ERROR,
                    'CRITICAL': Colors.CRITICAL,
                }
                color = level_colors.get(record.levelname, Colors.RESET)
                
                # Get icon based on component
                component_icons = {
                    'agent': Icons.AGENT,
                    'tool': Icons.TOOL,
                    'database': Icons.DATABASE,
                    'api': Icons.API,
                    'websocket': Icons.WEBSOCKET,
                    'auth': Icons.AUTH,
                    'cache': Icons.CACHE,
                }
                icon = component_icons.get(record.component.lower(), Icons.INFO)
                
                # Format timestamp
                timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
                
                # Format message
                if hasattr(record, 'context') and record.context:
                    context_str = json.dumps(record.context, indent=2) if isinstance(record.context, dict) else str(record.context)
                    message = f"{record.getMessage()}\n{Colors.DEBUG}Context:{Colors.RESET} {context_str}"
                else:
                    message = record.getMessage()
                
                # Build formatted string
                formatted = (
                    f"{Colors.DEBUG}[{timestamp}]{Colors.RESET} "
                    f"{color}{icon} {record.levelname:8s}{Colors.RESET} "
                    f"{Colors.BOLD}{record.component}{Colors.RESET} "
                    f"{message}"
                )
                
                return formatted
        
        return ColoredFormatter()
    
    def _log(self, level: int, message: str, context: Optional[Dict[str, Any]] = None, 
             sentry_level: Optional[str] = None, **kwargs):
        """Internal logging method with context"""
        # Add component to record
        extra = {'component': self.component, **kwargs}
        if context:
            extra['context'] = context
        
        # Log to Python logger
        self.logger.log(level, message, extra=extra)
        
        # Send to Sentry if available
        if SENTRY_AVAILABLE and sentry_level:
            with sentry_sdk.configure_scope() as scope:
                # Set component tag
                scope.set_tag("component", self.component)
                
                # Add context
                if context:
                    scope.set_context(self.component, context)
                
                # Add breadcrumb
                sentry_sdk.add_breadcrumb(
                    message=message,
                    category=self.component,
                    level=sentry_level,
                    data=context or {}
                )
    
    def debug(self, message: str, context: Optional[Dict[str, Any]] = None, **kwargs):
        """Log debug message"""
        self._log(logging.DEBUG, message, context, **kwargs)
    
    def info(self, message: str, context: Optional[Dict[str, Any]] = None, **kwargs):
        """Log info message"""
        self._log(logging.INFO, message, context, sentry_level="info", **kwargs)
    
    def warning(self, message: str, context: Optional[Dict[str, Any]] = None, **kwargs):
        """Log warning message"""
        self._log(logging.WARNING, message, context, sentry_level="warning", **kwargs)
    
    def error(self, message: str, context: Optional[Dict[str, Any]] = None, 
              exc_info: bool = False, **kwargs):
        """Log error message"""
        self._log(logging.ERROR, message, context, sentry_level="error", **kwargs)
        
        # Capture exception in Sentry
        if SENTRY_AVAILABLE and exc_info:
            sentry_sdk.capture_exception()
    
    def critical(self, message: str, context: Optional[Dict[str, Any]] = None, 
                 exc_info: bool = False, **kwargs):
        """Log critical message"""
        self._log(logging.CRITICAL, message, context, sentry_level="fatal", **kwargs)
        
        # Capture exception in Sentry
        if SENTRY_AVAILABLE and exc_info:
            sentry_sdk.capture_exception()
    
    def agent(self, message: str, user_id: Optional[str] = None, 
              prompt: Optional[str] = None, response: Optional[str] = None, **kwargs):
        """Log agent-specific events"""
        context = {
            "user_id": user_id,
            "prompt_preview": prompt[:100] + "..." if prompt and len(prompt) > 100 else prompt,
            "response_preview": response[:100] + "..." if response and len(response) > 100 else response,
            **kwargs
        }
        self.info(f"{Icons.AGENT} {message}", context=context)
    
    def tool(self, tool_name: str, action: str, success: bool = True, 
             duration: Optional[float] = None, **kwargs):
        """Log tool execution"""
        icon = Icons.SUCCESS if success else Icons.ERROR
        status = "completed" if success else "failed"
        message = f"{icon} Tool {tool_name}: {action} {status}"
        
        context = {
            "tool_name": tool_name,
            "action": action,
            "success": success,
            **kwargs
        }
        if duration:
            context["duration_ms"] = round(duration * 1000, 2)
            message += f" ({duration*1000:.0f}ms)"
        
        if success:
            self.info(message, context=context)
        else:
            self.error(message, context=context)
    
    def tool_execution(self, tool_name: str, tool_id: str, status: str, 
                      duration_ms: Optional[float] = None, 
                      arguments: Optional[Dict[str, Any]] = None,
                      result: Optional[Any] = None,
                      error: Optional[str] = None, **kwargs):
        """Log detailed tool execution with full context"""
        from convonet.tool_execution_viewer import ToolStatus, ToolExecutionTracker
        
        # Map status string to ToolStatus enum
        status_map = {
            "pending": Icons.DEBUG,
            "executing": Icons.PROCESSING,
            "success": Icons.SUCCESS,
            "failed": Icons.ERROR,
            "timeout": Icons.WARNING,
        }
        
        icon = status_map.get(status.lower(), Icons.TOOL)
        message = f"{icon} Tool Execution: {tool_name} [{status.upper()}]"
        
        if duration_ms:
            message += f" ({duration_ms:.2f}ms)"
        
        context = {
            "tool_name": tool_name,
            "tool_id": tool_id,
            "status": status,
            **kwargs
        }
        
        if duration_ms:
            context["duration_ms"] = duration_ms
        
        if arguments:
            context["arguments"] = arguments
        
        if result is not None:
            result_str = str(result)
            context["result_preview"] = result_str[:200] + "..." if len(result_str) > 200 else result_str
        
        if error:
            context["error"] = error
        
        # Log at appropriate level
        if status.lower() == "success":
            self.info(message, context=context)
        elif status.lower() in ["failed", "timeout"]:
            self.error(message, context=context, exc_info=bool(error))
        else:
            self.debug(message, context=context)
    
    def performance(self, operation: str, duration: float, **kwargs):
        """Log performance metrics"""
        context = {
            "operation": operation,
            "duration_ms": round(duration * 1000, 2),
            **kwargs
        }
        
        # Color code based on duration
        if duration < 1.0:
            level = "info"
            color = Colors.SUCCESS
        elif duration < 3.0:
            level = "warning"
            color = Colors.WARNING
        else:
            level = "error"
            color = Colors.FAILURE
        
        message = f"{Icons.PROCESSING} {operation} took {duration*1000:.0f}ms"
        self._log(
            logging.WARNING if duration >= 1.0 else logging.INFO,
            message,
            context,
            sentry_level=level
        )


# Convenience function to get a logger
def get_logger(name: str, component: Optional[str] = None) -> StructuredLogger:
    """Get a structured logger instance"""
    return StructuredLogger(name, component)


# Decorator for function logging
def log_function(logger: StructuredLogger):
    """Decorator to automatically log function calls"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            func_name = func.__name__
            logger.debug(f"Calling {func_name}", context={"args": str(args)[:200], "kwargs": str(kwargs)[:200]})
            try:
                import time
                start = time.time()
                result = await func(*args, **kwargs)
                duration = time.time() - start
                logger.performance(f"{func_name}", duration)
                return result
            except Exception as e:
                logger.error(f"{func_name} failed", context={"error": str(e)}, exc_info=True)
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            func_name = func.__name__
            logger.debug(f"Calling {func_name}", context={"args": str(args)[:200], "kwargs": str(kwargs)[:200]})
            try:
                import time
                start = time.time()
                result = func(*args, **kwargs)
                duration = time.time() - start
                logger.performance(f"{func_name}", duration)
                return result
            except Exception as e:
                logger.error(f"{func_name} failed", context={"error": str(e)}, exc_info=True)
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# Import asyncio for the decorator
import asyncio

