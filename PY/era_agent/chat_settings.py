"""Persistent storage for the user's custom chat instructions.

These are *standing instructions* the user writes once (tone, formatting, firm
preferences, how to cite law, signature, etc.). They are prepended to the chat
system prompt on every message by the .NET app, which reads them via the API.

Storage is a single UTF-8 text file. The path is configurable via the
CHAT_INSTRUCTIONS_PATH environment variable so it can point at a Railway volume
for durability across redeploys. Without a volume it still persists across
process restarts within the same container.
"""

import os
from pathlib import Path

# All durable files live under ERA_DATA_DIR (default PY/data; the Railway volume
# at /data in production). CHAT_INSTRUCTIONS_PATH still overrides for back-compat.
_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _path() -> Path:
    override = os.getenv("CHAT_INSTRUCTIONS_PATH")
    if override:
        return Path(override)
    base = Path(os.getenv("ERA_DATA_DIR", str(_DEFAULT_DATA_DIR)))
    return base / "chat_instructions.txt"


def load_instructions() -> str:
    """Return the saved instructions, or an empty string if none are set."""
    p = _path()
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError:
        return ""


def save_instructions(text: str) -> str:
    """Persist the instructions (trimmed) and return what was saved."""
    text = (text or "").strip()
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return text
