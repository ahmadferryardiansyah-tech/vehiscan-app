"""Kelola data referensi lewat web: lokasi, kamera, pengguna, dan parameter sistem (tambah / ubah / hapus)."""
import json
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from src.ai.detector import ROOT, get_cal
from src.api.deps import page
from src.database import db_manager as db
from src.traffic import pkji_calculator as calc

router = APIRouter()
ROAD_TYPES = db.SPEC["road_type"][1]  # 2/2-TT, 4/2-T, 6/2-T (nomenklatur PKJI 2023)
CAL = ROOT / "configs" / "calibration.json"
LBL = {"speed_limit": "Batas kecepatan", "speed_min": "Kecepatan minimum", "speed_max": "Kecepatan maksimum", "anpr_conf": "Ambang ANPR", "plate_every": "OCR tiap N frame", "plate_max_tries": "Maks percobaan OCR", "plate_min_width": "Lebar minimum kendaraan",
       "conf": "Confidence", "iou": "IoU", "imgsz": "Ukuran gambar", "device": "Perangkat", "track_buffer": "Track buffer", "match_thresh": "Match threshold",
       "track_high_thresh": "Track high threshold", "road_type": "Tipe jalan", "lane_width": "Lebar lajur", "split": "Pemisahan arah", "city_pop": "Ukuran kota", "f_chs": "F_CHS", "khs": "KHS", "lbe": "Lebar bahu efektif",
       **{f"los_{x}": f"Batas LOS {x.upper()}" for x in "abcde"}, **{f"lbl_{c}": f"Nama {c}" for c in db.PKJI_CODES}}

def go(path, ok=None, bad=None):
    return RedirectResponse(path + (f"?ok={quote(ok)}" if ok else f"?bad={quote(bad)}" if bad else ""), 303)

def num(raw, lo, hi, label, required=False):
    raw = str(raw or "").strip().replace(",", ".")
    if not raw:
        if required: raise ValueError(f"{label} wajib diisi")
        return None
    try: v = float(raw)
    except ValueError: raise ValueError(f"{label} harus berupa angka")
    if not lo <= v <= hi: raise ValueError(f"{label} harus antara {lo} dan {hi}")
    return v

def glob():
    return {k: db.param(k) for k in ("speed_limit", "lane_width", "split", "city_pop", "f_chs", "khs", "lbe")}

def drop_cal(cam_id):
    """Hapus kalibrasi kamera yang dihapus, agar id yang dipakai ulang tidak mewarisinya."""
    d = json.loads(CAL.read_text())
    if d.get("cameras", {}).pop(str(cam_id), None) is not None:
        tmp = CAL.with_suffix(".tmp"); tmp.write_text(json.dumps(d, indent=2)); tmp.replace(CAL)

# ------------------------------------------------------------------ lokasi
def loc_values(f, lid=0):
    name = (f.get("name") or "").strip()
    if not name: raise ValueError("Nama lokasi wajib diisi")
    if db.q("SELECT 1 FROM locations WHERE lower(name)=lower(?) AND id!=?", (name, lid), one=True): raise ValueError("Nama lokasi sudah dipakai")
    if f.get("road_type") not in ROAD_TYPES: raise ValueError("Tipe jalan tidak dikenal")
    lanes = int(num(f.get("lanes"), 1, 12, "Jumlah lajur", True))
    if lanes != calc.lanes_of(f.get("road_type")): raise ValueError(f"Tipe jalan {f.get('road_type')} berarti {calc.lanes_of(f.get('road_type'))} lajur; sesuaikan jumlah lajur")
    split = (f.get("split") or "").strip() or None
    if split and split not in db.SPEC["split"][1]: raise ValueError("Pemisahan arah tidak dikenal")
    khs, lbe = (f.get("khs") or "").strip() or None, (f.get("lbe") or "").strip() or None
    if khs and khs not in db.SPEC["khs"][1]: raise ValueError("KHS tidak dikenal")
    if lbe and lbe not in db.SPEC["lbe"][1]: raise ValueError("Lebar bahu efektif tidak dikenal")
    return (name, (f.get("zone") or "").strip(), lanes, f.get("road_type"),
            num(f.get("speed_limit"), 10, 200, "Batas kecepatan"), (f.get("note") or "").strip(), num(f.get("lane_w"), 2.5, 5, "Lebar lajur"),
            split, num(f.get("pop"), .01, 30, "Ukuran kota (juta jiwa)"), num(f.get("f_chs"), 0, 1.5, "F_CHS"), khs, lbe)

