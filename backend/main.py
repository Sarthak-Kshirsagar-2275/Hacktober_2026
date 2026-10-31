import json
import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from scorer import PERSONA_WEIGHTS, PRIORITY_PROFILES, build_live_report

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DB_PATH = Path(__file__).resolve().parent / "localeiq.db"

SEED_LOCALITIES = [
    ("dlf_phase_4", "DLF Phase 4 (Sector 28), Gurugram", 28.4672, 77.0819, 22500, 86, 78, 1.5),
    ("golf_course_road", "Golf Course Road (Sector 54), Gurugram", 28.4389, 77.1058, 28500, 91, 84, 1.0),
    ("golf_course_ext", "Golf Course Ext. Road (Sector 65), Gurugram", 28.4021, 77.0695, 18500, 83, 72, 2.5),
    ("sohna_road", "Sohna Road (Sector 49), Gurugram", 28.4128, 77.0419, 14200, 78, 68, 3.5),
    ("sushant_lok_1", "Sushant Lok Phase 1 (Sector 43), Gurugram", 28.4555, 77.0801, 19800, 82, 74, 2.0),
    ("dwarka_expressway", "Dwarka Expressway (Sector 104), Gurugram", 28.4789, 76.9932, 13800, 74, 65, 4.5),
    ("new_gurugram", "New Gurugram (Sector 82), Gurugram", 28.3875, 76.9685, 11500, 76, 70, 4.0),
    ("palam_vihar", "Palam Vihar (Sector 23), Gurugram", 28.5085, 77.0322, 15200, 80, 75, 2.5),
]


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS localities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                avg_price_sqft INTEGER NOT NULL,
                base_safety_score INTEGER NOT NULL,
                base_water_score INTEGER NOT NULL,
                power_outage_hrs_week REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS report_cache (
                cache_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO localities
            (id, name, lat, lon, avg_price_sqft, base_safety_score, base_water_score, power_outage_hrs_week)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            SEED_LOCALITIES,
        )
        conn.commit()


def get_locality_by_id(locality_id: str) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM localities WHERE id = ?", (locality_id,)).fetchone()
        return dict(row) if row else None


def get_all_localities() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM localities ORDER BY name").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


app = FastAPI(title="LocaleIQ API")


@app.exception_handler(RequestValidationError)
async def handle_invalid_request(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"detail": "Please check your choices and try again."})


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "We couldn't prepare the report. Please try again."})


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/localities")
def list_localities() -> list[dict]:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, name, avg_price_sqft FROM localities ORDER BY name").fetchall()
        return [dict(r) for r in rows]


@app.get("/api/report")
async def generate_report(
    locality_id: str = Query(..., description="Locality ID from database"),
    priorities: list[str] = Query(default=[], description="Repeatable household priority IDs"),
    persona: str | None = Query(default=None, description="Legacy profile: family, commuter, investor"),
) -> dict:
    selected_priorities = list(dict.fromkeys(priorities))
    unknown_priorities = sorted(set(selected_priorities) - set(PRIORITY_PROFILES))
    if unknown_priorities:
        raise HTTPException(status_code=400, detail="Please review your selected priorities and try again.")
    if persona is not None and persona not in PERSONA_WEIGHTS:
        raise HTTPException(status_code=400, detail="Please review your choices and try again.")

    init_db()
    locality = get_locality_by_id(locality_id)
    if not locality:
        raise HTTPException(status_code=404, detail="That area isn't available. Please choose another and try again.")

    cache_variant = (
        f"priorities:{','.join(sorted(selected_priorities))}"
        if selected_priorities
        else persona or "balanced"
    )
    cache_key = f"report-v4:{locality_id}:{cache_variant}"
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT payload FROM report_cache WHERE cache_key = ?", (cache_key,)).fetchone()
        if row:
            return json.loads(row[0])

    config = {
        "waqi_api_key": os.getenv("WAQI_API_KEY", ""),
        "openweather_api_key": os.getenv("OPENWEATHER_API_KEY", ""),
        "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434"),
        "ollama_model": os.getenv("OLLAMA_MODEL", "gemma4:12b"),
        "air_quality_api_url": os.getenv(
            "AIR_QUALITY_API_URL", "https://air-quality-api.open-meteo.com/v1/air-quality"
        ),
        "overpass_api_url": os.getenv(
            "OVERPASS_API_URL", "https://overpass-api.de/api/interpreter"
        ),
        "news_rss_url": os.getenv("NEWS_RSS_URL", "https://news.google.com/rss/search"),
    }

    report = await build_live_report(
        locality=locality,
        persona=persona,
        config=config,
        priorities=selected_priorities,
        comparison_localities=get_all_localities(),
    )

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO report_cache (cache_key, payload) VALUES (?, ?)",
            (cache_key, json.dumps(report)),
        )
        conn.commit()

    return report


FRONTEND_DIR = ROOT_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
