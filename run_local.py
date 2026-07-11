"""Local dev entrypoint — fixes cwd so relative sqlite path and imports work."""
import os
import sys

backend = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
os.chdir(backend)
sys.path.insert(0, backend)
os.environ.setdefault("DATABASE_URL", "sqlite:///./tracker.db")

import uvicorn

uvicorn.run("main:app", host="127.0.0.1", port=8000, loop="asyncio")