@router.get("/locations", response_class=HTMLResponse)
def locations(request: Request):
    rows = db.q("SELECT l.*, (SELECT COUNT(*) FROM cameras c WHERE c.location_id=l.id) AS n_cam FROM locations l ORDER BY l.id")
    return page(request, "locations.html", rows=rows, road_types=ROAD_TYPES, D=glob())

@router.post("/locations")
async def loc_add(request: Request):
    try: v = loc_values(await request.form())
    except ValueError as e: return go("/locations", bad=str(e))
    db.q("INSERT INTO locations(name,zone,lanes,road_type,speed_limit,note,lane_w,split,pop,f_chs,khs,lbe) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", v, commit=True)
    return go("/locations", ok="Lokasi ditambahkan.")

@router.post("/locations/{i}/edit")
async def loc_edit(i: int, request: Request):
    try: v = loc_values(await request.form(), i)
    except ValueError as e: return go("/locations", bad=str(e))
    db.q("UPDATE locations SET name=?,zone=?,lanes=?,road_type=?,speed_limit=?,note=?,lane_w=?,split=?,pop=?,f_chs=?,khs=?,lbe=? WHERE id=?", (*v, i), commit=True)
    return go("/locations", ok="Perubahan disimpan.")

@router.post("/locations/{i}/delete")
def loc_del(i: int):
    n = db.q("SELECT COUNT(*) n FROM cameras WHERE location_id=?", (i,), one=True)["n"]
    if n: return go("/locations", bad=f"Lokasi masih dipakai {n} kamera. Pindahkan atau hapus kameranya dulu.")
    db.q("DELETE FROM locations WHERE id=?", (i,), commit=True); return go("/locations", ok="Lokasi dihapus.")

# ------------------------------------------------------------------ kamera
def cam_values(f, cid=0):
    name, rtsp = (f.get("name") or "").strip(), (f.get("rtsp") or "").strip()
    if not name: raise ValueError("Nama kamera wajib diisi")
    if db.q("SELECT 1 FROM cameras WHERE lower(name)=lower(?) AND id!=?", (name, cid), one=True): raise ValueError("Nama kamera sudah dipakai")
    try: loc = int(f.get("location_id") or 0)
    except ValueError: loc = 0
    if not db.q("SELECT 1 FROM locations WHERE id=?", (loc,), one=True): raise ValueError("Pilih lokasi yang valid")
    return name, rtsp, loc, (f.get("direction") or "").strip(), (f.get("note") or "").strip()

@router.get("/cameras", response_class=HTMLResponse)
def cameras(request: Request):
    cal = get_cal().get("cameras", {})
    rows = [{**r, "calibrated": str(r["id"]) in cal} for r in db.q("SELECT c.*, l.name loc FROM cameras c LEFT JOIN locations l ON l.id=c.location_id ORDER BY c.id")]
    return page(request, "cameras.html", rows=rows, locs=db.q("SELECT * FROM locations ORDER BY name"))

@router.post("/cameras")
async def cam_add(request: Request):
    try: v = cam_values(await request.form())
    except ValueError as e: return go("/cameras", bad=str(e))
    db.q("INSERT INTO cameras(name,rtsp,location_id,direction,note) VALUES(?,?,?,?,?)", v, commit=True)
    return go("/cameras", ok="Kamera ditambahkan. Kalibrasi di menu Calibration agar kecepatan bisa dihitung.")

