#!/usr/bin/env python3
"""
WSGI file for CloudLinux Passenger
"""

import sys
import os

# Add your project directory to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Set environment for production
os.environ.setdefault('FLASK_ENV', 'production')

try:
    # Import your Flask application
    from app import app as application
    
    # Configure for production
    application.config['DEBUG'] = False
    application.config['TESTING'] = False
    
    # Ensure the app context is available
    with application.app_context():
        pass
    
except ImportError as e:
    # Fallback error handler
    def application(environ, start_response):
        status = '500 Internal Server Error'
        headers = [('Content-Type', 'text/html; charset=utf-8')]
        start_response(status, headers)
        
        error_page = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Application Error</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .error {{ background: #f8d7da; color: #721c24; padding: 20px; border-radius: 5px; }}
                .info {{ background: #d1ecf1; color: #0c5460; padding: 10px; border-radius: 5px; margin: 10px 0; }}
                pre {{ background: #f8f9fa; padding: 10px; overflow-x: auto; }}
            </style>
        </head>
        <body>
            <h1>Application Import Error</h1>
            <div class="error">
                <strong>Error:</strong> {str(e)}
            </div>
            
            <div class="info">
                <strong>Current Directory:</strong> {os.getcwd()}
            </div>
            
            <div class="info">
                <strong>Python Version:</strong> {sys.version}
            </div>
            
            <div class="info">
                <strong>Python Path:</strong>
                <pre>{'<br>'.join(sys.path[:10])}</pre>
            </div>
            
            <div class="info">
                <strong>Files in Directory:</strong>
                <pre>{'<br>'.join(sorted(os.listdir('.'))[:20])}</pre>
            </div>
            
            <div class="info">
                <strong>Environment Variables:</strong>
                <ul>
                    <li>FLASK_ENV: {os.environ.get('FLASK_ENV', 'Not set')}</li>
                    <li>PYTHONPATH: {os.environ.get('PYTHONPATH', 'Not set')}</li>
                    <li>PATH: {os.environ.get('PATH', 'Not set')[:200]}...</li>
                </ul>
            </div>
        </body>
        </html>
        """
        
        return [error_page.encode('utf-8')]

except Exception as e:
    # Handle any other errors
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
            <p><strong>Current Directory:</strong> {os.getcwd()}</p>
        </body>
        </html>
        """
        
        return [error_page.encode('utf-8')]

# Make sure this is available for Passenger
if __name__ == "__main__":
    print("WSGI module loaded successfully")