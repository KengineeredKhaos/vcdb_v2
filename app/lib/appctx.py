# app/lib/appctx.py

from flask import current_app

"""
This is a tiny accessor you can import anywhere that already runs 
inside an app context:
"""

def cfg():
    """Active Flask config (requires an app context)."""
    return current_app.config


"""
Use cfg() inside functions/routes/CLI that run under a context.
For modules that are imported outside a context (seeds, loaders),
don’t read config at import time — wrap it in functions.
"""
