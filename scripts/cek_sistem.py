"""Diagnosa VehiScan: paket, model AI, OCR, ffmpeg, kalibrasi, database, lalu uji alur video yang nyata.
Jalankan dari root proyek (venv aktif):   python scripts/cek_sistem.py
Hasil juga disimpan ke data/cek_sistem.txt, kirim isinya bila butuh bantuan. Tidak mengubah database/replay Anda."""
import importlib, importlib.metadata as md, json, os, platform, shutil, sqlite3, sys, tempfile, time, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; os.chdir(ROOT); sys.path.insert(0, str(ROOT))
STUB = "--stub" in sys.argv  # hanya untuk uji skrip ini sendiri (detektor tiruan)
OUT, RES, TMP = [], [], Path(tempfile.mkdtemp(prefix="vehiscan_cek_"))

class Skip(Exception): pass

def say(s=""): print(s, flush=True); OUT.append(s)

def step(title):
    def deco(fn):
        t = time.time()
        try:
            info = fn(); RES.append((True, title)); say(f"[OK]     {title}" + (f"  ->  {info}" if info else "") + f"   ({time.time() - t:.1f} dtk)")
        except Skip as e: RES.append((None, title)); say(f"[LEWAT]  {title}  ->  {e}")
        except Exception as e:
            RES.append((False, title)); say(f"[GAGAL]  {title}\n         {type(e).__name__}: {e}")
            if "--verbose" in sys.argv: [say("         " + l) for l in traceback.format_exc().strip().splitlines()]
        return fn
    return deco

say("=== VehiScan: diagnosa sistem ===")
say(f"Python {platform.python_version()} | {platform.system()} {platform.release()} | folder: {ROOT}")

@step("Versi Python (disarankan 3.11 atau 3.12)")
def _():
    v = sys.version_info
    if v >= (3, 13): raise RuntimeError(f"Python {v.major}.{v.minor} terlalu baru, sebagian paket (OCR) belum cocok. Pakai 3.12.")
    return f"{v.major}.{v.minor}"

@step("Paket Python terpasang")
def _():
    need = [("fastapi",), ("uvicorn",), ("opencv-python-headless", "opencv-python"), ("numpy",), ("PyYAML",), ("torch",), ("ultralytics",),
            ("rapidocr-onnxruntime", "rapidocr"), ("imageio-ffmpeg",), ("openpyxl",), ("reportlab",)]
    mods = {"opencv-python-headless": "cv2", "opencv-python": "cv2", "PyYAML": "yaml", "rapidocr-onnxruntime": "rapidocr_onnxruntime", "rapidocr": "rapidocr", "imageio-ffmpeg": "imageio_ffmpeg"}
    ok, miss = [], []
    for names in need:
        for n in names:
            try: importlib.import_module(mods.get(n, n)); ok.append(f"{n} {md.version(n)}"); break
            except Exception: pass
        else: miss.append(names[0])
    if miss: raise RuntimeError("belum terpasang / gagal dimuat: " + ", ".join(miss) + "   -> jalankan: python -m pip install -r requirements.txt")
    return ", ".join(ok)

@step("PyTorch dan GPU")
def _():
    import torch
    return f"torch {torch.__version__}; " + (f"GPU CUDA: {torch.cuda.get_device_name(0)}" if torch.cuda.is_available() else "tanpa GPU CUDA (CPU, pemrosesan video akan lambat)")

@step("Paket pelacak ByteTrack (lap / lapx)")
def _():
    for n in ("lap", "lapx"):
        try: importlib.import_module("lap"); return f"{n} tersedia"
        except Exception: continue
    raise RuntimeError("tidak ada. Jalankan: python -m pip install lapx  (ultralytics mencoba memasangnya sendiri saat pertama melacak, butuh internet)")

@step("Folder data/ bisa ditulis")
def _():
    (ROOT / "data").mkdir(exist_ok=True); f = ROOT / "data" / ".tulis"; f.write_text("x"); f.unlink(); return str(ROOT / "data")

