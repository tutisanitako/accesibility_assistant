# backend/config.py
"""
Central configuration. All paths, settings, and env vars live here.
Import from here — never use os.getenv() or hardcoded paths elsewhere.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Paths ─────────────────────────────────────────────────────────────────────

BACKEND_DIR = Path(__file__).parent
PROJECT_DIR = BACKEND_DIR.parent

DB_PATH        = BACKEND_DIR / "data.db"
TTC_CSV_PATH   = BACKEND_DIR / "ttc_final.csv"   # already scraped
LOG_DIR        = PROJECT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ── Environment ───────────────────────────────────────────────────────────────

load_dotenv(BACKEND_DIR / ".env")

GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── App settings ──────────────────────────────────────────────────────────────

CONCERT_CACHE_HOURS   = 3    # re-scrape TKT every N hours
BUS_CACHE_HOURS       = 24   # re-load TTC CSV once per day
CONCERT_DEFAULT_DAYS  = 3    # days ahead to show if user doesn't specify
WHISPER_MODEL         = "medium"   # small | medium | large

# ── Validation ────────────────────────────────────────────────────────────────

def check_env() -> list[str]:
    """Return a list of missing/empty required env vars."""
    missing = []
    if not GOOGLE_CREDENTIALS_PATH or not Path(GOOGLE_CREDENTIALS_PATH).exists():
        missing.append("GOOGLE_APPLICATION_CREDENTIALS (file not found)")
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    return missing