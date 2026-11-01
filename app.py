"""Vercel entrypoint for the existing LocaleIQ FastAPI application."""
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from main import app  # noqa: E402