@step("Database dan job terakhir")
def _():
    dbf = ROOT / "data" / "vehiscan.db"
    if not dbf.exists(): raise Skip("belum ada database (server belum pernah dijalankan)")
    con = sqlite3.connect(f"file:{dbf}?mode=ro", uri=True); con.row_factory = sqlite3.Row
    try:
        cols = [r["name"] for r in con.execute("PRAGMA table_info(jobs)")]
        if not cols: raise RuntimeError("tabel jobs belum ada; jalankan server sekali")
        rows = con.execute("SELECT id,status,progress,message FROM jobs ORDER BY id DESC LIMIT 5").fetchall()
    finally: con.close()
    for r in rows: say(f"           job {r['id']}: {r['status']} {r['progress'] or 0}%  {(r['message'] or '')[:170]}")
    log = ROOT / "data" / "errors.log"
    if log.exists(): say("           data/errors.log (akhir):"); [say("             " + l) for l in log.read_text(errors="replace").strip().splitlines()[-6:]]
    return f"{len(rows)} job terakhir ditampilkan"

CAL = {}
@step("Kalibrasi kamera (configs/calibration.json)")
def _():
    CAL.update(json.loads((ROOT / "configs" / "calibration.json").read_text()).get("cameras", {}))
    if not CAL: raise RuntimeError("belum ada kamera terkalibrasi -> menu Calibration")
    return ", ".join(f"kamera {k} (frame {v.get('frame')})" for k, v in CAL.items())

@step("Berkas bobot YOLO")
def _():
    f = [n for n in ("yolo11_pkji.pt", "yolo11s.pt") if (ROOT / n).exists()]
    if not f: raise RuntimeError("yolo11_pkji.pt maupun yolo11s.pt tidak ada di root proyek")
    return ", ".join(f)

det = None
@step("Muat model YOLO11")
def _():
    global det
    if STUB: raise Skip("mode --stub")
    from src.ai.detector import VehicleDetector
    det = VehicleDetector()
    if not det.ready: raise RuntimeError(det.msg)
    return det.msg

@step("Deteksi + pelacakan pada frame uji (ukur kecepatan komputer)")
def _():
    if det is None: raise Skip("model belum termuat")
    import numpy as np
    fr = np.full((720, 1280, 3), 100, np.uint8); t = time.time()
    for _i in range(3): det.process(fr, 0)
    s = (time.time() - t) / 3
    return f"{s:.2f} dtk/frame -> video 1 menit @30 fps: semua frame ≈ {s * 1800 / 60:.0f} menit; 'proses tiap 3 frame' ≈ {s * 600 / 60:.0f} menit"

def plate_img():
    import numpy as np, cv2
    f = np.full((360, 640, 3), 90, np.uint8); cv2.rectangle(f, (140, 150), (500, 250), (255, 255, 255), -1)
    cv2.putText(f, "AB 1234 XY", (160, 220), cv2.FONT_HERSHEY_DUPLEX, 1.6, (0, 0, 0), 4); return f

@step("Pembaca plat (OCR)")
def _():
    from src.ai.anpr import PlateReader
    r = PlateReader()
    if not r.ready: raise RuntimeError(r.msg)
    p, s = r.read(plate_img())
    if p != "AB 1234 XY": raise RuntimeError(f"OCR membaca '{p}' (skor {s:.2f}), seharusnya 'AB 1234 XY'")
    return f"terbaca '{p}' (skor {s:.2f})"

@step("ffmpeg dan pembuatan video replay H.264")
def _():
    import numpy as np, cv2
    from src.ai import video_processor as vp
    exe = vp.Replay.exe()
    if not exe: raise RuntimeError("ffmpeg tidak ditemukan -> jalankan: python -m pip install imageio-ffmpeg")
    vp.REPLAYS = TMP / "replays"; rp = vp.Replay(0, 30.0)
    for i in range(45):
        f = np.full((540, 960, 3), 60, np.uint8); cv2.rectangle(f, (20 + i * 10, 200), (160 + i * 10, 320), (0, 200, 0), -1); rp.write(f)
    rp.close()
    if rp.error or not rp.final.exists(): raise RuntimeError(rp.error or "file replay tidak terbentuk")
    cap = cv2.VideoCapture(str(rp.final)); n = int(cap.get(7)); cap.release()
    return f"{Path(exe).name}; file {rp.final.stat().st_size // 1024} KB, {n} frame terbaca kembali"

