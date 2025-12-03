"""
Tool Execution GUI - Flask routes and API endpoints
Provides web-based GUI for viewing tool execution results
"""

from flask import Blueprint, render_template, jsonify, request
from typing import Dict, List, Optional
import json
from datetime import datetime

# Import the tool execution viewer
from .tool_execution_viewer import (
    ToolExecutionTracker,
    ToolStatus,
    _trackers,
    get_tracker
)

tool_gui_bp = Blueprint('tool_gui', __name__, url_prefix='/anthropic/tool-execution')


@tool_gui_bp.route('/')
def tool_execution_dashboard():
    """Render the tool execution dashboard"""
    return render_template('tool_execution_dashboard.html')


@tool_gui_bp.route('/api/trackers')
def get_all_trackers():
    """Get all active trackers"""
    trackers_data = []
    
    for request_id, tracker in _trackers.items():
        summary = tracker.get_summary()
        trackers_data.append({
            "request_id": request_id,
            "user_id": tracker.user_id,
            "total_tools": summary["total_tools"],
            "successful": summary["successful"],
            "failed": summary["failed"],
            "timeout": summary["timeout"],
            "pending": summary["pending"],
            "all_successful": summary["all_successful"],
            "total_duration_ms": summary["total_duration_ms"],
            "start_time": tracker.start_time,
            "end_time": tracker.end_time
        })
    
    # Sort by start_time (most recent first)
    trackers_data.sort(key=lambda x: x.get("start_time", 0), reverse=True)
    
    return jsonify({
        "success": True,
        "trackers": trackers_data,
        "count": len(trackers_data)
    })


@tool_gui_bp.route('/api/tracker/<request_id>')
def get_tracker_details(request_id: str):
    """Get detailed information about a specific tracker"""
    tracker = get_tracker(request_id)
    
    if not tracker:
        return jsonify({
            "success": False,
            "error": f"Tracker not found for request_id: {request_id}"
        }), 404
    
    summary = tracker.get_summary()
    
    # Convert tool executions to JSON-serializable format
    tools_data = []
    for tool_id, execution in tracker.tools.items():
        tool_data = {
            "tool_id": tool_id,
            "tool_name": execution.tool_name,
            "status": execution.status.value,
            "start_time": execution.start_time,
            "end_time": execution.end_time,
            "duration_ms": execution.duration_ms,
            "arguments": execution.arguments,
            "result": str(execution.result) if execution.result is not None else None,
            "error": execution.error,
            "error_type": execution.error_type,
            "stack_trace": execution.stack_trace
        }
        tools_data.append(tool_data)
    
    return jsonify({
        "success": True,
        "request_id": request_id,
        "user_id": tracker.user_id,
        "summary": summary,
        "tools": tools_data,
        "start_time": tracker.start_time,
        "end_time": tracker.end_time,
        "total_duration_ms": tracker.total_duration_ms
    })


@tool_gui_bp.route('/api/tracker/<request_id>/summary')
def get_tracker_summary(request_id: str):
    """Get summary of a specific tracker"""
    tracker = get_tracker(request_id)
    
    if not tracker:
        return jsonify({
            "success": False,
            "error": f"Tracker not found for request_id: {request_id}"
        }), 404
    
    summary = tracker.get_summary()
    return jsonify({
        "success": True,
        "summary": summary
    })


@tool_gui_bp.route('/api/stats')
def get_overall_stats():
    """Get overall statistics across all trackers"""
    total_requests = len(_trackers)
    total_tools = 0
    total_successful = 0
    total_failed = 0
    total_timeout = 0
    total_duration = 0
    
    tool_name_counts = {}
    tool_name_success = {}
    tool_name_failed = {}
    
    for tracker in _trackers.values():
        summary = tracker.get_summary()
        total_tools += summary["total_tools"]
        total_successful += summary["successful"]
        total_failed += summary["failed"]
        total_timeout += summary["timeout"]
        if summary["total_duration_ms"]:
            total_duration += summary["total_duration_ms"]
        
        # Count tools by name
        for tool_id, execution in tracker.tools.items():
            tool_name = execution.tool_name
            tool_name_counts[tool_name] = tool_name_counts.get(tool_name, 0) + 1
            
            if execution.status == ToolStatus.SUCCESS:
                tool_name_success[tool_name] = tool_name_success.get(tool_name, 0) + 1
            elif execution.status in [ToolStatus.FAILED, ToolStatus.TIMEOUT]:
                tool_name_failed[tool_name] = tool_name_failed.get(tool_name, 0) + 1
    
    avg_duration = total_duration / total_requests if total_requests > 0 else 0
    success_rate = (total_successful / total_tools * 100) if total_tools > 0 else 0
    
    return jsonify({
        "success": True,
        "stats": {
            "total_requests": total_requests,
            "total_tools": total_tools,
            "total_successful": total_successful,
            "total_failed": total_failed,
            "total_timeout": total_timeout,
            "success_rate": round(success_rate, 2),
            "avg_duration_ms": round(avg_duration, 2),
            "tool_name_counts": tool_name_counts,
            "tool_name_success": tool_name_success,
            "tool_name_failed": tool_name_failed
        }
    })

