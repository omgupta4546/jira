import os
from pathlib import Path
import json

print("--- DIAGNOSTIC START ---")
print(f"Current Directory: {os.getcwd()}")

env_path = Path(".env").absolute()
print(f"Looking for .env at: {env_path}")
print(f"Exists: {env_path.exists()}")

if env_path.exists():
    with open(env_path, "r") as f:
        lines = f.readlines()
        print(f"Read {len(lines)} lines from .env")
        for line in lines:
            if "AI_PROVIDER" in line or "MOCK_MODE" in line or "OPENAI_API_KEY" in line:
                print(f"  [RAW] {line.strip()}")

try:
    from config import get_settings
    s = get_settings()
    print("--- SETTINGS LOADED ---")
    print(f"AI_PROVIDER: '{s.ai_provider}'")
    print(f"MOCK_MODE: {s.mock_mode}")
    print(f"OPENAI_KEY_LENGTH: {len(s.openai_api_key) if s.openai_api_key else 0}")
except Exception as e:
    print(f"ERROR: {e}")

print("--- DIAGNOSTIC END ---")