@step("Alur lengkap: video -> deteksi -> kecepatan -> plat -> replay")
def _():
    import numpy as np, cv2
    from src.ai import video_processor as vp
    from src.database import db_manager as db
    if not CAL: raise Skip("butuh kamera terkalibrasi")
    if det is None and not STUB: raise Skip("model belum termuat")
    cid, cfg = next(iter(CAL.items())); fw, fh = cfg.get("frame") or (1280, 720); src = np.array(cfg["src"], float)
    ymin, ymax, xc = src[:, 1].min(), src[:, 1].max(), src[:, 0].mean(); n = 90
    def box(i):  # kendaraan tiruan bergerak dari tepi atas ke tepi bawah area kalibrasi
        y2 = ymin + (ymax - ymin + 40) * i / n; return (int(xc - 60), int(y2 - 80), int(xc + 60), int(y2))
    vid = TMP / "uji.mp4"; w = cv2.VideoWriter(str(vid), cv2.VideoWriter_fourcc(*"mp4v"), 30, (int(fw), int(fh)))
    for i in range(n):
        f = np.full((int(fh), int(fw), 3), 90, np.uint8); x1, y1, x2, y2 = box(i)
        cv2.rectangle(f, (x1, y1), (x2, y2), (120, 60, 40), -1); cv2.rectangle(f, (x1 + 20, y2 - 30), (x2 - 20, y2 - 8), (255, 255, 255), -1); w.write(f)
    w.release()
    db.DB = TMP / "cek.db"; db.init_db(); vp.REPLAYS = TMP / "replays"
    db.q("INSERT OR IGNORE INTO cameras(id,name,rtsp,location_id) VALUES(?,?,?,1)", (int(cid), f"cek-{cid}", ""), commit=True)
    class Stub:
        ready = True
        def __init__(s): s.i = -1
        def clone(s): return s
        def process(s, fr, cam): s.i += 1; return fr, [{"id": 1, "cls": "MP", "bbox": box(s.i), "conf": .9}]
    d = Stub() if STUB else det
    if not STUB: d.clone = lambda: d  # jangan muat model dua kali
    db.q("INSERT INTO jobs(filename,path,camera_id,started,stride,status,message,created) VALUES('uji',?,?,?,1,'queued','','x')", (str(vid), int(cid), "2026-01-01T08:00:00"), commit=True)
    jid = db.q("SELECT MAX(id) i FROM jobs", one=True)["i"]; vp._run_job(jid, d)
    r = db.q("SELECT status,frames,events,message FROM jobs WHERE id=?", (jid,), one=True)
    if r["status"] != "done": raise RuntimeError(f"job {r['status']}: {r['message']}")
    if not (vp.REPLAYS / f"job_{jid}.mp4").exists(): raise RuntimeError("analisis selesai tetapi replay tidak dibuat: " + (r["message"] or ""))
    return f"job selesai, {r['frames']} frame, {r['events']} event, replay terbentuk" + ("" if STUB else " (kendaraan tiruan bisa saja tidak terdeteksi YOLO; yang diuji adalah rantai prosesnya)")

fail = [t for ok, t in RES if ok is False]
say("\n=== RINGKASAN ===")
say(f"{sum(1 for ok, _ in RES if ok is True)} lolos, {len(fail)} gagal, {sum(1 for ok, _ in RES if ok is None)} dilewati")
for t in fail: say(f"  - perbaiki: {t}")
if not fail: say("Semua komponen berfungsi. Jika video masih bermasalah, lihat kolom Catatan pada job di menu Video Analysis (dan data/errors.log).")
try: (ROOT / "data").mkdir(exist_ok=True); (ROOT / "data" / "cek_sistem.txt").write_text("\n".join(OUT), encoding="utf-8"); print("\nHasil disimpan di data/cek_sistem.txt")
except OSError: pass
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if fail else 0)
