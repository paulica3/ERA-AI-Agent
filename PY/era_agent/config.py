import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096

# ── Persistent data dir (Railway volume in prod, PY/data locally) ─────────────
_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR = Path(os.getenv("ERA_DATA_DIR", str(_DEFAULT_DATA_DIR)))

# ── Database ──────────────────────────────────────────────────────────────────
# Production sets DATABASE_URL to the Railway Postgres connection string.
# Without it, fall back to a local SQLite file under the data dir for dev.
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{(DATA_DIR / 'era.db').as_posix()}"

# ── Auth ──────────────────────────────────────────────────────────────────────
# JWT_SECRET MUST be set to a strong random value in production.
JWT_SECRET = os.getenv("JWT_SECRET", "dev-insecure-change-me")
JWT_EXPIRY_MINUTES = int(os.getenv("JWT_EXPIRY_MINUTES", str(60 * 24 * 7)))  # 7 days
# If set, /auth/register requires this invite code. Empty means no code enforced.
FIRM_SIGNUP_CODE = os.getenv("FIRM_SIGNUP_CODE", "")
