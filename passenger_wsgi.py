#!/usr/bin/env python3
"""
WSGI entry point for Flask-SocketIO with gevent support
Gevent is more robust for I/O-bound tasks and handles threading conflicts better than eventlet
"""

# CRITICAL: For gevent worker class, Gunicorn will handle monkey patching
# We should NOT monkey patch here to avoid conflicts with Gunicorn's gevent worker
# Gunicorn's gevent worker will automatically call monkey.patch_all() during init_process
# If we patch here, it conflicts with OpenAI's lazy loading of sounddevice
# 
# However, we need to ensure gevent is imported early to avoid import order issues
try:
    import gevent
    print("✅ Gevent imported (Gunicorn gevent worker will handle monkey patching)")
except ImportError:
    print("⚠️ Gevent not available - gevent worker class will fail")

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