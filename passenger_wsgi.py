#!/usr/bin/env python3
"""
WSGI entry point for Flask-SocketIO with gevent support
Gevent is more robust for I/O-bound tasks and handles threading conflicts better than eventlet
"""

# CRITICAL: Monkey patch MUST be the very first thing
# But we need to patch select=False to avoid blocking issues with gunicorn
import gevent
from gevent import monkey
# Monkey patch for gevent (more compatible with threading than eventlet)
monkey.patch_all(select=False, socket=True, time=True, thread=True)

print("✅ Gevent monkey patch applied (select=False to avoid gunicorn blocking)!")

import sys
import os

# Add the project directory to the Python path
sys.path.insert(0, os.path.dirname(__file__))

# Import the create_app factory and socketio from your main app module (app.py)
from app import create_app, socketio

print("✅ Imported create_app and socketio")

# Create the application instance
app = create_app()

print(f"✅ Flask app created: {app}")
print(f"✅ SocketIO instance: {socketio}")

# For Flask-SocketIO with gevent, we need to expose the Flask app directly
# Socket.IO middleware is already integrated via socketio.init_app()
application = app

print(f"✅ WSGI application exported: {application}")