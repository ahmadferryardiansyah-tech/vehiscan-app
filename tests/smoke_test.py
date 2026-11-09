"""Uji asap seluruh halaman & API (memakai database sementara, tidak menyentuh data/vehiscan.db).
Jalankan dari root proyek:  pip install httpx   lalu   python tests/smoke_test.py"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["VEHISCAN_SEED"] = "1"  # data simulasi supaya grafik/laporan punya isi

from fastapi.testclient import TestClient
from src.database import db_manager as db
db.DB = Path(tempfile.mkdtemp()) / "smoke.db"; db.init_db()
from src.ai.detector import VehicleDetector
from src.api.app import app
app.state.detector = VehicleDetector(autoload=False)  # tanpa memuat YOLO: uji ini hanya untuk web
c = TestClient(app); fails = 0

def check(method, url, expect=200, **kw):
    global fails
    r = getattr(c, method)(url, follow_redirects=True, **kw); ok = r.status_code == expect
    fails += not ok; print(("OK  " if ok else "GAGAL"), method.upper(), url, r.status_code, "" if ok else r.text[:200]); return r

for u in ["/", "/videos", "/logs", "/logs?plate=AB&pkji=SM", "/corridor", "/watchlist", "/reports", "/calibration", "/cameras", "/locations",
          "/parameters", "/notifications", "/settings", "/api/v1/overview", "/api/v1/corridor", "/api/v1/corridor?location_id=1", "/api/v1/videos/jobs",
          "/logs/export", "/reports/generate?fmt=xlsx&days=7", "/reports/generate?fmt=pdf&days=30", "/static/css/style.css"]:
    check("get", u)
for u in ["/live", "/users", "/recordings", "/health"]: check("get", u, 404)  # fitur yang sudah dihapus
r = check("post", "/watchlist", data={"plate": "ab9999zz", "reason": "uji"}); assert "AB 9999 ZZ" in r.text, "plat watchlist tidak dinormalkan"
check("post", "/locations", data={"name": "Uji", "zone": "Z", "lanes": "2", "road_type": "2/2 TT"})
check("post", "/parameters/kecepatan", data={"speed_limit": "60", "speed_min": "0", "speed_max": "250"})
check("post", "/parameters/kecepatan/reset")
check("post", "/parameters/kapasitas", data={"road_type": "4/2-T", "lane_width": "3.5", "split": "50-50", "city_pop": "0.85", "khs": "LO", "lbe": "2.0", "f_chs": "0", "los_a": ".2", "los_b": ".44", "los_c": ".74", "los_d": ".85", "los_e": "1"})
check("post", "/parameters/kapasitas/reset")
print("\nSEMUA LULUS" if not fails else f"\n{fails} GAGAL"); sys.exit(1 if fails else 0)
