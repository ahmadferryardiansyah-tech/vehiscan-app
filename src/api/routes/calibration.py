import base64, json, os, tempfile
from pathlib import Path
import cv2, numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from src.ai.detector import ROOT, get_cal
from src.api.deps import page
from src.database import db_manager as db

router = APIRouter(); CAL = ROOT / "configs" / "calibration.json"

class Geo(BaseModel):
    src: list[list[float]]; width: float; length: float; line_a: float; line_b: float

class SaveReq(Geo):
    camera_id: int; frame: list[int]; roi: list[list[float]] = []

def _enc(f):
    return {"w": f.shape[1], "h": f.shape[0], "image": "data:image/jpeg;base64," + base64.b64encode(cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 88])[1]).decode()}

def _grab(path, t):
    cap = cv2.VideoCapture(path); cap.set(cv2.CAP_PROP_POS_MSEC, max(t, 0) * 1000); ok, f = cap.read(); cap.release()
    if not ok: raise HTTPException(400, "Frame tidak bisa dibaca dari video (cek format/waktu).")
    return _enc(f)

def _check(g):
    s = np.array(g.src, float)
    if len(s) != 4 or g.width <= 0 or g.length <= 0: return "Butuh 4 titik serta lebar & panjang area > 0."
    cr = [(lambda a, b: a[0] * b[1] - a[1] * b[0])(s[(i + 1) % 4] - s[i], s[(i + 2) % 4] - s[(i + 1) % 4]) for i in range(4)]
    if not all(c > 0 for c in cr) or s[:2, 1].mean() >= s[2:, 1].mean() or s[0, 0] >= s[1, 0] or s[3, 0] >= s[2, 0]:
        return "Urutan titik harus: 1 kiri-atas → 2 kanan-atas → 3 kanan-bawah → 4 kiri-bawah (bentuk segiempat cembung, searah jarum jam)."
    if not (0 <= g.line_a <= g.length and 0 <= g.line_b <= g.length) or g.line_a == g.line_b: return "Garis A/B harus di dalam panjang area (0..L) dan tidak sama."
    return None

@router.get("/calibration", response_class=HTMLResponse)
def calibration(request: Request):
    return page(request, "calibration.html", cams=db.q("SELECT * FROM cameras ORDER BY id"), jobs=db.q("SELECT id,filename FROM jobs ORDER BY id DESC LIMIT 30"), cal=get_cal().get("cameras", {}))

@router.post("/api/v1/calibration/frame")
def frame(file: UploadFile | None = File(None), job_id: int = Form(0), t: float = Form(0)):
    tmp = None
    if file and file.filename:
        data = file.file.read(); img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is not None: return _enc(img)
        f = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix); f.write(data); f.close(); tmp = path = f.name
    else:
        j = db.q("SELECT path FROM jobs WHERE id=?", (job_id,), one=True) if job_id else None
        if not j: raise HTTPException(400, "Pilih file gambar/video atau video yang sudah diunggah.")
        path = j["path"]
    try: return _grab(path, t)
    finally:
        if tmp: os.unlink(tmp)

def _open(url):
    try: return cv2.VideoCapture(url, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
    except TypeError: return cv2.VideoCapture(url)

@router.get("/api/v1/calibration/snapshot/{cam_id}")
def snapshot(cam_id: int):
    cam = db.q("SELECT * FROM cameras WHERE id=?", (cam_id,), one=True)
    if not cam: raise HTTPException(404, "Kamera tidak ada")
    src = (cam["rtsp"] or "").strip()
    if not src or src.startswith("demo"): raise HTTPException(400, "Kamera ini tidak punya sumber RTSP. Ambil frame dari gambar/video.")
    cap = _open(src); ok, f = cap.read(); cap.release()
    if not ok: raise HTTPException(502, "Tidak bisa mengambil frame dari RTSP kamera.")
    return _enc(f)

@router.post("/api/v1/calibration/preview")
def preview(g: Geo):
    err = _check(g)
    if err: return {"ok": False, "error": err}
    s = np.array(g.src, np.float32); H = cv2.getPerspectiveTransform(s, np.float32([[0, 0], [g.width, 0], [g.width, g.length], [0, g.length]])); Hi = np.linalg.inv(H)
    line = lambda y: cv2.perspectiveTransform(np.float32([[[0, y], [g.width, y]]]), Hi)[0].tolist()
    return {"ok": True, "a": line(g.line_a), "b": line(g.line_b), "dist": abs(g.line_b - g.line_a),
            "ppm_far": round(float(np.linalg.norm(s[1] - s[0]) / g.width)), "ppm_near": round(float(np.linalg.norm(s[2] - s[3]) / g.width))}

@router.post("/api/v1/calibration/save")
def save(r: SaveReq):
    err = _check(r)
    if err: raise HTTPException(400, err)
    w, h = r.frame; rd = lambda pts: [[round(x, 1), round(y, 1)] for x, y in pts]
    data = json.loads(CAL.read_text())
    data.setdefault("cameras", {})[str(r.camera_id)] = {
        "roi": rd(r.roi) if len(r.roi) >= 3 else [[0, 0], [w, 0], [w, h], [0, h]], "src": rd(r.src),
        "dst": [[0, 0], [r.width, 0], [r.width, r.length], [0, r.length]], "line_a": r.line_a, "line_b": r.line_b,
        "frame": [w, h], "width_m": r.width, "length_m": r.length}
    tmp = CAL.with_suffix(".tmp"); tmp.write_text(json.dumps(data, indent=2)); tmp.replace(CAL)
    return {"ok": True}
