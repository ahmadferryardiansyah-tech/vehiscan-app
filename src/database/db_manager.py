import json, os, random, re, shutil, sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "vehiscan.db"

def ensure_cal():
    """configs/calibration.json adalah milik pengguna (hasil menu Calibration) dan tidak ikut paket;
    bila belum ada, dibuat dari calibration.example.json. Dengan begitu menimpa folder dengan paket baru tidak menghapus kalibrasi."""
    p, ex = ROOT / "configs" / "calibration.json", ROOT / "configs" / "calibration.example.json"
    if not p.exists() and ex.exists(): shutil.copy(ex, p)

ensure_cal()
PKJI = {"SM": "Sepeda Motor", "MP": "Mobil Penumpang", "KS": "Kendaraan Sedang", "LB": "Bus Besar", "LT": "Truk Besar"}  # kode baku PKJI 2023
LEGACY = {"KB": "LT", "BB": "LB"}  # kode lama (model YOLO / data lama) -> kode PKJI 2023

def q(sql, args=(), one=False, commit=False):
    con = sqlite3.connect(DB, timeout=30); con.row_factory = sqlite3.Row  # timeout: thread video & web berbagi DB
    try:
        cur = con.execute(sql, args)
        rows = [] if commit else [dict(r) for r in cur.fetchall()]
        if commit: con.commit()
    finally:
        con.close()
    return (rows[0] if rows else None) if one else rows

def insert(sql, args=()):
    """INSERT dan kembalikan id baris baru (aman dari balapan MAX(id) saat dua unggahan bersamaan)."""
    con = sqlite3.connect(DB, timeout=30)
    try:
        cur = con.execute(sql, args); con.commit(); return cur.lastrowid
    finally:
        con.close()

def compact(plate):
    """'AB 1234 xy' / 'ab-1234-xy' -> 'AB1234XY' agar pencocokan watchlist tidak bergantung spasi."""
    return re.sub(r"[^A-Z0-9]", "", str(plate or "").upper())

def setting(k, d=""):
    r = q("SELECT value FROM settings WHERE key=?", (k,), one=True)
    return r["value"] if r else d

