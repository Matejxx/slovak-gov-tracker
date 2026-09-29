import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

import api as api_router
import poller
from database import DATABASE_URL, SessionLocal, engine
from models import Base

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def wait_for_db(retries: int = 15, delay: float = 2.0):
    # SQLite is always ready immediately
    if DATABASE_URL.startswith("sqlite"):
        return
    for attempt in range(retries):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database ready")
            return
        except OperationalError:
            logger.warning("DB not ready, retry %d/%d", attempt + 1, retries)
            time.sleep(delay)
    raise RuntimeError("Could not connect to database after retries")


@asynccontextmanager
async def lifespan(app: FastAPI):
    wait_for_db()
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    poller.seed_aircraft(db)
    db.close()

    task = asyncio.create_task(poller.poll_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Slovak Gov Aircraft Tracker", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CANONICAL_HOST = "kamletifico.sk"


@app.middleware("http")
async def seo_middleware(request, call_next):
    host = request.headers.get("host", "").split(":")[0]
    path = request.url.path
    query = f"?{request.url.query}" if request.url.query else ""

    # www.* -> apex, single canonical host
    if host == f"www.{CANONICAL_HOST}":
        return RedirectResponse(f"https://{CANONICAL_HOST}{path}{query}", status_code=301)

    # duplicate-URL cleanup: /index.html and trailing-slash variants
    if path in ("/index.html", "/index.html/"):
        return RedirectResponse(f"/{query}", status_code=301)
    if path != "/" and path.endswith("/") and not path.startswith("/api"):
        return RedirectResponse(f"{path.rstrip('/')}{query}", status_code=301)

    if path == "/favicon.ico":
        return RedirectResponse("/favicon.svg", status_code=301)

    response = await call_next(request)

    response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if path.endswith((".svg", ".png", ".jpg", ".ico")):
        response.headers["Cache-Control"] = "public, max-age=86400"
    elif not path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.include_router(api_router.router, prefix="/api")

# Serve frontend — must be last
import os, pathlib
frontend_dir = pathlib.Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
