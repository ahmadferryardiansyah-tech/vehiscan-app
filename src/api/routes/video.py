import json, shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from src.ai import video_processor as vp
from src.api.deps import page
from src.database import db_manager as db

router = APIRouter()
UP = Path(__file__).resolve().parents[3] / "data" / "uploads"
ALLOWED = {".mp4", ".mov", ".avi", ".mkv"}

@router.get("/videos", response_class=HTMLResponse)
def videos(request: Request):
    return page(request, "videos.html", cams=db.q("SELECT * FROM cameras ORDER BY id"), engine=request.app.state.detector, err=request.query_params.get("err"))

@router.post("/videos/upload")
def upload(request: Request, file: UploadFile = File(...), camera_id: int = Form(...), started: str = Form(""), stride: int = Form(1)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED: return RedirectResponse("/videos?err=" + quote("Format harus MP4/MOV/AVI/MKV"), 303)
    UP.mkdir(parents=True, exist_ok=True); dest = UP / f"{uuid4().hex}{ext}"
    with open(dest, "wb") as f: shutil.copyfileobj(file.file, f, 1024 * 1024)
    info, errs, warns = vp.inspect(dest)
    if errs: dest.unlink(missing_ok=True); return RedirectResponse("/videos?err=" + quote(errs[0]), 303)
    try: datetime.fromisoformat(started)
    except ValueError: started = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    note = f"{info['w']}x{info['h']} · {info['fps']} fps · {info['dur']} dtk · {info['mbps']} Mbps." + "".join(" ⚠ " + w for w in warns)
    if not db.q("SELECT 1 FROM cameras WHERE id=?", (camera_id,), one=True):
        dest.unlink(missing_ok=True); return RedirectResponse("/videos?err=" + quote("Kamera tidak ditemukan."), 303)
    job_id = db.insert("INSERT INTO jobs(filename,path,camera_id,started,stride,status,message,created,dur) VALUES(?,?,?,?,?,?,?,?,?)",
         (file.filename, str(dest), camera_id, started, max(1, min(stride, 10)), "queued", note, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), info["dur"]))
    vp.start(job_id, request.app.state.detector)
    return RedirectResponse("/videos", 303)

@router.get("/api/v1/videos/jobs")
def jobs():
    rows = db.q("SELECT id,filename,camera_id,started,status,progress,frames,events,message FROM jobs ORDER BY id DESC LIMIT 30")
    for r in rows: r["replay"] = r["status"] not in ("queued", "processing", "cancelling") and (vp.REPLAYS / f"job_{r['id']}.mp4").exists()
    return rows

@router.get("/videos/{i}/replay.mp4")
def replay(i: int):
    f = vp.REPLAYS / f"job_{i}.mp4"
    if not f.exists(): raise HTTPException(404, "Replay belum tersedia")
    return FileResponse(f, media_type="video/mp4")  # mendukung Range -> bisa digeser

@router.get("/api/v1/videos/{i}/events")
def events(i: int):
    """Event job ini dengan offset detik di video (untuk penanda & lompat di replay)."""
    j = db.q("SELECT started FROM jobs WHERE id=?", (i,), one=True)
    if not j: raise HTTPException(404, "Job tidak ada")
    t0 = datetime.fromisoformat(j["started"])
    return [{"t": max(0, (datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S") - t0).total_seconds()), "plate": r["plate"], "pkji": r["pkji"], "speed": r["speed"], "status": r["status"]}
            for r in db.q("SELECT ts,plate,pkji,speed,status FROM detections WHERE src=? ORDER BY ts", (f"video:{i}",))]

@router.get("/api/v1/videos/{i}/preview.jpg")
def preview(i: int):
    b = vp.PREVIEW.get(i)
    if not b: raise HTTPException(404, "Pratinjau belum tersedia")
    return Response(b, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

@router.post("/videos/{i}/cancel")
def cancel(i: int):
    db.q("UPDATE jobs SET status='cancelling' WHERE id=? AND status IN ('queued','processing')", (i,), commit=True)
    return RedirectResponse("/videos", 303)

@router.post("/videos/{i}/delete")
def delete(i: int):
    """Hapus job: file video, pratinjau, DAN hasil deteksi/notifikasi yang dihasilkan job ini."""
    j = db.q("SELECT * FROM jobs WHERE id=?", (i,), one=True)
    if j and j["status"] not in ("processing", "cancelling"):
        Path(j["path"]).unlink(missing_ok=True); vp.PREVIEW.pop(i, None)
        for f in (vp.REPLAYS / f"job_{i}.mp4", vp.REPLAYS / f"job_{i}.part.mp4"): f.unlink(missing_ok=True)
        for t in ("detections", "notifications"): db.q(f"DELETE FROM {t} WHERE src=?", (f"video:{i}",), commit=True)
        db.q("DELETE FROM jobs WHERE id=?", (i,), commit=True)
    return RedirectResponse("/videos", 303)
