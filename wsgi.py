#!/usr/bin/env python3
"""WSGI entry point for production deployment."""

import sys
import os

# Add project directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Set environment for production
os.environ.setdefault('FLASK_ENV', 'production')

try:
    from app import application

    # Ensure production settings
    application.config['DEBUG'] = False
    application.config['TESTING'] = False

except Exception as e:
    import traceback

    def application(environ, start_response):
        status = '500 Internal Server Error'
        headers = [('Content-Type', 'text/html; charset=utf-8')]
        start_response(status, headers)

        error_page = f"""
        <!DOCTYPE html>
        <html>
        <head><title>Application Error</title></head>
        <body>
            <h1>Application Error</h1>
            <p><strong>Error:</strong> {str(e)}</p>
            <p><strong>Type:</strong> {type(e).__name__}</p>
            <pre>{traceback.format_exc()}</pre>
        </body>
        </html>
        """
        return [error_page.encode('utf-8')]

if __name__ == "__main__":
    print("WSGI module loaded successfully")
