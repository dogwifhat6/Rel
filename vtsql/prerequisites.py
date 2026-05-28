from __future__ import annotations

import os
import requests
import psycopg2
from vtsql.config import DEFAULT_DB_CONFIG, OLLAMA_URL, OLLAMA_MODEL

class PrerequisitesNotMetError(ImportError):
    """Custom ImportError raised when local dependencies/prerequisites are missing."""
    pass

def check_prerequisites() -> None:
    if os.environ.get("BYPASS_VTSQL_PRECHECKS") == "1":
        return

    errors = []
    
    # 1. Check PortAudio (sounddevice)
    portaudio_ok = True
    portaudio_error_msg = ""
    try:
        import sounddevice  # noqa: F401
    except OSError as e:
        portaudio_ok = False
        portaudio_error_msg = str(e)
    except ImportError as e:
        portaudio_ok = False
        portaudio_error_msg = str(e)

    if not portaudio_ok:
        errors.append({
            "name": "PortAudio System Library",
            "status": "MISSING / FAILED TO LOAD",
            "error_detail": portaudio_error_msg,
            "steps": [
                "Install PortAudio on macOS: brew install portaudio",
                "Install PortAudio on Debian/Ubuntu: sudo apt-get install libportaudio2",
                "Install PortAudio on Fedora/RedHat: sudo dnf install portaudio-devel",
                "Ensure your Python environment is restarted after installation."
            ]
        })

    # 2. Check Ollama
    ollama_ok = True
    ollama_error_msg = ""
    ollama_base_url = OLLAMA_URL.rsplit("/api/", 1)[0]
    
    try:
        r = requests.get(f"{ollama_base_url}/api/tags", timeout=1.5)
        if r.ok:
            models = [m["name"] for m in r.json().get("models", [])]
            model_found = False
            for m in models:
                if OLLAMA_MODEL in m or m in OLLAMA_MODEL:
                    model_found = True
                    break
            
            if not model_found:
                ollama_ok = False
                ollama_error_msg = f"Model '{OLLAMA_MODEL}' not found in Ollama local registry (Available models: {models})."
        else:
            ollama_ok = False
            ollama_error_msg = f"Ollama returned HTTP {r.status_code}."
    except Exception as e:
        ollama_ok = False
        ollama_error_msg = f"Failed to connect to Ollama at {ollama_base_url}: {e}"

    if not ollama_ok:
        steps = [
            "Download and install Ollama from https://ollama.com",
            "Ensure the Ollama application is running on your machine.",
        ]
        if "Failed to connect" not in ollama_error_msg:
            steps.append(f"Download the required model by running: ollama pull {OLLAMA_MODEL}")
        else:
            steps.append(f"Start the Ollama daemon and pull the model: ollama pull {OLLAMA_MODEL}")
            
        errors.append({
            "name": f"Ollama & {OLLAMA_MODEL} Model",
            "status": "NOT RUNNING / MODEL MISSING",
            "error_detail": ollama_error_msg,
            "steps": steps
        })

    # 3. Check PostgreSQL Connection
    postgres_ok = True
    postgres_error_msg = ""
    try:
        conn = psycopg2.connect(**DEFAULT_DB_CONFIG)
        conn.close()
    except Exception as e:
        postgres_ok = False
        postgres_error_msg = str(e)

    if not postgres_ok:
        errors.append({
            "name": "PostgreSQL Database",
            "status": "CONNECTION FAILED",
            "error_detail": postgres_error_msg,
            "steps": [
                "Ensure PostgreSQL is installed and running (e.g. brew services start postgresql or pg_ctl).",
                f"Verify database '{DEFAULT_DB_CONFIG['dbname']}' exists. Create it with: createdb {DEFAULT_DB_CONFIG['dbname']} or via psql.",
                f"Verify credentials: host={DEFAULT_DB_CONFIG['host']}, port={DEFAULT_DB_CONFIG['port']}, user={DEFAULT_DB_CONFIG['user']}.",
                "Set environmental variables DB_HOST, DB_USER, DB_PASSWORD, or DB_NAME if customized."
            ]
        })

    if errors:
        msg = ["\n" + "="*80, "❌ PREREQUISITES NOT MET FOR VOICETOSQLDATABASE", "="*80]
        for err in errors:
            msg.append(f"\n🔹 {err['name']} [{err['status']}]")
            msg.append(f"  Reason: {err['error_detail']}")
            msg.append("  Resolution Steps:")
            for idx, step in enumerate(err['steps'], 1):
                msg.append(f"    {idx}. {step}")
        msg.append("\n" + "="*80)
        msg.append("💡 Note: If you only need to use the REST HTTP client (VoiceToSQLClient) to connect to a remote server,")
        msg.append("   you can bypass these local prechecks by setting the environment variable:")
        msg.append("   export BYPASS_VTSQL_PRECHECKS=1")
        msg.append("="*80 + "\n")
        raise PrerequisitesNotMetError("\n".join(msg))