@router.post("/cameras/{i}/edit")
async def cam_edit(i: int, request: Request):
    old = db.q("SELECT name FROM cameras WHERE id=?", (i,), one=True)
    if not old: raise HTTPException(404, "Kamera tidak ada")
    try: v = cam_values(await request.form(), i)
    except ValueError as e: return go("/cameras", bad=str(e))
    db.q("UPDATE cameras SET name=?,rtsp=?,location_id=?,direction=?,note=? WHERE id=?", (*v, i), commit=True)
    if v[0] != old["name"]: db.q("UPDATE detections SET camera=? WHERE camera=?", (v[0], old["name"]), commit=True)  # riwayat ikut nama baru
    return go("/cameras", ok="Perubahan disimpan.")

@router.post("/cameras/{i}/toggle")
def cam_toggle(i: int):
    db.q("UPDATE cameras SET active=1-active WHERE id=?", (i,), commit=True); return go("/cameras")

@router.post("/cameras/{i}/delete")
def cam_del(i: int):
    busy = db.q("SELECT COUNT(*) n FROM jobs WHERE camera_id=? AND status IN ('queued','processing','cancelling')", (i,), one=True)["n"]
    if busy: return go("/cameras", bad="Kamera sedang dipakai job analisis video. Tunggu selesai atau batalkan dulu.")
    db.q("DELETE FROM cameras WHERE id=?", (i,), commit=True); drop_cal(i)
    return go("/cameras", ok="Kamera dan kalibrasinya dihapus. Riwayat deteksi tetap tersimpan.")

# ------------------------------------------------------------------ parameter
@router.get("/parameters", response_class=HTMLResponse)
def parameters(request: Request):
    keys = list(db.SPEC)
    return page(request, "parameters.html", P={k: db.param(k) for k in keys}, D={k: db.default(k) for k in keys}, codes=db.PKJI_CODES, EMP=calc.cfg()["dynamic_emp_rules"], C0=calc.cfg()["capacity_factors_lookup"]["base_capacity_C0"], CHS=calc.cfg()["capacity_factors_lookup"]["F_CHS_2_2_TT_bahu"])

@router.post("/parameters/{sec}")
async def param_save(sec: str, request: Request):
    keys = db.SECTIONS.get(sec)
    if not keys: raise HTTPException(404, "Bagian tidak dikenal")
    f = await request.form(); vals, errs = {}, []
    for k in keys:
        try: vals[k] = db.cast(k, ("1" if k in f else "0") if db.SPEC[k][0] == "b" else f.get(k, ""))
        except ValueError as e: errs.append(f"{LBL.get(k, k)} {e}")
    if sec == "kapasitas" and not errs:
        lim = [vals[f"los_{x}"] for x in "abcde"]
        if lim != sorted(lim) or len(set(lim)) < 5: errs.append("Batas LOS A–E harus naik berurutan")
    if sec == "kecepatan" and not errs and vals["speed_min"] >= vals["speed_max"]: errs.append("Kecepatan minimum harus lebih kecil dari maksimum")
    if errs: return go("/parameters", bad="Tidak disimpan: " + "; ".join(errs[:3]))
    for k, v in vals.items(): db.set_setting(k, ("1" if v else "0") if isinstance(v, bool) else v)
    return go("/parameters", ok="Tersimpan." + (" Klik Reload AI Engine di Settings agar berlaku." if sec == "deteksi" else ""))

@router.post("/parameters/{sec}/reset")
def param_reset(sec: str):
    keys = db.SECTIONS.get(sec)
    if not keys: raise HTTPException(404, "Bagian tidak dikenal")
    for k in keys: db.q("DELETE FROM settings WHERE key=?", (k,), commit=True)
    return go("/parameters", ok="Dikembalikan ke nilai default." + (" Klik Reload AI Engine di Settings agar berlaku." if sec == "deteksi" else ""))
