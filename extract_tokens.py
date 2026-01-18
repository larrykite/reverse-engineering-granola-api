#!/usr/bin/env python3
"""
Extract refresh_token and client_id from Granola's supabase.json and update config.json
"""

import json
import base64
import re
from pathlib import Path

SUPABASE_PATH = Path.home() / "Library" / "Application Support" / "Granola" / "supabase.json"
CONFIG_PATH = Path("config.json")


def extract_tokens():
    """Extract refresh_token and client_id from Granola's supabase.json"""

    if not SUPABASE_PATH.exists():
        print(f"Error: {SUPABASE_PATH} not found")
        print("Make sure Granola is installed and you've logged in at least once.")
        return None, None

    with open(SUPABASE_PATH, 'r') as f:
        supabase_data = json.load(f)

    # Parse the workos_tokens JSON string
    workos_tokens_str = supabase_data.get('workos_tokens')
    if not workos_tokens_str:
        print("Error: workos_tokens not found in supabase.json")
        return None, None

    workos_tokens = json.loads(workos_tokens_str)

    # Extract refresh_token
    refresh_token = workos_tokens.get('refresh_token')
    if not refresh_token:
        print("Error: refresh_token not found in workos_tokens")
        return None, None

    # Extract client_id from JWT access_token
    access_token = workos_tokens.get('access_token')
    if not access_token:
        print("Error: access_token not found in workos_tokens")
        return refresh_token, None

    # Decode JWT payload (middle section)
    parts = access_token.split('.')
    if len(parts) != 3:
        print("Error: access_token is not a valid JWT")
        return refresh_token, None

    # Add padding if needed for base64 decoding
    payload = parts[1]
    padding = 4 - len(payload) % 4
    if padding != 4:
        payload += '=' * padding

    try:
        decoded = base64.urlsafe_b64decode(payload)
        jwt_payload = json.loads(decoded)
    except Exception as e:
        print(f"Error decoding JWT: {e}")
        return refresh_token, None

    # Extract client_id from iss field
    iss = jwt_payload.get('iss', '')
    match = re.search(r'client_[^"/]+', iss)
    client_id = match.group(0) if match else None

    if not client_id:
        print("Error: Could not extract client_id from JWT iss field")
        return refresh_token, None

    return refresh_token, client_id


def update_config(refresh_token, client_id):
    """Update config.json with extracted tokens"""

    config = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r') as f:
            config = json.load(f)

    if refresh_token:
        config['refresh_token'] = refresh_token
    if client_id:
        config['client_id'] = client_id

    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"Updated {CONFIG_PATH}")


def main():
    print(f"Reading from: {SUPABASE_PATH}")

    refresh_token, client_id = extract_tokens()

    if not refresh_token:
        print("Failed to extract tokens")
        return 1

    print(f"refresh_token: {refresh_token[:10]}...")
    print(f"client_id: {client_id}")

    update_config(refresh_token, client_id)

    print("\nDone! You can now run: python3 main.py /path/to/output")
    return 0


if __name__ == "__main__":
    exit(main())
