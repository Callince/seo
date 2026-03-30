"""
Gmail API Authentication Script
Run this to authenticate and get the token.pickle file
"""

import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Gmail API scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def authenticate():
    """
    Authenticate with Gmail API and save token
    """
    print("=" * 70)
    print("GMAIL API AUTHENTICATION FOR support@seodada.com")
    print("=" * 70)
    print()

    creds = None
    token_path = 'token.pickle'

    # Check if token already exists
    if os.path.exists(token_path):
        print(f"Found existing token file: {token_path}")
        response = input("Do you want to re-authenticate? (y/n): ").strip().lower()
        if response != 'y':
            print("Using existing token. Exiting.")
            return True
        else:
            print("Removing existing token and re-authenticating...")
            os.remove(token_path)

    print()
    print("Starting OAuth authentication flow...")
    print()
    print("IMPORTANT STEPS:")
    print("1. A browser window will open (or you'll see a URL below)")
    print("2. Sign in with: support@seodada.com")
    print("3. Click 'Advanced' if you see 'App not verified' warning")
    print("4. Click 'Go to SEO Dada (unsafe)' - it's safe, this is your app")
    print("5. Click 'Allow' to grant email sending permissions")
    print()
    print("=" * 70)
    print()

    try:
        # Create OAuth flow
        flow = InstalledAppFlow.from_client_secrets_file(
            'credentials.json',
            SCOPES,
            redirect_uri='http://localhost:8080/'
        )

        # Run local server for OAuth
        print("Opening browser for authentication...")
        print()
        creds = flow.run_local_server(
            port=8080,
            open_browser=True,
            success_message='Authentication successful! You can close this window and return to the terminal.'
        )

        # Save the credentials
        with open(token_path, 'wb') as token:
            pickle.dump(creds, token)

        print()
        print("=" * 70)
        print("SUCCESS! Authentication Complete")
        print("=" * 70)
        print()
        print(f"✓ Token saved to: {token_path}")
        print(f"✓ Authenticated as: support@seodada.com")
        print(f"✓ Scope: {SCOPES[0]}")
        print()
        print("Your application can now send emails via Gmail API!")
        print()
        print("Next steps:")
        print("1. Run 'python quick_gmail_test.py' to send a test email")
        print("2. Start your Flask app with 'python app.py'")
        print("3. All emails will now be sent via Gmail API automatically")
        print()
        print("=" * 70)

        return True

    except Exception as e:
        print()
        print("=" * 70)
        print("ERROR: Authentication Failed")
        print("=" * 70)
        print(f"Error: {str(e)}")
        print()

        if "Gmail API has not been used" in str(e):
            print("SOLUTION:")
            print("1. Enable Gmail API in Google Cloud Console:")
            print("   https://console.cloud.google.com/apis/library/gmail.googleapis.com?project=original-bolt-477106-m2")
            print("2. Click 'ENABLE' button")
            print("3. Wait 1-2 minutes and try again")
        elif "redirect_uri_mismatch" in str(e):
            print("SOLUTION:")
            print("1. Go to Google Cloud Console:")
            print("   https://console.cloud.google.com/apis/credentials?project=original-bolt-477106-m2")
            print("2. Edit your Web application OAuth client")
            print("3. Add this redirect URI: http://localhost:8080/")
            print("4. Save and try again")
        elif "access_denied" in str(e):
            print("SOLUTION:")
            print("Make sure you:")
            print("1. Sign in with support@seodada.com")
            print("2. Click 'Allow' to grant permissions")
        else:
            print("Please check:")
            print("1. credentials.json exists in the current directory")
            print("2. Gmail API is enabled in Google Cloud Console")
            print("3. OAuth consent screen is configured with test user: support@seodada.com")

        print()
        return False

if __name__ == '__main__':
    success = authenticate()

    if not success:
        print()
        input("Press Enter to exit...")
