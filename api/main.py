"""API FastAPI : santé, routes branchées sur contracts.py, et service du front buildé."""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

import contracts  # noqa: E402
from api import db  # noqa: E402
from api.individuel_routes import router as individuel_router  # noqa: E402
from api.team_routes import router as team_router  # noqa: E402

USER_ID = os.getenv("USER_ID", "ichane")
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

app = FastAPI(title="Mental Health Project")
app.include_router(team_router)
app.include_router(individuel_router)


@app.get("/health")
def health():
    if not db.database_url():
        return {"status": "ok", "postgres": "non configuré"}
    try:
        db.ping()
        return {"status": "ok", "postgres": "ok"}
    except Exception as e:
        return {"status": "degraded", "postgres": f"erreur : {type(e).__name__}"}


@app.get("/api/metrics")
def metrics(days: int = 42):
    return contracts.get_daily_metrics(USER_ID, days)


@app.get("/api/drivers")
def drivers():
    return contracts.get_drivers(USER_ID)


@app.get("/api/forecast")
def forecast():
    return contracts.forecast_week(USER_ID)


@app.get("/api/slots/{date}")
def slots(date: str):
    return contracts.get_free_slots(USER_ID, date)


@app.get("/api/team/{team_id}")
def team(team_id: str):
    return contracts.team_trends(team_id)


# Front React buildé (web/dist), servi à la racine. Absent en dev : on utilise `npm run dev`.
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        return FileResponse(WEB_DIST / "index.html")