def set_setting(k, v):
    q("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, str(v)), commit=True)

# ---- parameter yang bisa diubah lewat web (halaman Parameter). Nilai awal: configs/*.yaml|json ----
PKJI_CODES = tuple(PKJI)
SPEC = {"speed_limit": ("f", 10, 200), "speed_min": ("f", 0, 50), "speed_max": ("f", 50, 400),
        "anpr_conf": ("f", .1, 1), "plate_every": ("i", 1, 30), "plate_max_tries": ("i", 1, 100), "plate_min_width": ("i", 20, 600),
        "conf": ("f", .05, .95), "iou": ("f", .1, .95), "imgsz": ("i", 320, 1920), "device": ("s", ("auto", "cpu", "0", "1")), "half": ("b",),
        "track_buffer": ("i", 1, 300), "match_thresh": ("f", .1, 1), "track_high_thresh": ("f", .05, .95),
        "road_type": ("s", ("2/2-TT", "4/2-T", "6/2-T")), "lane_width": ("f", 2.5, 5), "split": ("s", ("50-50", "60-40", "70-30")),
        "city_pop": ("f", .01, 30), "f_chs": ("f", 0, 1.5),  # f_chs 0 = otomatis dari KHS & bahu
        "khs": ("s", ("VLO", "LO", "MD", "HI", "VHI")), "lbe": ("s", ("0.5", "1.0", "1.5", "2.0"))}  # emp tidak lagi parameter: dinamis (lihat configs/pkji_2023.json)
for _c in PKJI_CODES: SPEC[f"lbl_{_c}"] = ("s", None)
for _x in "abcde": SPEC[f"los_{_x}"] = ("f", .01, 2)
SECTIONS = {"kecepatan": ["speed_limit", "speed_min", "speed_max"],
            "kelas": [f"lbl_{c}" for c in PKJI_CODES],
            "kapasitas": ["road_type", "lane_width", "split", "city_pop", "khs", "lbe", "f_chs"] + [f"los_{x}" for x in "abcde"],
            "deteksi": ["conf", "iou", "imgsz", "device", "half", "track_buffer", "match_thresh", "track_high_thresh"],
            "anpr": ["anpr_conf", "plate_every", "plate_max_tries", "plate_min_width"]}
_STATIC = {"speed_limit": 80, "speed_min": 2, "speed_max": 250, "anpr_conf": .7,  # speed_min 2: abaikan jitter kotak pada kendaraan berhenti
           "road_type": "2/2-TT", "lane_width": 3.5, "split": "50-50", "city_pop": .85, "f_chs": 0, "khs": "LO", "lbe": "2.0",
           "los_a": .2, "los_b": .44, "los_c": .74, "los_d": .85, "los_e": 1.0, **{f"lbl_{c}": v for c, v in PKJI.items()}}
_FD = {}

def _file_defaults():
    if not _FD:
        m = yaml.safe_load((ROOT / "configs" / "model.yaml").read_text()); t = yaml.safe_load((ROOT / "configs" / "tracker.yaml").read_text())
        _FD.update({k: m[k] for k in ("conf", "iou", "imgsz", "device", "half")})
        _FD.update(plate_every=m["plate"]["every"], plate_max_tries=m["plate"]["max_tries"], plate_min_width=m["plate"]["min_vehicle_width"])
        _FD.update({k: t[k] for k in ("track_buffer", "match_thresh", "track_high_thresh")})
    return _FD

def default(key):
    return _STATIC[key] if key in _STATIC else _file_defaults()[key]

def cast(key, raw):
    """Validasi & konversi nilai dari form; ValueError berisi pesan yang bisa ditampilkan."""
    sp = SPEC[key]
    if sp[0] == "b": return str(raw).lower() in ("1", "true", "on", "yes")
    if sp[0] == "s":
        raw = str(raw).strip()
        if not raw: raise ValueError("tidak boleh kosong")
        if sp[1] and raw not in sp[1]: raise ValueError("pilihan tidak dikenal")
        return raw
    try: v = float(str(raw).replace(",", ".")) if sp[0] == "f" else int(float(str(raw).replace(",", ".")))
    except ValueError: raise ValueError("harus berupa angka")
    if not sp[1] <= v <= sp[2]: raise ValueError(f"harus antara {sp[1]} dan {sp[2]}")
    return v

def param(key):
    """Nilai dari database bila ada, jika tidak nilai default dari file konfigurasi."""
    raw = setting(key, None)
    if raw is not None:
        try: return cast(key, raw)
        except ValueError: pass
    return default(key)

def pkji_labels():
    return {c: param(f"lbl_{c}") for c in PKJI_CODES}

def speed_limit_for(camera):
    """Batas kecepatan lokasi kamera ini; jika kosong, batas global."""
    r = q("SELECT l.speed_limit v FROM cameras c JOIN locations l ON l.id=c.location_id WHERE c.name=?", (camera,), one=True)
    return float(r["v"]) if r and r["v"] is not None else float(param("speed_limit"))

def log_detection(camera, plate, pkji, speed, ts=None, src="real", direction=None):
    """Dipakai pipeline AI & seeder. Menentukan status lalu membuat notifikasi bila perlu."""
    ts = ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    wl = {compact(w["plate"]) for w in q("SELECT plate FROM watchlist")}
    # kendaraan SELALU dicatat (dihitung sebagai volume) berapa pun kecepatannya; speed < speed_min hanya diberi status 'macet'
    # agar tidak ikut statistik kecepatan. direction: 1 = melintasi A lalu B, 2 = B lalu A (dipakai analisis jalan terbagi per arah).
    st = "watchlist" if compact(plate) in wl else ("speeding" if speed > speed_limit_for(camera) else ("macet" if speed < param("speed_min") else "normal"))
    q("INSERT INTO detections(ts,camera,plate,pkji,speed,status,src,dir) VALUES(?,?,?,?,?,?,?,?)", (ts, camera, plate, pkji, round(speed, 1), st, src, direction), commit=True)
    if st in ("watchlist", "speeding"):
        msg = f"Plat target terdeteksi: {plate}" if st == "watchlist" else f"Pelanggaran kecepatan {round(speed)} km/jam: {plate}"
        q("INSERT INTO notifications(ts,level,message,src) VALUES(?,?,?,?)", (ts, "critical" if st == "watchlist" else "warning", msg, src), commit=True)
    return st

def _migrate_pkji2023():
    """Database lama -> PKJI 2023 (aman dijalankan berulang): kode KB/BB -> LT/LB, tipe jalan '4/2 T' -> '4/2-T'. (Nilai FCsf lama adalah placeholder, tidak dibawa: F_CHS kini otomatis.)"""
    for old, new in LEGACY.items(): q("UPDATE detections SET pkji=? WHERE pkji=?", (new, old), commit=True)
    q("UPDATE locations SET road_type=REPLACE(road_type,' ','-') WHERE road_type LIKE '% %'", commit=True)

def init_db():
    DB.parent.mkdir(exist_ok=True)
    q("PRAGMA journal_mode=WAL", commit=True)  # baca & tulis bersamaan (job video + halaman web) tanpa 'database is locked'
    for s in [
        "CREATE TABLE IF NOT EXISTS detections(id INTEGER PRIMARY KEY, ts TEXT, camera TEXT, plate TEXT, pkji TEXT, speed REAL, status TEXT)",
        "CREATE TABLE IF NOT EXISTS watchlist(id INTEGER PRIMARY KEY, plate TEXT UNIQUE, reason TEXT, added TEXT)",
        "CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, ts TEXT, level TEXT, message TEXT)",
        "CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)",
        "CREATE TABLE IF NOT EXISTS locations(id INTEGER PRIMARY KEY, name TEXT, zone TEXT, lanes INTEGER, road_type TEXT)",
        "CREATE TABLE IF NOT EXISTS cameras(id INTEGER PRIMARY KEY, name TEXT, rtsp TEXT, location_id INTEGER, active INTEGER DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, filename TEXT, path TEXT, camera_id INTEGER, started TEXT, stride INTEGER, status TEXT, progress REAL DEFAULT 0, frames INTEGER DEFAULT 0, events INTEGER DEFAULT 0, message TEXT, created TEXT)"]:
        q(s, commit=True)
    for t in ("detections", "notifications"):  # kolom 'src' = demo | real | (video job); data lama dianggap demo
        try:
            q(f"ALTER TABLE {t} ADD COLUMN src TEXT DEFAULT 'real'", commit=True)
            q(f"UPDATE {t} SET src='demo'", commit=True)
        except sqlite3.OperationalError:
            pass
    q("UPDATE jobs SET status='failed', message='Server dihentikan saat proses berjalan' WHERE status IN ('queued','processing','cancelling')", commit=True)
    for t, col, ddl in [("locations", "note", "TEXT"), ("locations", "speed_limit", "REAL"), ("locations", "lane_w", "REAL"), ("locations", "split", "TEXT"),
                        ("locations", "pop", "REAL"), ("locations", "f_chs", "REAL"), ("locations", "khs", "TEXT"), ("locations", "lbe", "TEXT"),
                        ("detections", "dir", "INTEGER"),
                        ("cameras", "note", "TEXT"), ("cameras", "direction", "TEXT"), ("jobs", "dur", "REAL")]:  # migrasi aman untuk database lama
        try: q(f"ALTER TABLE {t} ADD COLUMN {col} {ddl}", commit=True)
        except sqlite3.OperationalError: pass
    _migrate_pkji2023()
    if q("SELECT COUNT(*) c FROM settings", one=True)["c"]:
        return
    set_setting("seeded", "1")  # penanda: kerangka awal (lokasi & kamera contoh) sudah dibuat
    for n, z, l, t in [("Koridor Tol Utara", "Zona A", 4, "4/2-T"), ("Simpang Kentungan", "Zona B", 2, "2/2-TT")]:
        q("INSERT INTO locations(name,zone,lanes,road_type) VALUES(?,?,?,?)", (n, z, l, t), commit=True)
    cams = ["CAM-01 Gerbang Tol Utara", "CAM-02 Km 12 Arah Barat", "CAM-03 Simpang Kentungan", "CAM-04 Flyover Selatan"]
    for i, c in enumerate(cams):
        q("INSERT INTO cameras(name,rtsp,location_id) VALUES(?,?,?)", (c, "", 1 if i < 2 else 2), commit=True)
    if os.getenv("VEHISCAN_SEED", "0") != "1":  # data simulasi HANYA bila diminta: start.bat demo
        return
    for p, r in [("AB 1234 XY", "DPO - Pencurian Kendaraan"), ("AB 7788 KD", "Tunggakan Pajak 2 Tahun"), ("AB 4521 BC", "Tunggakan Pajak 1 Tahun")]:
        q("INSERT INTO watchlist(plate,reason,added) VALUES(?,?,?)", (p, r, datetime.now().strftime("%Y-%m-%d")), commit=True)
    wl = [w["plate"] for w in q("SELECT plate FROM watchlist")]; now = datetime.now()
    for _ in range(900):
        ts = (now - timedelta(minutes=random.randint(0, 7 * 24 * 60))).strftime("%Y-%m-%d %H:%M:%S")
        pk = random.choices(list(PKJI), [50, 33, 8, 3, 6])[0]
        pl = random.choice(wl) if random.random() < .01 else f"AB {random.randint(1000,9999)} {random.choice(['AA','BC','KD','RT','XY'])}"
        log_detection(random.choice(cams), pl, pk, max(10, random.gauss(62, 14)), ts, src="demo", direction=random.choice((1, 2)))
