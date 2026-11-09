import cv2, numpy as np
from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from src.ai import anpr
from src.api.deps import page
from src.database import db_manager as db

router = APIRouter()
back = lambda p: RedirectResponse(p, 303)

@router.get("/notifications", response_class=HTMLResponse)
def notifs(request: Request):
    return page(request, "notifications.html", rows=db.q("SELECT * FROM notifications ORDER BY ts DESC LIMIT 100"))

@router.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    return page(request, "settings.html", engine=request.app.state.detector, anpr=anpr.get_reader(), saved=request.query_params.get("saved"),
                has_demo={r["src"]: r["n"] for r in db.q("SELECT src, COUNT(*) n FROM detections GROUP BY src")})

@router.post("/settings/clear-demo")
def clear_demo():
    for t in ("detections", "notifications"): db.q(f"DELETE FROM {t} WHERE src='demo'", commit=True)
    return back("/settings?saved=1")

@router.post("/settings/reload-ai")
def reload_ai(request: Request):
    request.app.state.detector.load(); anpr.get_reader().load(); return back("/settings?saved=1")

@router.post("/api/v1/anpr/test")
def anpr_test(file: UploadFile = File(...)):
    img = cv2.imdecode(np.frombuffer(file.file.read(), np.uint8), cv2.IMREAD_COLOR)
    if img is None: return {"ok": False, "error": "Bukan file gambar"}
    p, s = anpr.get_reader().read(img)
    return {"ok": True, "plate": p, "score": round(s, 2)}
