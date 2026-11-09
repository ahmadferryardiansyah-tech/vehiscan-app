from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from src.ai.detector import VehicleDetector
from src.ai import anpr
from src.api.routes import analytics, calibration, manage, system, video
from src.database import db_manager as db

@asynccontextmanager
async def lifespan(app):
    db.init_db(); app.state.detector = VehicleDetector(); anpr.get_reader(); yield

app = FastAPI(title="VehiScan ITS", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parents[2] / "static")), name="static")
for r in (analytics.router, system.router, video.router, calibration.router, manage.router): app.include_router(r)
